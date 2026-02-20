"""Unit tests for TUI optimizer rules and analysis.

Marked with:
- @pytest.mark.unit: Marks as unit test
- @pytest.mark.fast: Marks as fast test (<100ms)
"""

from __future__ import annotations

import pytest

from kubeagle.optimizer.rules import (
    RULES,
    _check_blocking_pdb,
    _check_missing_liveness_probe,
    _check_missing_readiness_probe,
    _check_missing_startup_probe,
    _check_no_memory_limits,
    _check_no_pdb,
    _check_no_pod_anti_affinity,
    _check_no_resource_requests,
    _check_running_as_root,
    _check_very_low_memory_request,
    get_rule_by_id,
)


@pytest.mark.unit
@pytest.mark.fast
class TestCheckMissingLivenessProbe:
    """Tests for liveness probe check rule."""

    def test_liveness_probe_missing(self):
        """Test detection of missing liveness probe."""
        chart = {
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            }
        }

        violations = _check_missing_liveness_probe(chart)

        assert len(violations) == 1
        assert violations[0].rule_id == "PRB001"

    def test_liveness_probe_present(self):
        """Test that liveness probe presence passes."""
        chart = {
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
            "livenessProbe": {"httpGet": {"path": "/health"}},
        }

        violations = _check_missing_liveness_probe(chart)

        assert len(violations) == 0

    def test_liveness_probe_nested(self):
        """Test nested liveness probe detection."""
        chart = {
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
            "probes": {"liveness": {"httpGet": {"path": "/health"}}},
        }

        violations = _check_missing_liveness_probe(chart)

        assert len(violations) == 0


@pytest.mark.unit
@pytest.mark.fast
class TestCheckMissingReadinessProbe:
    """Tests for readiness probe check rule."""

    def test_readiness_probe_missing(self):
        """Test detection of missing readiness probe."""
        chart = {
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            }
        }

        violations = _check_missing_readiness_probe(chart)

        assert len(violations) == 1
        assert violations[0].rule_id == "PRB002"

    def test_readiness_probe_present(self):
        """Test that readiness probe presence passes."""
        chart = {
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
            "readinessProbe": {"httpGet": {"path": "/ready"}},
        }

        violations = _check_missing_readiness_probe(chart)

        assert len(violations) == 0


@pytest.mark.unit
@pytest.mark.fast
class TestCheckMissingStartupProbe:
    """Tests for startup probe check rule."""

    def test_startup_probe_missing(self):
        """Test detection of missing startup probe."""
        chart = {
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            }
        }

        violations = _check_missing_startup_probe(chart)

        assert len(violations) == 1
        assert violations[0].rule_id == "PRB003"

    def test_startup_probe_present(self):
        """Test that startup probe presence passes."""
        chart = {
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
            "startupProbe": {"httpGet": {"path": "/health"}},
        }

        violations = _check_missing_startup_probe(chart)

        assert len(violations) == 0


@pytest.mark.unit
@pytest.mark.fast
class TestCheckNoPDB:
    """Tests for PDB check rule."""

    def test_pdb_missing(self):
        """Test detection of missing PDB."""
        chart = {
            "replicas": 3,
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
        }

        violations = _check_no_pdb(chart)

        assert len(violations) == 1
        assert violations[0].rule_id == "AVL001"

    def test_pdb_disabled(self):
        """Test detection of disabled PDB using 'pdb' key."""
        chart = {
            "replicas": 3,
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
            "pdb": {"enabled": False},
        }

        violations = _check_no_pdb(chart)

        assert len(violations) == 1
        assert violations[0].rule_id == "AVL001"

    def test_pdb_enabled(self):
        """Test that enabled PDB passes."""
        chart = {
            "replicas": 3,
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
            "podDisruptionBudget": {"minAvailable": 1},
        }

        violations = _check_no_pdb(chart)

        assert len(violations) == 0

    def test_pdb_single_replica_exempt(self):
        """Test that single replica doesn't require PDB."""
        chart = {
            "replicas": 1,
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
        }

        violations = _check_no_pdb(chart)

        assert len(violations) == 0


