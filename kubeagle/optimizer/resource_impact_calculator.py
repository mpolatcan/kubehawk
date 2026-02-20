"""Resource impact calculator for before/after optimization comparison."""

from __future__ import annotations

import logging
import math
from typing import Any

from kubeagle.constants.instance_types import (
    ALLOCATABLE_RATIO,
    DEFAULT_INSTANCE_TYPES,
    DEFAULT_OVERHEAD_PCT,
    HOURS_PER_MONTH,
    SPOT_PRICES,
)
from kubeagle.models.charts.chart_info import ChartInfo
from kubeagle.models.optimization.resource_impact import (
    ChartResourceSnapshot,
    ClusterNodeGroup,
    FleetResourceSummary,
    InstanceTypeSpec,
    NodeEstimation,
    ResourceDelta,
    ResourceImpactResult,
)
from kubeagle.optimizer.rules import _parse_cpu
from kubeagle.utils.resource_parser import memory_str_to_bytes

logger = logging.getLogger(__name__)

# Rule IDs that change CPU/memory values
RESOURCE_RULE_IDS: set[str] = {
    "RES002",
    "RES003",
    "RES004",
    "RES005",
    "RES006",
    "RES007",
    "RES008",
    "RES009",
}

# Rule IDs that change replica count
REPLICA_RULE_IDS: set[str] = {"AVL005"}

# All rule IDs that affect resource impact
IMPACT_RULE_IDS: set[str] = RESOURCE_RULE_IDS | REPLICA_RULE_IDS


def _build_instance_types(
    raw_types: list[tuple[str, int, float, float, float]] | None = None,
) -> list[InstanceTypeSpec]:
    """Build InstanceTypeSpec list from raw tuples."""
    source = raw_types or DEFAULT_INSTANCE_TYPES
    specs: list[InstanceTypeSpec] = []
    for name, vcpus, memory_gib, price, spot_price in source:
        specs.append(
            InstanceTypeSpec(
                name=name,
                vcpus=vcpus,
                memory_gib=memory_gib,
                cpu_millicores=vcpus * 1000,
                memory_bytes=int(memory_gib * 1024**3),
                hourly_price_usd=price,
                spot_price_usd=spot_price,
            )
        )
    return specs


