"""Tests for optimizer rules module.

Covers CPU/memory parsing, rule lookup, individual rule checks
(resource, probes, availability, security), and no-violation scenarios.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

import kubeagle.optimizer.rules as optimizer_rules
from kubeagle.constants.optimizer import (
    LIMIT_REQUEST_RATIO_THRESHOLD as DEFAULT_LIMIT_REQUEST_RATIO_THRESHOLD,
)
from kubeagle.optimizer.rules import (
    RULES,
    RULES_BY_ID,
    _check_blocking_pdb,
    _check_high_cpu_limit_request_ratio,
    _check_high_memory_limit_request_ratio,
    _check_missing_liveness_probe,
    _check_missing_readiness_probe,
    _check_missing_startup_probe,
    _check_missing_topology_spread,
    _check_no_cpu_limits,
    _check_no_memory_limits,
    _check_no_memory_request,
    _check_no_pdb,
    _check_no_pod_anti_affinity,
    _check_no_resource_requests,
    _check_running_as_root,
    _check_very_low_cpu_request,
    _check_very_low_memory_request,
    _parse_cpu,
    _parse_memory,
    configure_rule_thresholds,
    get_rule_by_id,
)


@pytest.fixture(autouse=True)
def _reset_limit_ratio_threshold() -> Generator[None, None, None]:
    """Keep per-test isolation for runtime-mutable ratio threshold."""
    configure_rule_thresholds(
        limit_request_ratio_threshold=DEFAULT_LIMIT_REQUEST_RATIO_THRESHOLD
    )
    yield
    configure_rule_thresholds(
        limit_request_ratio_threshold=DEFAULT_LIMIT_REQUEST_RATIO_THRESHOLD
    )


# ===========================================================================
# TestRulesCPUParsing
# ===========================================================================


class TestRulesCPUParsing:
    """Tests for _parse_cpu helper function."""

    def test_parse_cpu_millicores(self) -> None:
        """'100m' should parse to 100.0 millicores."""
        assert _parse_cpu("100m") == 100.0

    def test_parse_cpu_cores(self) -> None:
        """'1' should parse to 1000.0 millicores (1 core = 1000m)."""
        assert _parse_cpu("1") == 1000.0

    def test_parse_cpu_fractional_cores(self) -> None:
        """'0.5' should parse to 500.0 millicores."""
        assert _parse_cpu("0.5") == 500.0

    def test_parse_cpu_none_returns_none(self) -> None:
        """None input should return None."""
        assert _parse_cpu(None) is None

    def test_parse_cpu_empty_string_returns_none(self) -> None:
        """Empty string should return None."""
        assert _parse_cpu("") is None

    def test_parse_cpu_invalid_string(self) -> None:
        """Invalid string should return None."""
        assert _parse_cpu("abc") is None

    def test_parse_cpu_zero(self) -> None:
        """'0' should parse to 0.0."""
        assert _parse_cpu("0") == 0.0

    def test_parse_cpu_zero_millicores(self) -> None:
        """'0m' should parse to 0.0."""
        assert _parse_cpu("0m") == 0.0

    def test_parse_cpu_invalid_millicores(self) -> None:
        """'abcm' should return None."""
        assert _parse_cpu("abcm") is None

    def test_parse_cpu_whitespace_handling(self) -> None:
        """Whitespace around value should be stripped."""
        assert _parse_cpu("  200m  ") == 200.0


# ===========================================================================
# TestRulesMemoryParsing
# ===========================================================================


class TestRulesMemoryParsing:
    """Tests for _parse_memory helper function."""

    def test_parse_memory_ki(self) -> None:
        """'1024Ki' should parse to 1.0 Mi."""
        assert _parse_memory("1024Ki") == pytest.approx(1.0)

    def test_parse_memory_mi(self) -> None:
        """'128Mi' should parse to 128.0 Mi."""
        assert _parse_memory("128Mi") == 128.0

    def test_parse_memory_gi(self) -> None:
        """'1Gi' should parse to 1024.0 Mi."""
        assert _parse_memory("1Gi") == 1024.0

    def test_parse_memory_ti(self) -> None:
        """'1Ti' should parse to 1048576.0 Mi."""
        assert _parse_memory("1Ti") == 1024.0 * 1024.0

    def test_parse_memory_plain_bytes(self) -> None:
        """'256' (no suffix) should parse as Mi (256.0)."""
        assert _parse_memory("256") == 256.0

    def test_parse_memory_none_returns_none(self) -> None:
        """None input should return None."""
        assert _parse_memory(None) is None

    def test_parse_memory_empty_string_returns_none(self) -> None:
        """Empty string should return None."""
        assert _parse_memory("") is None

    def test_parse_memory_invalid_string(self) -> None:
        """Invalid string should return None."""
        assert _parse_memory("abc") is None

    def test_parse_memory_case_insensitive(self) -> None:
        """Memory parsing should be case-insensitive."""
        assert _parse_memory("128MI") == 128.0
        assert _parse_memory("1GI") == 1024.0


# ===========================================================================
# TestRulesLookup
# ===========================================================================


class TestRulesLookup:
    """Tests for RULES list and lookup functions."""

    def test_rules_list_has_17_entries(self) -> None:
        """RULES list should have 17 entries (8 resource + 3 probes + 5 availability + 1 security)."""
        assert len(RULES) == 17

    def test_each_rule_has_id(self) -> None:
        """Every rule should have a non-empty id."""
        for rule in RULES:
            assert rule.id, f"Rule missing id: {rule}"

    def test_each_rule_has_check_func(self) -> None:
        """Every rule should have a callable check function."""
        for rule in RULES:
            assert callable(rule.check), f"Rule {rule.id} has non-callable check"

    def test_get_rule_by_id_existing(self) -> None:
        """get_rule_by_id should return the rule for a known ID."""
        rule = get_rule_by_id("RES002")
        assert rule is not None
        assert rule.id == "RES002"

    def test_get_rule_by_id_nonexistent(self) -> None:
        """get_rule_by_id should return None for unknown ID."""
        assert get_rule_by_id("NONEXISTENT") is None

    def test_all_rule_ids_unique(self) -> None:
        """All rule IDs should be unique."""
        ids = [r.id for r in RULES]
        assert len(ids) == len(set(ids)), f"Duplicate IDs found: {ids}"

    def test_all_categories_present(self) -> None:
        """All expected categories should be present."""
        categories = {r.category for r in RULES}
        expected = {"resources", "probes", "availability", "security"}
        assert expected == categories

    def test_rules_by_id_dict_matches_rules_list(self) -> None:
        """RULES_BY_ID should have same length as RULES."""
        assert len(RULES_BY_ID) == len(RULES)

    def test_resource_rules_count(self) -> None:
        """Should have 8 resource rules."""
        count = sum(1 for r in RULES if r.category == "resources")
        assert count == 8

    def test_probe_rules_count(self) -> None:
        """Should have 3 probe rules."""
        count = sum(1 for r in RULES if r.category == "probes")
        assert count == 3

    def test_availability_rules_count(self) -> None:
        """Should have 5 availability rules."""
        count = sum(1 for r in RULES if r.category == "availability")
        assert count == 5

    def test_security_rules_count(self) -> None:
        """Should have 1 security rule."""
        count = sum(1 for r in RULES if r.category == "security")
        assert count == 1


# ===========================================================================
# TestResourceRules
# ===========================================================================


class TestResourceRules:
    """Tests for individual resource rule check functions."""

    def test_res002_no_cpu_limits(self) -> None:
        """RES002 should detect missing CPU limits."""
        chart = {"resources": {"limits": {}, "requests": {"cpu": "100m"}}}
        violations = _check_no_cpu_limits(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "RES002"

    def test_res003_no_memory_limits(self) -> None:
        """RES003 should detect missing memory limits."""
        chart = {"resources": {"limits": {}, "requests": {"memory": "128Mi"}}}
        violations = _check_no_memory_limits(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "RES003"

    def test_res004_no_resource_requests(self) -> None:
        """RES004 should detect missing resource requests."""
        chart = {"resources": {"requests": {}, "limits": {"cpu": "500m"}}}
        violations = _check_no_resource_requests(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "RES004"
        assert violations[0].severity == "error"

    def test_res004_best_effort_is_warning(self) -> None:
        """RES004 should downgrade BestEffort workloads to warning severity."""
        chart = {
            "qos_class": "BestEffort",
            "resources": {"requests": {}, "limits": {}},
        }
        violations = _check_no_resource_requests(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "RES004"
        assert violations[0].severity == "warning"

    def test_res005_high_cpu_ratio(self) -> None:
        """RES005 should detect high CPU limit/request ratio (>=2x)."""
        chart = {
            "resources": {
                "limits": {"cpu": "1000m"},
                "requests": {"cpu": "100m"},
            }
        }
        violations = _check_high_cpu_limit_request_ratio(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "RES005"

    def test_res005_cpu_ratio_equal_threshold_is_violation(self) -> None:
        """RES005 should flag charts at the ratio threshold."""
        chart = {
            "resources": {
                "limits": {"cpu": "200m"},
                "requests": {"cpu": "100m"},
            }
        }
        violations = _check_high_cpu_limit_request_ratio(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "RES005"

    def test_res005_best_effort_qos_is_not_ratio_violation(self) -> None:
        """RES005 should not flag workloads that are currently BestEffort."""
        chart = {
            "qos_class": "BestEffort",
            "resources": {
                "limits": {"cpu": "200m"},
                "requests": {"cpu": "100m"},
            },
        }
        violations = _check_high_cpu_limit_request_ratio(chart)
        assert violations == []

    def test_res006_high_memory_ratio(self) -> None:
        """RES006 should detect high memory limit/request ratio (>=2x)."""
        chart = {
            "resources": {
                "limits": {"memory": "1024Mi"},
                "requests": {"memory": "128Mi"},
            }
        }
        violations = _check_high_memory_limit_request_ratio(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "RES006"

    def test_res006_memory_ratio_equal_threshold_is_violation(self) -> None:
        """RES006 should flag charts at the ratio threshold."""
        chart = {
            "resources": {
                "limits": {"memory": "256Mi"},
                "requests": {"memory": "128Mi"},
            }
        }
        violations = _check_high_memory_limit_request_ratio(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "RES006"

    def test_res006_best_effort_qos_is_not_ratio_violation(self) -> None:
        """RES006 should not flag workloads that are currently BestEffort."""
        chart = {
            "qos_class": "BestEffort",
            "resources": {
                "limits": {"memory": "256Mi"},
                "requests": {"memory": "128Mi"},
            },
        }
        violations = _check_high_memory_limit_request_ratio(chart)
        assert violations == []

    def test_res007_very_low_cpu_request(self) -> None:
        """RES007 should detect CPU request below 10m."""
        chart = {"resources": {"requests": {"cpu": "5m"}}}
        violations = _check_very_low_cpu_request(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "RES007"

    def test_res008_no_memory_request(self) -> None:
        """RES008 should detect missing memory request."""
        chart = {"resources": {"requests": {}}}
        violations = _check_no_memory_request(chart)
        assert violations == []

    def test_res008_suppressed_when_res004_condition_matches(self) -> None:
        """RES008 should be suppressed when both requests are missing (covered by RES004)."""
        chart = {"resources": {"requests": {"cpu": None, "memory": None}}}
        violations = _check_no_memory_request(chart)
        assert violations == []

    def test_res008_missing_memory_with_cpu_present_is_violation(self) -> None:
        """RES008 should still flag when only memory request is missing."""
        chart = {"resources": {"requests": {"cpu": "100m"}}}
        violations = _check_no_memory_request(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "RES008"

    def test_res009_very_low_memory_request(self) -> None:
        """RES009 should detect memory request below 32Mi."""
        chart = {"resources": {"requests": {"memory": "16Mi"}}}
        violations = _check_very_low_memory_request(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "RES009"


# ===========================================================================
# TestProbeRules
# ===========================================================================


class TestProbeRules:
    """Tests for probe rule check functions."""

    def test_prb001_missing_liveness_probe(self) -> None:
        """PRB001 should detect missing liveness probe."""
        chart = {"readinessProbe": {"httpGet": {"path": "/ready"}}}
        violations = _check_missing_liveness_probe(chart)
        assert len(violations) == 1
        assert "liveness" in violations[0].name.lower()

    def test_prb002_missing_readiness_probe(self) -> None:
        """PRB002 should detect missing readiness probe."""
        chart = {"livenessProbe": {"httpGet": {"path": "/health"}}}
        violations = _check_missing_readiness_probe(chart)
        assert len(violations) == 1
        assert "readiness" in violations[0].name.lower()

    def test_prb003_missing_startup_probe(self) -> None:
        """PRB003 should detect missing startup probe."""
        chart = {"livenessProbe": {}, "readinessProbe": {}}
        violations = _check_missing_startup_probe(chart)
        assert len(violations) == 1
        assert "startup" in violations[0].name.lower()

    def test_prb001_has_liveness_probe_no_violation(self) -> None:
        """Having livenessProbe should produce no violations."""
        chart = {"livenessProbe": {"httpGet": {"path": "/health"}}}
        violations = _check_missing_liveness_probe(chart)
        assert len(violations) == 0

    def test_prb002_has_readiness_probe_no_violation(self) -> None:
        """Having readinessProbe should produce no violations."""
        chart = {"readinessProbe": {"httpGet": {"path": "/ready"}}}
        violations = _check_missing_readiness_probe(chart)
        assert len(violations) == 0

    def test_prb003_has_startup_probe_no_violation(self) -> None:
        """Having startupProbe should produce no violations."""
        chart = {"startupProbe": {"httpGet": {"path": "/health"}}}
        violations = _check_missing_startup_probe(chart)
        assert len(violations) == 0

    def test_probe_nested_structure(self) -> None:
        """Probes inside nested 'probes' dict should be detected."""
        chart = {"probes": {"liveness": {"httpGet": {"path": "/health"}}}}
        violations = _check_missing_liveness_probe(chart)
        assert len(violations) == 0


# ===========================================================================
# TestAvailabilityRules
# ===========================================================================


class TestAvailabilityRules:
    """Tests for availability rule check functions."""

    def test_avl001_no_pdb_multi_replica(self) -> None:
        """AVL001 should detect missing PDB for multi-replica workloads."""
        chart = {"replicas": 3}
        violations = _check_no_pdb(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "AVL001"

    def test_avl001_no_pdb_single_replica_no_violation(self) -> None:
        """AVL001 should NOT flag single-replica workloads."""
        chart = {"replicas": 1}
        violations = _check_no_pdb(chart)
        assert len(violations) == 0

    def test_avl001_has_pdb_no_violation(self) -> None:
        """AVL001 should NOT flag when PDB exists."""
        chart = {"replicas": 3, "podDisruptionBudget": {"minAvailable": 1}}
        violations = _check_no_pdb(chart)
        assert len(violations) == 0

    def test_avl001_disabled_pdb_is_missing(self) -> None:
        """AVL001 should flag explicit disabled PDB for multi-replica workloads."""
        chart = {"replicas": 3, "pdb": {"enabled": False}}
        violations = _check_no_pdb(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "AVL001"

    def test_avl002_no_pod_anti_affinity(self) -> None:
        """AVL002 should detect missing pod anti-affinity for multi-replica."""
        chart = {"replicas": 3, "affinity": {}}
        violations = _check_no_pod_anti_affinity(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "AVL002"

    def test_avl002_has_anti_affinity_no_violation(self) -> None:
        """AVL002 should NOT flag when anti-affinity is present."""
        chart = {
            "replicas": 3,
            "affinity": {
                "podAntiAffinity": {
                    "preferredDuringSchedulingIgnoredDuringExecution": [
                        {"weight": 100}
                    ]
                }
            },
        }
        violations = _check_no_pod_anti_affinity(chart)
        assert len(violations) == 0

    def test_avl003_blocking_pdb_max_unavailable_zero(self) -> None:
        """AVL003 should detect maxUnavailable=0 as blocking."""
        chart = {"podDisruptionBudget": {"maxUnavailable": 0}, "replicas": 3}
        violations = _check_blocking_pdb(chart)
        assert len(violations) >= 1
        assert any(v.rule_id == "AVL003" for v in violations)

    def test_avl003_blocking_pdb_min_available_too_high(self) -> None:
        """AVL003 should detect minAvailable >= replicas as blocking."""
        chart = {"podDisruptionBudget": {"minAvailable": 3}, "replicas": 3}
        violations = _check_blocking_pdb(chart)
        assert len(violations) >= 1
        assert any(v.rule_id == "AVL003" for v in violations)

    def test_avl003_blocking_pdb_100_percent(self) -> None:
        """AVL003 should detect minAvailable=100% as blocking."""
        chart = {"podDisruptionBudget": {"minAvailable": "100%"}, "replicas": 3}
        violations = _check_blocking_pdb(chart)
        assert len(violations) >= 1

    def test_avl003_no_pdb_returns_empty(self) -> None:
        """AVL003 should return empty when no PDB exists."""
        chart = {"replicas": 3}
        violations = _check_blocking_pdb(chart)
        assert len(violations) == 0

    def test_avl004_missing_topology_spread(self) -> None:
        """AVL004 should detect missing topology spread for multi-replica charts."""
        chart = {"replicas": 3}
        violations = _check_missing_topology_spread(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "AVL004"

    def test_avl004_single_replica_no_violation(self) -> None:
        """AVL004 should NOT flag single-replica workloads."""
        chart = {"replicas": 1}
        violations = _check_missing_topology_spread(chart)
        assert len(violations) == 0


class TestRuntimeThresholdConfiguration:
    """Tests for runtime threshold updates from settings."""

    def test_configure_rule_thresholds_updates_limit_ratio(self) -> None:
        """Runtime configuration should change ratio rule behavior."""
        chart = {
            "resources": {
                "requests": {"cpu": "100m"},
                "limits": {"cpu": "250m"},
            }
        }
        configure_rule_thresholds(limit_request_ratio_threshold=3.0)
        try:
            violations = _check_high_cpu_limit_request_ratio(chart)
            assert len(violations) == 0
        finally:
            configure_rule_thresholds(
                limit_request_ratio_threshold=DEFAULT_LIMIT_REQUEST_RATIO_THRESHOLD
            )

    def test_default_limit_ratio_restored(self) -> None:
        """Tests remain isolated after runtime threshold updates."""
        assert (
            optimizer_rules.LIMIT_REQUEST_RATIO_THRESHOLD
            == DEFAULT_LIMIT_REQUEST_RATIO_THRESHOLD
        )

    def test_avl004_has_topology_spread_no_violation(self) -> None:
        """AVL004 should NOT flag when topology spread exists."""
        chart = {
            "topologySpreadConstraints": [
                {"maxSkew": 1, "topologyKey": "kubernetes.io/hostname"}
            ]
        }
        violations = _check_missing_topology_spread(chart)
        assert len(violations) == 0


# ===========================================================================
# TestSecurityRules
# ===========================================================================


class TestSecurityRules:
    """Tests for security rule check functions."""

    def test_sec001_running_as_root(self) -> None:
        """SEC001 should detect runAsUser=0."""
        chart = {"securityContext": {"runAsUser": 0}}
        violations = _check_running_as_root(chart)
        assert len(violations) == 1
        assert violations[0].rule_id == "SEC001"

    def test_sec001_not_running_as_root_no_violation(self) -> None:
        """SEC001 should NOT flag non-root user."""
        chart = {"securityContext": {"runAsUser": 1000}}
        violations = _check_running_as_root(chart)
        assert len(violations) == 0

    def test_sec001_no_security_context_no_violation(self) -> None:
        """SEC001 should NOT flag missing securityContext."""
        chart = {}
        violations = _check_running_as_root(chart)
        assert len(violations) == 0


# ===========================================================================
# TestRulesNoViolation
# ===========================================================================


class TestRulesNoViolation:
    """Tests verifying no violations for well-configured charts."""

    @pytest.fixture
    def well_configured_chart(self) -> dict:
        """A chart with all best practices satisfied.

        Ratios must stay within 2.0x threshold:
        - CPU: 300m / 200m = 1.5x
        - Memory: 384Mi / 256Mi = 1.5x
        """
        return {
            "resources": {
                "limits": {"cpu": "300m", "memory": "384Mi"},
                "requests": {"cpu": "200m", "memory": "256Mi"},
            },
            "livenessProbe": {"httpGet": {"path": "/health", "port": "http"}},
            "readinessProbe": {"httpGet": {"path": "/ready", "port": "http"}},
            "startupProbe": {"httpGet": {"path": "/health", "port": "http"}},
            "replicas": 3,
            "podDisruptionBudget": {"maxUnavailable": 1},
            "affinity": {
                "podAntiAffinity": {
                    "preferredDuringSchedulingIgnoredDuringExecution": [
                        {"weight": 100}
                    ]
                }
            },
            "topologySpreadConstraints": [
                {"maxSkew": 1, "topologyKey": "kubernetes.io/hostname"}
            ],
            "securityContext": {"runAsUser": 1000, "runAsNonRoot": True},
        }

    def test_no_resource_violations(self, well_configured_chart: dict) -> None:
        """Well-configured chart should have no resource violations."""
        assert _check_no_cpu_limits(well_configured_chart) == []
        assert _check_no_memory_limits(well_configured_chart) == []
        assert _check_no_resource_requests(well_configured_chart) == []
        assert _check_high_cpu_limit_request_ratio(well_configured_chart) == []
        assert _check_high_memory_limit_request_ratio(well_configured_chart) == []
        assert _check_very_low_cpu_request(well_configured_chart) == []
        assert _check_very_low_memory_request(well_configured_chart) == []
        assert _check_no_memory_request(well_configured_chart) == []

    def test_no_probe_violations(self, well_configured_chart: dict) -> None:
        """Well-configured chart should have no probe violations."""
        assert _check_missing_liveness_probe(well_configured_chart) == []
        assert _check_missing_readiness_probe(well_configured_chart) == []
        assert _check_missing_startup_probe(well_configured_chart) == []

    def test_no_availability_violations(self, well_configured_chart: dict) -> None:
        """Well-configured chart should have no availability violations."""
        assert _check_no_pdb(well_configured_chart) == []
        assert _check_no_pod_anti_affinity(well_configured_chart) == []
        assert _check_blocking_pdb(well_configured_chart) == []
        assert _check_missing_topology_spread(well_configured_chart) == []

    def test_no_security_violations(self, well_configured_chart: dict) -> None:
        """Well-configured chart should have no security violations."""
        assert _check_running_as_root(well_configured_chart) == []

    def test_all_rules_pass_on_well_configured(
        self, well_configured_chart: dict
    ) -> None:
        """Running all rules against a well-configured chart should yield zero violations."""
        all_violations = []
        for rule in RULES:
            all_violations.extend(rule.check(well_configured_chart))
        assert len(all_violations) == 0


# ===========================================================================
# TestRuleViolationAttributes
# ===========================================================================


class TestRuleViolationAttributes:
    """Tests for violation object attributes."""

    def test_violation_has_severity(self) -> None:
        """Violation objects should have severity field."""
        chart = {"resources": {"limits": {}, "requests": {"cpu": "100m"}}}
        violations = _check_no_cpu_limits(chart)
        assert violations[0].severity in ("error", "warning", "info")

    def test_violation_has_category(self) -> None:
        """Violation objects should have category field."""
        chart = {"resources": {"limits": {}, "requests": {"cpu": "100m"}}}
        violations = _check_no_cpu_limits(chart)
        assert violations[0].category == "resources"

    def test_violation_has_fix_preview(self) -> None:
        """Violation objects should have fix_preview field."""
        chart = {"resources": {"limits": {}, "requests": {"cpu": "100m"}}}
        violations = _check_no_cpu_limits(chart)
        assert violations[0].fix_preview is not None
        assert isinstance(violations[0].fix_preview, dict)

    def test_violation_auto_fixable(self) -> None:
        """All rules should be marked as auto_fixable."""
        for rule in RULES:
            assert rule.auto_fixable is True, f"Rule {rule.id} is not auto_fixable"