@pytest.mark.unit
@pytest.mark.fast
class TestCheckBlockingPDB:
    """Tests for blocking PDB check rule."""

    def test_max_unavailable_zero(self):
        """Test detection of maxUnavailable=0."""
        chart = {
            "replicas": 3,
            "podDisruptionBudget": {
                "maxUnavailable": 0,
            },
        }

        violations = _check_blocking_pdb(chart)

        assert len(violations) == 1
        assert violations[0].rule_id == "AVL003"

    def test_max_unavailable_zero_string(self):
        """Test detection of maxUnavailable='0'."""
        chart = {
            "replicas": 3,
            "podDisruptionBudget": {
                "maxUnavailable": "0",
            },
        }

        violations = _check_blocking_pdb(chart)

        assert len(violations) == 1

    def test_min_available_too_high(self):
        """Test detection of minAvailable >= replicas."""
        chart = {
            "replicas": 3,
            "podDisruptionBudget": {
                "minAvailable": 3,
            },
        }

        violations = _check_blocking_pdb(chart)

        assert len(violations) == 1
        assert "minAvailable" in violations[0].name

    def test_min_available_100_percent(self):
        """Test detection of minAvailable=100%."""
        chart = {
            "replicas": 3,
            "podDisruptionBudget": {
                "minAvailable": "100%",
            },
        }

        violations = _check_blocking_pdb(chart)

        assert len(violations) == 1

    def test_valid_pdb(self):
        """Test that PDB with maxUnavailable=1 passes (minAvailable not set)."""
        chart = {
            "replicas": 3,
            "podDisruptionBudget": {
                "maxUnavailable": 1,
            },
        }

        violations = _check_blocking_pdb(chart)

        assert len(violations) == 0

    def test_no_pdb(self):
        """Test that no PDB passes (separate check)."""
        chart = {
            "replicas": 3,
        }

        violations = _check_blocking_pdb(chart)

        assert len(violations) == 0


@pytest.mark.unit
@pytest.mark.fast
class TestCheckNoPodAntiAffinity:
    """Tests for anti-affinity check rule."""

    def test_anti_affinity_missing(self):
        """Test detection of missing anti-affinity."""
        chart = {
            "replicas": 3,
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
        }

        violations = _check_no_pod_anti_affinity(chart)

        assert len(violations) == 1
        assert violations[0].rule_id == "AVL002"

    def test_anti_affinity_present_preferred(self):
        """Test that preferredDuringSchedulingIgnoredDuringExecution with content passes."""
        chart = {
            "replicas": 3,
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
            "affinity": {
                "podAntiAffinity": {
                    "preferredDuringSchedulingIgnoredDuringExecution": [
                        {"weight": 100, "podAffinityTerm": {}}
                    ]
                }
            },
        }

        violations = _check_no_pod_anti_affinity(chart)

        # Note: Implementation checks bool(list) which returns False for empty list
        # but also False for list with content since bool([...]) is True
        # Actually bool([...]) returns True for non-empty list
        assert len(violations) == 0

    def test_anti_affinity_required(self):
        """Test that requiredDuringSchedulingIgnoredDuringExecution with content passes."""
        chart = {
            "replicas": 3,
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
            "affinity": {
                "podAntiAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": [
                        {"labelSelector": {}}
                    ]
                }
            },
        }

        violations = _check_no_pod_anti_affinity(chart)

        assert len(violations) == 0

    def test_single_replica_exempt(self):
        """Test that single replica doesn't require anti-affinity."""
        chart = {
            "replicas": 1,
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
        }

        violations = _check_no_pod_anti_affinity(chart)

        assert len(violations) == 0


@pytest.mark.unit
@pytest.mark.fast
class TestCheckNoResourceRequests:
    """Tests for no resource requests check rule."""

    def test_no_resource_requests(self):
        """Test detection of no resource requests."""
        chart = {}

        violations = _check_no_resource_requests(chart)

        assert len(violations) == 1
        assert violations[0].rule_id == "RES004"

    def test_with_resource_requests(self):
        """Test that resource requests pass."""
        chart = {
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
            }
        }

        violations = _check_no_resource_requests(chart)

        assert len(violations) == 0


@pytest.mark.unit
@pytest.mark.fast
class TestCheckNoMemoryLimits:
    """Tests for no memory limits check rule."""

    def test_no_memory_limits(self):
        """Test detection of no memory limits."""
        chart = {
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m"},
            }
        }

        violations = _check_no_memory_limits(chart)

        assert len(violations) == 1
        assert violations[0].rule_id == "RES003"

    def test_with_memory_limits(self):
        """Test that memory limits pass."""
        chart = {
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            }
        }

        violations = _check_no_memory_limits(chart)

        assert len(violations) == 0


@pytest.mark.unit
@pytest.mark.fast
class TestCheckVeryLowMemoryRequest:
    """Tests for very low memory request check rule."""

    def test_very_low_memory(self):
        """Test detection of very low memory request."""
        chart = {
            "resources": {
                "requests": {
                    "memory": "16Mi",  # Below 32Mi threshold
                    "cpu": "100m",
                },
                "limits": {
                    "memory": "256Mi",
                    "cpu": "500m",
                },
            },
        }

        violations = _check_very_low_memory_request(chart)

        assert len(violations) == 1
        assert violations[0].rule_id == "RES009"

    def test_memory_at_threshold(self):
        """Test that memory at threshold passes."""
        chart = {
            "resources": {
                "requests": {
                    "memory": "32Mi",  # At threshold
                    "cpu": "100m",
                },
                "limits": {
                    "memory": "256Mi",
                    "cpu": "500m",
                },
            },
        }

        violations = _check_very_low_memory_request(chart)

        assert len(violations) == 0

    def test_adequate_memory(self):
        """Test that adequate memory passes."""
        chart = {
            "resources": {
                "requests": {
                    "memory": "128Mi",
                    "cpu": "100m",
                },
                "limits": {
                    "memory": "256Mi",
                    "cpu": "500m",
                },
            },
        }

        violations = _check_very_low_memory_request(chart)

        assert len(violations) == 0