class ResourceImpactCalculator:
    """Computes before/after resource impact for a fleet of charts."""

    def compute_impact(
        self,
        charts: list[ChartInfo],
        violations: list[Any],
        *,
        overhead_pct: float = DEFAULT_OVERHEAD_PCT,
        instance_types: list[tuple[str, int, float, float, float]] | None = None,
        optimizer_controller: Any | None = None,
        cluster_nodes: list[Any] | None = None,
    ) -> ResourceImpactResult:
        """Compute the full resource impact analysis.

        Args:
            charts: List of ChartInfo objects.
            violations: List of ViolationResult objects.
            overhead_pct: System overhead percentage (0.0-1.0).
            instance_types: Optional custom instance type specs (fallback).
            optimizer_controller: Optional UnifiedOptimizerController for fix generation.
            cluster_nodes: Optional list of NodeInfo from the live cluster.

        Returns:
            ResourceImpactResult with before/after summaries, delta, and node estimations.
        """
        specs = _build_instance_types(instance_types)

        # Group violations by chart name, only resource/replica rules
        violations_by_chart: dict[str, list[Any]] = {}
        for v in violations:
            rule_id = getattr(v, "rule_id", "") or getattr(v, "id", "")
            if rule_id in IMPACT_RULE_IDS:
                chart_name = getattr(v, "chart_name", "")
                violations_by_chart.setdefault(chart_name, []).append(v)

        before_charts: list[ChartResourceSnapshot] = []
        after_charts: list[ChartResourceSnapshot] = []

        for chart in charts:
            before = self._build_before_snapshot(chart)
            before_charts.append(before)

            chart_violations = violations_by_chart.get(chart.name, [])
            after = self._compute_after_snapshot(
                chart,
                chart_violations,
                optimizer_controller=optimizer_controller,
            )
            after_charts.append(after)

        before_summary = self._aggregate(before_charts)
        after_summary = self._aggregate(after_charts)
        delta = self._compute_delta(before_summary, after_summary)

        # Estimate nodes from hardcoded instance types (fallback)
        node_estimations = self._estimate_nodes(
            before_summary, after_summary, specs, overhead_pct
        )

        # Estimate from real cluster nodes when available
        cluster_node_groups: list[ClusterNodeGroup] = []
        if cluster_nodes:
            cluster_node_groups = self._estimate_from_cluster_nodes(
                after_summary, cluster_nodes, overhead_pct
            )

        # Total spot savings from whichever source is active
        if cluster_node_groups:
            total_savings = sum(g.cost_savings_monthly for g in cluster_node_groups)
        else:
            total_savings = sum(e.cost_savings_monthly for e in node_estimations)

        return ResourceImpactResult(
            before=before_summary,
            after=after_summary,
            delta=delta,
            before_charts=before_charts,
            after_charts=after_charts,
            node_estimations=node_estimations,
            cluster_node_groups=cluster_node_groups,
            total_spot_savings_monthly=total_savings,
        )

    def _build_before_snapshot(self, chart: ChartInfo) -> ChartResourceSnapshot:
        """Build a resource snapshot from current chart values."""
        replicas = max(1, chart.replicas or 1)
        cpu_req = chart.cpu_request  # already millicores
        cpu_lim = chart.cpu_limit
        mem_req = chart.memory_request  # already bytes
        mem_lim = chart.memory_limit

        return ChartResourceSnapshot(
            name=chart.name,
            team=chart.team,
            replicas=replicas,
            cpu_request_per_replica=cpu_req,
            cpu_limit_per_replica=cpu_lim,
            memory_request_per_replica=mem_req,
            memory_limit_per_replica=mem_lim,
            cpu_request_total=cpu_req * replicas,
            cpu_limit_total=cpu_lim * replicas,
            memory_request_total=mem_req * replicas,
            memory_limit_total=mem_lim * replicas,
        )

    def _compute_after_snapshot(
        self,
        chart: ChartInfo,
        chart_violations: list[Any],
        *,
        optimizer_controller: Any | None = None,
    ) -> ChartResourceSnapshot:
        """Compute the after-optimization snapshot for a chart.

        Applies fix dicts from the optimizer controller to compute new values.
        Falls back to parsing violation recommended_value if controller unavailable.
        """
        replicas = max(1, chart.replicas or 1)
        cpu_req = chart.cpu_request
        cpu_lim = chart.cpu_limit
        mem_req = chart.memory_request
        mem_lim = chart.memory_limit

        for violation in chart_violations:
            rule_id = getattr(violation, "rule_id", "") or getattr(violation, "id", "")

            # Try to get fix dict from controller
            fix_dict = None
            if optimizer_controller is not None:
                try:
                    fix_dict = optimizer_controller.generate_fix(chart, violation)
                except Exception:
                    logger.debug(
                        "Failed to generate fix for %s/%s", chart.name, rule_id
                    )

            if fix_dict and rule_id in RESOURCE_RULE_IDS:
                cpu_req, cpu_lim, mem_req, mem_lim = self._apply_resource_fix(
                    fix_dict, cpu_req, cpu_lim, mem_req, mem_lim
                )
            elif rule_id in RESOURCE_RULE_IDS and fix_dict is None:
                # Fallback: apply default fix values for known rules
                cpu_req, cpu_lim, mem_req, mem_lim = self._apply_default_resource_fix(
                    rule_id, cpu_req, cpu_lim, mem_req, mem_lim
                )

            if rule_id in REPLICA_RULE_IDS:
                if fix_dict and "replicaCount" in fix_dict:
                    replicas = max(1, int(fix_dict["replicaCount"]))
                elif replicas < 2:
                    replicas = 2

        return ChartResourceSnapshot(
            name=chart.name,
            team=chart.team,
            replicas=replicas,
            cpu_request_per_replica=cpu_req,
            cpu_limit_per_replica=cpu_lim,
            memory_request_per_replica=mem_req,
            memory_limit_per_replica=mem_lim,
            cpu_request_total=cpu_req * replicas,
            cpu_limit_total=cpu_lim * replicas,
            memory_request_total=mem_req * replicas,
            memory_limit_total=mem_lim * replicas,
        )

    @staticmethod
    def _apply_resource_fix(
        fix_dict: dict[str, Any],
        cpu_req: float,
        cpu_lim: float,
        mem_req: float,
        mem_lim: float,
    ) -> tuple[float, float, float, float]:
        """Apply a fix dict's resource changes to current values."""
        resources = fix_dict.get("resources", {})
        requests = resources.get("requests", {})
        limits = resources.get("limits", {})

        if "cpu" in requests:
            parsed = _parse_cpu(requests["cpu"])
            if parsed is not None:
                cpu_req = parsed
        if "cpu" in limits:
            parsed = _parse_cpu(limits["cpu"])
            if parsed is not None:
                cpu_lim = parsed
        if "memory" in requests:
            parsed_bytes = memory_str_to_bytes(str(requests["memory"]))
            if parsed_bytes > 0:
                mem_req = parsed_bytes
        if "memory" in limits:
            parsed_bytes = memory_str_to_bytes(str(limits["memory"]))
            if parsed_bytes > 0:
                mem_lim = parsed_bytes

        return cpu_req, cpu_lim, mem_req, mem_lim

    @staticmethod
    def _apply_default_resource_fix(
        rule_id: str,
        cpu_req: float,
        cpu_lim: float,
        mem_req: float,
        mem_lim: float,
    ) -> tuple[float, float, float, float]:
        """Apply default fix values when optimizer controller is not available."""
        if rule_id == "RES002":
            # No CPU limit -> set to 2x request or 500m
            cpu_lim = max(cpu_req * 2, 500.0) if cpu_req > 0 else 500.0
        elif rule_id == "RES003":
            # No memory limit -> set to 2x request or 512Mi
            mem_lim = max(mem_req * 2, 512 * 1024**2) if mem_req > 0 else 512 * 1024**2
        elif rule_id == "RES004":
            # No requests -> add defaults
            if cpu_req == 0:
                cpu_req = 100.0
            if mem_req == 0:
                mem_req = 128 * 1024**2
            if cpu_lim == 0:
                cpu_lim = 500.0
            if mem_lim == 0:
                mem_lim = 512 * 1024**2
        elif rule_id == "RES005":
            # High CPU ratio -> reduce limit to 1.5x request
            if cpu_req > 0:
                cpu_lim = cpu_req * 1.5
        elif rule_id == "RES006":
            # High memory ratio -> reduce limit to 1.5x request
            if mem_req > 0:
                mem_lim = mem_req * 1.5
        elif rule_id == "RES007":
            # Very low CPU request -> bump to 100m
            cpu_req = max(cpu_req, 100.0)
        elif rule_id == "RES008":
            # No memory request -> add 128Mi
            if mem_req == 0:
                mem_req = 128 * 1024**2
        elif rule_id == "RES009":
            # Very low memory request -> bump to 128Mi
            mem_req = max(mem_req, 128 * 1024**2)

        return cpu_req, cpu_lim, mem_req, mem_lim

    @staticmethod
    def _aggregate(snapshots: list[ChartResourceSnapshot]) -> FleetResourceSummary:
        """Sum resource totals across all chart snapshots."""
        cpu_req = 0.0
        cpu_lim = 0.0
        mem_req = 0.0
        mem_lim = 0.0
        total_replicas = 0

        for snap in snapshots:
            cpu_req += snap.cpu_request_total
            cpu_lim += snap.cpu_limit_total
            mem_req += snap.memory_request_total
            mem_lim += snap.memory_limit_total
            total_replicas += snap.replicas

        return FleetResourceSummary(
            cpu_request_total=cpu_req,
            cpu_limit_total=cpu_lim,
            memory_request_total=mem_req,
            memory_limit_total=mem_lim,
            chart_count=len(snapshots),
            total_replicas=total_replicas,
        )

    @staticmethod
    def _compute_delta(
        before: FleetResourceSummary,
        after: FleetResourceSummary,
    ) -> ResourceDelta:
        """Compute the difference between before and after summaries."""

        def _pct(old: float, new: float) -> float:
            if old == 0:
                return 0.0 if new == 0 else 100.0
            return ((new - old) / old) * 100.0

        return ResourceDelta(
            cpu_request_diff=after.cpu_request_total - before.cpu_request_total,
            cpu_limit_diff=after.cpu_limit_total - before.cpu_limit_total,
            memory_request_diff=after.memory_request_total - before.memory_request_total,
            memory_limit_diff=after.memory_limit_total - before.memory_limit_total,
            cpu_request_pct=_pct(before.cpu_request_total, after.cpu_request_total),
            cpu_limit_pct=_pct(before.cpu_limit_total, after.cpu_limit_total),
            memory_request_pct=_pct(before.memory_request_total, after.memory_request_total),
            memory_limit_pct=_pct(before.memory_limit_total, after.memory_limit_total),
            replicas_diff=after.total_replicas - before.total_replicas,
            replicas_pct=_pct(
                float(before.total_replicas), float(after.total_replicas)
            ),
        )

    @staticmethod
    def _estimate_nodes(
        before: FleetResourceSummary,
        after: FleetResourceSummary,
        instance_types: list[InstanceTypeSpec],
        overhead_pct: float,
    ) -> list[NodeEstimation]:
        """Estimate node counts per instance type before and after optimization."""
        estimations: list[NodeEstimation] = []

        for spec in instance_types:
            usable_cpu = spec.cpu_millicores * ALLOCATABLE_RATIO * (1 - overhead_pct)
            usable_mem = spec.memory_bytes * ALLOCATABLE_RATIO * (1 - overhead_pct)

            if usable_cpu <= 0 or usable_mem <= 0:
                continue

            nodes_before = max(
                math.ceil(before.cpu_request_total / usable_cpu),
                math.ceil(before.memory_request_total / usable_mem),
                1,
            )
            nodes_after = max(
                math.ceil(after.cpu_request_total / usable_cpu),
                math.ceil(after.memory_request_total / usable_mem),
                1,
            )

            reduction = nodes_before - nodes_after
            reduction_pct = (
                (reduction / nodes_before * 100.0) if nodes_before > 0 else 0.0
            )

            cost_before = nodes_before * spec.spot_price_usd * HOURS_PER_MONTH
            cost_after = nodes_after * spec.spot_price_usd * HOURS_PER_MONTH

            estimations.append(
                NodeEstimation(
                    instance_type=spec.name,
                    vcpus=spec.vcpus,
                    memory_gib=spec.memory_gib,
                    nodes_before=nodes_before,
                    nodes_after=nodes_after,
                    reduction=reduction,
                    reduction_pct=reduction_pct,
                    spot_price_usd=spec.spot_price_usd,
                    cost_before_monthly=cost_before,
                    cost_after_monthly=cost_after,
                    cost_savings_monthly=cost_before - cost_after,
                )
            )

        return estimations

    @staticmethod
    def _estimate_from_cluster_nodes(
        after: FleetResourceSummary,
        cluster_nodes: list[Any],
        overhead_pct: float,
    ) -> list[ClusterNodeGroup]:
        """Estimate node needs using real cluster node data.

        Groups nodes by instance_type, then estimates how many nodes of each
        type would be needed after optimization (proportional allocation).
        """
        # Group nodes by instance type
        groups: dict[str, list[Any]] = {}
        for node in cluster_nodes:
            itype = getattr(node, "instance_type", "") or "unknown"
            groups.setdefault(itype, []).append(node)

        if not groups:
            return []

        # Compute total cluster allocatable (for proportional split)
        total_cluster_cpu = 0.0
        total_cluster_mem = 0.0
        for nodes in groups.values():
            for n in nodes:
                total_cluster_cpu += getattr(n, "cpu_allocatable", 0.0)
                total_cluster_mem += getattr(n, "memory_allocatable", 0.0)

        result: list[ClusterNodeGroup] = []
        for itype, nodes in sorted(groups.items()):
            node_count = len(nodes)
            # Average allocatable per node in this group
            cpu_per_node = sum(getattr(n, "cpu_allocatable", 0.0) for n in nodes) / node_count
            mem_per_node = sum(getattr(n, "memory_allocatable", 0.0) for n in nodes) / node_count

            cpu_total = cpu_per_node * node_count
            mem_total = mem_per_node * node_count

            # Usable capacity after overhead
            usable_cpu_per_node = cpu_per_node * (1 - overhead_pct)
            usable_mem_per_node = mem_per_node * (1 - overhead_pct)

            if usable_cpu_per_node <= 0 or usable_mem_per_node <= 0:
                continue

            # Proportional share of after-optimization workload for this group
            cpu_share = (cpu_total / total_cluster_cpu) if total_cluster_cpu > 0 else 0.0
            mem_share = (mem_total / total_cluster_mem) if total_cluster_mem > 0 else 0.0

            group_cpu_needed = after.cpu_request_total * cpu_share
            group_mem_needed = after.memory_request_total * mem_share

            nodes_needed = max(
                math.ceil(group_cpu_needed / usable_cpu_per_node),
                math.ceil(group_mem_needed / usable_mem_per_node),
                1,
            )

            reduction = node_count - nodes_needed
            reduction_pct = (reduction / node_count * 100.0) if node_count > 0 else 0.0

            # Look up spot price from known prices
            spot_price = SPOT_PRICES.get(itype, 0.0)
            cost_current = node_count * spot_price * HOURS_PER_MONTH
            cost_after = nodes_needed * spot_price * HOURS_PER_MONTH

            result.append(
                ClusterNodeGroup(
                    instance_type=itype,
                    node_count=node_count,
                    cpu_allocatable_per_node=cpu_per_node,
                    memory_allocatable_per_node=mem_per_node,
                    cpu_allocatable_total=cpu_total,
                    memory_allocatable_total=mem_total,
                    nodes_needed_after=nodes_needed,
                    reduction=reduction,
                    reduction_pct=reduction_pct,
                    spot_price_usd=spot_price,
                    cost_current_monthly=cost_current,
                    cost_after_monthly=cost_after,
                    cost_savings_monthly=cost_current - cost_after,
                )
            )

        return result
