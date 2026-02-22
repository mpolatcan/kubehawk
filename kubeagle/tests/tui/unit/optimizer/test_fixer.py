"""Tests for fix generator."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kubeagle.optimizer.fixer import (
    FixGenerator,
    _deep_merge,
    apply_fix,
)


class TestFixGenerator:
    """Tests for FixGenerator class."""

    @pytest.fixture
    def generator(self) -> FixGenerator:
        """Create FixGenerator instance."""
        return FixGenerator()

    def test_generator_init(self, generator: FixGenerator) -> None:
        """Test FixGenerator initialization."""
        assert isinstance(generator, FixGenerator)

    def test_generate_fix_res002(self, generator: FixGenerator) -> None:
        """Test generating fix for RES002 (No CPU Limits)."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="RES002",
            name="No CPU Limits",
            description="Chart has no CPU limits",
            category="resources",
            severity="warning",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {"resources": {"requests": {"cpu": "100m"}}}

        fix = generator.generate_fix(violation, chart_data)

        assert fix is not None
        assert "resources" in fix
        assert "limits" in fix["resources"]
        assert "cpu" in fix["resources"]["limits"]

    def test_generate_fix_res003(self, generator: FixGenerator) -> None:
        """Test generating fix for RES003 (No Memory Limits)."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="RES003",
            name="No Memory Limits",
            description="Chart has no Memory limits",
            category="resources",
            severity="warning",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {"resources": {"requests": {"memory": "128Mi"}}}

        fix = generator.generate_fix(violation, chart_data)

        assert fix is not None
        assert "resources" in fix
        assert "limits" in fix["resources"]
        assert "memory" in fix["resources"]["limits"]

    def test_generate_fix_res004(self, generator: FixGenerator) -> None:
        """Test generating fix for RES004 (No Resource Requests)."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="RES004",
            name="No Resource Requests",
            description="Chart has no resource requests",
            category="resources",
            severity="warning",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {}

        fix = generator.generate_fix(violation, chart_data)

        assert fix is not None
        assert "resources" in fix
        assert "requests" in fix["resources"]
        assert "cpu" in fix["resources"]["requests"]
        assert "memory" in fix["resources"]["requests"]
        assert "limits" in fix["resources"]
        assert "cpu" in fix["resources"]["limits"]
        assert "memory" in fix["resources"]["limits"]

    def test_generate_fix_res005_increases_request_with_burstable_ratio(
        self, generator: FixGenerator
    ) -> None:
        """RES005 always increases request (limit / 1.5) — never decreases limit."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="RES005",
            name="High CPU Limit/Request Ratio",
            description="CPU ratio is too high",
            category="resources",
            severity="warning",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {"resources": {"requests": {"cpu": "100m"}, "limits": {"cpu": "300m"}}}

        fix = generator.generate_fix(violation, chart_data)

        assert fix is not None
        assert fix["resources"]["requests"]["cpu"] == "200m"

    def test_generate_fix_res006_increases_request_with_burstable_ratio(
        self, generator: FixGenerator
    ) -> None:
        """RES006 always increases request (limit / 1.5) — never decreases limit."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="RES006",
            name="High Memory Limit/Request Ratio",
            description="Memory ratio is too high",
            category="resources",
            severity="warning",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {"resources": {"requests": {"memory": "128Mi"}, "limits": {"memory": "512Mi"}}}

        fix = generator.generate_fix(violation, chart_data)

        assert fix is not None
        assert fix["resources"]["requests"]["memory"] == "341Mi"

    def test_generate_fix_res005_burstable_2x_strategy(
        self, generator: FixGenerator
    ) -> None:
        """RES005 should honor Burstable 2.0x strategy (limit / 2.0)."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="RES005",
            name="High CPU Limit/Request Ratio",
            description="CPU ratio is too high",
            category="resources",
            severity="warning",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {"resources": {"requests": {"cpu": "100m"}, "limits": {"cpu": "400m"}}}

        fix = generator.generate_fix(
            violation,
            chart_data,
            ratio_strategy="burstable_2_0",
        )

        assert fix is not None
        assert fix["resources"]["requests"]["cpu"] == "200m"

    def test_generate_fix_res006_guaranteed_strategy(
        self, generator: FixGenerator
    ) -> None:
        """RES006 Guaranteed strategy sets request = limit."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="RES006",
            name="High Memory Limit/Request Ratio",
            description="Memory ratio is too high",
            category="resources",
            severity="warning",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {"resources": {"requests": {"memory": "128Mi"}, "limits": {"memory": "512Mi"}}}

        fix = generator.generate_fix(
            violation,
            chart_data,
            ratio_strategy="guaranteed",
        )

        assert fix is not None
        assert fix["resources"]["requests"]["memory"] == "512Mi"

    def test_generate_fix_res005_preserves_limit(
        self, generator: FixGenerator
    ) -> None:
        """RES005 should increase request from current limit, preserving limit."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="RES005",
            name="High CPU Limit/Request Ratio",
            description="CPU ratio is too high",
            category="resources",
            severity="warning",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {"resources": {"requests": {"cpu": "100m"}, "limits": {"cpu": "300m"}}}

        fix = generator.generate_fix(
            violation,
            chart_data,
            ratio_strategy="burstable_1_5",
        )

        assert fix is not None
        assert "limits" not in fix["resources"]
        assert fix["resources"]["requests"]["cpu"] == "200m"

    def test_generate_fix_res006_target_request_guaranteed(
        self, generator: FixGenerator
    ) -> None:
        """RES006 request target with Guaranteed should set request to current limit."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="RES006",
            name="High Memory Limit/Request Ratio",
            description="Memory ratio is too high",
            category="resources",
            severity="warning",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {
            "resources": {
                "requests": {"memory": "128Mi"},
                "limits": {"memory": "512Mi"},
            }
        }

        fix = generator.generate_fix(
            violation,
            chart_data,
            ratio_strategy="guaranteed",
        )

        assert fix is not None
        assert fix["resources"]["requests"]["memory"] == "512Mi"

    def test_generate_fix_prb003(self, generator: FixGenerator) -> None:
        """Test generating fix for PRB003 (Missing Startup Probe)."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="PRB003",
            name="Missing Startup Probe",
            description="Chart has no startup probe",
            category="probes",
            severity="warning",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {}

        fix = generator.generate_fix(violation, chart_data)

        assert fix is not None
        assert "startupProbe" in fix
        assert "httpGet" in fix["startupProbe"]

    def test_generate_fix_prb001_applies_probe_overrides(
        self, generator: FixGenerator
    ) -> None:
        """PRB001 should honor path/port and timing override settings."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="PRB001",
            name="Missing Liveness Probe",
            description="Chart has no liveness probe",
            category="probes",
            severity="warning",
            fix_preview={},
            auto_fixable=True,
        )

        fix = generator.generate_fix(
            violation,
            {},
            probe_settings={
                "path": "/livez",
                "port": "8080",
                "initialDelaySeconds": 20,
                "timeoutSeconds": 5,
                "periodSeconds": 11,
                "failureThreshold": 4,
            },
        )

        assert fix is not None
        probe = fix["livenessProbe"]
        assert probe["httpGet"]["path"] == "/livez"
        assert probe["httpGet"]["port"] == "8080"
        assert probe["initialDelaySeconds"] == 20
        assert probe["timeoutSeconds"] == 5
        assert probe["periodSeconds"] == 11
        assert probe["failureThreshold"] == 4

    def test_generate_fix_avl004(self, generator: FixGenerator) -> None:
        """Test generating fix for AVL004 (Missing Topology Spread)."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="AVL004",
            name="Missing Topology Spread",
            description="Chart has no topology spread",
            category="availability",
            severity="warning",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {"chart_name": "my-app"}

        fix = generator.generate_fix(violation, chart_data)

        assert fix is not None
        assert "topologySpreadConstraints" in fix

    def test_generate_fix_sec001(self, generator: FixGenerator) -> None:
        """Test generating fix for SEC001 (Running As Root)."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="SEC001",
            name="Running As Root",
            description="Chart runs as root",
            category="security",
            severity="error",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {}

        fix = generator.generate_fix(violation, chart_data)

        assert fix is not None
        assert "securityContext" in fix
        assert "runAsNonRoot" in fix["securityContext"]

    def test_generate_fix_unknown_rule(self, generator: FixGenerator) -> None:
        """Test generating fix for unknown rule returns None."""
        violation = pytest.importorskip(
            "kubeagle.optimizer.rules"
        ).OptimizationViolation(
            rule_id="UNKNOWN",
            name="Unknown Rule",
            description="Unknown rule",
            category="unknown",
            severity="info",
            fix_preview={},
            auto_fixable=True,
        )
        chart_data = {}

        fix = generator.generate_fix(violation, chart_data)

        assert fix is None

    def test_double_cpu(self) -> None:
        """Test _double_cpu helper."""
        assert FixGenerator._double_cpu("100m") == "200m"
        # 500m * 2 = 1000m = 1 core, so it converts to whole number
        assert FixGenerator._double_cpu("500m") == "1"
        assert FixGenerator._double_cpu("invalid") == "500m"

    def test_double_memory(self) -> None:
        """Test _double_memory helper."""
        result = FixGenerator._double_memory("128Mi")
        assert result == "256Mi"

        # 512Mi * 2 = 1024Mi = 1Gi, so it converts to Gi
        result = FixGenerator._double_memory("512Mi")
        assert result == "1Gi"