@pytest.mark.unit
@pytest.mark.fast
class TestCheckRunningAsRoot:
    """Tests for running as root check rule."""

    def test_running_as_root(self):
        """Test detection of running as root."""
        chart = {
            "securityContext": {
                "runAsUser": 0,
            }
        }

        violations = _check_running_as_root(chart)

        assert len(violations) == 1
        assert violations[0].rule_id == "SEC001"

    def test_not_running_as_root(self):
        """Test that non-root user passes."""
        chart = {
            "securityContext": {
                "runAsUser": 1000,
            }
        }

        violations = _check_running_as_root(chart)

        assert len(violations) == 0


@pytest.mark.unit
@pytest.mark.fast
class TestRulesCollection:
    """Tests for the rules collection."""

    def test_all_rules_defined(self):
        """Test that all expected rules are defined."""
        rule_ids = [rule.id for rule in RULES]

        expected_rules = [
            "RES002",  # No CPU Limits
            "RES003",  # No Memory Limits
            "RES004",  # No Resource Requests
            "RES005",  # High CPU Limit/Request Ratio
            "RES006",  # High Memory Limit/Request Ratio
            "RES007",  # Very Low CPU Request
            "RES008",  # No Memory Request
            "RES009",  # Very Low Memory Request
            "PRB001",  # Missing Liveness Probe
            "PRB002",  # Missing Readiness Probe
            "PRB003",  # Missing Startup Probe
            "AVL001",  # No Pod Disruption Budget
            "AVL002",  # No Pod Anti-Affinity
            "AVL003",  # Blocking PDB Configuration
            "AVL004",  # Missing Topology Spread
            "SEC001",  # Running As Root
        ]

        for rule_id in expected_rules:
            assert rule_id in rule_ids, f"Rule {rule_id} not found in RULES"

    def test_all_categories_present(self):
        """Test all expected categories are present in RULES."""
        categories = {r.category for r in RULES}
        expected = {"resources", "probes", "availability", "security"}
        assert expected == categories

    def test_get_rule_by_id(self):
        """Test get_rule_by_id returns correct rule."""
        rule = get_rule_by_id("PRB001")

        assert rule is not None
        assert rule.id == "PRB001"
        assert rule.name == "Missing Liveness Probe"

    def test_get_rule_by_id_not_found(self):
        """Test get_rule_by_id returns None for unknown rule."""
        rule = get_rule_by_id("UNKNOWN")

        assert rule is None


@pytest.mark.unit
@pytest.mark.fast
class TestOptimizationViolation:
    """Tests for OptimizationViolation dataclass."""

    def test_violation_properties(self):
        """Test that violations have all required properties."""
        chart = {}

        violations = _check_no_resource_requests(chart)

        assert len(violations) == 1
        violation = violations[0]

        assert violation.rule_id == "RES004"
        assert violation.name == "No Resource Requests"
        assert violation.description is not None
        assert violation.severity in ["error", "warning", "info"]
        assert violation.category == "resources"

    def test_violation_fix_preview(self):
        """Test that violations include fix preview."""
        chart = {}

        violations = _check_no_resource_requests(chart)

        assert len(violations) == 1
        assert violations[0].fix_preview is not None

    def test_violation_auto_fixable(self):
        """Test that violations indicate if auto-fixable."""
        chart = {}

        violations = _check_no_resource_requests(chart)

        assert len(violations) == 1
        assert violations[0].auto_fixable is True


@pytest.mark.unit
@pytest.mark.fast
class TestViolationSeverity:
    """Tests for violation severity levels."""

    def test_error_severity(self):
        """Test violations with ERROR severity."""
        chart = {"securityContext": {"runAsUser": 0}}

        violations = _check_running_as_root(chart)

        assert len(violations) == 1
        assert violations[0].severity == "error"

    def test_warning_severity(self):
        """Test violations with WARNING severity."""
        chart = {
            "resources": {
                "requests": {"memory": "16Mi", "cpu": "100m"},
                "limits": {"memory": "256Mi", "cpu": "500m"},
            }
        }

        violations = _check_very_low_memory_request(chart)

        assert len(violations) == 1
        assert violations[0].severity == "warning"

    def test_info_severity(self):
        """Test violations with INFO severity."""
        chart = {"replicas": 3}

        violations = _check_no_pod_anti_affinity(chart)

        assert len(violations) == 1
        assert violations[0].severity == "info"
