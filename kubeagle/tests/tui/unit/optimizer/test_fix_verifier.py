"""Unit tests for rendered fix verifier outcomes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kubeagle.constants.enums import QoSClass, Severity
from kubeagle.models.analysis.violation import ViolationResult
from kubeagle.models.charts.chart_info import ChartInfo
from kubeagle.optimizer import fix_verifier
from kubeagle.optimizer.helm_renderer import HelmRenderResult


def _create_local_chart(tmp_path: Path, *, values_file: str | None = None) -> ChartInfo:
    chart_dir = tmp_path / "payments"
    chart_dir.mkdir(parents=True, exist_ok=True)
    (chart_dir / "Chart.yaml").write_text(
        "apiVersion: v2\nname: payments\nversion: 0.1.0\n",
        encoding="utf-8",
    )
    local_values = chart_dir / "values.yaml"
    local_values.write_text("replicaCount: 2\n", encoding="utf-8")

    return ChartInfo(
        name="payments",
        team="payments",
        values_file=values_file or str(local_values),
        namespace="default",
        cpu_request=100.0,
        cpu_limit=200.0,
        memory_request=128 * 1024 * 1024,
        memory_limit=256 * 1024 * 1024,
        qos_class=QoSClass.BURSTABLE,
        has_liveness=False,
        has_readiness=True,
        has_startup=False,
        has_anti_affinity=False,
        has_topology_spread=False,
        has_topology=False,
        pdb_enabled=False,
        pdb_template_exists=False,
        pdb_min_available=None,
        pdb_max_unavailable=None,
        replicas=2,
        priority_class=None,
    )


def _violation(rule_id: str = "PRB001") -> ViolationResult:
    return ViolationResult(
        id=rule_id,
        chart_name="payments",
        rule_name="Missing Liveness Probe",
        rule_id=rule_id,
        category="probes",
        severity=Severity.WARNING,
        description="Container has no liveness probe",
        current_value="Not configured",
        recommended_value="Add livenessProbe",
        fix_available=True,
    )


def _deployment_doc(*, with_liveness: bool) -> dict[str, Any]:
    container: dict[str, Any] = {
        "name": "app",
        "resources": {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "200m", "memory": "256Mi"},
        },
    }
    if with_liveness:
        container["livenessProbe"] = {"httpGet": {"path": "/health", "port": "http"}}
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "payments"},
        "spec": {
            "replicas": 2,
            "template": {
                "spec": {
                    "containers": [container],
                }
            },
        },
    }


def test_fix_verification_result_dataclass() -> None:
    """FixVerificationResult dataclass should be importable and constructible."""
    result = fix_verifier.FixVerificationResult(
        status="verified",
        note="test",
    )
    assert result.status == "verified"
    assert result.note == "test"
    assert result.before_has_violation is None
    assert result.after_has_violation is None
    assert result.suggestions == []


def test_full_fix_bundle_verification_result_dataclass() -> None:
    """FullFixBundleVerificationResult dataclass should be importable and constructible."""
    result = fix_verifier.FullFixBundleVerificationResult(
        status="not_run",
        note="skipped",
    )
    assert result.status == "not_run"
    assert result.per_violation == {}


def test_unverified_from_render_result_with_error(tmp_path: Path) -> None:
    """_unverified_from_render_result should format error details."""
    values_path = tmp_path / "values.yaml"
    values_path.write_text("test: true\n", encoding="utf-8")

    render_result = HelmRenderResult(
        ok=False,
        chart_dir=tmp_path,
        values_file=values_path,
        error_kind="helm_missing",
        error_message="helm binary not found",
    )

    result = fix_verifier._unverified_from_render_result(render_result, "current values")
    assert result.status == "unverified"
    assert "helm_missing" in result.note


def test_unverified_from_render_result_dependency_hint(tmp_path: Path) -> None:
    """Dependency build failures should include parent-chart hint."""
    values_path = tmp_path / "values.yaml"
    values_path.write_text("test: true\n", encoding="utf-8")

    render_result = HelmRenderResult(
        ok=False,
        chart_dir=tmp_path,
        values_file=values_path,
        error_kind="parent_render_failed",
        error_message="missing dependency: parameter-store",
        parent_only_render_attempted=True,
    )

    result = fix_verifier._unverified_from_render_result(render_result, "test")
    assert "Parent-chart-only verification mode" in result.note