class TestDeepMerge:
    """Tests for _deep_merge function."""

    def test_deep_merge_simple(self) -> None:
        """Test deep merge with simple dict."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}

        result = _deep_merge(base, override)

        assert result["a"] == 1
        assert result["b"] == 3
        assert result["c"] == 4

    def test_deep_merge_nested(self) -> None:
        """Test deep merge with nested dicts."""
        base = {"resources": {"requests": {"cpu": "100m"}}}
        override = {"resources": {"limits": {"cpu": "200m"}}}

        result = _deep_merge(base, override)

        assert result["resources"]["requests"]["cpu"] == "100m"
        assert result["resources"]["limits"]["cpu"] == "200m"


class TestApplyFix:
    """Tests for apply_fix function."""

    def test_apply_fix_does_not_create_backup_artifacts(self, tmp_path: Path) -> None:
        """apply_fix should not create disk backup files."""
        values_file = tmp_path / "values.yaml"
        values_file.write_text("key: value")

        fix = {"new_key": "new_value"}

        result = apply_fix(str(values_file), fix)

        assert result is True
        # No backup artifacts should be left on disk.
        backups = list(tmp_path.glob("values.yaml.backup.*"))
        assert len(backups) == 0

    def test_apply_fix_updates_file(self, tmp_path: Path) -> None:
        """Test apply_fix updates the values file."""
        values_file = tmp_path / "values.yaml"
        values_file.write_text("key: value")

        fix = {"new_key": "new_value"}

        apply_fix(str(values_file), fix)

        data = yaml.safe_load(values_file.read_text())
        assert data["key"] == "value"
        assert data["new_key"] == "new_value"

    def test_apply_fix_file_not_found(self, tmp_path: Path) -> None:
        """Test apply_fix returns False for nonexistent file."""
        nonexistent = tmp_path / "nonexistent.yaml"

        result = apply_fix(str(nonexistent), {"key": "value"})

        assert result is False

    def test_apply_fix_invalid_yaml(self, tmp_path: Path) -> None:
        """Test apply_fix handles invalid YAML gracefully."""
        values_file = tmp_path / "values.yaml"
        values_file.write_text("invalid: yaml: content: [[[")

        result = apply_fix(str(values_file), {"key": "value"})

        assert result is False
