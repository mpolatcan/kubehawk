"""Fix verification using rendered manifests as the source of truth."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from kubeagle.models.analysis.violation import ViolationResult
from kubeagle.models.charts.chart_info import ChartInfo
from kubeagle.optimizer.helm_renderer import HelmRenderResult, render_chart
from kubeagle.optimizer.rendered_rule_input import (
    build_rule_inputs_from_rendered,
)
from kubeagle.optimizer.rules import get_rule_by_id


@dataclass(slots=True)
class FixVerificationResult:
    """Verification state for a single violation fix action."""

    status: str  # verified|unresolved|unverified|not_run
    note: str = ""
    before_has_violation: bool | None = None
    after_has_violation: bool | None = None
    suggestions: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class FullFixBundleVerificationResult:
    """Verification state for chart-level full fix bundle."""

    status: str  # verified|unresolved|unverified|not_run
    note: str = ""
    per_violation: dict[str, FixVerificationResult] = field(default_factory=dict)


def _resolve_local_paths(chart: ChartInfo) -> tuple[Path, Path] | None:
    values_file = str(chart.values_file or "")
    if not values_file or values_file.startswith("cluster:"):
        return None
    values_path = Path(values_file).expanduser().resolve()
    if not values_path.exists():
        return None
    chart_dir = values_path.parent
    if not (chart_dir / "Chart.yaml").exists():
        return None
    return chart_dir, values_path


def _read_values_as_mapping(values_path: Path) -> dict[str, Any] | None:
    try:
        raw = values_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw) or {}
    except (OSError, yaml.YAMLError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            nested_base = base[key]
            nested_override = value
            if isinstance(nested_base, dict) and isinstance(nested_override, dict):
                _deep_merge(nested_base, nested_override)
            else:
                base[key] = copy.deepcopy(value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _evaluate_rule_from_render(
    *,
    violation: ViolationResult,
    chart_name: str,
    before_render: HelmRenderResult,
    after_render: HelmRenderResult,
) -> tuple[bool | None, bool | None]:
    before_inputs = build_rule_inputs_from_rendered(before_render.docs, chart_name=chart_name)
    after_inputs = build_rule_inputs_from_rendered(after_render.docs, chart_name=chart_name)
    before_has = _rule_matches(violation.rule_id, before_inputs)
    after_has = _rule_matches(violation.rule_id, after_inputs)
    return before_has, after_has


def _rule_matches(rule_id: str, inputs: list[dict[str, Any]]) -> bool | None:
    rule = get_rule_by_id(rule_id)
    if rule is None:
        return None
    if not inputs:
        return False
    try:
        return any(bool(rule.check(item)) for item in inputs)
    except Exception:
        return None


def _unverified_from_render_result(
    render_result: HelmRenderResult,
    source_label: str,
) -> FixVerificationResult:
    error_parts = []
    if render_result.error_kind:
        error_parts.append(render_result.error_kind)
    if render_result.error_message:
        error_parts.append(render_result.error_message)
    elif render_result.stderr:
        error_parts.append(render_result.stderr.strip())
    error_text = " | ".join(part for part in error_parts if part)
    if not error_text:
        error_text = "unknown render error"
    dependency_hint = ""
    if (
        render_result.error_kind in {"parent_render_failed", "parent_render_setup_failed"}
        or "missing in charts/" in error_text.lower()
    ):
        dependency_hint = (
            " Parent-chart-only verification mode could not render this chart."
        )
    return FixVerificationResult(
        status="unverified",
        note=(
            f"Verification failed while rendering {source_label}: "
            f"{error_text}{dependency_hint}"
        ),
    )


def _evaluate_bundle_violation_results(
    *,
    violations: list[ViolationResult],
    inputs: list[dict[str, Any]],
    unresolved_note: str,
    resolved_note: str,
    unverified_note: str,
) -> FullFixBundleVerificationResult:
    per_violation: dict[str, FixVerificationResult] = {}
    counts = {"verified": 0, "unresolved": 0, "unverified": 0}
    for violation in violations:
        has_violation = _rule_matches(violation.rule_id, inputs)
        if has_violation is None:
            result = FixVerificationResult(
                status="unverified",
                note=unverified_note,
            )
            counts["unverified"] += 1
        elif has_violation:
            result = FixVerificationResult(
                status="unresolved",
                note=unresolved_note,
                after_has_violation=True,
            )
            counts["unresolved"] += 1
        else:
            result = FixVerificationResult(
                status="verified",
                note=resolved_note,
                after_has_violation=False,
            )
            counts["verified"] += 1
        per_violation[_violation_identity_key(violation)] = result

    aggregate_status = "verified"
    if counts["unverified"] > 0:
        aggregate_status = "unverified"
    elif counts["unresolved"] > 0:
        aggregate_status = "unresolved"
    note = (
        f"Bundle verification: {counts['verified']} verified, "
        f"{counts['unresolved']} unresolved, "
        f"{counts['unverified']} unverified."
    )
    return FullFixBundleVerificationResult(
        status=aggregate_status,
        note=note,
        per_violation=per_violation,
    )


def _violation_identity_key(violation: ViolationResult) -> str:
    """Stable key for chart-level per-violation verification mapping."""
    return (
        f"{violation.chart_name}|{violation.rule_id}|"
        f"{violation.rule_name}|{violation.current_value}"
    )
