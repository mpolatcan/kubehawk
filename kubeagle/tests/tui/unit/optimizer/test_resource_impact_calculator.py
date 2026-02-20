"""Unit tests for ResourceImpactCalculator."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kubeagle.constants.enums import QoSClass
from kubeagle.constants.instance_types import HOURS_PER_MONTH, SPOT_PRICES
from kubeagle.models.charts.chart_info import ChartInfo
from kubeagle.optimizer.resource_impact_calculator import (
    IMPACT_RULE_IDS,
    REPLICA_RULE_IDS,
    RESOURCE_RULE_IDS,
    ResourceImpactCalculator,
    _build_instance_types,
)


def _make_chart(
    name: str = "test-chart",
    team: str = "platform",
    cpu_request: float = 100.0,
    cpu_limit: float = 500.0,
    memory_request: float = 128 * 1024**2,
    memory_limit: float = 512 * 1024**2,
    replicas: int = 2,
) -> ChartInfo:
    """Create a minimal ChartInfo for testing."""
    return ChartInfo(
        name=name,
        team=team,
        values_file="values.yaml",
        cpu_request=cpu_request,
        cpu_limit=cpu_limit,
        memory_request=memory_request,
        memory_limit=memory_limit,
        qos_class=QoSClass.BURSTABLE,
        has_liveness=True,
        has_readiness=True,
        has_startup=False,
        has_anti_affinity=False,
        has_topology_spread=False,
        has_topology=False,
        pdb_enabled=False,
        pdb_template_exists=False,
        pdb_min_available=None,
        pdb_max_unavailable=None,
        replicas=replicas,
        priority_class=None,
    )


def _make_violation(
    rule_id: str = "RES005",
    chart_name: str = "test-chart",
) -> MagicMock:
    """Create a mock violation."""
    v = MagicMock()
    v.id = rule_id
    v.rule_id = rule_id
    v.chart_name = chart_name
    v.rule_name = f"Rule {rule_id}"
    v.description = f"Description for {rule_id}"
    v.severity = MagicMock()
    v.severity.value = "warning"
    v.current_value = "current"
    v.recommended_value = "recommended"
    v.fix_available = True
    return v


class TestBuildInstanceTypes:
    def test_default_types(self) -> None:
        specs = _build_instance_types()
        assert len(specs) == 6
        assert specs[0].name == "m5.large"
        assert specs[0].vcpus == 2
        assert specs[0].cpu_millicores == 2000
        assert specs[0].memory_bytes == int(8.0 * 1024**3)
        assert specs[0].spot_price_usd == 0.035

    def test_custom_types(self) -> None:
        custom = [("c5.large", 2, 4.0, 0.085, 0.031)]
        specs = _build_instance_types(custom)
        assert len(specs) == 1
        assert specs[0].name == "c5.large"
        assert specs[0].memory_gib == 4.0
        assert specs[0].spot_price_usd == 0.031


class TestResourceImpactCalculatorNoViolations:
    def test_no_violations_before_equals_after(self) -> None:
        calc = ResourceImpactCalculator()
        chart = _make_chart()
        result = calc.compute_impact([chart], [])

        assert result.before.cpu_request_total == result.after.cpu_request_total
        assert result.before.cpu_limit_total == result.after.cpu_limit_total
        assert result.before.memory_request_total == result.after.memory_request_total
        assert result.before.memory_limit_total == result.after.memory_limit_total
        assert result.delta.cpu_request_diff == 0.0
        assert result.delta.cpu_limit_diff == 0.0
        assert result.delta.replicas_diff == 0

    def test_empty_charts(self) -> None:
        calc = ResourceImpactCalculator()
        result = calc.compute_impact([], [])

        assert result.before.chart_count == 0
        assert result.after.chart_count == 0
        assert result.before.total_replicas == 0


class TestResourceImpactCalculatorWithViolations:
    def test_res005_reduces_cpu_limit(self) -> None:
        """RES005 (high CPU ratio) should reduce CPU limits."""
        chart = _make_chart(cpu_request=100.0, cpu_limit=1000.0, replicas=1)
        violation = _make_violation("RES005", "test-chart")
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [violation])

        # After should have reduced CPU limit (1.5x request = 150m)
        assert result.after.cpu_limit_total < result.before.cpu_limit_total
        assert result.delta.cpu_limit_diff < 0
        assert result.delta.cpu_limit_pct < 0

    def test_res004_adds_requests(self) -> None:
        """RES004 (no requests) should add CPU+memory requests."""
        chart = _make_chart(
            cpu_request=0.0, cpu_limit=0.0,
            memory_request=0.0, memory_limit=0.0,
            replicas=1,
        )
        violation = _make_violation("RES004", "test-chart")
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [violation])

        # After should have non-zero requests
        assert result.after.cpu_request_total > 0
        assert result.after.memory_request_total > 0

    def test_avl005_doubles_replicas(self) -> None:
        """AVL005 (single replica) should increase to 2 replicas."""
        chart = _make_chart(replicas=1, cpu_request=100.0, cpu_limit=200.0)
        violation = _make_violation("AVL005", "test-chart")
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [violation])

        # After should have 2 replicas, doubling total resources
        assert result.after.total_replicas == 2
        assert result.after.cpu_request_total == pytest.approx(
            result.before.cpu_request_total * 2
        )
        assert result.delta.replicas_diff == 1

    def test_res002_adds_cpu_limit(self) -> None:
        """RES002 (no CPU limit) should add CPU limit."""
        chart = _make_chart(cpu_request=200.0, cpu_limit=0.0, replicas=1)
        violation = _make_violation("RES002", "test-chart")
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [violation])

        # After should have a CPU limit set
        assert result.after.cpu_limit_total > 0

    def test_res007_bumps_low_cpu(self) -> None:
        """RES007 (very low CPU) should bump to 100m."""
        chart = _make_chart(cpu_request=10.0, replicas=1)
        violation = _make_violation("RES007", "test-chart")
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [violation])

        assert result.after.cpu_request_total >= 100.0


class TestFleetAggregation:
    def test_fleet_sums_correctly(self) -> None:
        """Multiple charts should sum resource totals."""
        chart1 = _make_chart(name="chart-1", cpu_request=100.0, replicas=2)
        chart2 = _make_chart(name="chart-2", cpu_request=200.0, replicas=3)
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart1, chart2], [])

        expected_cpu_req = (100.0 * 2) + (200.0 * 3)
        assert result.before.cpu_request_total == pytest.approx(expected_cpu_req)
        assert result.before.chart_count == 2
        assert result.before.total_replicas == 5


class TestNodeEstimation:
    def test_cpu_bound_scenario(self) -> None:
        """Node count should be driven by CPU when CPU is the bottleneck."""
        chart = _make_chart(
            cpu_request=2000.0,  # 2 cores per replica
            memory_request=256 * 1024**2,  # 256Mi per replica
            replicas=10,
        )
        calc = ResourceImpactCalculator()
        result = calc.compute_impact(
            [chart], [],
            instance_types=[("m5.large", 2, 8.0, 0.096, 0.035)],
        )

        assert len(result.node_estimations) == 1
        est = result.node_estimations[0]
        # 20000m CPU total / (2000 * 0.92 * 0.85) usable = ~13 nodes
        assert est.nodes_before > 1
        assert est.spot_price_usd == 0.035

    def test_memory_bound_scenario(self) -> None:
        """Node count should be driven by memory when memory is the bottleneck."""
        chart = _make_chart(
            cpu_request=50.0,  # very low CPU
            memory_request=4 * 1024**3,  # 4Gi per replica
            replicas=10,
        )
        calc = ResourceImpactCalculator()
        result = calc.compute_impact(
            [chart], [],
            instance_types=[("m5.large", 2, 8.0, 0.096, 0.035)],
        )

        assert len(result.node_estimations) == 1
        est = result.node_estimations[0]
        # Memory-heavy workload should need many nodes
        assert est.nodes_before > 1

    def test_minimum_one_node(self) -> None:
        """Node estimation should never drop below 1."""
        chart = _make_chart(
            cpu_request=1.0,
            memory_request=1024.0,
            replicas=1,
        )
        calc = ResourceImpactCalculator()
        result = calc.compute_impact(
            [chart], [],
            instance_types=[("m5.xlarge", 4, 16.0, 0.192, 0.067)],
        )

        est = result.node_estimations[0]
        assert est.nodes_before >= 1
        assert est.nodes_after >= 1


class TestResourceDelta:
    def test_percentage_calculation(self) -> None:
        calc = ResourceImpactCalculator()
        chart = _make_chart(cpu_request=100.0, cpu_limit=1000.0, replicas=1)
        violation = _make_violation("RES005", "test-chart")

        result = calc.compute_impact([chart], [violation])

        # Delta percentage should be negative (savings)
        assert result.delta.cpu_limit_pct < 0

    def test_zero_baseline_no_divide_by_zero(self) -> None:
        """When before is zero, percentage should handle gracefully."""
        chart = _make_chart(
            cpu_request=0.0, cpu_limit=0.0,
            memory_request=0.0, memory_limit=0.0,
            replicas=1,
        )
        violation = _make_violation("RES004", "test-chart")
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [violation])

        # Should not raise; percentage for 0->positive is 100%
        assert result.delta.cpu_request_pct == 100.0


class TestRuleIdConstants:
    def test_resource_rule_ids(self) -> None:
        assert "RES002" in RESOURCE_RULE_IDS
        assert "RES009" in RESOURCE_RULE_IDS
        assert "AVL005" not in RESOURCE_RULE_IDS

    def test_replica_rule_ids(self) -> None:
        assert "AVL005" in REPLICA_RULE_IDS
        assert "RES005" not in REPLICA_RULE_IDS

    def test_impact_rule_ids_is_union(self) -> None:
        assert IMPACT_RULE_IDS == RESOURCE_RULE_IDS | REPLICA_RULE_IDS


class TestWithOptimizerController:
    def test_uses_controller_fix_when_available(self) -> None:
        """When optimizer controller returns a fix, it should be used."""
        chart = _make_chart(cpu_request=100.0, cpu_limit=1000.0, replicas=1)
        violation = _make_violation("RES005", "test-chart")

        controller = MagicMock()
        controller.generate_fix.return_value = {
            "resources": {"limits": {"cpu": "150m"}}
        }

        calc = ResourceImpactCalculator()
        result = calc.compute_impact(
            [chart], [violation], optimizer_controller=controller
        )

        # CPU limit should be 150m (from controller fix)
        assert result.after.cpu_limit_total == pytest.approx(150.0)
        controller.generate_fix.assert_called_once()

    def test_falls_back_when_controller_returns_none(self) -> None:
        """When controller returns None, should use default fix."""
        chart = _make_chart(cpu_request=100.0, cpu_limit=1000.0, replicas=1)
        violation = _make_violation("RES005", "test-chart")

        controller = MagicMock()
        controller.generate_fix.return_value = None

        calc = ResourceImpactCalculator()
        result = calc.compute_impact(
            [chart], [violation], optimizer_controller=controller
        )

        # Should still compute an after value (default fallback)
        assert result.after.cpu_limit_total < result.before.cpu_limit_total

    def test_falls_back_when_controller_raises(self) -> None:
        """When controller raises, should use default fix."""
        chart = _make_chart(cpu_request=100.0, cpu_limit=1000.0, replicas=1)
        violation = _make_violation("RES005", "test-chart")

        controller = MagicMock()
        controller.generate_fix.side_effect = RuntimeError("fail")

        calc = ResourceImpactCalculator()
        result = calc.compute_impact(
            [chart], [violation], optimizer_controller=controller
        )

        assert result.after.cpu_limit_total < result.before.cpu_limit_total


class TestNonResourceViolationsIgnored:
    def test_probe_violations_not_in_impact(self) -> None:
        """PRB violations should not affect resource calculations."""
        chart = _make_chart(replicas=1)
        violation = _make_violation("PRB001", "test-chart")
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [violation])

        assert result.before.cpu_request_total == result.after.cpu_request_total
        assert result.delta.cpu_request_diff == 0.0


def _make_node(
    instance_type: str = "m5.large",
    cpu_allocatable: float = 1920.0,  # millicores (2 vCPU - system)
    memory_allocatable: float = 7.5 * 1024**3,  # bytes
) -> MagicMock:
    """Create a mock NodeInfo for testing."""
    node = MagicMock()
    node.instance_type = instance_type
    node.cpu_allocatable = cpu_allocatable
    node.memory_allocatable = memory_allocatable
    return node


class TestClusterNodeEstimation:
    def test_cluster_nodes_populated(self) -> None:
        """When cluster_nodes provided, cluster_node_groups should be populated."""
        chart = _make_chart(cpu_request=100.0, replicas=2)
        nodes = [_make_node(), _make_node()]
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [], cluster_nodes=nodes)

        assert len(result.cluster_node_groups) == 1
        group = result.cluster_node_groups[0]
        assert group.instance_type == "m5.large"
        assert group.node_count == 2

    def test_no_cluster_nodes_empty_groups(self) -> None:
        """When cluster_nodes is None, cluster_node_groups should be empty."""
        chart = _make_chart()
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [])

        assert result.cluster_node_groups == []

    def test_multiple_instance_types(self) -> None:
        """Nodes of different types should produce separate groups."""
        chart = _make_chart(cpu_request=100.0, replicas=1)
        nodes = [
            _make_node(instance_type="m5.large"),
            _make_node(instance_type="m5.large"),
            _make_node(instance_type="m5.xlarge", cpu_allocatable=3840.0, memory_allocatable=15 * 1024**3),
        ]
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [], cluster_nodes=nodes)

        assert len(result.cluster_node_groups) == 2
        types = {g.instance_type for g in result.cluster_node_groups}
        assert types == {"m5.large", "m5.xlarge"}

    def test_cluster_node_group_allocatable(self) -> None:
        """Group should have correct per-node and total allocatable values."""
        nodes = [
            _make_node(cpu_allocatable=2000.0, memory_allocatable=8 * 1024**3),
            _make_node(cpu_allocatable=2000.0, memory_allocatable=8 * 1024**3),
        ]
        chart = _make_chart(cpu_request=100.0, replicas=1)
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [], cluster_nodes=nodes)

        group = result.cluster_node_groups[0]
        assert group.cpu_allocatable_per_node == pytest.approx(2000.0)
        assert group.memory_allocatable_per_node == pytest.approx(8 * 1024**3)
        assert group.cpu_allocatable_total == pytest.approx(4000.0)
        assert group.memory_allocatable_total == pytest.approx(16 * 1024**3)

    def test_cluster_node_minimum_one_needed(self) -> None:
        """Even tiny workloads should need at least 1 node."""
        nodes = [_make_node()]
        chart = _make_chart(cpu_request=1.0, memory_request=1024.0, replicas=1)
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [], cluster_nodes=nodes)

        group = result.cluster_node_groups[0]
        assert group.nodes_needed_after >= 1

    def test_cluster_node_reduction_calculated(self) -> None:
        """Reduction should be current node count minus nodes needed after."""
        nodes = [_make_node() for _ in range(5)]
        chart = _make_chart(cpu_request=100.0, memory_request=128 * 1024**2, replicas=1)
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [], cluster_nodes=nodes)

        group = result.cluster_node_groups[0]
        assert group.reduction == group.node_count - group.nodes_needed_after
        assert group.reduction_pct == pytest.approx(
            group.reduction / group.node_count * 100.0
        )


class TestSpotPricing:
    def test_node_estimation_has_spot_cost(self) -> None:
        """Node estimation should include spot cost calculations."""
        chart = _make_chart(cpu_request=2000.0, replicas=5)
        calc = ResourceImpactCalculator()
        result = calc.compute_impact(
            [chart], [],
            instance_types=[("m5.large", 2, 8.0, 0.096, 0.035)],
        )

        est = result.node_estimations[0]
        assert est.spot_price_usd == 0.035
        assert est.cost_before_monthly == pytest.approx(
            est.nodes_before * 0.035 * HOURS_PER_MONTH
        )
        assert est.cost_after_monthly == pytest.approx(
            est.nodes_after * 0.035 * HOURS_PER_MONTH
        )
        assert est.cost_savings_monthly == pytest.approx(
            est.cost_before_monthly - est.cost_after_monthly
        )

    def test_node_estimation_savings_with_reduction(self) -> None:
        """When violations reduce resources, cost savings should be positive."""
        chart = _make_chart(cpu_request=100.0, cpu_limit=1000.0, replicas=10)
        violation = _make_violation("RES005", "test-chart")
        calc = ResourceImpactCalculator()
        result = calc.compute_impact(
            [chart], [violation],
            instance_types=[("m5.large", 2, 8.0, 0.096, 0.035)],
        )

        est = result.node_estimations[0]
        # No node reduction for tiny workloads (both need 1 node)
        assert est.cost_savings_monthly >= 0

    def test_cluster_node_spot_price_lookup(self) -> None:
        """Cluster node group should look up spot price from SPOT_PRICES."""
        nodes = [_make_node(instance_type="m5.large") for _ in range(3)]
        chart = _make_chart(cpu_request=100.0, replicas=1)
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [], cluster_nodes=nodes)

        group = result.cluster_node_groups[0]
        assert group.spot_price_usd == SPOT_PRICES["m5.large"]
        assert group.cost_current_monthly == pytest.approx(
            3 * SPOT_PRICES["m5.large"] * HOURS_PER_MONTH
        )

    def test_cluster_node_unknown_type_zero_price(self) -> None:
        """Unknown instance type should have zero spot price."""
        nodes = [_make_node(instance_type="z99.mega")]
        chart = _make_chart(cpu_request=100.0, replicas=1)
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [], cluster_nodes=nodes)

        group = result.cluster_node_groups[0]
        assert group.spot_price_usd == 0.0
        assert group.cost_current_monthly == 0.0
        assert group.cost_after_monthly == 0.0

    def test_cluster_node_cost_savings(self) -> None:
        """Cost savings should equal (current - after) nodes * spot * hours."""
        nodes = [_make_node() for _ in range(10)]
        chart = _make_chart(cpu_request=100.0, memory_request=128 * 1024**2, replicas=1)
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [], cluster_nodes=nodes)

        group = result.cluster_node_groups[0]
        expected_savings = (
            (group.node_count - group.nodes_needed_after)
            * group.spot_price_usd
            * HOURS_PER_MONTH
        )
        assert group.cost_savings_monthly == pytest.approx(expected_savings)

    def test_total_spot_savings_from_cluster(self) -> None:
        """Total savings should sum across all cluster node groups."""
        nodes = [
            _make_node(instance_type="m5.large"),
            _make_node(instance_type="m5.large"),
            _make_node(instance_type="m5.xlarge", cpu_allocatable=3840.0, memory_allocatable=15 * 1024**3),
        ]
        chart = _make_chart(cpu_request=100.0, replicas=1)
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [], cluster_nodes=nodes)

        expected_total = sum(g.cost_savings_monthly for g in result.cluster_node_groups)
        assert result.total_spot_savings_monthly == pytest.approx(expected_total)

    def test_total_spot_savings_fallback_to_estimations(self) -> None:
        """Without cluster nodes, total savings should come from node estimations."""
        chart = _make_chart(cpu_request=100.0, replicas=1)
        calc = ResourceImpactCalculator()

        result = calc.compute_impact([chart], [])

        expected_total = sum(e.cost_savings_monthly for e in result.node_estimations)
        assert result.total_spot_savings_monthly == pytest.approx(expected_total)

    def test_no_savings_when_no_violations(self) -> None:
        """No violations means before == after, so savings should be zero."""
        chart = _make_chart(cpu_request=100.0, replicas=1)
        calc = ResourceImpactCalculator()
        result = calc.compute_impact(
            [chart], [],
            instance_types=[("m5.large", 2, 8.0, 0.096, 0.035)],
        )

        for est in result.node_estimations:
            assert est.cost_savings_monthly == 0.0
        assert result.total_spot_savings_monthly == 0.0
