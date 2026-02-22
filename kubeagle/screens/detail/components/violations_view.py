"""Violations view component — DataTable + fix preview panel.

Extracted from the original OptimizerScreen. Handles all violations-specific UI:
filter bar, search, violations table, fix preview panel, KPI summary, and fix application.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import difflib
import hashlib
import json
import logging
import re
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, TypedDict, cast

import yaml
from rich.markup import escape
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.events import Resize
from textual.message import Message
from textual.screen import ModalScreen
from textual.timer import Timer

from kubeagle.constants.enums import Severity
from kubeagle.constants.limits import (
    AI_FIX_BULK_PARALLELISM_MAX,
    AI_FIX_BULK_PARALLELISM_MIN,
)
from kubeagle.constants.ui import (
    CATEGORIES as FILTER_CATEGORIES,
    SEVERITIES as FILTER_SEVERITIES,
)
from kubeagle.models.analysis.violation import ViolationResult
from kubeagle.optimizer.fix_verifier import (
    FixVerificationResult,
    FullFixBundleVerificationResult,
)
from kubeagle.optimizer.full_ai_fixer import (
    AIFullFixResult,
    AIFullFixStagedArtifact,
    generate_ai_full_fix_for_chart,
    generate_ai_full_fix_for_violation,
)
from kubeagle.optimizer.full_fix_applier import (
    apply_full_fix_bundle_atomic,
    apply_full_fix_bundle_via_staged_replace,
    parse_template_patches_from_bundle_diff,
    parse_values_patch_yaml,
    promote_staged_workspace_atomic,
)
from kubeagle.optimizer.llm_cli_runner import LLMProvider
from kubeagle.optimizer.llm_patch_protocol import FullFixTemplatePatch
from kubeagle.optimizer.template_patch_suggester import (
    format_wiring_suggestions_markdown,
)
from kubeagle.screens.detail.components.ai_full_fix_bulk_modal import (
    AIFullFixBulkModal,
    AIFullFixBulkModalResult,
    ChartBundleEditorState,
)
from kubeagle.screens.detail.components.ai_full_fix_modal import (
    AIFullFixModal,
    AIFullFixModalResult,
)
from kubeagle.screens.detail.components.fix_details_modal import (
    BundleDiffModal,
    FixDetailsModal,
)
from kubeagle.screens.detail.components.recommendations_view import (
    RecommendationsView,
)
from kubeagle.screens.detail.components.resource_impact_view import (
    ResourceImpactView,
)
from kubeagle.screens.detail.config import (
    OPTIMIZER_HEADER_TOOLTIPS,
    OPTIMIZER_TABLE_COLUMNS,
    SORT_CHART,
    SORT_RULE,
    SORT_SELECT_OPTIONS,
    SORT_SEVERITY,
    SORT_TEAM,
    VIEW_IMPACT,
    VIEW_OPTIONS,
    VIEW_VIOLATIONS,
)
from kubeagle.widgets import (
    CustomButton,
    CustomConfirmDialog,
    CustomContainer,
    CustomDataTable,
    CustomHorizontal,
    CustomInput,
    CustomKPI,
    CustomLoadingIndicator,
    CustomMarkdownViewer as TextualMarkdownViewer,
    CustomRichLog,
    CustomSelect as Select,
    CustomSelectionList,
    CustomStatic,
    CustomTree,
    CustomVertical,
)

if TYPE_CHECKING:
    from kubeagle.app import EKSHelmReporterApp
    from kubeagle.models.charts.chart_info import ChartInfo
    from kubeagle.models.optimization import UnifiedOptimizerController

logger = logging.getLogger(__name__)

# Filter options
CATEGORIES = [(value, value.title()) for value in FILTER_CATEGORIES]
SEVERITIES = [(value, value.title()) for value in FILTER_SEVERITIES]
SORT_DIRECTION_OPTIONS: list[tuple[str, str]] = [
    ("Asc", "asc"),
    ("Desc", "desc"),
]

RATIO_STRATEGY_BURSTABLE_15 = "burstable_1_5"
RATIO_STRATEGY_BURSTABLE_20 = "burstable_2_0"
RATIO_STRATEGY_GUARANTEED = "guaranteed"
RATIO_STRATEGY_INHERIT_GLOBAL = "inherit_global"
RATIO_TARGET_LIMIT = "limit"
RATIO_TARGET_REQUEST = "request"
RATIO_TARGET_INHERIT_GLOBAL = "inherit_global"

_RATIO_STRATEGY_LABELS: dict[str, str] = {
    RATIO_STRATEGY_BURSTABLE_15: "Burstable 1.5x",
    RATIO_STRATEGY_BURSTABLE_20: "Burstable 2.0x",
    RATIO_STRATEGY_GUARANTEED: "Guaranteed (req = limit)",
}
_RATIO_TARGET_LABELS: dict[str, str] = {
    RATIO_TARGET_LIMIT: "Fix Limit",
    RATIO_TARGET_REQUEST: "Fix Request",
}

_RATIO_RULE_IDS: set[str] = {"RES005", "RES006"}
_PROBE_RULE_IDS: set[str] = {"PRB001", "PRB002", "PRB003"}
_PROBE_INT_FIELDS: tuple[str, ...] = (
    "initialDelaySeconds",
    "timeoutSeconds",
    "periodSeconds",
    "successThreshold",
    "failureThreshold",
    "terminationGracePeriodSeconds",
)
_PROBE_SETTING_FIELDS: tuple[str, ...] = (
    "path",
    "port",
    "scheme",
    "host",
    "header",
    "initialDelaySeconds",
    "timeoutSeconds",
    "periodSeconds",
    "successThreshold",
    "failureThreshold",
    "terminationGracePeriodSeconds",
)

_FIX_DEFAULT_SETTINGS: dict[str, str] = {
    "cpu_request": "100m",
    "cpu_limit": "500m",
    "memory_request": "128Mi",
    "memory_limit": "512Mi",
    "replica_count": "2",
    "pdb_min_available": "1",
    "pdb_max_unavailable": "1",
    "topology_max_skew": "1",
    "topology_key": "kubernetes.io/hostname",
    "topology_when_unsatisfiable": "ScheduleAnyway",
    "workload_label_key": "app",
    "anti_affinity_weight": "100",
    "anti_affinity_topology_key": "kubernetes.io/hostname",
}

_DESCRIPTION_FALLBACK_BY_RULE: dict[str, str] = {
    "RES005": (
        "CPU limit/request ratio is higher than recommended and may cause inefficient scheduling."
    ),
    "RES006": (
        "Memory limit/request ratio is higher than recommended and may cause inefficient reservation."
    ),
    "PRB001": (
        "Liveness probe is missing or incomplete. Pods may remain unhealthy without automated restart."
    ),
    "PRB002": (
        "Readiness probe is missing or incomplete. Traffic may be routed to pods before they are ready."
    ),
    "PRB003": (
        "Startup probe is missing or incomplete. Slow-starting workloads may restart before initialization."
    ),
}

_BUNDLE_VERIFICATION_COUNTS_PATTERN = re.compile(
    (
        r"bundle verification:\s*(\d+)\s+verified,\s*(\d+)\s+"
        r"(?:wiring issue(?:s)?|unresolved),\s*(\d+)\s+unverified"
    ),
    re.IGNORECASE,
)


def _prefixed_option(prefix: str, label: str) -> str:
    return f"{prefix}: {label}"


def _normalize_prompt_override(value: object) -> str:
    return str(value or "").replace("\r\n", "\n").strip()


def _hash_prompt_override(value: str) -> str:
    normalized = _normalize_prompt_override(value)
    if not normalized:
        return "none"
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _full_fix_template_diff_text(
    template_patches: list[FullFixTemplatePatch] | None,
    *,
    chart_dir: Path | None = None,
) -> str:
    if not template_patches:
        return ""
    sections: list[str] = []
    for patch in template_patches:
        if chart_dir is not None and patch.updated_content.strip():
            target_path = (chart_dir / str(patch.file).strip()).resolve()
            if str(target_path).startswith(str(chart_dir)) and target_path.exists():
                try:
                    current_template = target_path.read_text(encoding="utf-8")
                    updated_template = patch.updated_content
                    if updated_template and not updated_template.endswith("\n"):
                        updated_template = f"{updated_template}\n"
                    diff_lines = list(
                        difflib.unified_diff(
                            current_template.splitlines(),
                            updated_template.splitlines(),
                            fromfile=f"a/{patch.file}",
                            tofile=f"b/{patch.file}",
                            lineterm="",
                        )
                    )
                    if diff_lines:
                        sections.append("\n".join(diff_lines).rstrip())
                        continue
                except OSError:
                    pass
        if patch.unified_diff.strip():
            sections.append(patch.unified_diff.rstrip())
    return "\n\n".join(sections).strip()


def _full_fix_values_yaml_text(values_patch: dict[str, Any] | None) -> str:
    if not values_patch:
        return "{}\n"
    dumped = yaml.safe_dump(values_patch, sort_keys=False)
    return dumped if dumped.endswith("\n") else f"{dumped}\n"


def _compact_ai_full_fix_status(
    *,
    ai_result: AIFullFixResult,
    verification: FullFixBundleVerificationResult | None,
    violation_count: int,
    provider_label: str = "",
    model_label: str = "",
) -> str:
    _ = violation_count
    provider = ai_result.provider or "none"
    tried = ", ".join(ai_result.tried_providers) if ai_result.tried_providers else provider
    lines: list[str] = []
    if provider_label:
        lines.append(f"Provider: {provider_label}")
    if model_label:
        lines.append(f"Model: {model_label}")
    if ai_result.ok:
        lines.extend(
            [
                f"LLM: COMPLETED via {provider} (tried: {tried})",
                f"Bundle: {ai_result.status.upper()}",
            ]
        )
    else:
        first_error = ai_result.errors[0] if ai_result.errors else ai_result.note or "unknown failure"
        friendly_error = _friendly_ai_error(first_error)
        lines.extend(
            [
                f"LLM: FAILED (tried: {tried})",
                f"Details: {friendly_error[:220]}",
            ]
        )
    if verification is not None:
        lines.append(f"Render Verification: {verification.status.upper()}")
        lines.append(f"Verification Details: {verification.note}")
        if verification.status != "verified":
            hint = _bundle_verification_hint(verification.note)
            if hint:
                lines.append(f"Hint: {hint}")
    return "\n".join(lines).strip()


def _friendly_ai_error(error_text: str) -> str:
    normalized = str(error_text or "").strip()
    lowered = normalized.lower()
    if not lowered:
        return "Unknown AI generation failure."
    if "patch hunk context mismatch" in lowered:
        return (
            "AI patch does not match current template lines. "
            "Regenerate Chart so patch hunks are rebuilt from current files."
        )
    if "llm response schema validation failed" in lowered or "response is not valid json" in lowered:
        return "AI returned invalid response format. Regenerate Chart."
    if "timed out" in lowered:
        return "AI provider timed out. Try regenerate or switch provider/model."
    if "command not found" in lowered or "no such file or directory" in lowered:
        return "Selected AI CLI is unavailable in environment."
    return normalized


def _bundle_verification_hint(note: str) -> str:
    normalized = str(note or "").lower()
    if "hunk context does not match target file" in normalized or "hunk removal does not match target file" in normalized:
        return (
            "Template diff context is stale for the current file. "
            "Regenerate the chart bundle or edit diff hunks so removed/context lines match the target template."
        )
    if "patch target file not found" in normalized:
        return "Patch references a template file that does not exist in the chart's templates/ directory."
    if "patch file is outside allowed set" in normalized:
        return "Patch file is outside allowed templates/. Keep template patches only under templates/*.yaml|yml|tpl."
    if "template diff parse error" in normalized:
        return "Unified diff format is invalid. Ensure each file has ---/+++ headers and @@ hunk sections."
    if "values patch parse error" in normalized:
        return "Values patch YAML is invalid. Fix YAML indentation/structure and re-verify."
    if "render failed" in normalized:
        return "Helm render failed after staging. Review chart render error details and dependency/template assumptions."
    return ""


def _is_ratio_violation(violation: ViolationResult) -> bool:
    return (violation.rule_id or "").upper() in _RATIO_RULE_IDS


def _is_probe_violation(violation: ViolationResult) -> bool:
    return (violation.rule_id or "").upper() in _PROBE_RULE_IDS


def _normalize_description_text(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()


def _description_fallback_text(violation: ViolationResult) -> str:
    rule_id = (violation.rule_id or "").upper()
    if rule_id in _DESCRIPTION_FALLBACK_BY_RULE:
        return _DESCRIPTION_FALLBACK_BY_RULE[rule_id]
    safe_rule_name = _normalize_description_text(violation.rule_name) or "This rule"
    return (
        f"{safe_rule_name} detected a configuration issue. "
        "Review current and recommended values below."
    )


def _violation_description_lines(violation: ViolationResult) -> tuple[str, ...]:
    description = _normalize_description_text(violation.description)
    if not description:
        description = _description_fallback_text(violation)

    current_value = _normalize_description_text(violation.current_value)
    recommended_value = _normalize_description_text(violation.recommended_value)

    lines = [
        "### Description",
        description,
    ]
    if current_value:
        safe_current_value = current_value.replace("`", "'")
        lines.append(f"- **Current State:** `{safe_current_value}`")
    if recommended_value:
        safe_recommended_value = recommended_value.replace("`", "'")
        lines.append(f"- **Recommended State:** `{safe_recommended_value}`")
    lines.append("")
    return tuple(lines)


def _ratio_strategy_label(strategy: str | None) -> str:
    if strategy is None:
        return "Default"
    return _RATIO_STRATEGY_LABELS.get(strategy, strategy)


def _ratio_target_label(target: str | None) -> str:
    if target is None:
        return "Default"
    return _RATIO_TARGET_LABELS.get(target, target)


def _violation_strategy_key(violation: ViolationResult) -> str:
    return (
        f"{violation.chart_path or violation.chart_name}|"
        f"{violation.rule_id}|"
        f"{violation.rule_name}|"
        f"{violation.current_value}"
    )


def _resolve_ratio_strategy_for_violation(
    violation: ViolationResult,
    *,
    global_strategy: str,
    overrides: dict[str, str] | None = None,
) -> str | None:
    if not _is_ratio_violation(violation):
        return None
    violation_key = _violation_strategy_key(violation)
    if overrides and violation_key in overrides:
        return overrides[violation_key]
    return global_strategy


def _resolve_ratio_target_for_violation(
    violation: ViolationResult,
    *,
    global_target: str,
    overrides: dict[str, str] | None = None,
) -> str | None:
    if not _is_ratio_violation(violation):
        return None
    violation_key = _violation_strategy_key(violation)
    if overrides and violation_key in overrides:
        return overrides[violation_key]
    return global_target


def _normalize_probe_settings(
    raw_settings: dict[str, str] | None,
) -> dict[str, Any] | None:
    if not raw_settings:
        return None
    normalized: dict[str, Any] = {}
    path = raw_settings.get("path", "").strip()
    if path:
        normalized["path"] = path
    port = raw_settings.get("port", "").strip()
    if port:
        normalized["port"] = port
    scheme = raw_settings.get("scheme", "").strip().upper()
    if scheme in {"HTTP", "HTTPS"}:
        normalized["scheme"] = scheme
    host = raw_settings.get("host", "").strip()
    if host:
        normalized["host"] = host
    header = raw_settings.get("header", "").strip()
    if header:
        normalized["header"] = header
    for field in _PROBE_INT_FIELDS:
        value = raw_settings.get(field, "").strip()
        if not value:
            continue
        with contextlib.suppress(ValueError):
            parsed = int(value)
            if parsed > 0:
                normalized[field] = parsed
    return normalized or None


def _int_setting(value: str | None, fallback: int, *, minimum: int = 1) -> int:
    raw = str(value or "").strip()
    with contextlib.suppress(ValueError):
        parsed = int(raw)
        if parsed >= minimum:
            return parsed
    return fallback


def _string_setting(value: str | None, fallback: str) -> str:
    cleaned = str(value or "").strip()
    return cleaned or fallback


def _apply_default_fix_settings(
    violation: ViolationResult,
    fix_payload: dict[str, Any] | None,
    default_settings: dict[str, str] | None,
    *,
    chart_name: str | None = None,
) -> dict[str, Any] | None:
    if not fix_payload:
        return fix_payload

    settings = dict(_FIX_DEFAULT_SETTINGS)
    if default_settings:
        for key, value in default_settings.items():
            settings[key] = str(value).strip()

    rule_id = (violation.rule_id or "").upper()
    payload = cast(dict[str, Any], copy.deepcopy(fix_payload))

    cpu_request = _string_setting(settings.get("cpu_request"), _FIX_DEFAULT_SETTINGS["cpu_request"])
    cpu_limit = _string_setting(settings.get("cpu_limit"), _FIX_DEFAULT_SETTINGS["cpu_limit"])
    memory_request = _string_setting(
        settings.get("memory_request"),
        _FIX_DEFAULT_SETTINGS["memory_request"],
    )
    memory_limit = _string_setting(
        settings.get("memory_limit"),
        _FIX_DEFAULT_SETTINGS["memory_limit"],
    )
    replica_count = _int_setting(
        settings.get("replica_count"),
        int(_FIX_DEFAULT_SETTINGS["replica_count"]),
    )
    pdb_min_available = _int_setting(
        settings.get("pdb_min_available"),
        int(_FIX_DEFAULT_SETTINGS["pdb_min_available"]),
    )
    pdb_max_unavailable = _int_setting(
        settings.get("pdb_max_unavailable"),
        int(_FIX_DEFAULT_SETTINGS["pdb_max_unavailable"]),
    )
    topology_max_skew = _int_setting(
        settings.get("topology_max_skew"),
        int(_FIX_DEFAULT_SETTINGS["topology_max_skew"]),
    )
    topology_key = _string_setting(
        settings.get("topology_key"),
        _FIX_DEFAULT_SETTINGS["topology_key"],
    )
    topology_when_unsatisfiable = _string_setting(
        settings.get("topology_when_unsatisfiable"),
        _FIX_DEFAULT_SETTINGS["topology_when_unsatisfiable"],
    )
    workload_label_key = _string_setting(
        settings.get("workload_label_key"),
        _FIX_DEFAULT_SETTINGS["workload_label_key"],
    )
    anti_affinity_weight = _int_setting(
        settings.get("anti_affinity_weight"),
        int(_FIX_DEFAULT_SETTINGS["anti_affinity_weight"]),
    )
    anti_affinity_topology_key = _string_setting(
        settings.get("anti_affinity_topology_key"),
        _FIX_DEFAULT_SETTINGS["anti_affinity_topology_key"],
    )
    safe_chart_name = (chart_name or violation.chart_name or "app").strip() or "app"

    if rule_id in {"RES002"}:
        payload.setdefault("resources", {}).setdefault("limits", {})["cpu"] = cpu_limit
    elif rule_id in {"RES003"}:
        payload.setdefault("resources", {}).setdefault("limits", {})["memory"] = memory_limit
    elif rule_id == "RES004":
        resources = payload.setdefault("resources", {})
        resources.setdefault("requests", {})["cpu"] = cpu_request
        resources.setdefault("requests", {})["memory"] = memory_request
        resources.setdefault("limits", {})["cpu"] = cpu_limit
        resources.setdefault("limits", {})["memory"] = memory_limit
    elif rule_id == "RES007":
        payload.setdefault("resources", {}).setdefault("requests", {})["cpu"] = cpu_request
    elif rule_id in {"RES008", "RES009"}:
        payload.setdefault("resources", {}).setdefault("requests", {})["memory"] = memory_request
    elif rule_id == "AVL001":
        pdb = payload.setdefault("podDisruptionBudget", {})
        pdb["minAvailable"] = pdb_min_available
        pdb.setdefault("labelSelector", {}).setdefault("matchLabels", {})[workload_label_key] = safe_chart_name
    elif rule_id == "AVL003":
        payload.setdefault("podDisruptionBudget", {})["maxUnavailable"] = pdb_max_unavailable
    elif rule_id == "AVL004":
        constraints = payload.setdefault("topologySpreadConstraints", [])
        if not constraints:
            constraints.append(
                {
                    "maxSkew": topology_max_skew,
                    "topologyKey": topology_key,
                    "whenUnsatisfiable": topology_when_unsatisfiable,
                    "labelSelector": {"matchLabels": {workload_label_key: safe_chart_name}},
                }
            )
        else:
            first = constraints[0]
            if isinstance(first, dict):
                first["maxSkew"] = topology_max_skew
                first["topologyKey"] = topology_key
                first["whenUnsatisfiable"] = topology_when_unsatisfiable
                first.setdefault("labelSelector", {}).setdefault("matchLabels", {})[workload_label_key] = safe_chart_name
    elif rule_id == "AVL002":
        anti_affinity = (
            payload.setdefault("affinity", {})
            .setdefault("podAntiAffinity", {})
            .setdefault("preferredDuringSchedulingIgnoredDuringExecution", [])
        )
        if not anti_affinity:
            anti_affinity.append(
                {
                    "weight": anti_affinity_weight,
                    "podAffinityTerm": {
                        "labelSelector": {"matchLabels": {workload_label_key: safe_chart_name}},
                        "topologyKey": anti_affinity_topology_key,
                    },
                }
            )
        else:
            first_term = anti_affinity[0]
            if isinstance(first_term, dict):
                first_term["weight"] = anti_affinity_weight
                first_term.setdefault("podAffinityTerm", {}).setdefault(
                    "labelSelector",
                    {},
                ).setdefault("matchLabels", {})[workload_label_key] = safe_chart_name
                first_term.setdefault("podAffinityTerm", {})["topologyKey"] = anti_affinity_topology_key
    elif rule_id == "AVL005":
        payload["replicaCount"] = replica_count

    return payload


def _resolve_probe_settings_for_violation(
    violation: ViolationResult,
    *,
    global_settings: dict[str, str] | None = None,
    overrides: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    if not _is_probe_violation(violation):
        return None
    merged: dict[str, str] = {}
    if global_settings:
        for field in _PROBE_SETTING_FIELDS:
            value = global_settings.get(field)
            if value is None:
                continue
            stripped = str(value).strip()
            if stripped:
                merged[field] = stripped
    if overrides:
        violation_key = _violation_strategy_key(violation)
        raw_settings = overrides.get(violation_key, {})
        for field in _PROBE_SETTING_FIELDS:
            if field not in raw_settings:
                continue
            stripped = str(raw_settings[field]).strip()
            if stripped:
                merged[field] = stripped
            else:
                merged.pop(field, None)
    if not merged:
        return None
    return _normalize_probe_settings(merged)


def _probe_fix_guidance_lines(violation: ViolationResult) -> tuple[str, ...]:
    rule_id = (violation.rule_id or "").upper()
    if rule_id == "PRB001":
        return (
            "### How To Fix",
            "- Add a liveness probe that detects deadlocked or stuck containers.",
            "- Use `path`/`port` overrides to match your service health endpoint.",
            "- Tune delay/timeout/period/failure values based on startup and response times.",
        )
    if rule_id == "PRB002":
        return (
            "### How To Fix",
            "- Add a readiness probe so traffic only goes to ready pods.",
            "- Use `path`/`port` overrides to target the correct readiness endpoint.",
            "- Tune timings to avoid flapping during normal warm-up periods.",
        )
    if rule_id == "PRB003":
        return (
            "### How To Fix",
            "- Add a startup probe for slow-boot services to prevent premature restarts.",
            "- Use `path`/`port` overrides for startup health checks.",
            "- Increase `failureThreshold` for applications with long initialization.",
        )
    return ()


def _fix_guidance_lines(violation: ViolationResult) -> tuple[str, ...]:
    ratio_lines = _ratio_fix_guidance_lines(violation)
    if ratio_lines:
        return ratio_lines
    probe_lines = _probe_fix_guidance_lines(violation)
    if probe_lines:
        return probe_lines
    safe_recommended = (violation.recommended_value or "See generated fix").replace("`", "'")
    return (
        "### How To Fix",
        f"- Recommended action: `{safe_recommended}`",
        "- Review the generated YAML preview before applying.",
    )


def _ratio_fix_guidance_lines(violation: ViolationResult) -> tuple[str, ...]:
    """Return remediation guidance lines for ratio-based violations."""
    rule_id = (violation.rule_id or "").upper()
    if rule_id == "RES005":
        return (
            "### How To Fix",
            "- **Fix target:** Choose whether to adjust `request` or `limit` based on what is already correct.",
            "- **Burstable target:** Keep CPU limit around `1.5x` to `2.0x` of CPU request.",
            "- **Guaranteed target:** Set CPU request and CPU limit equal (`req = limit`).",
            "- Use **Guaranteed** for steady workloads; keep **Burstable** if short CPU spikes are expected.",
        )
    if rule_id == "RES006":
        return (
            "### How To Fix",
            "- **Fix target:** Choose whether to adjust `request` or `limit` based on what is already correct.",
            "- **Burstable target:** Keep memory limit around `1.5x` to `2.0x` of memory request.",
            "- **Guaranteed target:** Set memory request and memory limit equal (`req = limit`).",
            "- Use **Guaranteed** for stable memory usage; keep **Burstable** if temporary memory spikes are expected.",
        )
    return ()


class _ViolationFilterSelectionModal(ModalScreen[set[str] | None]):
    """Modal for multi-selecting violation filter values."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    _DIALOG_MIN_WIDTH = 44
    _DIALOG_MAX_WIDTH = 76
    _DIALOG_MIN_HEIGHT = 26
    _DIALOG_MAX_HEIGHT = 30
    _VISIBLE_ROWS_MIN = 4
    _VISIBLE_ROWS_MAX = 14
    _COMPACT_ACTIONS_MAX_WIDTH = 52
    _OPTION_RENDER_PADDING = 18

    def __init__(
        self,
        title: str,
        options: tuple[tuple[str, str], ...],
        selected_values: set[str],
    ) -> None:
        super().__init__(classes="viol-filter-modal-screen selection-modal-screen")
        self._title = title
        self._all_options = options
        self._all_values = {value for _, value in options}
        self._selected_values = {
            value for value in selected_values if value in self._all_values
        }
        self._visible_option_values: set[str] = set()
        self._search_query = ""

    def compose(self) -> ComposeResult:
        with CustomContainer(
            classes="viol-filter-modal-shell selection-modal-shell"
        ):
            yield CustomStatic(
                self._title,
                classes="viol-filter-modal-title selection-modal-title",
                markup=False,
            )
            yield CustomStatic(
                "",
                id="viol-filter-modal-summary",
                classes="viol-filter-modal-summary selection-modal-summary",
                markup=False,
            )
            yield CustomInput(
                placeholder="Search values...",
                id="viol-filter-modal-search",
                classes="viol-filter-modal-search selection-modal-search",
            )
            with CustomContainer(
                classes="viol-filter-modal-list-wrap selection-modal-list-wrap"
            ):
                yield CustomSelectionList[str](
                    id="viol-filter-modal-list",
                    classes="viol-filter-modal-list selection-modal-list",
                )
                yield CustomStatic(
                    "No matching values",
                    id="viol-filter-modal-empty",
                    classes="viol-filter-modal-empty selection-modal-empty hidden",
                    markup=False,
                )
            with CustomHorizontal(
                classes="viol-filter-modal-actions selection-modal-actions"
            ):
                yield CustomButton(
                    "Select All",
                    id="viol-filter-modal-select-all",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Clear",
                    id="viol-filter-modal-clear",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Apply",
                    variant="primary",
                    id="viol-filter-modal-apply",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Cancel",
                    id="viol-filter-modal-cancel",
                    compact=True,
                    classes="selection-modal-action-btn",
                )

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        self._refresh_selection_options()
        self._sync_action_buttons()
        with contextlib.suppress(Exception):
            search_input = self.query_one("#viol-filter-modal-search", CustomInput)
            search_input.input.focus()

    def on_resize(self, _: Resize) -> None:
        self._apply_dynamic_layout()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_custom_input_changed(self, event: CustomInput.Changed) -> None:
        if event.input.id != "viol-filter-modal-search":
            return
        self._search_query = event.value.strip().lower()
        self._refresh_selection_options()

    def on_selection_list_selected_changed(
        self,
        event: object,
    ) -> None:
        event_obj = cast(Any, event)
        control = getattr(event_obj, "control", None)
        visible_selected_values = {
            str(value) for value in getattr(control, "selected", [])
        }
        self._selected_values.difference_update(self._visible_option_values)
        self._selected_values.update(visible_selected_values)
        self._update_selection_summary()
        self._sync_action_buttons()

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "viol-filter-modal-select-all":
            self._selected_values = set(self._all_values)
            self._refresh_selection_options()
            self._sync_action_buttons()
            return
        if button_id == "viol-filter-modal-clear":
            self._selected_values.clear()
            self._refresh_selection_options()
            self._sync_action_buttons()
            return
        if button_id == "viol-filter-modal-apply":
            selected_values = set(self._selected_values)
            if selected_values == self._all_values:
                selected_values = set()
            self.dismiss(selected_values)
            return
        if button_id == "viol-filter-modal-cancel":
            self.dismiss(None)

    def _refresh_selection_options(self) -> None:
        visible_options = self._visible_options()
        self._visible_option_values = {value for _, value in visible_options}
        with contextlib.suppress(Exception):
            selection_list = self.query_one(
                "#viol-filter-modal-list", CustomSelectionList
            )
            if selection_list.selection_list is not None:
                selection_list.selection_list.clear_options()
                selection_list.selection_list.add_options(
                    [
                        (label, value, value in self._selected_values)
                        for label, value in visible_options
                    ]
                )
        with contextlib.suppress(Exception):
            empty_state = self.query_one("#viol-filter-modal-empty", CustomStatic)
            if visible_options:
                empty_state.add_class("hidden")
            else:
                empty_state.remove_class("hidden")
        self._update_selection_summary()

    def _visible_options(self) -> tuple[tuple[str, str], ...]:
        if not self._search_query:
            return self._all_options
        return tuple(
            (label, value)
            for label, value in self._all_options
            if self._search_query in label.lower()
        )

    def _sync_action_buttons(self) -> None:
        selected_count = len(self._selected_values)
        total_count = len(self._all_values)
        with contextlib.suppress(Exception):
            self.query_one(
                "#viol-filter-modal-select-all", CustomButton
            ).disabled = total_count == 0 or selected_count >= total_count
        with contextlib.suppress(Exception):
            self.query_one(
                "#viol-filter-modal-clear", CustomButton
            ).disabled = selected_count == 0

    def _update_selection_summary(self) -> None:
        total = len(self._all_values)
        selected_count = len(self._selected_values)
        if selected_count == 0 or selected_count == total:
            summary = f"All values ({total})"
        else:
            summary = f"{selected_count} of {total} selected"
        with contextlib.suppress(Exception):
            self.query_one("#viol-filter-modal-summary", CustomStatic).update(summary)

    def _apply_dynamic_layout(self) -> None:
        button_ids = [
            "viol-filter-modal-select-all",
            "viol-filter-modal-clear",
            "viol-filter-modal-apply",
            "viol-filter-modal-cancel",
        ]
        for button_id in button_ids:
            with contextlib.suppress(Exception):
                button = self.query_one(f"#{button_id}", CustomButton)
                button.styles.width = "1fr"
                button.styles.min_width = "0"
                button.styles.max_width = "100%"

        total_values = len(self._all_values)
        summary_all = f"All values ({total_values})"
        summary_partial = f"{total_values} of {total_values} selected"
        title_width = len(self._title)
        longest_option = max((len(label) for label, _ in self._all_options), default=0)
        target_width = max(
            title_width + 8,
            len("Search values...") + 8,
            len(summary_all) + 8,
            len(summary_partial) + 8,
            longest_option + self._OPTION_RENDER_PADDING,
            self._DIALOG_MIN_WIDTH,
        )

        available_width = max(
            24,
            getattr(self.app.size, "width", self._DIALOG_MIN_WIDTH + 6) - 4,
        )
        max_width = min(self._DIALOG_MAX_WIDTH, available_width)
        min_width = min(self._DIALOG_MIN_WIDTH, max_width)
        dialog_width = max(min_width, min(target_width, max_width))
        dialog_width_value = str(dialog_width)
        compact_actions = dialog_width <= self._COMPACT_ACTIONS_MAX_WIDTH

        with contextlib.suppress(Exception):
            select_all_btn = self.query_one(
                "#viol-filter-modal-select-all",
                CustomButton,
            )
            select_all_btn.label = "All" if compact_actions else "Select All"
        with contextlib.suppress(Exception):
            search_input = self.query_one("#viol-filter-modal-search", CustomInput)
            search_input.styles.height = "3"
            search_input.styles.min_height = "3"
            search_input.styles.max_height = "3"
            search_input.styles.width = "1fr"
            search_input.styles.min_width = "0"
            search_input.styles.max_width = "100%"

        visible_rows = min(
            max(len(self._all_options), self._VISIBLE_ROWS_MIN),
            self._VISIBLE_ROWS_MAX,
        )
        # Title + summary + input + action row + shell spacing.
        target_height = visible_rows + 12
        available_height = max(
            10,
            getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT) - 2,
        )
        max_height = min(self._DIALOG_MAX_HEIGHT, available_height)
        dialog_min_height = min(self._DIALOG_MIN_HEIGHT, max_height)
        dialog_max_height = max(dialog_min_height, min(target_height, max_height))
        dialog_min_height_value = str(dialog_min_height)
        dialog_max_height_value = str(dialog_max_height)
        with contextlib.suppress(Exception):
            shell = self.query_one(".viol-filter-modal-shell", CustomContainer)
            shell.styles.width = dialog_width_value
            shell.styles.min_width = dialog_width_value
            shell.styles.max_width = dialog_width_value
            shell.styles.height = dialog_max_height_value
            shell.styles.min_height = dialog_min_height_value
            shell.styles.max_height = dialog_max_height_value


class _ViolationsFiltersState(TypedDict):
    category_filter: set[str]
    severity_filter: set[str]
    team_filter: set[str]
    visible_column_names: set[str]
    rule_filter: set[str]
    chart_filter: set[str]
    values_type_filter: set[str]


class _ViolationsFiltersModal(ModalScreen[_ViolationsFiltersState | None]):
    """Unified modal for storing violations filter selections."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    _DIALOG_MIN_WIDTH = 144
    _DIALOG_MAX_WIDTH = 184
    _DIALOG_MIN_HEIGHT = 36
    _DIALOG_MAX_HEIGHT = 46
    _FILTER_KEYS: tuple[str, ...] = (
        "category",
        "severity",
        "team",
        "column",
        "rule",
        "chart",
        "values_type",
    )
    _FILTER_SUFFIX_BY_KEY: dict[str, str] = {
        "category": "category",
        "severity": "severity",
        "team": "team",
        "column": "column",
        "rule": "rule",
        "chart": "chart",
        "values_type": "values-type",
    }
    _FILTER_LABEL_BY_KEY: dict[str, str] = {
        "category": "Category",
        "severity": "Severity",
        "team": "Team",
        "column": "Columns",
        "rule": "Rule",
        "chart": "Chart",
        "values_type": "Values Type",
    }
    _FILTER_ALL_LABEL_BY_KEY: dict[str, str] = {
        "team": "Teams",
    }

    def __init__(
        self,
        *,
        filter_options: dict[str, tuple[tuple[str, str], ...]],
        selected_values: dict[str, set[str]],
        locked_column_names: set[str] | None = None,
    ) -> None:
        super().__init__(classes="viol-filters-modal-screen selection-modal-screen")
        self._filter_options = filter_options
        self._all_values_by_key: dict[str, set[str]] = {}
        self._selected_values_by_key: dict[str, set[str]] = {}
        self._locked_column_values = set(locked_column_names or set())

        for key in self._FILTER_KEYS:
            options = self._filter_options.get(key, ())
            all_values = {value for _, value in options}
            self._all_values_by_key[key] = all_values
            selected = {
                value for value in selected_values.get(key, set()) if value in all_values
            }
            selected_values_for_key = selected if selected else set(all_values)
            if key == "column":
                selected_values_for_key.update(
                    self._locked_column_values & all_values,
                )
            self._selected_values_by_key[key] = selected_values_for_key

    def compose(self) -> ComposeResult:
        with CustomContainer(
            classes="viol-filters-modal-shell selection-modal-shell"
        ):
            yield CustomStatic(
                "Optimizer Filters",
                classes="viol-filters-modal-title selection-modal-title",
                markup=False,
            )
            with CustomHorizontal(classes="viol-filters-modal-lists-row"):
                with CustomVertical(classes="viol-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Category",
                            id="viol-filters-modal-category-title",
                            classes="viol-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="viol-filters-modal-category-list",
                            classes="viol-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(classes="viol-filters-modal-list-actions"):
                        yield CustomButton(
                            "All",
                            id="viol-filters-modal-category-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="viol-filters-modal-category-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="viol-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Severity",
                            id="viol-filters-modal-severity-title",
                            classes="viol-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="viol-filters-modal-severity-list",
                            classes="viol-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(classes="viol-filters-modal-list-actions"):
                        yield CustomButton(
                            "All",
                            id="viol-filters-modal-severity-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="viol-filters-modal-severity-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="viol-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Team",
                            id="viol-filters-modal-team-title",
                            classes="viol-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="viol-filters-modal-team-list",
                            classes="viol-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(classes="viol-filters-modal-list-actions"):
                        yield CustomButton(
                            "All",
                            id="viol-filters-modal-team-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="viol-filters-modal-team-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="viol-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Columns",
                            id="viol-filters-modal-column-title",
                            classes="viol-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="viol-filters-modal-column-list",
                            classes="viol-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(classes="viol-filters-modal-list-actions"):
                        yield CustomButton(
                            "All",
                            id="viol-filters-modal-column-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="viol-filters-modal-column-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
            with CustomHorizontal(classes="viol-filters-modal-lists-row"):
                with CustomVertical(classes="viol-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Rule",
                            id="viol-filters-modal-rule-title",
                            classes="viol-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="viol-filters-modal-rule-list",
                            classes="viol-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(classes="viol-filters-modal-list-actions"):
                        yield CustomButton(
                            "All",
                            id="viol-filters-modal-rule-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="viol-filters-modal-rule-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="viol-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Chart",
                            id="viol-filters-modal-chart-title",
                            classes="viol-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="viol-filters-modal-chart-list",
                            classes="viol-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(classes="viol-filters-modal-list-actions"):
                        yield CustomButton(
                            "All",
                            id="viol-filters-modal-chart-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="viol-filters-modal-chart-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="viol-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Values Type",
                            id="viol-filters-modal-values-type-title",
                            classes="viol-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="viol-filters-modal-values-type-list",
                            classes="viol-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(classes="viol-filters-modal-list-actions"):
                        yield CustomButton(
                            "All",
                            id="viol-filters-modal-values-type-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="viol-filters-modal-values-type-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
            with CustomHorizontal(classes="viol-filters-modal-actions selection-modal-actions"):
                yield CustomButton(
                    "Apply",
                    id="viol-filters-modal-apply",
                    compact=True,
                    variant="primary",
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Cancel",
                    id="viol-filters-modal-cancel",
                    compact=True,
                    classes="selection-modal-action-btn",
                )

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        self._refresh_all_selection_options()
        self._update_summary()
        for key in self._FILTER_KEYS:
            self._sync_filter_action_buttons(key)
        with contextlib.suppress(Exception):
            self.query_one("#viol-filters-modal-category-list", CustomSelectionList).focus()

    def on_resize(self, _: Resize) -> None:
        self._apply_dynamic_layout()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_selection_list_selected_changed(self, event: object) -> None:
        event_obj = cast(Any, event)
        control = getattr(event_obj, "control", None)
        control_id = str(getattr(control, "id", ""))
        selected_values = {str(value) for value in getattr(control, "selected", [])}
        for key in self._FILTER_KEYS:
            suffix = self._FILTER_SUFFIX_BY_KEY[key]
            if control_id == f"viol-filters-modal-{suffix}-list-inner":
                selected_values_for_key = set(selected_values)
                if key == "column":
                    selected_values_for_key.update(
                        self._locked_column_values & self._all_values_by_key.get("column", set()),
                    )
                self._selected_values_by_key[key] = selected_values_for_key
                self._update_summary()
                self._sync_filter_action_buttons(key)
                return

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        for key in self._FILTER_KEYS:
            suffix = self._FILTER_SUFFIX_BY_KEY[key]
            if button_id == f"viol-filters-modal-{suffix}-all":
                self._selected_values_by_key[key] = set(self._all_values_by_key.get(key, set()))
                self._refresh_selection_options(key)
                self._sync_filter_action_buttons(key)
                return
            if button_id == f"viol-filters-modal-{suffix}-clear":
                if key == "column":
                    self._selected_values_by_key[key] = set(
                        self._locked_column_values & self._all_values_by_key.get("column", set()),
                    )
                else:
                    self._selected_values_by_key[key].clear()
                self._refresh_selection_options(key)
                self._sync_filter_action_buttons(key)
                return
        if button_id == "viol-filters-modal-apply":
            self._apply()
            return
        if button_id == "viol-filters-modal-cancel":
            self.dismiss(None)

    def _refresh_all_selection_options(self) -> None:
        for key in self._FILTER_KEYS:
            self._refresh_selection_options(key)

    def _refresh_selection_options(self, key: str) -> None:
        suffix = self._FILTER_SUFFIX_BY_KEY[key]
        options = self._filter_options.get(key, ())
        selected_values = self._selected_values_by_key.get(key, set())
        with contextlib.suppress(Exception):
            selection_list = self.query_one(
                f"#viol-filters-modal-{suffix}-list",
                CustomSelectionList,
            )
            if selection_list.selection_list is not None:
                selection_list.selection_list.clear_options()
                selection_list.selection_list.add_options(
                    [
                        (label, value, value in selected_values)
                        for label, value in options
                    ]
                )
        self._update_summary()

    def _apply(self) -> None:
        self._selected_values_by_key["column"].update(
            self._locked_column_values & self._all_values_by_key.get("column", set()),
        )
        if self._all_values_by_key.get("column") and not self._selected_values_by_key.get("column"):
            self.notify("Select at least one column", severity="warning")
            return

        state: _ViolationsFiltersState = {
            "category_filter": set(),
            "severity_filter": set(),
            "team_filter": set(),
            "visible_column_names": set(),
            "rule_filter": set(),
            "chart_filter": set(),
            "values_type_filter": set(),
        }
        field_map = {
            "category": "category_filter",
            "severity": "severity_filter",
            "team": "team_filter",
            "column": "visible_column_names",
            "rule": "rule_filter",
            "chart": "chart_filter",
            "values_type": "values_type_filter",
        }
        for key in self._FILTER_KEYS:
            all_values = self._all_values_by_key.get(key, set())
            selected_values = set(self._selected_values_by_key.get(key, set()))
            if key != "column" and all_values and selected_values == all_values:
                selected_values = set()
            state[field_map[key]] = selected_values
        self.dismiss(state)

    def _sync_filter_action_buttons(self, key: str) -> None:
        suffix = self._FILTER_SUFFIX_BY_KEY[key]
        selected_count = len(self._selected_values_by_key.get(key, set()))
        total_count = len(self._all_values_by_key.get(key, set()))
        min_selected_count = 0
        if key == "column":
            min_selected_count = len(
                self._locked_column_values & self._all_values_by_key.get("column", set()),
            )
        with contextlib.suppress(Exception):
            self.query_one(
                f"#viol-filters-modal-{suffix}-all", CustomButton
            ).disabled = total_count == 0 or selected_count >= total_count
        with contextlib.suppress(Exception):
            self.query_one(
                f"#viol-filters-modal-{suffix}-clear", CustomButton
            ).disabled = selected_count <= min_selected_count

    def _update_summary(self) -> None:
        for key in self._FILTER_KEYS:
            label = self._FILTER_LABEL_BY_KEY[key]
            all_label = self._FILTER_ALL_LABEL_BY_KEY.get(key)
            total = len(self._all_values_by_key.get(key, set()))
            selected = len(self._selected_values_by_key.get(key, set()))
            title = self._format_filter_title(
                label=label,
                total=total,
                selected=selected,
                all_label=all_label,
            )
            title_id = f"#viol-filters-modal-{self._FILTER_SUFFIX_BY_KEY[key]}-title"
            with contextlib.suppress(Exception):
                self.query_one(title_id, CustomStatic).update(title)

    @staticmethod
    def _format_filter_title(
        *,
        label: str,
        total: int,
        selected: int,
        all_label: str | None = None,
    ) -> str:
        if total > 0 and selected == total:
            return f"{all_label or label} (All)"
        return f"{label} ({selected})"

    def _apply_dynamic_layout(self) -> None:
        available_width = max(84, getattr(self.app.size, "width", self._DIALOG_MAX_WIDTH) - 8)
        dialog_width = min(self._DIALOG_MAX_WIDTH, available_width)
        dialog_width = max(self._DIALOG_MIN_WIDTH, dialog_width)
        dialog_width_value = str(dialog_width)

        available_height = max(
            12,
            getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT) - 2,
        )
        max_height = min(self._DIALOG_MAX_HEIGHT, available_height)
        dialog_min_height = min(self._DIALOG_MIN_HEIGHT, max_height)
        dialog_max_height = max(dialog_min_height, max_height)
        dialog_min_height_value = str(dialog_min_height)
        dialog_max_height_value = str(dialog_max_height)

        with contextlib.suppress(Exception):
            shell = self.query_one(".viol-filters-modal-shell", CustomContainer)
            shell.styles.width = dialog_width_value
            shell.styles.min_width = dialog_width_value
            shell.styles.max_width = dialog_width_value
            shell.styles.height = dialog_max_height_value
            shell.styles.min_height = dialog_min_height_value
            shell.styles.max_height = dialog_max_height_value


class _ApplyAllFixesModalResult(TypedDict):
    global_ratio_strategy: str
    ratio_strategy_overrides: dict[str, str]
    global_ratio_target: str
    ratio_target_overrides: dict[str, str]
    global_probe_settings: dict[str, str]
    probe_overrides: dict[str, dict[str, str]]
    global_fix_defaults: dict[str, str]


class _GlobalViolationSettingsModalResult(TypedDict):
    global_ratio_strategy: str
    global_ratio_target: str
    global_probe_settings: dict[str, str]
    global_fix_defaults: dict[str, str]


class _GlobalViolationSettingsModal(ModalScreen[_GlobalViolationSettingsModalResult | None]):
    """Modal to configure global violation fix settings."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    _DIALOG_TITLE = "Default Fix Configs"
    _DIALOG_MIN_WIDTH = 102
    _DIALOG_MAX_WIDTH = 128
    _DIALOG_MIN_HEIGHT = 22
    _DIALOG_MAX_HEIGHT = 34

    def __init__(
        self,
        *,
        has_ratio_violations: bool,
        has_probe_violations: bool,
        initial_ratio_strategy: str,
        initial_ratio_target: str,
        initial_probe_settings: dict[str, str] | None = None,
        initial_fix_defaults: dict[str, str] | None = None,
    ) -> None:
        super().__init__(classes="selection-modal-screen")
        self._has_ratio_violations = has_ratio_violations
        self._has_probe_violations = has_probe_violations
        self._initial_ratio_strategy = initial_ratio_strategy
        self._initial_ratio_target = initial_ratio_target
        self._initial_probe_settings = dict(initial_probe_settings or {})
        self._initial_fix_defaults = dict(_FIX_DEFAULT_SETTINGS)
        self._initial_fix_defaults.update(
            {
                key: str(value).strip()
                for key, value in dict(initial_fix_defaults or {}).items()
            }
        )

    def compose(self) -> ComposeResult:
        with CustomContainer(
            classes="apply-fixes-global-settings-shell selection-modal-shell",
        ):
            yield CustomStatic(
                self._DIALOG_TITLE,
                classes="selection-modal-title",
                markup=False,
            )
            with CustomVertical(id="apply-fixes-global-settings-content"):
                yield CustomStatic(
                    "Configure default fix values used when generating fixes.",
                    classes="selection-modal-summary",
                    markup=False,
                )
                with CustomVertical(id="apply-fixes-global-settings-scroll"):
                    with CustomVertical(id="apply-fixes-global-settings-defaults-pane"):
                        yield CustomStatic(
                            "Default Resource & Availability Fixes",
                            classes="apply-fixes-modal-panel-title selection-modal-list-title",
                            markup=False,
                        )
                        with CustomHorizontal(id="apply-fixes-global-settings-defaults-row-1"):
                            with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                yield CustomStatic(
                                    "CPU Request",
                                    classes="apply-fixes-modal-strategy-title",
                                    markup=False,
                                )
                                yield CustomInput(
                                    placeholder="100m",
                                    id="apply-fixes-global-settings-default-cpu-request",
                                )
                            with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                yield CustomStatic(
                                    "CPU Limit",
                                    classes="apply-fixes-modal-strategy-title",
                                    markup=False,
                                )
                                yield CustomInput(
                                    placeholder="500m",
                                    id="apply-fixes-global-settings-default-cpu-limit",
                                )
                            with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                yield CustomStatic(
                                    "Memory Request",
                                    classes="apply-fixes-modal-strategy-title",
                                    markup=False,
                                )
                                yield CustomInput(
                                    placeholder="128Mi",
                                    id="apply-fixes-global-settings-default-memory-request",
                                )
                            with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                yield CustomStatic(
                                    "Memory Limit",
                                    classes="apply-fixes-modal-strategy-title",
                                    markup=False,
                                )
                                yield CustomInput(
                                    placeholder="512Mi",
                                    id="apply-fixes-global-settings-default-memory-limit",
                                )
                        with CustomHorizontal(id="apply-fixes-global-settings-defaults-row-2"):
                            with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                yield CustomStatic(
                                    "Replica Count",
                                    classes="apply-fixes-modal-strategy-title",
                                    markup=False,
                                )
                                yield CustomInput(
                                    placeholder="2",
                                    id="apply-fixes-global-settings-default-replica-count",
                                    restrict=r"[0-9]",
                                )
                            with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                yield CustomStatic(
                                    "PDB Min Available",
                                    classes="apply-fixes-modal-strategy-title",
                                    markup=False,
                                )
                                yield CustomInput(
                                    placeholder="1",
                                    id="apply-fixes-global-settings-default-pdb-min-available",
                                    restrict=r"[0-9]",
                                )
                            with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                yield CustomStatic(
                                    "PDB Max Unavailable",
                                    classes="apply-fixes-modal-strategy-title",
                                    markup=False,
                                )
                                yield CustomInput(
                                    placeholder="1",
                                    id="apply-fixes-global-settings-default-pdb-max-unavailable",
                                    restrict=r"[0-9]",
                                )
                            with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                yield CustomStatic(
                                    "Topology Max Skew",
                                    classes="apply-fixes-modal-strategy-title",
                                    markup=False,
                                )
                                yield CustomInput(
                                    placeholder="1",
                                    id="apply-fixes-global-settings-default-topology-max-skew",
                                    restrict=r"[0-9]",
                                )
                        with CustomHorizontal(id="apply-fixes-global-settings-defaults-row-3"):
                            with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                yield CustomStatic(
                                    "Topology Key",
                                    classes="apply-fixes-modal-strategy-title",
                                    markup=False,
                                )
                                yield CustomInput(
                                    placeholder="kubernetes.io/hostname",
                                    id="apply-fixes-global-settings-default-topology-key",
                                )
                            with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                yield CustomStatic(
                                    "When Unsatisfiable",
                                    classes="apply-fixes-modal-strategy-title",
                                    markup=False,
                                )
                                yield Select(
                                    [
                                        ("ScheduleAnyway", "ScheduleAnyway"),
                                        ("DoNotSchedule", "DoNotSchedule"),
                                    ],
                                    value="ScheduleAnyway",
                                    allow_blank=False,
                                    id="apply-fixes-global-settings-default-topology-when-unsatisfiable",
                                    classes="filter-select",
                                )
                            with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                yield CustomStatic(
                                    "Anti-Affinity Weight",
                                    classes="apply-fixes-modal-strategy-title",
                                    markup=False,
                                )
                                yield CustomInput(
                                    placeholder="100",
                                    id="apply-fixes-global-settings-default-anti-affinity-weight",
                                    restrict=r"[0-9]",
                                )
                            with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                yield CustomStatic(
                                    "Anti-Affinity Topology Key",
                                    classes="apply-fixes-modal-strategy-title",
                                    markup=False,
                                )
                                yield CustomInput(
                                    placeholder="kubernetes.io/hostname",
                                    id="apply-fixes-global-settings-default-anti-affinity-topology-key",
                                )
                        with (
                            CustomHorizontal(id="apply-fixes-global-settings-defaults-row-4"),
                            CustomVertical(classes="apply-fixes-modal-strategy-control"),
                        ):
                            yield CustomStatic(
                                "Workload Label Key",
                                classes="apply-fixes-modal-strategy-title",
                                markup=False,
                            )
                            yield CustomInput(
                                placeholder="app",
                                id="apply-fixes-global-settings-default-workload-label-key",
                            )
                    if self._has_ratio_violations:
                        with CustomVertical(id="apply-fixes-global-settings-ratio-pane"):
                            yield CustomStatic(
                                "Default Extreme-Ratio Settings",
                                classes="apply-fixes-modal-panel-title selection-modal-list-title",
                                markup=False,
                            )
                            with CustomHorizontal(id="apply-fixes-global-settings-ratio-row"):
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Ratio Strategy",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield Select(
                                        [
                                            (_prefixed_option("Strategy", "Burstable 1.5x"), RATIO_STRATEGY_BURSTABLE_15),
                                            (_prefixed_option("Strategy", "Burstable 2.0x"), RATIO_STRATEGY_BURSTABLE_20),
                                            (_prefixed_option("Strategy", "Guaranteed (req = limit)"), RATIO_STRATEGY_GUARANTEED),
                                        ],
                                        value=self._initial_ratio_strategy,
                                        allow_blank=False,
                                        id="apply-fixes-global-settings-ratio-strategy",
                                        classes="filter-select",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Fix Target (Field To Update)",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield Select(
                                        [
                                            (_prefixed_option("Target", "Fix Request"), RATIO_TARGET_REQUEST),
                                            (_prefixed_option("Target", "Fix Limit"), RATIO_TARGET_LIMIT),
                                        ],
                                        value=self._initial_ratio_target,
                                        allow_blank=False,
                                        id="apply-fixes-global-settings-ratio-target",
                                        classes="filter-select",
                                    )
                    if self._has_probe_violations:
                        with CustomVertical(id="apply-fixes-global-settings-probe-pane"):
                            yield CustomStatic(
                                "Default Probe Settings",
                                classes="apply-fixes-modal-panel-title selection-modal-list-title",
                                markup=False,
                            )
                            with CustomHorizontal(id="apply-fixes-global-settings-probe-row-main"):
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "HTTP Path",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="/health",
                                        id="apply-fixes-global-settings-probe-path",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Port Name/Number",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="http",
                                        id="apply-fixes-global-settings-probe-port",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "HTTP Scheme",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield Select(
                                        [
                                            ("HTTP", "HTTP"),
                                            ("HTTPS", "HTTPS"),
                                        ],
                                        value="HTTP",
                                        allow_blank=False,
                                        id="apply-fixes-global-settings-probe-scheme",
                                        classes="filter-select",
                                    )
                            with CustomHorizontal(id="apply-fixes-global-settings-probe-row-advanced"):
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Initial Delay",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="seconds",
                                        id="apply-fixes-global-settings-probe-initial-delay",
                                        restrict=r"[0-9]",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Timeout",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="seconds",
                                        id="apply-fixes-global-settings-probe-timeout",
                                        restrict=r"[0-9]",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Period",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="seconds",
                                        id="apply-fixes-global-settings-probe-period",
                                        restrict=r"[0-9]",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Failure Threshold",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="count",
                                        id="apply-fixes-global-settings-probe-failure-threshold",
                                        restrict=r"[0-9]",
                                    )
                            with CustomHorizontal(id="apply-fixes-global-settings-probe-row-extra"):
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "HTTP Host",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="service.local",
                                        id="apply-fixes-global-settings-probe-host",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Success Threshold",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="count",
                                        id="apply-fixes-global-settings-probe-success-threshold",
                                        restrict=r"[0-9]",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Grace Period",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="seconds",
                                        id="apply-fixes-global-settings-probe-grace-period",
                                        restrict=r"[0-9]",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "HTTP Header",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="Name:Value",
                                        id="apply-fixes-global-settings-probe-header",
                                    )
            with CustomHorizontal(
                classes="apply-fixes-global-settings-actions selection-modal-actions",
            ):
                yield CustomButton(
                    "Save",
                    id="apply-fixes-global-settings-save",
                    variant="primary",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Reset",
                    id="apply-fixes-global-settings-reset",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Cancel",
                    id="apply-fixes-global-settings-cancel",
                    compact=True,
                    classes="selection-modal-action-btn",
                )

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        self._load_initial_values()
        with contextlib.suppress(Exception):
            if self._has_ratio_violations:
                self.query_one("#apply-fixes-global-settings-ratio-strategy", Select).focus()
            elif self._has_probe_violations:
                self.query_one("#apply-fixes-global-settings-probe-path", CustomInput).focus()

    def on_resize(self, _: Resize) -> None:
        self._apply_dynamic_layout()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "apply-fixes-global-settings-save":
            self.dismiss(self._collect_values())
            return
        if button_id == "apply-fixes-global-settings-reset":
            self.dismiss(
                {
                    "global_ratio_strategy": RATIO_STRATEGY_BURSTABLE_15,
                    "global_ratio_target": RATIO_TARGET_REQUEST,
                    "global_probe_settings": {},
                    "global_fix_defaults": dict(_FIX_DEFAULT_SETTINGS),
                }
            )
            return
        self.dismiss(None)

    @staticmethod
    def _probe_field_by_input_id() -> dict[str, str]:
        return {
            "apply-fixes-global-settings-probe-path": "path",
            "apply-fixes-global-settings-probe-port": "port",
            "apply-fixes-global-settings-probe-initial-delay": "initialDelaySeconds",
            "apply-fixes-global-settings-probe-timeout": "timeoutSeconds",
            "apply-fixes-global-settings-probe-period": "periodSeconds",
            "apply-fixes-global-settings-probe-success-threshold": "successThreshold",
            "apply-fixes-global-settings-probe-failure-threshold": "failureThreshold",
            "apply-fixes-global-settings-probe-grace-period": "terminationGracePeriodSeconds",
            "apply-fixes-global-settings-probe-host": "host",
            "apply-fixes-global-settings-probe-header": "header",
        }

    @staticmethod
    def _default_field_by_input_id() -> dict[str, str]:
        return {
            "apply-fixes-global-settings-default-cpu-request": "cpu_request",
            "apply-fixes-global-settings-default-cpu-limit": "cpu_limit",
            "apply-fixes-global-settings-default-memory-request": "memory_request",
            "apply-fixes-global-settings-default-memory-limit": "memory_limit",
            "apply-fixes-global-settings-default-replica-count": "replica_count",
            "apply-fixes-global-settings-default-pdb-min-available": "pdb_min_available",
            "apply-fixes-global-settings-default-pdb-max-unavailable": "pdb_max_unavailable",
            "apply-fixes-global-settings-default-topology-max-skew": "topology_max_skew",
            "apply-fixes-global-settings-default-topology-key": "topology_key",
            "apply-fixes-global-settings-default-anti-affinity-weight": "anti_affinity_weight",
            "apply-fixes-global-settings-default-anti-affinity-topology-key": "anti_affinity_topology_key",
            "apply-fixes-global-settings-default-workload-label-key": "workload_label_key",
        }

    def _collect_values(self) -> _GlobalViolationSettingsModalResult:
        strategy = self._initial_ratio_strategy
        target = self._initial_ratio_target
        if self._has_ratio_violations:
            with contextlib.suppress(Exception):
                strategy = str(self.query_one("#apply-fixes-global-settings-ratio-strategy", Select).value)
            with contextlib.suppress(Exception):
                target = str(self.query_one("#apply-fixes-global-settings-ratio-target", Select).value)

        probe_values: dict[str, str] = {}
        if self._has_probe_violations:
            for input_id, field in self._probe_field_by_input_id().items():
                with contextlib.suppress(Exception):
                    control = self.query_one(f"#{input_id}", CustomInput)
                    value = control.value.strip()
                    if not value:
                        continue
                    if field in _PROBE_INT_FIELDS and not value.isdigit():
                        continue
                    probe_values[field] = value
            with contextlib.suppress(Exception):
                scheme = self.query_one("#apply-fixes-global-settings-probe-scheme", Select)
                scheme_value = str(scheme.value).strip().upper()
                if scheme_value in {"HTTP", "HTTPS"}:
                    probe_values["scheme"] = scheme_value

        default_values = dict(_FIX_DEFAULT_SETTINGS)
        for input_id, field in self._default_field_by_input_id().items():
            with contextlib.suppress(Exception):
                control = self.query_one(f"#{input_id}", CustomInput)
                value = control.value.strip()
                if value:
                    default_values[field] = value

        with contextlib.suppress(Exception):
            when_unsatisfiable = self.query_one(
                "#apply-fixes-global-settings-default-topology-when-unsatisfiable",
                Select,
            )
            selected_value = str(when_unsatisfiable.value).strip()
            if selected_value:
                default_values["topology_when_unsatisfiable"] = selected_value

        return {
            "global_ratio_strategy": strategy,
            "global_ratio_target": target,
            "global_probe_settings": probe_values,
            "global_fix_defaults": default_values,
        }

    def _load_initial_values(self) -> None:
        for input_id, field in self._default_field_by_input_id().items():
            with contextlib.suppress(Exception):
                control = self.query_one(f"#{input_id}", CustomInput)
                control.value = self._initial_fix_defaults.get(field, _FIX_DEFAULT_SETTINGS[field])

        with contextlib.suppress(Exception):
            when_unsatisfiable = self.query_one(
                "#apply-fixes-global-settings-default-topology-when-unsatisfiable",
                Select,
            )
            when_unsatisfiable.value = self._initial_fix_defaults.get(
                "topology_when_unsatisfiable",
                _FIX_DEFAULT_SETTINGS["topology_when_unsatisfiable"],
            )

        if self._has_probe_violations:
            for input_id, field in self._probe_field_by_input_id().items():
                with contextlib.suppress(Exception):
                    control = self.query_one(f"#{input_id}", CustomInput)
                    control.value = self._initial_probe_settings.get(field, "")
            with contextlib.suppress(Exception):
                scheme = self.query_one("#apply-fixes-global-settings-probe-scheme", Select)
                scheme_value = str(self._initial_probe_settings.get("scheme", "HTTP")).strip().upper()
                scheme.value = scheme_value if scheme_value in {"HTTP", "HTTPS"} else "HTTP"

    def _apply_dynamic_layout(self) -> None:
        available_width = max(
            self._DIALOG_MIN_WIDTH,
            getattr(self.app.size, "width", self._DIALOG_MAX_WIDTH) - 10,
        )
        dialog_width = min(self._DIALOG_MAX_WIDTH, available_width)
        dialog_width = max(self._DIALOG_MIN_WIDTH, dialog_width)
        dialog_width_value = str(dialog_width)

        available_height = max(
            self._DIALOG_MIN_HEIGHT,
            getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT) - 4,
        )
        max_height = min(self._DIALOG_MAX_HEIGHT, available_height)
        dialog_max_height_value = str(max_height)

        with contextlib.suppress(Exception):
            shell = self.query_one(".apply-fixes-global-settings-shell", CustomContainer)
            shell.styles.width = dialog_width_value
            shell.styles.min_width = dialog_width_value
            shell.styles.max_width = dialog_width_value
            shell.styles.height = "auto"
            shell.styles.min_height = "0"
            shell.styles.max_height = dialog_max_height_value
        with contextlib.suppress(Exception):
            scroll = self.query_one("#apply-fixes-global-settings-scroll", CustomVertical)
            scroll.styles.height = "auto"
            scroll.styles.min_height = "0"
            # Keep dialog compact while limiting inner body height before scrolling.
            scroll.styles.max_height = str(max(10, max_height - 12))


class _ViolationOverrideSettingsModalResult(TypedDict):
    ratio_strategy_override: str
    ratio_target_override: str
    probe_override: dict[str, str]


class _ViolationOverrideSettingsModal(ModalScreen[_ViolationOverrideSettingsModalResult | None]):
    """Modal to configure per-violation override settings."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    _DIALOG_TITLE = "Override Fix Config"
    _DIALOG_MIN_WIDTH = 100
    _DIALOG_MAX_WIDTH = 132
    _DIALOG_MIN_HEIGHT = 18
    _DIALOG_MAX_HEIGHT = 32

    def __init__(
        self,
        *,
        violation: ViolationResult,
        ratio_strategy_override: str,
        ratio_target_override: str,
        probe_override: dict[str, str] | None = None,
    ) -> None:
        super().__init__(classes="selection-modal-screen")
        self._violation = violation
        self._ratio_strategy_override = ratio_strategy_override
        self._ratio_target_override = ratio_target_override
        self._probe_override = dict(probe_override or {})
        self._is_ratio = _is_ratio_violation(violation)
        self._is_probe = _is_probe_violation(violation)

    def compose(self) -> ComposeResult:
        with CustomContainer(
            classes="apply-fixes-global-settings-shell selection-modal-shell",
        ):
            yield CustomStatic(
                self._DIALOG_TITLE,
                classes="selection-modal-title",
                markup=False,
            )
            with CustomVertical(id="apply-fixes-override-settings-content"):
                yield CustomStatic(
                    f"{self._violation.chart_name} | {self._violation.rule_name}",
                    classes="selection-modal-summary",
                    markup=False,
                )
                with CustomVertical(id="apply-fixes-override-settings-scroll"):
                    if self._is_ratio:
                        with CustomVertical(id="apply-fixes-override-settings-ratio-pane"):
                            yield CustomStatic(
                                "Extreme Ratio Override",
                                classes="apply-fixes-modal-panel-title selection-modal-list-title",
                                markup=False,
                            )
                            with CustomHorizontal(id="apply-fixes-override-settings-ratio-row"):
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Ratio Strategy",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield Select(
                                        [
                                            (_prefixed_option("Override", "Use Global"), RATIO_STRATEGY_INHERIT_GLOBAL),
                                            (_prefixed_option("Override", "Burstable 1.5x"), RATIO_STRATEGY_BURSTABLE_15),
                                            (_prefixed_option("Override", "Burstable 2.0x"), RATIO_STRATEGY_BURSTABLE_20),
                                            (_prefixed_option("Override", "Guaranteed (req = limit)"), RATIO_STRATEGY_GUARANTEED),
                                        ],
                                        value=self._ratio_strategy_override,
                                        allow_blank=False,
                                        id="apply-fixes-override-settings-ratio-strategy",
                                        classes="filter-select",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Fix Target",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield Select(
                                        [
                                            (_prefixed_option("Override", "Use Global"), RATIO_TARGET_INHERIT_GLOBAL),
                                            (_prefixed_option("Override", "Fix Request"), RATIO_TARGET_REQUEST),
                                            (_prefixed_option("Override", "Fix Limit"), RATIO_TARGET_LIMIT),
                                        ],
                                        value=self._ratio_target_override,
                                        allow_blank=False,
                                        id="apply-fixes-override-settings-ratio-target",
                                        classes="filter-select",
                                    )
                    if self._is_probe:
                        with CustomVertical(id="apply-fixes-override-settings-probe-pane"):
                            yield CustomStatic(
                                "Probe Override",
                                classes="apply-fixes-modal-panel-title selection-modal-list-title",
                                markup=False,
                            )
                            with CustomHorizontal(id="apply-fixes-override-settings-probe-row-main"):
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "HTTP Path",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="/health",
                                        id="apply-fixes-override-settings-probe-path",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Port Name/Number",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="http",
                                        id="apply-fixes-override-settings-probe-port",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "HTTP Scheme",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield Select(
                                        [
                                            ("HTTP", "HTTP"),
                                            ("HTTPS", "HTTPS"),
                                        ],
                                        value="HTTP",
                                        allow_blank=False,
                                        id="apply-fixes-override-settings-probe-scheme",
                                        classes="filter-select",
                                    )
                            with CustomHorizontal(id="apply-fixes-override-settings-probe-row-advanced"):
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Initial Delay",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="seconds",
                                        id="apply-fixes-override-settings-probe-initial-delay",
                                        restrict=r"[0-9]",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Timeout",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="seconds",
                                        id="apply-fixes-override-settings-probe-timeout",
                                        restrict=r"[0-9]",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Period",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="seconds",
                                        id="apply-fixes-override-settings-probe-period",
                                        restrict=r"[0-9]",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Failure Threshold",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="count",
                                        id="apply-fixes-override-settings-probe-failure-threshold",
                                        restrict=r"[0-9]",
                                    )
                            with CustomHorizontal(id="apply-fixes-override-settings-probe-row-extra"):
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "HTTP Host",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="service.local",
                                        id="apply-fixes-override-settings-probe-host",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Success Threshold",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="count",
                                        id="apply-fixes-override-settings-probe-success-threshold",
                                        restrict=r"[0-9]",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "Grace Period",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="seconds",
                                        id="apply-fixes-override-settings-probe-grace-period",
                                        restrict=r"[0-9]",
                                    )
                                with CustomVertical(classes="apply-fixes-modal-strategy-control"):
                                    yield CustomStatic(
                                        "HTTP Header",
                                        classes="apply-fixes-modal-strategy-title",
                                        markup=False,
                                    )
                                    yield CustomInput(
                                        placeholder="Name:Value",
                                        id="apply-fixes-override-settings-probe-header",
                                    )
            with CustomHorizontal(
                classes="apply-fixes-global-settings-actions selection-modal-actions",
            ):
                yield CustomButton(
                    "Save",
                    id="apply-fixes-override-settings-save",
                    variant="primary",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Reset",
                    id="apply-fixes-override-settings-reset",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Cancel",
                    id="apply-fixes-override-settings-cancel",
                    compact=True,
                    classes="selection-modal-action-btn",
                )

    @staticmethod
    def _probe_field_by_input_id() -> dict[str, str]:
        return {
            "apply-fixes-override-settings-probe-path": "path",
            "apply-fixes-override-settings-probe-port": "port",
            "apply-fixes-override-settings-probe-initial-delay": "initialDelaySeconds",
            "apply-fixes-override-settings-probe-timeout": "timeoutSeconds",
            "apply-fixes-override-settings-probe-period": "periodSeconds",
            "apply-fixes-override-settings-probe-success-threshold": "successThreshold",
            "apply-fixes-override-settings-probe-failure-threshold": "failureThreshold",
            "apply-fixes-override-settings-probe-grace-period": "terminationGracePeriodSeconds",
            "apply-fixes-override-settings-probe-host": "host",
            "apply-fixes-override-settings-probe-header": "header",
        }

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        if self._is_probe:
            for input_id, field in self._probe_field_by_input_id().items():
                with contextlib.suppress(Exception):
                    control = self.query_one(f"#{input_id}", CustomInput)
                    control.value = self._probe_override.get(field, "")
            with contextlib.suppress(Exception):
                scheme = self.query_one("#apply-fixes-override-settings-probe-scheme", Select)
                scheme_value = str(self._probe_override.get("scheme", "HTTP")).strip().upper()
                scheme.value = scheme_value if scheme_value in {"HTTP", "HTTPS"} else "HTTP"

    def on_resize(self, _: Resize) -> None:
        self._apply_dynamic_layout()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "apply-fixes-override-settings-save":
            self.dismiss(self._collect_values())
            return
        if button_id == "apply-fixes-override-settings-reset":
            self.dismiss(
                {
                    "ratio_strategy_override": RATIO_STRATEGY_INHERIT_GLOBAL,
                    "ratio_target_override": RATIO_TARGET_INHERIT_GLOBAL,
                    "probe_override": {},
                }
            )
            return
        self.dismiss(None)

    def _collect_values(self) -> _ViolationOverrideSettingsModalResult:
        ratio_strategy = self._ratio_strategy_override
        ratio_target = self._ratio_target_override
        if self._is_ratio:
            with contextlib.suppress(Exception):
                ratio_strategy = str(
                    self.query_one("#apply-fixes-override-settings-ratio-strategy", Select).value
                )
            with contextlib.suppress(Exception):
                ratio_target = str(
                    self.query_one("#apply-fixes-override-settings-ratio-target", Select).value
                )

        probe_override: dict[str, str] = {}
        if self._is_probe:
            for input_id, field in self._probe_field_by_input_id().items():
                with contextlib.suppress(Exception):
                    control = self.query_one(f"#{input_id}", CustomInput)
                    value = control.value.strip()
                    if not value:
                        continue
                    if field in _PROBE_INT_FIELDS and not value.isdigit():
                        continue
                    probe_override[field] = value
            with contextlib.suppress(Exception):
                scheme = self.query_one("#apply-fixes-override-settings-probe-scheme", Select)
                scheme_value = str(scheme.value).strip().upper()
                if scheme_value in {"HTTP", "HTTPS"}:
                    probe_override["scheme"] = scheme_value

        return {
            "ratio_strategy_override": ratio_strategy,
            "ratio_target_override": ratio_target,
            "probe_override": probe_override,
        }

    def _apply_dynamic_layout(self) -> None:
        available_width = max(
            self._DIALOG_MIN_WIDTH,
            getattr(self.app.size, "width", self._DIALOG_MAX_WIDTH) - 10,
        )
        dialog_width = min(self._DIALOG_MAX_WIDTH, available_width)
        dialog_width = max(self._DIALOG_MIN_WIDTH, dialog_width)
        dialog_width_value = str(dialog_width)

        available_height = max(
            self._DIALOG_MIN_HEIGHT,
            getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT) - 4,
        )
        max_height = min(self._DIALOG_MAX_HEIGHT, available_height)
        dialog_max_height_value = str(max_height)

        with contextlib.suppress(Exception):
            shell = self.query_one(".apply-fixes-global-settings-shell", CustomContainer)
            shell.styles.width = dialog_width_value
            shell.styles.min_width = dialog_width_value
            shell.styles.max_width = dialog_width_value
            shell.styles.height = "auto"
            shell.styles.min_height = "0"
            shell.styles.max_height = dialog_max_height_value
        with contextlib.suppress(Exception):
            scroll = self.query_one("#apply-fixes-override-settings-scroll", CustomVertical)
            scroll.styles.height = "auto"
            scroll.styles.min_height = "0"
            # Keep dialog compact while limiting inner body height before scrolling.
            scroll.styles.max_height = str(max(10, max_height - 12))


class _ApplyAllFixesPreviewModal(ModalScreen[_ApplyAllFixesModalResult | None]):
    """Two-pane modal preview for bulk fix application."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    _DIALOG_MIN_WIDTH = 138
    _DIALOG_MAX_WIDTH = 184
    _DIALOG_MIN_HEIGHT = 30
    _DIALOG_MAX_HEIGHT = 46

    def __init__(
        self,
        *,
        fixable_violations: list[ViolationResult],
        dialog_title: str,
        resolve_chart: Callable[[ViolationResult], Any | None],
        generate_fix: Callable[
            [Any, ViolationResult, str | None, str | None, dict[str, Any] | None],
            dict[str, Any] | None,
        ],
        render_timeout_seconds: int = 30,
    ) -> None:
        super().__init__(classes="selection-modal-screen")
        self._fixable_violations = list(fixable_violations)
        self._dialog_title = dialog_title.strip() or "Fix All"
        self._resolve_chart = resolve_chart
        self._generate_fix = generate_fix
        self._preview_cache: dict[str, str] = {}
        self._preview_request_token: int = 0
        self._global_ratio_strategy = RATIO_STRATEGY_BURSTABLE_15
        self._global_ratio_target = RATIO_TARGET_REQUEST
        self._ratio_strategy_overrides: dict[str, str] = {}
        self._ratio_target_overrides: dict[str, str] = {}
        self._global_probe_settings: dict[str, str] = {}
        self._probe_overrides: dict[str, dict[str, str]] = {}
        self._global_fix_defaults: dict[str, str] = dict(_FIX_DEFAULT_SETTINGS)
        self._selected_violation: ViolationResult | None = None
        self._render_timeout_seconds = max(1, int(render_timeout_seconds))

    def compose(self) -> ComposeResult:
        with CustomContainer(
            classes="apply-fixes-modal-shell selection-modal-shell",
        ):
            yield CustomStatic(
                self._dialog_title,
                classes="selection-modal-title",
                markup=False,
            )
            yield CustomStatic(
                self._summary_text(),
                id="apply-fixes-modal-summary",
                classes="selection-modal-summary",
                markup=False,
            )
            yield CustomStatic(
                self._global_settings_summary(),
                id="apply-fixes-modal-global-settings-summary",
                classes="apply-fixes-modal-config-summary",
                markup=False,
            )
            with CustomHorizontal(
                id="apply-fixes-modal-content",
                classes="apply-fixes-modal-panels",
            ):
                with (
                    CustomVertical(classes="apply-fixes-modal-panel"),
                    CustomVertical(
                        id="apply-fixes-modal-list-pane",
                        classes="apply-fixes-modal-pane-layout",
                    ),
                ):
                    yield CustomStatic(
                        "Fixes To Apply",
                        classes="apply-fixes-modal-panel-title selection-modal-list-title",
                        markup=False,
                    )
                    with CustomVertical(
                        id="apply-fixes-modal-list-wrap",
                        classes="apply-fixes-modal-pane-wrap",
                    ):
                        yield CustomTree("Fixes", id="apply-fixes-modal-tree")
                with (
                    CustomVertical(classes="apply-fixes-modal-panel"),
                    CustomVertical(
                        id="apply-fixes-modal-preview-pane",
                        classes="apply-fixes-modal-pane-layout",
                    ),
                ):
                    yield CustomStatic(
                        "Preview",
                        classes="apply-fixes-modal-panel-title selection-modal-list-title",
                        markup=False,
                    )
                    with CustomHorizontal(id="apply-fixes-modal-preview-toolbar"):
                        yield CustomButton(
                            "Show Diff",
                            id="apply-fixes-modal-show-diff-open",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Override Fix Config",
                            id="apply-fixes-modal-override-fix-open",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                    with CustomVertical(
                        id="apply-fixes-modal-preview-wrap",
                        classes="apply-fixes-modal-pane-wrap",
                    ):
                        yield TextualMarkdownViewer(
                            "### Fix Preview\n\nSelect a fix on the left to preview generated YAML.",
                            id="apply-fixes-modal-preview",
                            show_table_of_contents=False,
                        )
            with CustomHorizontal(
                classes="apply-fixes-modal-actions selection-modal-actions",
            ):
                yield CustomButton(
                    "Apply All",
                    id="apply-fixes-modal-apply",
                    variant="primary",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Default Fix Configs",
                    id="apply-fixes-modal-default-fixes-open",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Cancel",
                    id="apply-fixes-modal-cancel",
                    compact=True,
                    classes="selection-modal-action-btn",
                )

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        self._populate_tree()
        self._sync_strategy_selects()
        with contextlib.suppress(Exception):
            self.query_one("#apply-fixes-modal-tree", CustomTree).focus()
        if self._fixable_violations:
            self._selected_violation = self._fixable_violations[0]
            self._sync_strategy_selects()
            self._queue_preview(self._fixable_violations[0])

    def on_resize(self, _: Resize) -> None:
        self._apply_dynamic_layout()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "apply-fixes-modal-apply":
            self.dismiss(
                {
                    "global_ratio_strategy": self._global_ratio_strategy,
                    "ratio_strategy_overrides": dict(self._ratio_strategy_overrides),
                    "global_ratio_target": self._global_ratio_target,
                    "ratio_target_overrides": dict(self._ratio_target_overrides),
                    "global_probe_settings": dict(self._global_probe_settings),
                    "probe_overrides": dict(self._probe_overrides),
                    "global_fix_defaults": dict(self._global_fix_defaults),
                }
            )
            return
        if button_id == "apply-fixes-modal-cancel":
            self.dismiss(None)
            return
        if button_id == "apply-fixes-modal-show-diff-open":
            violation = self._selected_violation
            if violation is None:
                self.notify("Select a fix first to open Show Diff", severity="warning")
                return
            self.call_later(self._open_values_diff_preview_modal, violation)
            return
        if button_id == "apply-fixes-modal-default-fixes-open":
            self.app.push_screen(
                _GlobalViolationSettingsModal(
                    has_ratio_violations=self._has_ratio_violations(),
                    has_probe_violations=self._has_probe_violations(),
                    initial_ratio_strategy=self._global_ratio_strategy,
                    initial_ratio_target=self._global_ratio_target,
                    initial_probe_settings=dict(self._global_probe_settings),
                    initial_fix_defaults=dict(self._global_fix_defaults),
                ),
                self._on_global_settings_closed,
            )
            return
        if button_id == "apply-fixes-modal-override-fix-open":
            self._open_override_fix_settings_modal()

    def on_custom_tree_node_selected(self, event: CustomTree.NodeSelected) -> None:
        if event.tree.id != "apply-fixes-modal-tree":
            return
        violation = getattr(event.node, "data", None)
        if isinstance(violation, ViolationResult):
            self._selected_violation = violation
            self._sync_strategy_selects()
            self._queue_preview(violation)

    def _open_override_fix_settings_modal(self) -> None:
        violation = self._selected_violation
        if violation is None:
            self.notify("Select a violation first to override fix settings", severity="warning")
            return
        if not (_is_ratio_violation(violation) or _is_probe_violation(violation)):
            self.notify("No override options available for this violation", severity="information")
            return

        violation_key = _violation_strategy_key(violation)
        self.app.push_screen(
            _ViolationOverrideSettingsModal(
                violation=violation,
                ratio_strategy_override=self._ratio_strategy_overrides.get(
                    violation_key,
                    RATIO_STRATEGY_INHERIT_GLOBAL,
                ),
                ratio_target_override=self._ratio_target_overrides.get(
                    violation_key,
                    RATIO_TARGET_INHERIT_GLOBAL,
                ),
                probe_override=self._probe_overrides.get(violation_key, {}),
            ),
            lambda result: self._on_override_settings_closed(violation, result),
        )

    def _on_override_settings_closed(
        self,
        violation: ViolationResult,
        result: _ViolationOverrideSettingsModalResult | None,
    ) -> None:
        if result is None:
            return
        violation_key = _violation_strategy_key(violation)
        strategy_override = str(result.get("ratio_strategy_override", RATIO_STRATEGY_INHERIT_GLOBAL))
        target_override = str(result.get("ratio_target_override", RATIO_TARGET_INHERIT_GLOBAL))

        if strategy_override == RATIO_STRATEGY_INHERIT_GLOBAL:
            self._ratio_strategy_overrides.pop(violation_key, None)
        else:
            self._ratio_strategy_overrides[violation_key] = strategy_override

        if target_override == RATIO_TARGET_INHERIT_GLOBAL:
            self._ratio_target_overrides.pop(violation_key, None)
        else:
            self._ratio_target_overrides[violation_key] = target_override

        probe_override = {
            field: str(value).strip()
            for field, value in dict(result.get("probe_override", {})).items()
            if str(value).strip()
        }
        if probe_override:
            self._probe_overrides[violation_key] = probe_override
        else:
            self._probe_overrides.pop(violation_key, None)

        self._preview_cache.clear()
        self._sync_strategy_selects()
        self._queue_preview(violation)

    def _on_global_settings_closed(
        self,
        result: _GlobalViolationSettingsModalResult | None,
    ) -> None:
        if result is None:
            return
        ratio_strategy = str(result.get("global_ratio_strategy", "")).strip()
        ratio_target = str(result.get("global_ratio_target", "")).strip()
        if ratio_strategy not in _RATIO_STRATEGY_LABELS:
            ratio_strategy = self._global_ratio_strategy
        if ratio_target not in _RATIO_TARGET_LABELS:
            ratio_target = self._global_ratio_target

        cleaned: dict[str, str] = {}
        raw_probe_settings = result.get("global_probe_settings", {})
        for field in _PROBE_SETTING_FIELDS:
            raw_value = str(raw_probe_settings.get(field, "")).strip()
            if not raw_value:
                continue
            if field in _PROBE_INT_FIELDS and not raw_value.isdigit():
                continue
            cleaned[field] = raw_value

        raw_fix_defaults = dict(result.get("global_fix_defaults", {}))
        normalized_defaults = dict(_FIX_DEFAULT_SETTINGS)
        for key, fallback in _FIX_DEFAULT_SETTINGS.items():
            raw_value = str(raw_fix_defaults.get(key, fallback)).strip()
            normalized_defaults[key] = raw_value or fallback

        unchanged = (
            ratio_strategy == self._global_ratio_strategy
            and ratio_target == self._global_ratio_target
            and cleaned == self._global_probe_settings
            and normalized_defaults == self._global_fix_defaults
        )
        if unchanged:
            return
        self._global_ratio_strategy = ratio_strategy
        self._global_ratio_target = ratio_target
        self._global_probe_settings = cleaned
        self._global_fix_defaults = normalized_defaults
        self._sync_global_settings_summary()
        self._preview_cache.clear()
        if self._selected_violation is not None:
            self._queue_preview(self._selected_violation)

    def _summary_text(self) -> str:
        chart_keys = {
            violation.chart_path or violation.chart_name
            for violation in self._fixable_violations
        }
        return (
            f"{len(self._fixable_violations)} fixable violation(s) across "
            f"{len(chart_keys)} chart(s)"
        )

    def _has_ratio_violations(self) -> bool:
        return any(_is_ratio_violation(violation) for violation in self._fixable_violations)

    def _has_probe_violations(self) -> bool:
        return any(_is_probe_violation(violation) for violation in self._fixable_violations)

    def _global_settings_summary(self) -> str:
        parts: list[str] = []
        if self._has_ratio_violations():
            strategy = _ratio_strategy_label(self._global_ratio_strategy)
            target = _ratio_target_label(self._global_ratio_target)
            parts.append(f"Ratio: {strategy}, {target}")
        if self._has_probe_violations():
            if self._global_probe_settings:
                parts.append(f"Probe: {self._probe_settings_summary_inline()}")
            else:
                parts.append("Probe: using rule defaults")
        parts.append(f"Defaults: {self._fix_defaults_summary_inline()}")
        if not parts:
            return "No global settings available."
        return " | ".join(parts)

    def _probe_settings_summary_inline(self) -> str:
        labels = {
            "path": "path",
            "port": "port",
            "scheme": "scheme",
            "host": "host",
            "header": "header",
            "initialDelaySeconds": "initial-delay",
            "timeoutSeconds": "timeout",
            "periodSeconds": "period",
            "successThreshold": "success-threshold",
            "failureThreshold": "failure-threshold",
            "terminationGracePeriodSeconds": "grace-period",
        }
        parts = [
            f"{labels[field]}={self._global_probe_settings[field]}"
            for field in _PROBE_SETTING_FIELDS
            if field in self._global_probe_settings
        ]
        return ", ".join(parts)

    def _fix_defaults_summary_inline(self) -> str:
        labels = {
            "cpu_request": "cpu-req",
            "cpu_limit": "cpu-lim",
            "memory_request": "mem-req",
            "memory_limit": "mem-lim",
            "replica_count": "replicas",
            "topology_max_skew": "topology-skew",
            "workload_label_key": "label-key",
        }
        return ", ".join(
            f"{labels[key]}={self._global_fix_defaults.get(key, _FIX_DEFAULT_SETTINGS[key])}"
            for key in (
                "cpu_request",
                "cpu_limit",
                "memory_request",
                "memory_limit",
                "replica_count",
                "topology_max_skew",
                "workload_label_key",
            )
        )

    def _sync_global_settings_summary(self) -> None:
        with contextlib.suppress(Exception):
            summary = self.query_one("#apply-fixes-modal-global-settings-summary", CustomStatic)
            summary.update(self._global_settings_summary())

    def _populate_tree(self) -> None:
        with contextlib.suppress(Exception):
            tree = self.query_one("#apply-fixes-modal-tree", CustomTree)
            tree.root.remove_children()
            tree.root.expand()

            grouped: dict[str, list[ViolationResult]] = {}
            for violation in self._fixable_violations:
                team_name = violation.team or "Unknown"
                group_label = f"{violation.chart_name} ({team_name})"
                grouped.setdefault(group_label, []).append(violation)

            for index, group_label in enumerate(sorted(grouped)):
                violations = sorted(grouped[group_label], key=lambda item: item.rule_name.lower())
                chart_node = tree.root.add(
                    f"[bold]{escape(group_label)}[/] ({len(violations)})",
                )
                if index == 0:
                    chart_node.expand()
                for violation in violations:
                    severity = self._severity_label(violation)
                    sev_style = self._severity_style(violation)
                    leaf = chart_node.add_leaf(
                        f"[{sev_style}]{severity}[/] {escape(violation.rule_name)}",
                    )
                    leaf.data = violation

    def _sync_ratio_controls_visibility(self) -> None:
        selected_is_ratio = (
            self._selected_violation is not None
            and _is_ratio_violation(self._selected_violation)
        )
        selected_is_probe = (
            self._selected_violation is not None
            and _is_probe_violation(self._selected_violation)
        )

        with contextlib.suppress(Exception):
            override_button = self.query_one("#apply-fixes-modal-override-fix-open", CustomButton)
            override_button.disabled = not (selected_is_ratio or selected_is_probe)
            override_button.display = True
        with contextlib.suppress(Exception):
            default_button = self.query_one("#apply-fixes-modal-default-fixes-open", CustomButton)
            default_button.display = True

    def _sync_strategy_selects(self) -> None:
        self._sync_ratio_controls_visibility()
        self._sync_global_settings_summary()

    def _effective_ratio_strategy(self, violation: ViolationResult) -> str | None:
        return _resolve_ratio_strategy_for_violation(
            violation,
            global_strategy=self._global_ratio_strategy,
            overrides=self._ratio_strategy_overrides,
        )

    def _effective_ratio_target(self, violation: ViolationResult) -> str | None:
        return _resolve_ratio_target_for_violation(
            violation,
            global_target=self._global_ratio_target,
            overrides=self._ratio_target_overrides,
        )

    def _effective_probe_settings(self, violation: ViolationResult) -> dict[str, Any] | None:
        return _resolve_probe_settings_for_violation(
            violation,
            global_settings=self._global_probe_settings,
            overrides=self._probe_overrides,
        )

    def _preferred_ai_fix_provider(self) -> LLMProvider | None:
        raw_provider = str(
            getattr(
                getattr(self.app, "settings", None),
                "ai_fix_llm_provider",
                "codex",
            )
        ).strip().lower()
        if raw_provider == LLMProvider.CLAUDE.value:
            return LLMProvider.CLAUDE
        if raw_provider == LLMProvider.CODEX.value:
            return LLMProvider.CODEX
        return None

    def _ai_fix_provider_models(self) -> dict[LLMProvider, str | None]:
        settings = getattr(self.app, "settings", None)
        codex_model = str(getattr(settings, "ai_fix_codex_model", "auto")).strip().lower()
        claude_model = str(getattr(settings, "ai_fix_claude_model", "auto")).strip().lower()
        return {
            LLMProvider.CODEX: None if codex_model in {"", "auto"} else codex_model,
            LLMProvider.CLAUDE: None if claude_model in {"", "auto"} else claude_model,
        }

    @classmethod
    def _preview_cache_key(
        cls,
        violation: ViolationResult,
        ratio_strategy: str | None,
        ratio_target: str | None,
        probe_settings: dict[str, Any] | None,
        global_fix_defaults: dict[str, str] | None,
    ) -> str:
        base_key = cls._preview_key(violation)
        key = base_key
        if ratio_strategy is not None:
            key = f"{key}|strategy={ratio_strategy}"
        if ratio_target is not None:
            key = f"{key}|target={ratio_target}"
        if probe_settings:
            probe_parts = ",".join(
                f"{k}={probe_settings[k]}" for k in sorted(probe_settings)
            )
            key = f"{key}|probe={probe_parts}"
        if global_fix_defaults:
            defaults_parts = ",".join(
                f"{key_name}={global_fix_defaults[key_name]}"
                for key_name in sorted(global_fix_defaults)
            )
            key = f"{key}|defaults={defaults_parts}"
        return key

    def _queue_preview(self, violation: ViolationResult) -> None:
        ratio_strategy = self._effective_ratio_strategy(violation)
        ratio_target = self._effective_ratio_target(violation)
        probe_settings = self._effective_probe_settings(violation)
        preview_cache_key = self._preview_cache_key(
            violation,
            ratio_strategy,
            ratio_target,
            probe_settings,
            self._global_fix_defaults,
        )
        cached = self._preview_cache.get(preview_cache_key)
        if cached is not None:
            self.call_later(self._set_preview_markdown, cached)
            return
        self.call_later(
            self._set_preview_markdown,
            "### Fix Preview\n\nGenerating fix preview...",
        )
        self._preview_request_token += 1
        request_token = self._preview_request_token
        self.call_later(
            self._load_preview,
            violation,
            request_token,
            ratio_strategy,
            ratio_target,
            probe_settings,
            self._global_fix_defaults,
        )

    async def _load_preview(
        self,
        violation: ViolationResult,
        request_token: int,
        ratio_strategy: str | None,
        ratio_target: str | None,
        probe_settings: dict[str, Any] | None,
        global_fix_defaults: dict[str, str] | None,
    ) -> None:
        preview_cache_key = self._preview_cache_key(
            violation,
            ratio_strategy,
            ratio_target,
            probe_settings,
            global_fix_defaults,
        )
        chart = self._resolve_chart(violation)
        if chart is None:
            markdown = self._build_preview_markdown(
                violation=violation,
                fix_yaml="",
                error=f"Chart '{violation.chart_name}' not found",
                ratio_strategy=ratio_strategy,
                ratio_target=ratio_target,
                probe_settings=probe_settings,
            )
        else:
            fix_payload = await asyncio.to_thread(
                self._generate_fix,
                chart,
                violation,
                ratio_strategy,
                ratio_target,
                probe_settings,
            )
            if not fix_payload:
                markdown = self._build_preview_markdown(
                    violation=violation,
                    fix_yaml="",
                    no_fix=True,
                    ratio_strategy=ratio_strategy,
                    ratio_target=ratio_target,
                    probe_settings=probe_settings,
                )
            else:
                fix_payload = _apply_default_fix_settings(
                    violation,
                    fix_payload,
                    global_fix_defaults,
                    chart_name=getattr(chart, "chart_name", violation.chart_name),
                )
                if not fix_payload:
                    markdown = self._build_preview_markdown(
                        violation=violation,
                        fix_yaml="",
                        no_fix=True,
                        ratio_strategy=ratio_strategy,
                        ratio_target=ratio_target,
                        probe_settings=probe_settings,
                    )
                else:
                    verification: FixVerificationResult | None = None
                    markdown = self._build_preview_markdown(
                        violation=violation,
                        fix_yaml=yaml.dump(
                            fix_payload,
                            default_flow_style=False,
                            sort_keys=False,
                        ),
                        ratio_strategy=ratio_strategy,
                        ratio_target=ratio_target,
                        probe_settings=probe_settings,
                        verification=verification,
                    )
        self._preview_cache[preview_cache_key] = markdown
        if request_token != self._preview_request_token:
            return
        await self._set_preview_markdown(markdown)

    async def _set_preview_markdown(self, content: str) -> None:
        with contextlib.suppress(Exception):
            viewer = self.query_one(
                "#apply-fixes-modal-preview",
                TextualMarkdownViewer,
            )
            await viewer.document.update(content)

    async def _open_values_diff_preview_modal(self, violation: ViolationResult) -> None:
        ratio_strategy = self._effective_ratio_strategy(violation)
        ratio_target = self._effective_ratio_target(violation)
        probe_settings = self._effective_probe_settings(violation)

        safe_chart_name = (violation.chart_name or "").replace("`", "'")
        safe_team_name = (violation.team or "Unknown").replace("`", "'")
        subtitle = (
            f"{safe_chart_name} | {safe_team_name} | {self._severity_label(violation)}"
        )
        diff_text = ""

        chart = self._resolve_chart(violation)
        if chart is None:
            markdown = (
                "### Values File Diff\n\n"
                f"Unable to resolve chart for `{safe_chart_name}`."
            )
        else:
            fix_payload = await asyncio.to_thread(
                self._generate_fix,
                chart,
                violation,
                ratio_strategy,
                ratio_target,
                probe_settings,
            )
            if not fix_payload:
                markdown = (
                    "### Values File Diff\n\n"
                    "No auto-fix available for this violation, so diff preview cannot be generated."
                )
            else:
                fix_payload = _apply_default_fix_settings(
                    violation,
                    fix_payload,
                    self._global_fix_defaults,
                    chart_name=getattr(chart, "chart_name", violation.chart_name),
                )
                values_file = str(getattr(chart, "values_file", "") or "")
                values_path = Path(values_file)
                if not fix_payload:
                    markdown = (
                        "### Values File Diff\n\n"
                        "No auto-fix available after applying default settings, so diff preview cannot be generated."
                    )
                elif not values_file:
                    markdown = (
                        "### Values File Diff\n\n"
                        "Chart values file path is missing, so diff preview cannot be generated."
                    )
                elif not values_path.exists():
                    markdown = (
                        "### Values File Diff\n\n"
                        f"Values file not found: `{values_path}`"
                    )
                else:
                    try:
                        current_content = values_path.read_text(encoding="utf-8")
                    except OSError as exc:
                        safe_error = str(exc).replace("`", "'")
                        markdown = (
                            "### Values File Diff\n\n"
                            f"Failed to read values file: `{safe_error}`"
                        )
                    else:
                        try:
                            loaded = yaml.safe_load(current_content) or {}
                        except yaml.YAMLError as exc:
                            safe_error = str(exc).replace("`", "'")
                            markdown = (
                                "### Values File Diff\n\n"
                                f"Failed to parse values file YAML: `{safe_error}`"
                            )
                        else:
                            if not isinstance(loaded, dict):
                                markdown = (
                                    "### Values File Diff\n\n"
                                    "Values file root is not a mapping; merge preview is not supported for this file."
                                )
                            else:
                                proposed = self._deep_merge_preview_dict(
                                    copy.deepcopy(loaded),
                                    fix_payload,
                                )
                                proposed_content = yaml.dump(
                                    proposed,
                                    default_flow_style=False,
                                    sort_keys=False,
                                )
                                diff_lines = list(
                                    difflib.unified_diff(
                                        current_content.splitlines(),
                                        proposed_content.splitlines(),
                                        fromfile=f"{values_path.name} (current)",
                                        tofile=f"{values_path.name} (proposed)",
                                        lineterm="",
                                    )
                                )
                                diff_text = "\n".join(diff_lines).rstrip()
                                safe_values_path = str(values_path).replace("`", "'")

                                markdown_lines = [
                                    "### Values File Diff",
                                    f"- **Chart:** `{safe_chart_name}`",
                                    f"- **Values File:** `{safe_values_path}`",
                                    "",
                                ]
                                if _is_ratio_violation(violation):
                                    strategy_text = _ratio_strategy_label(
                                        ratio_strategy or self._global_ratio_strategy
                                    )
                                    target_text = _ratio_target_label(
                                        ratio_target or self._global_ratio_target
                                    )
                                    markdown_lines.extend(
                                        [
                                            "### Applied Overrides",
                                            f"- **Strategy:** `{strategy_text}`",
                                            f"- **Fix Target:** `{target_text}`",
                                            "",
                                        ]
                                    )
                                if _is_probe_violation(violation) and probe_settings:
                                    markdown_lines.extend(
                                        [
                                            "### Applied Probe Overrides",
                                            "```yaml",
                                            yaml.dump(
                                                probe_settings,
                                                default_flow_style=False,
                                                sort_keys=False,
                                            ).rstrip(),
                                            "```",
                                            "",
                                        ]
                                    )
                                markdown_lines.extend(
                                    [
                                        "### Diff",
                                        "```diff",
                                        diff_text if diff_text else "# No content changes",
                                        "```",
                                    ]
                                )
                                markdown = "\n".join(markdown_lines)

        modal = FixDetailsModal(
            title="Show Diff",
            subtitle=subtitle,
            markdown=markdown,
            actions=(
                ("copy", "Copy Diff", None),
                ("close", "Close", None),
            ),
        )

        def _on_diff_modal_dismiss(action: str | None) -> None:
            if action != "copy":
                return
            if not diff_text:
                self.notify("No diff output to copy", severity="warning")
                return
            self.app.copy_to_clipboard(diff_text)
            self.notify("Diff copied to clipboard", severity="information")

        self.app.push_screen(modal, _on_diff_modal_dismiss)

    @staticmethod
    def _chart_dir_from_chart(chart: object | None) -> Path | None:
        if chart is None:
            return None
        values_file = str(getattr(chart, "values_file", "") or "")
        if not values_file or values_file.startswith("cluster:"):
            return None
        values_path = Path(values_file).expanduser()
        try:
            return values_path.resolve().parent
        except OSError:
            return values_path.parent

    @staticmethod
    def _deep_merge_preview_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        for key, value in override.items():
            if (
                key in base
                and isinstance(base[key], dict)
                and isinstance(value, dict)
            ):
                nested_base = cast(dict[str, Any], base[key])
                nested_override = cast(dict[str, Any], value)
                base[key] = _ApplyAllFixesPreviewModal._deep_merge_preview_dict(
                    nested_base,
                    nested_override,
                )
            else:
                base[key] = value
        return base

    @staticmethod
    def _preview_key(violation: ViolationResult) -> str:
        return _violation_strategy_key(violation)

    @staticmethod
    def _severity_label(violation: ViolationResult) -> str:
        severity_value = (
            violation.severity.value
            if isinstance(violation.severity, Severity)
            else str(violation.severity)
        )
        return severity_value.upper()

    @classmethod
    def _severity_style(cls, violation: ViolationResult) -> str:
        label = cls._severity_label(violation)
        if label == "ERROR":
            return "bold red"
        if label == "WARNING":
            return "bold yellow"
        return "bold cyan"

    def _build_preview_markdown(
        self,
        *,
        violation: ViolationResult,
        fix_yaml: str,
        no_fix: bool = False,
        error: str | None = None,
        ratio_strategy: str | None = None,
        ratio_target: str | None = None,
        probe_settings: dict[str, Any] | None = None,
        verification: FixVerificationResult | None = None,
    ) -> str:
        safe_chart_name = (violation.chart_name or "").replace("`", "'")
        safe_team_name = (violation.team or "Unknown").replace("`", "'")
        lines = [
            f"### {escape(violation.rule_name)}",
            "",
            f"- **Chart:** `{safe_chart_name}`",
            f"- **Team:** `{safe_team_name}`",
            f"- **Severity:** `{self._severity_label(violation)}`",
            "",
        ]
        lines.extend(_violation_description_lines(violation))
        guidance = _fix_guidance_lines(violation)
        if guidance:
            lines.extend([*guidance, ""])
        if _is_ratio_violation(violation):
            strategy_text = _ratio_strategy_label(ratio_strategy or self._global_ratio_strategy)
            target_text = _ratio_target_label(ratio_target or self._global_ratio_target)
            lines.extend(
                [
                    "### Selected Configuration",
                    f"- **Strategy:** `{strategy_text}`",
                    f"- **Fix Target:** `{target_text}`",
                    "",
                ]
            )
        if _is_probe_violation(violation) and probe_settings:
            lines.extend(
                [
                    "### Selected Probe Overrides",
                    "```yaml",
                    yaml.dump(probe_settings, default_flow_style=False, sort_keys=False).rstrip(),
                    "```",
                    "",
                ]
            )
        if error:
            safe_error = error.replace("`", "'")
            lines.extend(
                [
                    "### Status",
                    f"Failed to generate preview: `{safe_error}`",
                ]
            )
            return "\n".join(lines)
        if no_fix:
            lines.extend(
                [
                    "### Status",
                    "No auto-fix available for this violation.",
                ]
            )
            return "\n".join(lines)
        lines.extend(
            [
                "### Generated Fix",
                "```yaml",
                fix_yaml.rstrip(),
                "```",
            ]
        )
        if verification is not None:
            status = verification.status.upper()
            lines.extend(
                [
                    "",
                    "### Rendered Verification",
                    f"- **Status:** `{status}`",
                    f"- **Details:** {verification.note}",
                ]
            )
            if verification.suggestions:
                lines.extend(
                    [
                        "",
                        "### Wiring Suggestions",
                        format_wiring_suggestions_markdown(verification.suggestions),
                    ]
                )
        return "\n".join(lines)

    def _apply_dynamic_layout(self) -> None:
        available_width = max(
            self._DIALOG_MIN_WIDTH,
            getattr(self.app.size, "width", self._DIALOG_MAX_WIDTH) - 8,
        )
        dialog_width = min(self._DIALOG_MAX_WIDTH, available_width)
        dialog_width = max(self._DIALOG_MIN_WIDTH, dialog_width)
        dialog_width_value = str(dialog_width)

        available_height = max(
            self._DIALOG_MIN_HEIGHT,
            getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT) - 2,
        )
        max_height = min(self._DIALOG_MAX_HEIGHT, available_height)
        dialog_min_height = min(self._DIALOG_MIN_HEIGHT, max_height)
        dialog_max_height = max(dialog_min_height, max_height)
        dialog_min_height_value = str(dialog_min_height)
        dialog_max_height_value = str(dialog_max_height)

        with contextlib.suppress(Exception):
            shell = self.query_one(".apply-fixes-modal-shell", CustomContainer)
            shell.styles.width = dialog_width_value
            shell.styles.min_width = dialog_width_value
            shell.styles.max_width = dialog_width_value
            shell.styles.height = dialog_max_height_value
            shell.styles.min_height = dialog_min_height_value
            shell.styles.max_height = dialog_max_height_value

        with contextlib.suppress(Exception):
            content = self.query_one("#apply-fixes-modal-content", CustomHorizontal)
            content.styles.height = "1fr"
            content.styles.min_height = "14"

        with contextlib.suppress(Exception):
            list_pane = self.query_one("#apply-fixes-modal-list-pane", CustomVertical)
            list_pane.styles.width = "1fr"
            list_pane.styles.min_width = "0"
            list_pane.styles.height = "1fr"
            list_pane.styles.min_height = "0"

        with contextlib.suppress(Exception):
            preview_pane = self.query_one("#apply-fixes-modal-preview-pane", CustomVertical)
            preview_pane.styles.width = "1fr"
            preview_pane.styles.min_width = "0"
            preview_pane.styles.height = "1fr"
            preview_pane.styles.min_height = "0"

        with contextlib.suppress(Exception):
            list_wrap = self.query_one("#apply-fixes-modal-list-wrap", CustomVertical)
            list_wrap.styles.height = "1fr"
            list_wrap.styles.min_height = "0"

        with contextlib.suppress(Exception):
            tree_wrapper = self.query_one("#apply-fixes-modal-tree", CustomTree)
            tree_wrapper.styles.height = "1fr"
            tree_wrapper.styles.min_height = "0"
            tree_wrapper.styles.overflow_x = "hidden"
            tree_wrapper.styles.overflow_y = "hidden"
            tree_widget = tree_wrapper.tree
            tree_widget.show_horizontal_scrollbar = True
            tree_widget.show_vertical_scrollbar = True
            tree_widget.styles.height = "1fr"
            tree_widget.styles.min_height = "0"
            tree_widget.styles.overflow_x = "scroll"
            tree_widget.styles.overflow_y = "auto"
            tree_styles = cast(Any, tree_widget.styles)
            tree_styles.text_wrap = "nowrap"

        with contextlib.suppress(Exception):
            preview_wrap = self.query_one("#apply-fixes-modal-preview-wrap", CustomVertical)
            preview_wrap.styles.height = "1fr"
            preview_wrap.styles.min_height = "0"


class ViolationRefreshRequested(Message):
    """Posted when the violations view needs a data refresh."""


# -- Performance caches (module-level) --

_SEV_ORDER: dict[Severity, int] = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

_CAPITALIZED_CACHE: dict[str, str] = {}

_LAYOUT_CLASSES = frozenset({"ultra", "wide", "medium", "narrow"})

_SEV_TEXT: dict[Severity, Text] = {
    Severity.ERROR: Text("ERROR", style="bold #ff3b30"),
    Severity.WARNING: Text("WARN", style="#ff9f0a"),
    Severity.INFO: Text("INFO", style="blue"),
}
_SEV_TEXT_UNKNOWN = Text("???")


def _capitalize(s: str) -> str:
    r = _CAPITALIZED_CACHE.get(s)
    if r is None:
        r = s.capitalize()
        _CAPITALIZED_CACHE[s] = r
    return r


class _ViolationMeta(NamedTuple):
    team: str
    chart_path: str
    chart_key: str
    values_file_type: str
    search_text: str
    formatted_path: str
    severity_rank: int


class ViolationsView(CustomVertical):
    """Violations DataTable + fix preview panel."""

    _ULTRA_MIN_WIDTH = 205
    _WIDE_MIN_WIDTH = 175
    _MEDIUM_MIN_WIDTH = 100
    _RESIZE_DEBOUNCE_SECONDS = 0.08
    _FILTER_INLINE_MIN_WIDTH = 152
    _FILTER_COMPACT_MIN_WIDTH = 118
    _MAIN_CONTENT_INLINE_MIN_WIDTH = 74
    _ROW_INLINE_MIN_WIDTH = 74
    _LOCKED_COLUMN_NAMES = frozenset({"Chart", "Team", "Values File Type"})

    def __init__(self, team_filter: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.violations: list[ViolationResult] = []
        self.charts: list = []
        self.sorted_violations: list[ViolationResult] = []
        self.team_filter: set[str] = {team_filter} if team_filter else set()
        self._chart_team_map: dict[str, str] = {}
        self._chart_path_map: dict[str, str] = {}
        self._chart_by_path: dict[str, object] = {}
        self._chart_by_name: dict[str, object] = {}
        self._filter_options: dict[str, list[tuple[str, str]]] = {}
        self._column_filter_options: tuple[tuple[str, str], ...] = tuple(
            (column_name, column_name) for column_name, _ in OPTIMIZER_TABLE_COLUMNS
        )
        self._visible_column_names: set[str] = {
            column_name for column_name, _ in OPTIMIZER_TABLE_COLUMNS
        }
        self.category_filter: set[str] = set()
        self.severity_filter: set[str] = set()
        self.rule_filter: set[str] = set()
        self.chart_filter: set[str] = set()
        self.values_file_type_filter: set[str] = set()
        self.search_query: str = ""
        self.sort_field: str = SORT_CHART
        self.sort_reverse: bool = False
        self.selected_violation: ViolationResult | None = None
        self._fix_yaml_cache: str = ""
        self._optimizer_controller: UnifiedOptimizerController | None = None
        self._cancel_fixes: bool = False
        self._applying_fixes: bool = False
        self._search_debounce_timer: Timer | None = None
        self._resize_debounce_timer: Timer | None = None
        self._show_advanced_filters: bool = False
        self._table_loading: bool = True
        self._layout_mode: str | None = None
        self._last_table_render_signature: tuple[Any, ...] | None = None
        self._last_table_columns_signature: tuple[int, ...] | None = None
        self._table_populate_sequence: int = 0
        self._optimizer_controller_signature: tuple[str, int] | None = None
        self._violation_meta: dict[int, _ViolationMeta] = {}
        self._ai_full_fix_cache: dict[str, dict[str, Any]] = {}
        self._ai_full_fix_artifacts: dict[str, AIFullFixStagedArtifact] = {}
        self._background_tasks: set[asyncio.Task[Any]] = set()

    def _get_optimizer_controller(self) -> UnifiedOptimizerController:
        analysis_source = str(
            getattr(getattr(self.app, "settings", None), "optimizer_analysis_source", "auto")
        ).strip() or "auto"
        render_timeout = int(
            getattr(getattr(self.app, "settings", None), "helm_template_timeout_seconds", 30)
        )
        controller_signature = (analysis_source, max(1, render_timeout))
        if (
            self._optimizer_controller is None
            or self._optimizer_controller_signature != controller_signature
        ):
            from kubeagle.models.optimization import (
                UnifiedOptimizerController,
            )
            self._optimizer_controller = UnifiedOptimizerController(
                analysis_source=analysis_source,
                render_timeout_seconds=max(1, render_timeout),
            )
            self._optimizer_controller_signature = controller_signature
        return self._optimizer_controller

    def _render_timeout_seconds(self) -> int:
        raw_value = int(
            getattr(
                getattr(self.app, "settings", None),
                "helm_template_timeout_seconds",
                30,
            )
        )
        return max(1, raw_value)

    def _ai_fix_bulk_parallelism(self) -> int:
        raw_setting = getattr(
            getattr(self.app, "settings", None),
            "ai_fix_bulk_parallelism",
            2,
        )
        try:
            raw_value = int(raw_setting)
        except (TypeError, ValueError):
            raw_value = 2
        return max(AI_FIX_BULK_PARALLELISM_MIN, min(raw_value, AI_FIX_BULK_PARALLELISM_MAX))

    def _preferred_ai_fix_provider(self) -> LLMProvider | None:
        raw_provider = str(
            getattr(
                getattr(self.app, "settings", None),
                "ai_fix_llm_provider",
                "codex",
            )
        ).strip().lower()
        if raw_provider == LLMProvider.CLAUDE.value:
            return LLMProvider.CLAUDE
        if raw_provider == LLMProvider.CODEX.value:
            return LLMProvider.CODEX
        return None

    def _ai_fix_provider_models(self) -> dict[LLMProvider, str | None]:
        settings = getattr(self.app, "settings", None)
        codex_model = str(getattr(settings, "ai_fix_codex_model", "auto")).strip().lower()
        claude_model = str(getattr(settings, "ai_fix_claude_model", "auto")).strip().lower()
        return {
            LLMProvider.CODEX: None if codex_model in {"", "auto"} else codex_model,
            LLMProvider.CLAUDE: None if claude_model in {"", "auto"} else claude_model,
        }

    def _ai_fix_full_fix_system_prompt(self) -> str:
        return _normalize_prompt_override(
            getattr(
                getattr(self.app, "settings", None),
                "ai_fix_full_fix_system_prompt",
                "",
            )
        )

    def _clear_ai_full_fix_cache(self) -> None:
        for entry in list(self._ai_full_fix_cache.values()):
            artifact_key = str(entry.get("artifact_key", "")).strip()
            cleanup_on_close = bool(entry.get("artifact_cleanup_on_close", False))
            if artifact_key and cleanup_on_close:
                self._cleanup_ai_full_fix_artifact(artifact_key)
        self._ai_full_fix_cache.clear()

    def compose(self) -> ComposeResult:
        yield CustomHorizontal(
            CustomStatic("", id="error-text"),
            CustomButton("Retry", id="retry-btn"),
            id="error-banner",
        )
        yield CustomVertical(
            CustomHorizontal(
                CustomContainer(
                    CustomStatic("Search", classes="optimizer-filter-group-title"),
                    CustomHorizontal(
                        CustomVertical(
                            CustomHorizontal(
                                CustomInput(placeholder="Search...", id="search-input"),
                                CustomButton("Search", id="search-btn"),
                                CustomButton("Clear", id="clear-search-btn"),
                                id="search-row",
                            ),
                            id="search-control",
                            classes="filter-control",
                        ),
                        classes="optimizer-filter-group-body",
                    ),
                    id="search-group",
                    classes="optimizer-filter-group",
                ),
                CustomContainer(
                    CustomStatic("Filter", classes="optimizer-filter-group-title"),
                    CustomHorizontal(
                        CustomHorizontal(
                            CustomVertical(
                                CustomButton(
                                    "Filters",
                                    id="filters-btn",
                                    classes="filter-picker-btn cluster-tab-filter-trigger",
                                ),
                                id="filters-control",
                                classes="filter-control",
                            ),
                            id="filter-selection-row",
                            classes="cluster-tab-filters-row",
                        ),
                        classes="optimizer-filter-group-body",
                    ),
                    id="filter-group",
                    classes="optimizer-filter-group",
                ),
                CustomContainer(
                    CustomStatic("Sort", classes="optimizer-filter-group-title"),
                    CustomHorizontal(
                        CustomVertical(
                            CustomHorizontal(
                                Select(
                                    [
                                        (_prefixed_option("Sort", label), value)
                                        for value, label in SORT_SELECT_OPTIONS
                                    ],
                                    value=SORT_CHART,
                                    allow_blank=False,
                                    id="sort-select",
                                    classes="filter-select cluster-tab-control-select cluster-tab-sort",
                                ),
                                Select(
                                    SORT_DIRECTION_OPTIONS,
                                    value="asc",
                                    allow_blank=False,
                                    id="sort-order-select",
                                    classes="filter-select cluster-tab-control-select cluster-tab-order",
                                ),
                                id="sort-control-row",
                                classes="cluster-tab-sort-controls",
                            ),
                            id="sort-control",
                            classes="filter-control",
                        ),
                        classes="optimizer-filter-group-body",
                    ),
                    id="sort-group",
                    classes="optimizer-filter-group",
                ),
                CustomContainer(
                    CustomStatic("View", classes="optimizer-filter-group-title"),
                    CustomHorizontal(
                        CustomVertical(
                            Select(
                                [
                                    (_prefixed_option("View", label), value)
                                    for label, value in VIEW_OPTIONS
                                ],
                                value=VIEW_VIOLATIONS,
                                allow_blank=False,
                                id="view-select",
                                classes="filter-select cluster-tab-control-select",
                            ),
                            id="view-control",
                            classes="filter-control",
                        ),
                        classes="optimizer-filter-group-body",
                    ),
                    id="view-group",
                    classes="optimizer-filter-group",
                ),
                id="filter-row",
            ),
            id="filter-bar",
        )
        yield CustomHorizontal(
            CustomVertical(
                CustomHorizontal(
                    CustomVertical(
                        CustomStatic("Violations Table (0)", id="violations-header"),
                        CustomContainer(
                            CustomDataTable(id="violations-table"),
                            CustomContainer(
                                CustomVertical(
                                    CustomLoadingIndicator(id="viol-loading-indicator"),
                                    CustomStatic("Loading violations...", id="viol-loading-message"),
                                    id="viol-loading-row",
                                ),
                                id="viol-loading-overlay",
                            ),
                            id="violations-table-container",
                        ),
                        CustomHorizontal(
                            CustomKPI("Total", "0", id="kpi-total", classes="kpi-inline"),
                            CustomKPI("Errors", "0", status="error", id="kpi-errors", classes="kpi-inline"),
                            CustomKPI(
                                "Warnings",
                                "0",
                                status="warning",
                                id="kpi-warnings",
                                classes="kpi-inline",
                            ),
                            CustomKPI("Info", "0", status="info", id="kpi-info", classes="kpi-inline"),
                            CustomKPI("Charts", "0", id="kpi-charts", classes="kpi-inline"),
                            id="summary-bar",
                        ),
                        id="violations-panel",
                    ),
                    CustomVertical(
                        CustomStatic("Fix Preview", id="preview-title"),
                        CustomRichLog(id="preview-content", wrap=True),
                        CustomHorizontal(
                            CustomButton("Apply Fix", id="preview-fix-btn", variant="primary"),
                            CustomButton("Copy YAML", id="copy-yaml-btn"),
                            id="preview-actions",
                        ),
                        id="preview-panel",
                    ),
                    id="main-content",
                ),
                CustomHorizontal(
                    CustomStatic("", id="action-bar-left-spacer"),
                    CustomButton("Fix All", id="apply-all-btn"),
                    CustomButton("Fix Violation", id="fix-selected-btn"),
                    CustomButton("Fix Selected Chart", id="fix-all-selected-btn"),
                    CustomStatic("", id="action-bar-right-spacer"),
                    id="action-bar",
                ),
                id="violations-left-pane",
            ),
            RecommendationsView(
                id="recommendations-view",
                embedded=True,
            ),
            ResourceImpactView(
                id="impact-analysis-view",
            ),
            id="optimizer-combined-content",
        )

    def initialize(self) -> None:
        """Set up table columns and initial loading state."""
        try:
            table = self.query_one("#violations-table", CustomDataTable)
            table.clear(columns=True)
            self._configure_violations_table_header_tooltips(table)
            self._configure_violations_table_columns(table)
            table.set_loading(False)
        except Exception:
            pass
        self._set_loading_overlay(True, "Loading violations...")
        self.set_recommendations_loading(True)
        # Hide impact analysis view initially
        with contextlib.suppress(Exception):
            self.query_one("#impact-analysis-view", ResourceImpactView).display = False
        # First-pass UX: fix preview is shown via modal instead of inline side panel.
        with contextlib.suppress(Exception):
            self.query_one("#preview-panel", CustomVertical).display = False
        try:
            preview = self.query_one("#preview-content", CustomRichLog)
            preview.write("[dim]Select a violation to preview its fix[/dim]")
        except Exception:
            pass
        self._update_action_states()
        self._force_table_scrollbars()

    def _force_table_scrollbars(self) -> None:
        """Keep both DataTable scrollbars visible and refreshed after layout changes."""
        with contextlib.suppress(Exception):
            table = self.query_one("#violations-table", CustomDataTable)
            table.styles.overflow_x = "auto"
            table.styles.overflow_y = "hidden"
            inner_table = table.data_table
            if inner_table is None:
                return
            inner_styles = cast(Any, inner_table.styles)
            inner_styles.overflow_x = "scroll"
            inner_styles.overflow_y = "auto"
            inner_styles.scrollbar_size_horizontal = 1
            inner_styles.scrollbar_size_vertical = 2
            inner_table.show_horizontal_scrollbar = True
            inner_table.show_vertical_scrollbar = True
            inner_table.refresh(layout=True)

    def on_resize(self, _: Resize) -> None:
        """Re-apply responsive layout and scrollbars after terminal resize."""
        self._schedule_resize_update()

    def on_unmount(self) -> None:
        """Stop debounce timers to prevent leaked timers after widget removal."""
        if self._resize_debounce_timer is not None:
            with contextlib.suppress(Exception):
                self._resize_debounce_timer.stop()
            self._resize_debounce_timer = None
        if self._search_debounce_timer is not None:
            with contextlib.suppress(Exception):
                self._search_debounce_timer.stop()
            self._search_debounce_timer = None

    def on_mount(self) -> None:
        """Adapt responsive layout to initial terminal width."""
        self.call_later(self._update_responsive_layout)

    def update_data(self, violations: list[ViolationResult], charts: list) -> None:
        """Receive data from the parent screen after worker completes."""
        self._optimizer_controller = None
        self._cancel_fixes = False
        self._applying_fixes = False
        self.selected_violation = None
        self._fix_yaml_cache = ""
        self._last_table_render_signature = None
        self._last_table_columns_signature = None
        self._clear_ai_full_fix_cache()

        try:
            table = self.query_one("#violations-table", CustomDataTable)
            table.set_loading(False)
        except Exception:
            pass
        self._set_loading_overlay(False)
        self._table_loading = False

        self.violations = violations
        self.charts = charts
        self._build_chart_indexes(charts)

        self._violation_meta = self._build_violation_meta(violations)

        if not charts:
            self._show_no_charts_state()
            return

        self._update_filter_dropdowns()

        if not violations:
            self._show_no_violations_state()
        else:
            self.populate_violations_table()

        self._update_filter_status()
        self._sync_recommendations_filters()
        self._compute_resource_impact()
        self._schedule_resize_update()

    def update_partial_data(
        self,
        violations: list[ViolationResult],
        charts: list,
        *,
        progress_message: str | None = None,
    ) -> None:
        """Incrementally refresh violations table while analysis is still running."""
        self.violations = violations
        self.charts = charts
        self._build_chart_indexes(charts)

        self._violation_meta = self._build_violation_meta(violations)

        if charts:
            self._update_filter_dropdowns()
            if violations:
                self.populate_violations_table()
            else:
                self._show_no_violations_state()
            self._update_filter_status()
            self._sync_recommendations_filters()
            if progress_message:
                self.update_loading_message(progress_message)

    def _schedule_resize_update(self) -> None:
        """Debounce expensive resize-driven relayout/refresh to avoid flicker."""
        if self._resize_debounce_timer is not None:
            self._resize_debounce_timer.stop()
            self._resize_debounce_timer = None

        self._resize_debounce_timer = self.set_timer(
            self._RESIZE_DEBOUNCE_SECONDS,
            self._run_debounced_resize_update,
        )

    def _run_debounced_resize_update(self) -> None:
        self._resize_debounce_timer = None
        self._update_responsive_layout()
        self._force_table_scrollbars()

    def show_error(self, message: str) -> None:
        """Show error banner and update table."""
        try:
            table = self.query_one("#violations-table", CustomDataTable)
            table.set_loading(False)
        except Exception:
            pass
        self._set_loading_overlay(False)
        self._show_error_banner(message)

    def set_table_loading(self, loading: bool) -> None:
        """Toggle loading state on violations table."""
        self._table_loading = loading
        try:
            table = self.query_one("#violations-table", CustomDataTable)
            table.set_loading(False)
        except Exception:
            pass
        self._set_loading_overlay(loading)
        self._update_action_states()

    def update_loading_message(self, message: str) -> None:
        """Keep header text stable while loading work runs in the background."""
        self._set_loading_overlay(self._table_loading, message)
        with contextlib.suppress(Exception):
            count = len(self.sorted_violations)
            if count == 0 and self.violations:
                count = len(self.get_filtered_violations(self.violations))
            header = self.query_one("#violations-header", CustomStatic)
            header.update(f"Violations Table ({count})")
            header.remove_class("loading")

    def _set_loading_overlay(self, loading: bool, message: str | None = None) -> None:
        with contextlib.suppress(Exception):
            if message:
                self.query_one("#viol-loading-message", CustomStatic).update(message)
        with contextlib.suppress(Exception):
            self.query_one("#viol-loading-overlay", CustomContainer).display = loading

    def set_recommendations_loading(
        self,
        loading: bool,
        message: str = "Loading recommendations...",
    ) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#recommendations-view", RecommendationsView).set_loading(
                loading,
                message,
            )

    def update_recommendations_data(
        self,
        recommendations: list[dict[str, Any]],
        charts: list[Any],
        *,
        partial: bool = False,
    ) -> None:
        with contextlib.suppress(Exception):
            rec_view = self.query_one("#recommendations-view", RecommendationsView)
            if partial:
                rec_view.update_partial_data(recommendations, charts)
            else:
                rec_view.update_data(recommendations, charts)
        self._sync_recommendations_filters()

    def show_recommendations_error(self, message: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#recommendations-view", RecommendationsView).show_error(
                message,
            )

    def focus_recommendation_sort(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#recommendations-view", RecommendationsView).focus_sort()

    def cycle_recommendation_severity(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#recommendations-view", RecommendationsView).cycle_severity()

    def go_to_recommendation_chart(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#recommendations-view", RecommendationsView).go_to_chart()

    @staticmethod
    def _map_recommendation_severity_filter(
        severity_filter: set[str],
    ) -> set[str]:
        mapping = {"error": "critical", "warning": "warning", "info": "info"}
        return {
            mapped
            for severity in severity_filter
            if (mapped := mapping.get(severity))
        }

    def _sync_recommendations_filters(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#recommendations-view", RecommendationsView).set_external_filters(
                search_query=self.search_query,
                category_filter=set(self.category_filter),
                severity_filter=self._map_recommendation_severity_filter(
                    self.severity_filter,
                ),
            )

    # ------------------------------------------------------------------
    # Impact Analysis
    # ------------------------------------------------------------------

    def _compute_resource_impact(self) -> None:
        """Compute and display resource impact analysis."""
        with contextlib.suppress(Exception):
            from kubeagle.optimizer.resource_impact_calculator import (
                ResourceImpactCalculator,
            )

            calculator = ResourceImpactCalculator()
            controller = self._get_optimizer_controller()

            # Fetch cluster nodes from app state when available
            cluster_nodes = None
            with contextlib.suppress(Exception):
                state = getattr(self.app, "state", None)
                if state is not None:
                    nodes = getattr(state, "nodes", None)
                    if nodes:
                        cluster_nodes = nodes

            result = calculator.compute_impact(
                self.charts,
                self.violations,
                optimizer_controller=controller,
                cluster_nodes=cluster_nodes,
            )
            impact_view = self.query_one("#impact-analysis-view", ResourceImpactView)
            impact_view.set_source_data(
                result,
                charts=self.charts,
                violations=self.violations,
                optimizer_controller=controller,
                cluster_nodes=cluster_nodes,
            )

    def show_impact_view(self) -> None:
        """Show the impact analysis view and hide others."""
        with contextlib.suppress(Exception):
            self.query_one("#violations-left-pane", CustomVertical).display = False
        with contextlib.suppress(Exception):
            self.query_one("#recommendations-view", RecommendationsView).display = False
        with contextlib.suppress(Exception):
            self.query_one("#impact-analysis-view", ResourceImpactView).display = True

    def hide_impact_view(self) -> None:
        """Hide the impact analysis view."""
        with contextlib.suppress(Exception):
            self.query_one("#impact-analysis-view", ResourceImpactView).display = False

    def show_violations_view(self) -> None:
        """Show the violations view and hide others."""
        with contextlib.suppress(Exception):
            self.query_one("#violations-left-pane", CustomVertical).display = True
        with contextlib.suppress(Exception):
            self.query_one("#recommendations-view", RecommendationsView).display = True
        with contextlib.suppress(Exception):
            self.query_one("#impact-analysis-view", ResourceImpactView).display = False

    # ------------------------------------------------------------------
    # Chart indexes
    # ------------------------------------------------------------------

    def _build_chart_indexes(self, charts: list) -> None:
        """Build lookup dicts from a charts list for O(1) access."""
        team_map: dict[str, str] = {}
        path_map: dict[str, str] = {}
        by_path: dict[str, object] = {}
        by_name: dict[str, object] = {}

        for chart in charts:
            chart_name = getattr(chart, "name", None)
            chart_team = getattr(chart, "team", None)
            chart_path = getattr(chart, "values_file", None)

            if not chart_name:
                continue

            if chart_team:
                team_map[chart_name] = chart_team

            if chart_path:
                by_path.setdefault(chart_path, chart)
                existing = path_map.get(chart_name)
                if existing is None:
                    path_map[chart_name] = chart_path
                elif existing != chart_path:
                    path_map[chart_name] = ""

            by_name.setdefault(chart_name, chart)

        self._chart_team_map = team_map
        self._chart_path_map = path_map
        self._chart_by_path = by_path
        self._chart_by_name = by_name

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _get_violation_team(self, violation: ViolationResult) -> str:
        if violation.team:
            return violation.team
        return self._chart_team_map.get(violation.chart_name, "Unknown")

    def _get_violation_chart_path(self, violation: ViolationResult) -> str:
        if violation.chart_path:
            return violation.chart_path
        return self._chart_path_map.get(violation.chart_name, "")

    @staticmethod
    def _values_file_type_from_path(values_file: str) -> str:
        normalized = str(values_file or "").strip()
        if not normalized:
            return "Other"
        file_name = Path(normalized).name.lower()
        if "automation" in file_name:
            return "Automation"
        if file_name == "values.yaml":
            return "Main"
        if "default" in file_name:
            return "Default"
        return "Other"

    def _bulk_chart_display_name(self, chart: object) -> str:
        chart_name = str(getattr(chart, "chart_name", "") or getattr(chart, "name", "") or "chart")
        values_file = str(getattr(chart, "values_file", "") or "")
        values_file_type = self._values_file_type_from_path(values_file)
        return f"{chart_name} ({values_file_type})"

    def _get_violation_chart_key(self, violation: ViolationResult) -> str:
        chart_path = self._get_violation_chart_path(violation)
        return chart_path if chart_path else violation.chart_name

    def _build_violation_meta(
        self, violations: list[ViolationResult],
    ) -> dict[int, _ViolationMeta]:
        """Pre-compute per-violation derived fields for O(1) lookups."""
        meta: dict[int, _ViolationMeta] = {}
        fmt_path = self._format_chart_path_display
        chart_team = self._chart_team_map
        chart_path_map = self._chart_path_map
        vft_from_path = self._values_file_type_from_path
        for v in violations:
            team = v.team or chart_team.get(v.chart_name, "Unknown")
            cp = v.chart_path or chart_path_map.get(v.chart_name, "")
            ck = cp if cp else v.chart_name
            vft = vft_from_path(cp)
            st = f"{v.chart_name}\0{v.rule_name}\0{cp}\0{vft}\0{v.description}\0{v.category}\0{team}".lower()
            fp = fmt_path(cp) if cp else "-"
            sr = _SEV_ORDER.get(v.severity, 99)
            meta[id(v)] = _ViolationMeta(team, cp, ck, vft, st, fp, sr)
        return meta

    def _meta(self, v: ViolationResult) -> _ViolationMeta:
        """Return cached per-violation derived fields."""
        m = self._violation_meta.get(id(v))
        if m is not None:
            return m
        team = self._get_violation_team(v)
        chart_path = self._get_violation_chart_path(v)
        chart_key = chart_path if chart_path else v.chart_name
        vft = self._values_file_type_from_path(chart_path)
        search_text = f"{v.chart_name}\0{v.rule_name}\0{chart_path}\0{vft}\0{v.description}\0{v.category}\0{team}".lower()
        formatted_path = self._format_chart_path_display(chart_path) if chart_path else "-"
        sev_rank = _SEV_ORDER.get(v.severity, 99)
        entry = _ViolationMeta(team, chart_path, chart_key, vft, search_text, formatted_path, sev_rank)
        self._violation_meta[id(v)] = entry
        return entry

    def _format_chart_filter_label(self, violation: ViolationResult) -> str:
        return f"{violation.chart_name} ({self._meta(violation).values_file_type})"

    def _find_chart_for_violation(self, violation: ViolationResult) -> Any | None:
        chart_path = self._get_violation_chart_path(violation)
        if chart_path:
            chart = self._chart_by_path.get(chart_path)
            if chart is not None:
                return chart
        return self._chart_by_name.get(violation.chart_name)

    def get_filtered_violations(self, violations: list[ViolationResult]) -> list[ViolationResult]:
        # Single-pass filter using pre-computed _meta() lookups.
        team_f = self.team_filter
        cat_f = self.category_filter
        sev_f = self.severity_filter
        rule_f = self.rule_filter
        chart_f = self.chart_filter
        vft_f = self.values_file_type_filter
        q = self.search_query.strip().lower() if self.search_query else ""
        has_any = team_f or cat_f or sev_f or rule_f or chart_f or vft_f or q
        if not has_any:
            return violations
        result: list[ViolationResult] = []
        for v in violations:
            meta = self._meta(v)
            if team_f and meta.team not in team_f:
                continue
            if cat_f and v.category not in cat_f:
                continue
            if sev_f and v.severity.value not in sev_f:
                continue
            if rule_f and v.rule_name not in rule_f:
                continue
            if chart_f and meta.chart_key not in chart_f:
                continue
            if vft_f and meta.values_file_type.lower() not in vft_f:
                continue
            if q and q not in meta.search_text:
                continue
            result.append(v)
        return result

    @on(Select.Changed, "#sort-select")
    def _on_sort_changed(self, event: Select.Changed) -> None:
        if event.value is not Select.BLANK:
            self.sort_field = str(event.value)
            self.populate_violations_table()

    @on(Select.Changed, "#sort-order-select")
    def _on_sort_order_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self.sort_reverse = str(event.value) == "desc"
        self.populate_violations_table()

    @on(Select.Changed, "#view-select")
    def _on_view_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        view_id = str(event.value)
        if view_id == VIEW_VIOLATIONS:
            self.show_violations_view()
        elif view_id == VIEW_IMPACT:
            self.show_impact_view()

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def populate_violations_table(self) -> None:
        try:
            table = self.query_one("#violations-table", CustomDataTable)
        except Exception:
            return
        visible_column_indices = self._visible_column_indices()
        columns_changed = visible_column_indices != self._last_table_columns_signature
        render_signature: tuple[Any, ...] = (
            id(self.violations),
            len(self.violations),
            self.sort_field,
            self.sort_reverse,
            self.search_query.strip().lower(),
            frozenset(self.category_filter),
            frozenset(self.severity_filter),
            frozenset(self.team_filter),
            frozenset(self.rule_filter),
            frozenset(self.chart_filter),
            frozenset(self.values_file_type_filter),
            tuple(self._iter_visible_column_names()),
        )
        if render_signature == self._last_table_render_signature:
            self._update_action_states()
            return
        self._last_table_render_signature = render_signature
        self._table_populate_sequence += 1
        sequence = self._table_populate_sequence

        def _filter_and_sort(
            violations: list[ViolationResult], sf: str, sr: bool,
        ) -> list[ViolationResult]:
            filtered = self.get_filtered_violations(violations)

            def sort_key(v: ViolationResult) -> tuple[object, ...]:
                meta = self._meta(v)
                severity_rank = meta.severity_rank
                team_name = meta.team
                chart_key = meta.chart_key
                values_file_type = meta.values_file_type
                rule_name = v.rule_name
                if sf == SORT_SEVERITY:
                    return (
                        severity_rank,
                        v.category,
                        chart_key,
                        team_name,
                        values_file_type,
                        rule_name,
                    )
                if sf == SORT_CHART:
                    return (
                        chart_key,
                        team_name,
                        values_file_type,
                        severity_rank,
                        v.category,
                        rule_name,
                    )
                if sf == SORT_TEAM:
                    return (
                        team_name,
                        values_file_type,
                        severity_rank,
                        v.category,
                        chart_key,
                        rule_name,
                    )
                if sf == SORT_RULE:
                    return (
                        rule_name,
                        severity_rank,
                        v.category,
                        chart_key,
                        team_name,
                        values_file_type,
                    )
                return (
                    v.category,
                    severity_rank,
                    chart_key,
                    team_name,
                    values_file_type,
                    rule_name,
                )

            return sorted(filtered, key=sort_key, reverse=sr)

        sf, sr = self.sort_field, self.sort_reverse

        async def _do_populate() -> None:
            if sequence != self._table_populate_sequence:
                return
            try:
                if sequence != self._table_populate_sequence:
                    return
                selected_key = self._violation_selection_key(self.selected_violation)
                if len(self.violations) > 50:
                    result = await asyncio.to_thread(_filter_and_sort, self.violations, sf, sr)
                else:
                    result = _filter_and_sort(self.violations, sf, sr)
                if sequence != self._table_populate_sequence:
                    return
                self.sorted_violations = result
                selected_row = self._find_violation_row_by_key(result, selected_key)
                if selected_row is not None:
                    self.selected_violation = result[selected_row]
                elif self.selected_violation is not None:
                    self.selected_violation = None
                    self._fix_yaml_cache = ""

                def _build_visible_rows(
                    violations: list[ViolationResult],
                    col_indices: tuple[int, ...],
                ) -> list[tuple[str | Text, ...]]:
                    return [
                        tuple(
                            row_values[index]
                            for index in col_indices
                        )
                        for row_values in (
                            self._build_violation_table_row(violation)
                            for violation in violations
                        )
                    ]

                if result and len(result) > 50:
                    visible_rows = await asyncio.to_thread(
                        _build_visible_rows,
                        result,
                        visible_column_indices,
                    )
                else:
                    visible_rows = _build_visible_rows(result, visible_column_indices)
                if sequence != self._table_populate_sequence:
                    return

                async with table.batch():
                    if sequence != self._table_populate_sequence:
                        return
                    # Opt 1: disable cursor animation during bulk row insert
                    dt = table.data_table
                    if dt is not None:
                        dt.show_cursor = False
                        dt.fixed_columns = self._locked_fixed_column_count(
                            visible_column_indices,
                        )
                    if columns_changed:
                        table.clear(columns=True)
                        self._configure_violations_table_header_tooltips(table)
                        self._configure_violations_table_columns(
                            table,
                            visible_column_indices=visible_column_indices,
                        )
                        self._last_table_columns_signature = visible_column_indices
                    else:
                        table.clear(columns=False)
                    try:
                        hdr = self.query_one("#violations-header", CustomStatic)
                        hdr.update(f"Violations Table ({len(result)})")
                        hdr.remove_class("loading")
                    except Exception:
                        pass
                    if visible_rows:
                        table.add_rows(visible_rows)
                        if selected_row is not None:
                            table.cursor_row = selected_row
                    # Restore cursor after bulk insert
                    if dt is not None:
                        dt.show_cursor = True
                    if not result:
                        self._add_state_row(
                            table,
                            values_by_column={
                                "Rule": "[#30d158]No violations found[/#30d158]",
                            },
                            key="state-empty",
                        )
                    self._update_filter_status(result)
                    self._sync_recommendations_filters()
                    self._update_action_states()
            finally:
                if sequence == self._table_populate_sequence:
                    table.set_loading(False)
                    self._force_table_scrollbars()

        self.call_later(_do_populate)

    def _add_violation_table_row(
        self,
        table: CustomDataTable,
        idx: int,
        violation: ViolationResult,
        *,
        visible_column_indices: tuple[int, ...],
    ) -> None:
        """Append one violation row, logging failures without breaking table rendering."""
        try:
            row_values = self._build_violation_table_row(violation)
            table.add_row(
                *(row_values[index] for index in visible_column_indices),
                key=f"v-{idx}",
            )
        except Exception as e:
            logger.warning("Failed to add row for %s: %s", violation.rule_name, e)

    def _build_violation_table_row(self, violation: ViolationResult) -> tuple[str | Text, ...]:
        """Build one canonical violations row aligned with OPTIMIZER_TABLE_COLUMNS order."""
        meta = self._meta(violation)
        return (
            violation.chart_name,
            meta.team,
            meta.values_file_type,
            _SEV_TEXT.get(violation.severity, _SEV_TEXT_UNKNOWN),
            _capitalize(violation.category),
            violation.rule_name,
            violation.current_value,
            meta.formatted_path,
        )

    @staticmethod
    def _format_chart_path_display(values_file: str) -> str:
        """Format values file path for the Chart Path column.

        Shows up to two ancestor directories so nested chart identity is
        preserved (e.g. ``enigma/architect-api/values.yaml``).
        Cluster sources (``cluster:ns``) pass through unchanged.
        """
        if values_file.startswith("cluster:"):
            return values_file
        path = Path(values_file)
        parent = path.parent.name
        grandparent = path.parent.parent.name if parent else ""
        if grandparent:
            return f"{grandparent}/{parent}/{path.name}"
        if parent:
            return f"{parent}/{path.name}"
        return path.name

    def _iter_visible_column_names(self) -> tuple[str, ...]:
        """Return visible table columns in canonical optimizer order."""
        visible_columns = tuple(
            column_name
            for column_name, _ in OPTIMIZER_TABLE_COLUMNS
            if column_name in self._visible_column_names
        )
        if visible_columns:
            return visible_columns
        return (OPTIMIZER_TABLE_COLUMNS[0][0],)

    def _visible_column_indices(self) -> tuple[int, ...]:
        """Return visible optimizer column indexes in canonical order."""
        visible_names = set(self._iter_visible_column_names())
        return tuple(
            index
            for index, (column_name, _) in enumerate(OPTIMIZER_TABLE_COLUMNS)
            if column_name in visible_names
        )

    def _locked_fixed_column_count(
        self,
        visible_column_indices: tuple[int, ...],
    ) -> int:
        """Return contiguous fixed-column count required for locked optimizer columns."""
        visible_column_names = [
            OPTIMIZER_TABLE_COLUMNS[column_index][0]
            for column_index in visible_column_indices
        ]
        locked_positions = [
            position
            for position, column_name in enumerate(visible_column_names)
            if column_name in self._LOCKED_COLUMN_NAMES
        ]
        if not locked_positions:
            return 0
        return max(locked_positions) + 1

    def _configure_violations_table_columns(
        self,
        table: CustomDataTable,
        *,
        visible_column_indices: tuple[int, ...] | None = None,
    ) -> None:
        """Apply visible table columns in canonical order."""
        column_indices = visible_column_indices or self._visible_column_indices()
        if table.data_table is not None:
            table.data_table.fixed_columns = self._locked_fixed_column_count(column_indices)
        for column_index in column_indices:
            column_name, _ = OPTIMIZER_TABLE_COLUMNS[column_index]
            table.add_column(column_name)

    def _add_state_row(
        self,
        table: CustomDataTable,
        *,
        values_by_column: dict[str, str],
        key: str,
    ) -> None:
        """Add a placeholder/message row honoring current visible columns."""
        row_values = [
            values_by_column.get(column_name, "-")
            for column_name in self._iter_visible_column_names()
        ]
        table.add_row(*row_values, key=key)

    def _update_filter_status(
        self,
        filtered: list[ViolationResult] | None = None,
    ) -> None:
        filtered_violations = (
            filtered
            if filtered is not None
            else self.get_filtered_violations(self.violations)
        )
        shown = len(filtered_violations)
        try:
            error_count = sum(
                1 for v in filtered_violations if v.severity == Severity.ERROR
            )
            warn_count = sum(
                1 for v in filtered_violations if v.severity == Severity.WARNING
            )
            info_count = sum(
                1 for v in filtered_violations if v.severity == Severity.INFO
            )
            charts_with = len(
                {self._get_violation_chart_key(v) for v in filtered_violations}
            )
            self.query_one("#kpi-total", CustomKPI).set_value(str(shown))
            self.query_one("#kpi-errors", CustomKPI).set_value(str(error_count))
            self.query_one("#kpi-warnings", CustomKPI).set_value(str(warn_count))
            self.query_one("#kpi-info", CustomKPI).set_value(str(info_count))
            self.query_one("#kpi-charts", CustomKPI).set_value(
                f"{charts_with}/{len(self.charts)}" if self.charts else "0")
        except Exception:
            pass

    def _update_filter_dropdowns(self) -> None:
        category_options = [(label, value) for value, label in CATEGORIES]
        severity_options = [(label, value) for value, label in SEVERITIES]

        unique_teams = sorted({
            team
            for team in self._chart_team_map.values()
            if team
        })
        unique_teams.extend(
            sorted({
                v.team
                for v in self.violations
                if v.team and v.team not in unique_teams
            })
        )
        team_options = [(self._truncate_option_label(team), team) for team in sorted(set(unique_teams))]

        unique_rules = sorted({v.rule_name for v in self.violations})
        rule_options = [
            (self._truncate_option_label(rule_name), rule_name)
            for rule_name in unique_rules
        ]

        chart_options = sorted(
            {
                (
                    self._truncate_option_label(self._format_chart_filter_label(v)),
                    self._get_violation_chart_key(v),
                )
                for v in self.violations
            },
            key=lambda item: (item[0], item[1]),
        )

        values_type_options = sorted({
            self._meta(v).values_file_type.lower()
            for v in self.violations
        })
        values_file_type_options = [
            (value_type.capitalize(), value_type)
            for value_type in values_type_options
        ]

        column_options = list(self._column_filter_options)
        self._filter_options = {
            "category": category_options,
            "severity": severity_options,
            "team": team_options,
            "column": column_options,
            "rule": rule_options,
            "chart": chart_options,
            "values_type": values_file_type_options,
        }

        self._sync_filter_selection_with_options()
        self._update_filters_button_label()
        self._apply_static_filter_select_widths()

    def _sync_filter_selection_with_options(self) -> None:
        for key, selected_values in (
            ("category", self.category_filter),
            ("severity", self.severity_filter),
            ("team", self.team_filter),
            ("rule", self.rule_filter),
            ("chart", self.chart_filter),
            ("values_type", self.values_file_type_filter),
        ):
            valid_values = {value for _, value in self._filter_options.get(key, [])}
            selected_values.intersection_update(valid_values)
        valid_column_names = {value for _, value in self._filter_options.get("column", [])}
        self._visible_column_names.intersection_update(valid_column_names)
        self._visible_column_names.update(self._LOCKED_COLUMN_NAMES & valid_column_names)
        if not self._visible_column_names:
            self._visible_column_names = set(valid_column_names)

    def _get_filter_selected_values(self, key: str) -> set[str]:
        if key == "category":
            return self.category_filter
        if key == "severity":
            return self.severity_filter
        if key == "team":
            return self.team_filter
        if key == "rule":
            return self.rule_filter
        if key == "chart":
            return self.chart_filter
        if key == "values_type":
            return self.values_file_type_filter
        return set()

    def _set_filter_selected_values(self, key: str, values: set[str]) -> None:
        if key == "category":
            self.category_filter = values
        elif key == "severity":
            self.severity_filter = values
        elif key == "team":
            self.team_filter = values
        elif key == "rule":
            self.rule_filter = values
        elif key == "chart":
            self.chart_filter = values
        elif key == "values_type":
            self.values_file_type_filter = values

    def _update_filters_button_label(self) -> None:
        all_column_names = {column_name for column_name, _ in OPTIMIZER_TABLE_COLUMNS}
        has_column_filter = (
            bool(self._visible_column_names)
            and self._visible_column_names != all_column_names
        )
        active_filters = sum(
            1
            for values in (
                self.category_filter,
                self.severity_filter,
                self.team_filter,
                self.rule_filter,
                self.chart_filter,
                self.values_file_type_filter,
            )
            if values
        )
        if has_column_filter:
            active_filters += 1
        label = "Filters"
        if active_filters > 0:
            label = f"Filters ({active_filters})"
        with contextlib.suppress(Exception):
            self.query_one("#filters-btn", CustomButton).label = label

    def _open_filters_modal(self) -> None:
        filter_options = {
            key: tuple(values)
            for key, values in self._filter_options.items()
        }
        modal = _ViolationsFiltersModal(
            filter_options=filter_options,
            selected_values={
                "category": set(self.category_filter),
                "severity": set(self.severity_filter),
                "team": set(self.team_filter),
                "column": set(self._visible_column_names),
                "rule": set(self.rule_filter),
                "chart": set(self.chart_filter),
                "values_type": set(self.values_file_type_filter),
            },
            locked_column_names=set(self._LOCKED_COLUMN_NAMES),
        )
        self.app.push_screen(modal, self._on_filters_modal_dismissed)

    def _on_filters_modal_dismissed(
        self,
        result: _ViolationsFiltersState | None,
    ) -> None:
        if result is None:
            return

        self.category_filter = set(result["category_filter"])
        self.severity_filter = set(result["severity_filter"])
        self.team_filter = set(result["team_filter"])
        visible_column_names = set(result["visible_column_names"])
        visible_column_names.update(self._LOCKED_COLUMN_NAMES)
        self._visible_column_names = (
            visible_column_names
            if visible_column_names
            else {column_name for column_name, _ in OPTIMIZER_TABLE_COLUMNS}
        )
        self.rule_filter = set(result["rule_filter"])
        self.chart_filter = set(result["chart_filter"])
        self.values_file_type_filter = set(result["values_type_filter"])
        self._sync_filter_selection_with_options()
        self._update_filters_button_label()
        self.populate_violations_table()

    @staticmethod
    def _swap_layout_class(widget: Any, mode: str, extras: frozenset[str] = frozenset()) -> None:
        """Replace layout breakpoint classes with *mode* in one operation."""
        to_remove = _LAYOUT_CLASSES | extras
        for cn in to_remove:
            widget.remove_class(cn)
        widget.add_class(mode)

    def _update_filter_bar_layout(self, mode: str) -> None:
        """Apply responsive breakpoint class to filter bar."""
        self._swap_layout_class(self, mode)
        with contextlib.suppress(Exception):
            filter_bar = self.query_one("#filter-bar", CustomVertical)
            self._swap_layout_class(
                filter_bar, mode, frozenset({"stacked", "compact", "advanced-visible"}),
            )
        self._sync_advanced_filter_state()

    def _update_main_content_layout(self, mode: str) -> None:
        """Switch violations table/preview between side-by-side and stacked layouts."""
        with contextlib.suppress(Exception):
            main_content = self.query_one("#main-content", CustomHorizontal)
            self._swap_layout_class(main_content, mode, frozenset({"stacked"}))
            if mode == "narrow":
                main_content.add_class("stacked")

    def _update_row_layouts(self, mode: str) -> None:
        """Stack action row vertically on very narrow terminals."""
        with contextlib.suppress(Exception):
            action_bar = self.query_one("#action-bar", CustomHorizontal)
            action_bar.set_class(mode == "narrow", "stacked")

    def _get_layout_mode(self) -> str:
        width = self.size.width
        if width <= 0:
            # During first mount, child width can be 0 before first real layout pass.
            width = getattr(getattr(self, "app", None), "size", self.size).width
        if width >= self._ULTRA_MIN_WIDTH:
            return "ultra"
        if width >= self._WIDE_MIN_WIDTH:
            return "wide"
        if width >= self._MEDIUM_MIN_WIDTH:
            return "medium"
        return "narrow"

    def _update_responsive_layout(self) -> None:
        """Apply all responsive layout switches for current terminal width."""
        mode = self._get_layout_mode()
        if mode == self._layout_mode:
            return
        self._layout_mode = mode
        self._update_filter_bar_layout(mode)
        self._update_scroll_layout()
        self._update_filters_button_label()
        self._apply_static_action_button_widths()
        self._update_main_content_layout(mode)
        self._update_row_layouts(mode)

    def _update_scroll_layout(self) -> None:
        """Let inner tables/trees own scrolling; keep action row in normal flow."""
        self.styles.overflow_y = "auto"
        self.styles.overflow_x = "hidden"

        with contextlib.suppress(Exception):
            action_bar = self.query_one("#action-bar", CustomHorizontal)
            action_bar.styles.dock = "none"

    def _sync_advanced_filter_state(self) -> None:
        with contextlib.suppress(Exception):
            advanced_btn = self.query_one("#advanced-filters-btn", CustomButton)
            advanced_btn.display = False

    def _toggle_advanced_filters(self) -> None:
        self._show_advanced_filters = not self._show_advanced_filters
        self._sync_advanced_filter_state()

    def _set_fluid_select_width(self, select_id: str, *, control_id: str | None = None) -> None:
        with contextlib.suppress(Exception):
            select = self.query_one(f"#{select_id}", Select)
            select.styles.width = "1fr"
            select.styles.min_width = "0"
            select.styles.max_width = "100%"
        if control_id:
            with contextlib.suppress(Exception):
                control = self.query_one(f"#{control_id}", CustomVertical)
                control.styles.width = "1fr"
                control.styles.min_width = "4"
                control.styles.max_width = "100%"

    def _set_fluid_button_width(self, button_id: str, *, control_id: str | None = None) -> None:
        with contextlib.suppress(Exception):
            button = self.query_one(f"#{button_id}", CustomButton)
            button.styles.width = "1fr"
            # Keep >= 1 writable cell after internal horizontal padding.
            button.styles.min_width = "4"
            button.styles.max_width = "100%"
        if control_id:
            with contextlib.suppress(Exception):
                control = self.query_one(f"#{control_id}", CustomVertical)
                control.styles.width = "1fr"
                control.styles.min_width = "0"
                control.styles.max_width = "100%"

    def _apply_static_action_button_widths(self) -> None:
        with contextlib.suppress(Exception):
            search_input = self.query_one("#search-input", CustomInput)
            search_input.styles.width = "1fr"
            search_input.styles.min_width = "0"
            search_input.styles.max_width = "100%"
        with contextlib.suppress(Exception):
            search_control = self.query_one("#search-control", CustomVertical)
            search_control.styles.width = "1fr"
            search_control.styles.min_width = "0"
            search_control.styles.max_width = "100%"
        self._set_fluid_button_width("search-btn")
        self._set_fluid_button_width("clear-search-btn")

    def _apply_static_filter_select_widths(self) -> None:
        self._set_fluid_select_width("sort-select")
        self._set_fluid_select_width("sort-order-select")
        self._set_fluid_button_width("filters-btn", control_id="filters-control")

    @staticmethod
    def _truncate_option_label(label: str) -> str:
        """Normalize whitespace while preserving full label content."""
        return " ".join(label.split())

    def _has_fixable_selection(self) -> bool:
        violation = self.selected_violation
        return bool(violation and violation.fix_available)

    def _selected_chart_fixable_violations(self) -> list[ViolationResult]:
        """Return fixable violations for the currently selected chart."""
        violation = self.selected_violation
        if violation is None:
            return []
        selected_chart_key = self._get_violation_chart_key(violation)
        return [
            item
            for item in self._current_filtered_violations()
            if item.fix_available and self._get_violation_chart_key(item) == selected_chart_key
        ]

    def _has_fixable_selected_chart(self) -> bool:
        return bool(self._selected_chart_fixable_violations())

    def _current_filtered_violations(self) -> list[ViolationResult]:
        """Return currently visible violations, even before table sort cache is ready."""
        if self.sorted_violations:
            return self.sorted_violations
        if not self.violations:
            return []
        return self.get_filtered_violations(self.violations)

    def _update_action_states(self) -> None:
        """Keep action buttons in sync with current data/selection/loading state."""
        visible_violations = self._current_filtered_violations()
        has_violations = bool(visible_violations)
        can_fix_selected = self._has_fixable_selection() and not self._applying_fixes
        can_fix_all_selected = self._has_fixable_selected_chart() and not self._applying_fixes
        can_apply_all = (
            any(v.fix_available for v in visible_violations)
            and not self._applying_fixes
        )
        can_copy_yaml = bool(self._fix_yaml_cache)
        show_preview_actions = can_fix_selected or can_copy_yaml

        with contextlib.suppress(Exception):
            self.query_one("#apply-all-btn", CustomButton).disabled = not can_apply_all
        with contextlib.suppress(Exception):
            self.query_one("#fix-selected-btn", CustomButton).disabled = not can_fix_selected
        with contextlib.suppress(Exception):
            self.query_one("#fix-all-selected-btn", CustomButton).disabled = not can_fix_all_selected
        with contextlib.suppress(Exception):
            self.query_one("#preview-fix-btn", CustomButton).disabled = not can_fix_selected
        with contextlib.suppress(Exception):
            self.query_one("#copy-yaml-btn", CustomButton).disabled = not can_copy_yaml
        with contextlib.suppress(Exception):
            self.query_one("#sort-order-select", Select).disabled = not has_violations
        with contextlib.suppress(Exception):
            self.query_one("#preview-actions", CustomHorizontal).display = show_preview_actions

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def focus_search(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#search-input", CustomInput).focus()

    def focus_sort(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#sort-select", Select).focus()

    def on_input_changed(self, event: CustomInput.Changed) -> None:
        if event.input.id == "search-input":
            self.search_query = event.value
            if self._search_debounce_timer is not None:
                self._search_debounce_timer.stop()
            self._search_debounce_timer = self.set_timer(0.3, self.populate_violations_table)

    def on_input_submitted(self, event: CustomInput.Submitted) -> None:
        if event.input.id == "search-input":
            self._run_search(event.value)

    def _run_search(self, value: str) -> None:
        self.search_query = value
        self.populate_violations_table()
        with contextlib.suppress(Exception):
            self.query_one("#violations-table", CustomDataTable).focus()

    def _clear_search(self) -> None:
        self.search_query = ""
        with contextlib.suppress(Exception):
            self.query_one("#search-input", CustomInput).value = ""
        self.populate_violations_table()
        with contextlib.suppress(Exception):
            self.query_one("#violations-table", CustomDataTable).focus()

    # ------------------------------------------------------------------
    # Fix preview
    # ------------------------------------------------------------------

    def preview_fix(self) -> None:
        table = self.query_one("#violations-table", CustomDataTable)
        row_key = table.cursor_row
        if row_key is None:
            self.notify("No violation selected - use arrow keys to select a row", severity="warning")
            return
        violation = self._get_violation_for_row(row_key)
        if violation is None:
            self.notify("Select a violation row (not a group header)", severity="information")
            return
        self.selected_violation = violation
        if not violation.fix_available:
            self.notify("No AI fix available for selected violation", severity="information")
            return
        chart = self._find_chart_for_violation(violation)
        if chart is None:
            self.notify(f"Chart not found for '{violation.chart_name}'", severity="error")
            return
        _task = asyncio.create_task(self._open_ai_full_fix_modal_for_single_violation(violation, chart))
        self._background_tasks.add(_task)
        _task.add_done_callback(self._background_tasks.discard)

    def _show_fix_preview(self, violation: ViolationResult) -> None:
        if violation.fix_available:
            chart = self._find_chart_for_violation(violation)
            if chart is not None:
                _task = asyncio.create_task(self._open_ai_full_fix_modal_for_single_violation(violation, chart))
                self._background_tasks.add(_task)
                _task.add_done_callback(self._background_tasks.discard)
                return

        self._fix_yaml_cache = ""
        self._update_action_states()
        async def _do_preview() -> None:
            chart_ref: object | None = self._find_chart_for_violation(violation)
            fix_payload: dict[str, Any] | None = None
            fix_yaml = ""
            verification: FixVerificationResult | None = None
            modal_actions: tuple[tuple[str, str, str | None], ...]

            if chart_ref is None:
                markdown = self._build_violation_fix_markdown(
                    violation=violation,
                    fix_yaml="",
                    error=f"Chart '{violation.chart_name}' not found",
                )
                modal_actions = (("close", "Close", None),)
            else:
                optimizer = self._get_optimizer_controller()
                fix_payload = await asyncio.to_thread(
                    optimizer.generate_fix,
                    chart_ref,
                    violation,
                )
                if not fix_payload:
                    markdown = self._build_violation_fix_markdown(
                        violation=violation,
                        fix_yaml="",
                        no_fix=True,
                    )
                    modal_actions = (("close", "Close", None),)
                else:
                    fix_yaml = yaml.dump(
                        fix_payload,
                        default_flow_style=False,
                        sort_keys=False,
                    )
                    self._fix_yaml_cache = fix_yaml
                    markdown = self._build_violation_fix_markdown(
                        violation=violation,
                        fix_yaml=fix_yaml,
                        verification=verification,
                    )
                    action_items: list[tuple[str, str, str | None]] = [
                        ("apply", "Apply Fix", "primary"),
                        ("copy", "Copy YAML", None),
                    ]
                    action_items.append(("close", "Close", None))
                    modal_actions = tuple(action_items)

            subtitle = (
                f"{violation.chart_name} | "
                f"{self._get_violation_team(violation)} | "
                f"{self._severity_label(violation)}"
            )
            modal = FixDetailsModal(
                title=violation.rule_name,
                subtitle=subtitle,
                markdown=markdown,
                actions=modal_actions,
            )

            def _on_modal_dismiss(action: str | None) -> None:
                if action == "copy":
                    if not fix_yaml:
                        self.notify("No fix YAML to copy", severity="warning")
                        return
                    self.app.copy_to_clipboard(fix_yaml)
                    self.notify("Fix YAML copied to clipboard", severity="information")
                    return
                if action == "apply":
                    if chart_ref is None or fix_payload is None:
                        self.notify("No auto-fix available for this violation", severity="warning")
                        return
                    self._confirm_apply_violation(
                        violation=violation,
                        chart=chart_ref,
                        fix=fix_payload,
                        fix_yaml=fix_yaml,
                    )
                    return

            self.app.push_screen(modal, _on_modal_dismiss)
            self._update_action_states()

        self.call_later(_do_preview)

    def _build_violation_fix_markdown(
        self,
        *,
        violation: ViolationResult,
        fix_yaml: str,
        no_fix: bool = False,
        error: str | None = None,
        verification: FixVerificationResult | None = None,
    ) -> str:
        lines = [
            "### Violation",
            f"- **Rule:** `{violation.rule_name}`",
            f"- **Category:** `{violation.category}`",
            f"- **Severity:** `{self._severity_label(violation)}`",
            f"- **Current Value:** `{violation.current_value}`",
            "",
        ]
        lines.extend(_violation_description_lines(violation))
        ratio_guidance = _ratio_fix_guidance_lines(violation)
        if ratio_guidance:
            lines.extend([*ratio_guidance, ""])
        if error:
            lines.extend(
                [
                    "### Status",
                    f"Failed to generate fix preview: `{error}`",
                ]
            )
            return "\n".join(lines)
        if no_fix:
            lines.extend(
                [
                    "### Status",
                    "No auto-fix available for this violation.",
                ]
            )
            return "\n".join(lines)
        lines.extend(
            [
                "### Generated Fix",
                "```yaml",
                fix_yaml.rstrip(),
                "```",
            ]
        )
        if verification is not None:
            lines.extend(
                [
                    "",
                    "### Rendered Verification",
                    f"- **Status:** `{verification.status.upper()}`",
                    f"- **Details:** {verification.note}",
                ]
            )
            if verification.suggestions:
                lines.extend(
                    [
                        "",
                        "### Wiring Suggestions",
                        format_wiring_suggestions_markdown(verification.suggestions),
                    ]
                )
        return "\n".join(lines)

    @staticmethod
    def _severity_label(violation: ViolationResult) -> str:
        severity_value = (
            violation.severity.value
            if isinstance(violation.severity, Severity)
            else str(violation.severity)
        )
        return severity_value.upper()

    def _confirm_apply_violation(
        self,
        *,
        violation: ViolationResult,
        chart: object,
        fix: dict[str, Any],
        fix_yaml: str,
    ) -> None:
        def on_confirm(result: bool | None) -> None:
            if result:
                self._apply_fix_to_violation(violation, chart, fix)

        self.app.push_screen(
            CustomConfirmDialog(
                f"Apply fix for '{violation.rule_name}' on '{violation.chart_name}'?\n\n{fix_yaml}",
            ),
            on_confirm,
        )

    @staticmethod
    def _chart_dir_from_chart(chart: object | None) -> Path | None:
        if chart is None:
            return None
        values_file = str(getattr(chart, "values_file", "") or "")
        if not values_file or values_file.startswith("cluster:"):
            return None
        values_path = Path(values_file).expanduser()
        try:
            return values_path.resolve().parent
        except OSError:
            return values_path.parent

    # ------------------------------------------------------------------
    # Fix application
    # ------------------------------------------------------------------

    async def fix_violation(self) -> None:
        table = self.query_one("#violations-table", CustomDataTable)
        row_key = table.cursor_row
        if row_key is None:
            self.notify("No violation selected - use arrow keys to select a row", severity="warning")
            return
        violation = self._get_violation_for_row(row_key)
        if violation is None:
            self.notify("Select a violation row (not a group header)", severity="information")
            return
        self.selected_violation = violation
        if not violation.fix_available:
            self.notify("No auto-fix available for selected violation", severity="information")
            return
        chart = self._find_chart_for_violation(violation)
        if chart is None:
            self.notify(f"Chart not found for '{violation.chart_name}'", severity="error")
            return
        await self._open_ai_full_fix_bulk_modal([violation], "Fix Selected Chart")

    async def fix_all_selected(self) -> None:
        table = self.query_one("#violations-table", CustomDataTable)
        row_key = table.cursor_row
        if row_key is None:
            self.notify("No violation selected - use arrow keys to select a row", severity="warning")
            return
        violation = self._get_violation_for_row(row_key)
        if violation is None:
            self.notify("Select a violation row (not a group header)", severity="information")
            return
        self.selected_violation = violation
        chart_fixables = self._selected_chart_fixable_violations()
        if not chart_fixables:
            self.notify(
                f"No fixable violations found for chart '{violation.chart_name}'",
                severity="information",
            )
            return
        await self._open_ai_full_fix_bulk_modal(chart_fixables, "Fix Selected Chart")

    @staticmethod
    def _local_chart_paths_from_chart(chart: object | None) -> tuple[Path, Path] | None:
        if chart is None:
            return None
        values_file = str(getattr(chart, "values_file", "") or "")
        if not values_file or values_file.startswith("cluster:"):
            return None
        values_path = Path(values_file).expanduser().resolve()
        if not values_path.exists():
            return None
        chart_dir = values_path.parent
        if not (chart_dir / "Chart.yaml").exists():
            return None
        return chart_dir, values_path

    @staticmethod
    def _template_allowlist(chart_dir: Path) -> set[str]:
        templates = chart_dir / "templates"
        if not templates.exists():
            return set()
        return {
            str(path.relative_to(chart_dir))
            for path in templates.rglob("*")
            if path.is_file() and path.suffix.lower() in {".yaml", ".yml", ".tpl"}
        }

    @staticmethod
    def _parse_template_patches_json(
        *,
        template_patches_json: str,
        allowed_files: set[str],
    ) -> list[FullFixTemplatePatch]:
        raw_text = str(template_patches_json or "").strip()
        if not raw_text:
            return []
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Template patch JSON parse error: {exc.msg}") from exc
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise ValueError("Template patch JSON must be a list.")
        patches: list[FullFixTemplatePatch] = []
        for index, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"Template patch JSON item {index} must be an object.")
            try:
                patch = FullFixTemplatePatch.model_validate(item)
            except Exception as exc:
                raise ValueError(f"Template patch JSON item {index} is invalid: {exc!s}") from exc
            rel_path = str(patch.file).strip()
            if rel_path not in allowed_files:
                raise ValueError(f"Patch file is outside allowed set: {rel_path}")
            patches.append(patch)
        return patches

    @staticmethod
    def _violation_identity_key_for_bundle(violation: ViolationResult) -> str:
        return (
            f"{violation.chart_name}|{violation.rule_id}|"
            f"{violation.rule_name}|{violation.current_value}"
        )

    def _provider_signature(self) -> str:
        preferred = self._preferred_ai_fix_provider()
        provider_models = self._ai_fix_provider_models()
        full_fix_prompt_hash = _hash_prompt_override(self._ai_fix_full_fix_system_prompt())
        return (
            f"provider={preferred.value if preferred else 'auto'}|"
            f"codex={provider_models.get(LLMProvider.CODEX) or 'auto'}|"
            f"claude={provider_models.get(LLMProvider.CLAUDE) or 'auto'}|"
            f"full_fix_prompt={full_fix_prompt_hash}"
        )

    @staticmethod
    def _status_field_value(status_text: str, key: str) -> str:
        prefix = f"{key.strip().lower()}:"
        for line in str(status_text or "").splitlines():
            normalized = line.strip()
            if normalized.lower().startswith(prefix):
                _, _, value = normalized.partition(":")
                return value.strip()
        return ""

    @classmethod
    def _bundle_verification_counts(
        cls,
        verification: FullFixBundleVerificationResult | None,
    ) -> tuple[int, int, int]:
        if verification is None:
            return 0, 0, 0
        counts = {"verified": 0, "unresolved": 0, "unverified": 0}
        if verification.per_violation:
            for item in verification.per_violation.values():
                status = str(getattr(item, "status", "")).strip().lower()
                if status in {"wiring_issue", "wiring issue"}:
                    status = "unresolved"
                if status in counts:
                    counts[status] += 1
            return counts["verified"], counts["unresolved"], counts["unverified"]
        match = _BUNDLE_VERIFICATION_COUNTS_PATTERN.search(str(verification.note or ""))
        if match is not None:
            return int(match.group(1)), int(match.group(2)), int(match.group(3))
        status = str(verification.status or "").strip().lower()
        if status in {"wiring_issue", "wiring issue"}:
            status = "unresolved"
        if status in counts:
            counts[status] = 1
        return counts["verified"], counts["unresolved"], counts["unverified"]

    @classmethod
    def _bundle_can_apply_verified_subset(
        cls,
        verification: FullFixBundleVerificationResult | None,
    ) -> bool:
        if verification is None:
            return False
        if str(verification.status or "").strip().lower() == "verified":
            return True
        verified_count, _unresolved_count, unverified_count = cls._bundle_verification_counts(verification)
        return verified_count > 0 and unverified_count == 0

    @classmethod
    def _payload_can_apply_verified_subset(cls, payload: dict[str, Any]) -> bool:
        if str(payload.get("can_apply", "false")).strip().lower() == "true":
            return True
        status_text = str(payload.get("status_text", ""))
        verification_note = (
            cls._status_field_value(status_text, "Verification Details")
            or cls._status_field_value(status_text, "Details")
        )
        if not verification_note:
            return False
        render_status = cls._status_field_value(status_text, "Render Verification")
        verification = FullFixBundleVerificationResult(
            status=(render_status or "unresolved").strip().lower(),
            note=verification_note,
        )
        return cls._bundle_can_apply_verified_subset(verification)

    def _selected_model_for_provider_name(self, provider_name: str) -> str:
        normalized_provider = str(provider_name or "").strip().lower()
        provider_models = self._ai_fix_provider_models()
        if normalized_provider == LLMProvider.CLAUDE.value:
            return str(provider_models.get(LLMProvider.CLAUDE) or "auto")
        if normalized_provider == LLMProvider.CODEX.value:
            return str(provider_models.get(LLMProvider.CODEX) or "auto")
        preferred_provider = self._preferred_ai_fix_provider()
        if preferred_provider is None:
            return "auto"
        return str(provider_models.get(preferred_provider) or "auto")

    @staticmethod
    def _provider_display_name(provider_name: str) -> str:
        normalized = str(provider_name or "").strip().lower()
        if normalized == "claude":
            return "Claude"
        if normalized == "codex":
            return "Codex"
        if normalized == "auto":
            return "AI"
        return normalized.capitalize() if normalized else "AI"

    @staticmethod
    def _model_display_name(model_name: str) -> str:
        raw = str(model_name or "").strip()
        if not raw or raw.lower() == "auto":
            return ""
        normalized = raw.replace("_", "-").replace("/", "-")
        tokens = [token for token in re.split(r"[-\\s]+", normalized) if token]
        if not tokens:
            return raw
        acronyms = {"gpt", "llm", "api", "sdk"}
        rendered: list[str] = []
        for token in tokens:
            lowered = token.lower()
            if lowered in acronyms:
                rendered.append(lowered.upper())
            elif lowered.isdigit():
                rendered.append(lowered)
            else:
                rendered.append(lowered.capitalize())
        return " ".join(rendered).strip()

    def _bulk_loading_generation_message(self) -> str:
        preferred_provider = self._preferred_ai_fix_provider()
        provider_name = preferred_provider.value if preferred_provider is not None else "auto"
        model_name = self._selected_model_for_provider_name(provider_name)
        provider_label = self._provider_display_name(provider_name)
        model_label = self._model_display_name(model_name)
        if model_label:
            return f"Generating fix with {provider_label} {model_label}..."
        return f"Generating fix with {provider_label}..."

    def _bulk_overlay_loading_message(self, message: str) -> str:
        raw = str(message or "").strip()
        lowered = raw.lower()
        if not raw:
            return self._bulk_loading_generation_message()
        if any(
            token in lowered
            for token in (
                "generating",
                "preparing deterministic fix seed",
                "trying direct-edit mode",
                "direct-edit:",
                "trying json contract mode",
                "running codex (attempt",
                "running claude (attempt",
                "building preview",
                "building updated file previews",
                "finalizing response",
            )
        ):
            return self._bulk_loading_generation_message()
        return raw

    @staticmethod
    def _claude_agent_sdk_error_details(ai_result: AIFullFixResult) -> list[str]:
        details: list[str] = []
        for raw_error in ai_result.errors:
            error_text = str(raw_error or "").strip()
            if not error_text:
                continue
            lowered = error_text.lower()
            if error_text.lower().startswith("claude:") or "claude-agent-sdk" in lowered or "agent sdk" in lowered:
                details.append(error_text)
        if details:
            return details

        note_text = str(ai_result.note or "").strip()
        tried = {str(item or "").strip().lower() for item in ai_result.tried_providers}
        provider = str(ai_result.provider or "").strip().lower()
        if note_text and (provider == "claude" or "claude" in tried):
            lowered_note = note_text.lower()
            if "claude-agent-sdk" in lowered_note or "agent sdk" in lowered_note:
                details.append(note_text)
        return details

    def _notify_claude_agent_sdk_error(
        self,
        ai_result: AIFullFixResult,
        *,
        context_label: str,
    ) -> None:
        if ai_result.ok:
            return
        details = self._claude_agent_sdk_error_details(ai_result)
        if not details:
            return
        shown = details[:2]
        extra = len(details) - len(shown)
        detail_text = " | ".join(shown)
        if extra > 0:
            detail_text = f"{detail_text} | +{extra} more"
        message = f"{context_label}: Claude Agent SDK error - {detail_text}"
        if len(message) > 420:
            message = f"{message[:417].rstrip()}..."
        with contextlib.suppress(Exception):
            self.notify(message, severity="error")

    def _provider_model_for_result(self, ai_result: AIFullFixResult) -> tuple[str, str]:
        provider_name = str(ai_result.provider or "").strip().lower()
        if not provider_name:
            preferred = self._preferred_ai_fix_provider()
            provider_name = preferred.value if preferred is not None else "auto"
        return provider_name, self._selected_model_for_provider_name(provider_name)

    def _status_with_provider_model(
        self,
        message: str,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> str:
        preferred = self._preferred_ai_fix_provider()
        fallback_provider = preferred.value if preferred is not None else "auto"
        resolved_provider = str(provider_name or "").strip().lower() or fallback_provider
        resolved_model = str(model_name or "").strip() or self._selected_model_for_provider_name(
            resolved_provider
        )
        body = str(message or "").strip() or "Generating fix..."
        return (
            f"{body}\n"
            f"Provider: {resolved_provider}\n"
            f"Model: {resolved_model}"
        )

    def _pending_ai_generation_status(self) -> str:
        return self._status_with_provider_model(self._bulk_loading_generation_message())

    def _queued_bulk_ai_generation_status(self) -> str:
        return self._status_with_provider_model("Queued: waiting for fix worker...")

    def _single_ai_full_fix_cache_key(self, violation: ViolationResult) -> str:
        return f"single|{self._violation_identity_key_for_bundle(violation)}|{self._provider_signature()}"

    def _chart_bundle_ai_full_fix_cache_key(
        self,
        *,
        chart_key: str,
        violations: list[ViolationResult],
    ) -> str:
        parts = sorted(self._violation_identity_key_for_bundle(v) for v in violations)
        return f"chart|{chart_key}|{self._provider_signature()}|{hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()[:16]}"

    def _register_ai_full_fix_artifact(self, artifact: AIFullFixStagedArtifact) -> str:
        artifact_key = f"artifact-{uuid.uuid4().hex}"
        self._ai_full_fix_artifacts[artifact_key] = artifact
        return artifact_key

    def _get_ai_full_fix_artifact(self, artifact_key: str) -> AIFullFixStagedArtifact | None:
        key = str(artifact_key or "").strip()
        if not key:
            return None
        return self._ai_full_fix_artifacts.get(key)

    def _cleanup_ai_full_fix_artifact(self, artifact_key: str) -> None:
        key = str(artifact_key or "").strip()
        if not key:
            return
        artifact = self._ai_full_fix_artifacts.pop(key, None)
        if artifact is None:
            return
        stage_root = Path(artifact.stage_root)
        with contextlib.suppress(OSError):
            if stage_root.exists():
                shutil.rmtree(stage_root)

    def _cleanup_success_ai_full_fix_artifacts(self) -> None:
        for entry in list(self._ai_full_fix_cache.values()):
            artifact_key = str(entry.get("artifact_key", "")).strip()
            cleanup_on_close = bool(entry.get("artifact_cleanup_on_close", False))
            if artifact_key and cleanup_on_close:
                self._cleanup_ai_full_fix_artifact(artifact_key)
                entry["artifact_key"] = ""
                entry["execution_log_text"] = ""
                entry["artifact_cleanup_on_close"] = False

    @staticmethod
    def _merge_patch_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in override.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = ViolationsView._merge_patch_dict(merged[key], value)
            else:
                merged[key] = value
        return merged

    async def _seed_fix_payload_for_violations(
        self,
        chart: object,
        violations: list[ViolationResult],
    ) -> dict[str, Any]:
        optimizer = self._get_optimizer_controller()
        chart_info = cast("ChartInfo", chart)
        seed: dict[str, Any] = {}
        for violation in violations:
            fix_payload = await asyncio.to_thread(
                optimizer.generate_fix,
                chart_info,
                violation,
            )
            if isinstance(fix_payload, dict):
                seed = self._merge_patch_dict(seed, fix_payload)
        return seed

    async def _build_single_ai_full_fix_entry(
        self,
        *,
        violation: ViolationResult,
        chart: object,
        force_refresh: bool = False,
        status_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        cache_key = self._single_ai_full_fix_cache_key(violation)
        if not force_refresh and cache_key in self._ai_full_fix_cache:
            return self._ai_full_fix_cache[cache_key]
        if force_refresh:
            previous = self._ai_full_fix_cache.pop(cache_key, None)
            if isinstance(previous, dict):
                stale_artifact_key = str(previous.get("artifact_key", "")).strip()
                if stale_artifact_key:
                    self._cleanup_ai_full_fix_artifact(stale_artifact_key)

        local_paths = self._local_chart_paths_from_chart(chart)
        if local_paths is None:
            entry = {
                "values_patch_text": "{}\n",
                "template_diff_text": "",
                "status_text": "Chart is not a local Helm chart path.",
                "can_apply": False,
                "verification": None,
                "artifact_key": "",
                "execution_log_text": "",
                "artifact_cleanup_on_close": False,
            }
            self._ai_full_fix_cache[cache_key] = entry
            return entry
        chart_dir, values_path = local_paths
        if status_callback is not None:
            status_callback("Preparing fix seed...")
        seed_payload = await self._seed_fix_payload_for_violations(chart, [violation])
        if status_callback is not None:
            status_callback("Generating fix...")
        full_fix_system_prompt = self._ai_fix_full_fix_system_prompt()
        _worker_cb = None
        if status_callback is not None:
            _app_ref = self.app

            def _thread_safe_cb(text: str) -> None:
                _app_ref.call_from_thread(status_callback, text)

            _worker_cb = _thread_safe_cb
        result = await asyncio.to_thread(
            generate_ai_full_fix_for_violation,
            chart_dir=chart_dir,
            values_path=values_path,
            violation=violation,
            seed_fix_payload=seed_payload,
            timeout_seconds=120,
            preferred_provider=self._preferred_ai_fix_provider(),
            provider_models=self._ai_fix_provider_models(),
            full_fix_system_prompt=full_fix_system_prompt,
            status_callback=_worker_cb,
        )
        self._notify_claude_agent_sdk_error(
            result,
            context_label=f"AI full fix ({violation.chart_name})",
        )
        if status_callback is not None:
            if result.ok:
                status_callback("Building preview...")
            else:
                status_callback("Finalizing response...")
        entry = await self._entry_from_ai_result(
            ai_result=result,
            chart=chart,
            violations=[violation],
            status_callback=status_callback,
        )
        self._ai_full_fix_cache[cache_key] = entry
        return entry

    async def _build_chart_ai_full_fix_entry(
        self,
        *,
        chart_key: str,
        chart: object,
        violations: list[ViolationResult],
        force_refresh: bool = False,
        status_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        cache_key = self._chart_bundle_ai_full_fix_cache_key(
            chart_key=chart_key,
            violations=violations,
        )
        if not force_refresh and cache_key in self._ai_full_fix_cache:
            return self._ai_full_fix_cache[cache_key]
        if force_refresh:
            previous = self._ai_full_fix_cache.pop(cache_key, None)
            if isinstance(previous, dict):
                stale_artifact_key = str(previous.get("artifact_key", "")).strip()
                if stale_artifact_key:
                    self._cleanup_ai_full_fix_artifact(stale_artifact_key)

        local_paths = self._local_chart_paths_from_chart(chart)
        if local_paths is None:
            entry = {
                "values_patch_text": "{}\n",
                "template_diff_text": "",
                "status_text": "Chart is not a local Helm chart path.",
                "can_apply": False,
                "verification": None,
                "artifact_key": "",
                "execution_log_text": "",
                "artifact_cleanup_on_close": False,
            }
            self._ai_full_fix_cache[cache_key] = entry
            return entry
        chart_dir, values_path = local_paths
        if status_callback is not None:
            status_callback("Preparing fix seed...")
        seed_payload = await self._seed_fix_payload_for_violations(chart, violations)
        if status_callback is not None:
            status_callback("Generating fix...")
        full_fix_system_prompt = self._ai_fix_full_fix_system_prompt()
        # Wrap callback for thread-safety: generate_ai_full_fix_for_chart runs
        # in a worker thread via asyncio.to_thread, so widget updates from the
        # callback must be posted back to the main event loop.
        _worker_cb = None
        if status_callback is not None:
            _app_ref = self.app

            def _thread_safe_cb(text: str) -> None:
                _app_ref.call_from_thread(status_callback, text)

            _worker_cb = _thread_safe_cb
        result = await asyncio.to_thread(
            generate_ai_full_fix_for_chart,
            chart_dir=chart_dir,
            values_path=values_path,
            violations=violations,
            seed_fix_payload=seed_payload,
            timeout_seconds=120,
            preferred_provider=self._preferred_ai_fix_provider(),
            provider_models=self._ai_fix_provider_models(),
            full_fix_system_prompt=full_fix_system_prompt,
            status_callback=_worker_cb,
        )
        chart_name = str(getattr(chart, "chart_name", "") or getattr(chart, "name", "") or "chart")
        self._notify_claude_agent_sdk_error(
            result,
            context_label=f"AI full fix ({chart_name})",
        )
        if status_callback is not None:
            if result.ok:
                status_callback("Building preview...")
            else:
                status_callback("Finalizing response...")
        entry = await self._entry_from_ai_result(
            ai_result=result,
            chart=chart,
            violations=violations,
            status_callback=status_callback,
        )
        self._ai_full_fix_cache[cache_key] = entry
        return entry

    async def _entry_from_ai_result(
        self,
        *,
        ai_result: AIFullFixResult,
        chart: object,
        violations: list[ViolationResult],
        status_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        values_patch_text = "{}\n"
        diff_text = ""
        values_preview_text = "{}\n"
        template_preview_text = ""
        values_diff_text = ""
        template_patches: list[FullFixTemplatePatch] = []
        template_patches_json = "[]"
        artifact_key = ""
        execution_log_text = ""
        artifact_cleanup_on_close = False
        verification: FullFixBundleVerificationResult | None = None
        direct_artifact = ai_result.staged_artifact
        if direct_artifact is not None:
            artifact_key = self._register_ai_full_fix_artifact(direct_artifact)
            execution_log_text = str(direct_artifact.execution_log or "").strip()
            (
                values_preview_text,
                template_preview_text,
                values_diff_text,
                values_patch_text,
                diff_text,
            ) = self._build_direct_edit_preview_texts(
                chart=chart,
                artifact=direct_artifact,
            )
        if ai_result.response is not None:
            response_values_patch_text = _full_fix_values_yaml_text(
                ai_result.response.values_patch
            )
            if direct_artifact is None or (values_patch_text.strip() in {"", "{}"} and response_values_patch_text.strip() != "{}"):
                values_patch_text = response_values_patch_text
            template_patches = list(ai_result.response.template_patches)
            template_patches_json = json.dumps(
                [patch.model_dump(mode="json") for patch in template_patches],
                ensure_ascii=True,
            )
            local_paths = self._local_chart_paths_from_chart(chart)
            chart_dir = local_paths[0] if local_paths is not None else None
            if direct_artifact is None or not diff_text.strip():
                diff_text = await asyncio.to_thread(
                    _full_fix_template_diff_text,
                    template_patches,
                    chart_dir=chart_dir,
                )
            if direct_artifact is None:
                (
                    values_preview_text,
                    template_preview_text,
                    values_diff_text,
                ) = self._build_full_bundle_preview_texts(
                    chart=chart,
                    values_patch=ai_result.response.values_patch,
                    template_patches=template_patches,
                    fallback_values_text=values_patch_text,
                    fallback_template_text=diff_text,
                )
        provider_name, selected_model = self._provider_model_for_result(ai_result)
        status_text = _compact_ai_full_fix_status(
            ai_result=ai_result,
            verification=verification,
            violation_count=len(violations),
            provider_label=provider_name,
            model_label=selected_model,
        )
        has_ai_bundle = ai_result.response is not None or direct_artifact is not None
        can_apply = bool(ai_result.ok and has_ai_bundle)
        if direct_artifact is not None and can_apply:
            artifact_cleanup_on_close = True
        raw_output_text = str(ai_result.raw_output_text or "")
        if execution_log_text:
            raw_output_text = execution_log_text
        entry = {
            "values_patch_text": values_patch_text,
            "template_diff_text": diff_text,
            "template_patches_json": template_patches_json,
            "raw_llm_output_text": raw_output_text,
            "artifact_key": artifact_key,
            "execution_log_text": execution_log_text,
            "artifact_cleanup_on_close": artifact_cleanup_on_close,
            "values_preview_text": values_preview_text,
            "template_preview_text": template_preview_text,
            "values_diff_text": values_diff_text,
            "status_text": status_text,
            "can_apply": can_apply,
            "verification": verification,
            "has_ai_bundle": has_ai_bundle,
        }
        return entry

    def _build_direct_edit_preview_texts(
        self,
        *,
        chart: object,
        artifact: AIFullFixStagedArtifact,
    ) -> tuple[str, str, str, str, str]:
        local_paths = self._local_chart_paths_from_chart(chart)
        if local_paths is None:
            return "{}\n", "# FILE: templates/no-changes\n# No template file changes in bundle.\n", "", "{}\n", ""
        chart_dir, values_path = local_paths
        staged_chart_dir = Path(artifact.staged_chart_dir).expanduser().resolve()
        rel_values_path = str(artifact.rel_values_path or "").strip()
        staged_values_path = (staged_chart_dir / rel_values_path).resolve()
        values_preview_text = "{}\n"
        values_patch_text = "{}\n"
        values_diff_text = ""
        template_diff_sections: list[str] = []
        if (
            rel_values_path
            and str(staged_values_path).startswith(str(staged_chart_dir))
            and staged_values_path.exists()
        ):
            try:
                current_values = values_path.read_text(encoding="utf-8")
                staged_values = staged_values_path.read_text(encoding="utf-8")
                values_preview_text = staged_values if staged_values.endswith("\n") else f"{staged_values}\n"
                values_patch_text = values_preview_text
                values_diff_lines = list(
                    difflib.unified_diff(
                        current_values.splitlines(),
                        values_preview_text.splitlines(),
                        fromfile=f"{values_path.name} (current)",
                        tofile=f"{values_path.name} (updated)",
                        lineterm="",
                    )
                )
                values_diff_text = "\n".join(values_diff_lines).rstrip()
            except OSError:
                values_preview_text = "{}\n"
                values_patch_text = "{}\n"

        template_sections: list[str] = []
        for rel_path in artifact.changed_rel_paths:
            if not str(rel_path).startswith("templates/"):
                continue
            original_path = (chart_dir / rel_path).resolve()
            staged_path = (staged_chart_dir / rel_path).resolve()
            if (
                not str(staged_path).startswith(str(staged_chart_dir))
                or not staged_path.exists()
                or not original_path.exists()
            ):
                continue
            try:
                original_content = original_path.read_text(encoding="utf-8")
                content = staged_path.read_text(encoding="utf-8")
            except OSError:
                continue
            diff_lines = list(
                difflib.unified_diff(
                    original_content.splitlines(),
                    content.splitlines(),
                    fromfile=f"a/{rel_path}",
                    tofile=f"b/{rel_path}",
                    lineterm="",
                )
            )
            if diff_lines:
                template_diff_sections.append("\n".join(diff_lines).rstrip())
            template_sections.append(f"# FILE: {rel_path}\n{content.rstrip()}")

        template_preview_text = "\n\n".join(template_sections).strip()
        if template_preview_text:
            template_preview_text = f"{template_preview_text}\n"
        else:
            template_preview_text = (
                "# FILE: templates/no-changes\n"
                "# No template file changes in bundle.\n"
            )
        template_diff_text = "\n\n".join(template_diff_sections).strip()
        return (
            values_preview_text,
            template_preview_text,
            values_diff_text,
            values_patch_text,
            template_diff_text,
        )

    def _build_full_bundle_preview_texts(
        self,
        *,
        chart: object,
        values_patch: dict[str, Any],
        template_patches: list[FullFixTemplatePatch],
        fallback_values_text: str,
        fallback_template_text: str,
    ) -> tuple[str, str, str]:
        """Build full updated values/template previews plus values diff text."""
        local_paths = self._local_chart_paths_from_chart(chart)
        if local_paths is None:
            return fallback_values_text, fallback_template_text, ""

        chart_dir, values_path = local_paths
        values_preview_text = fallback_values_text
        values_diff_text = ""
        template_sections: list[str] = []
        preview_errors: list[str] = []
        try:
            with tempfile.TemporaryDirectory(prefix="kubeagle-full-fix-preview-") as tmp_dir:
                staged_chart_dir = Path(tmp_dir) / chart_dir.name
                shutil.copytree(chart_dir, staged_chart_dir)
                rel_values_path = values_path.relative_to(chart_dir)
                staged_values_path = staged_chart_dir / rel_values_path
                if not staged_values_path.exists():
                    raise ValueError("staged values file path could not be resolved")

                staged_apply_result = apply_full_fix_bundle_atomic(
                    chart_dir=staged_chart_dir,
                    values_path=staged_values_path,
                    values_patch=values_patch,
                    template_patches=template_patches,
                )
                if not staged_apply_result.ok:
                    raise ValueError(staged_apply_result.note)

                current_values_content = values_path.read_text(encoding="utf-8")
                staged_values_content = staged_values_path.read_text(encoding="utf-8")
                values_preview_text = (
                    staged_values_content
                    if staged_values_content.endswith("\n")
                    else f"{staged_values_content}\n"
                )
                values_diff_lines = list(
                    difflib.unified_diff(
                        current_values_content.splitlines(),
                        values_preview_text.splitlines(),
                        fromfile=f"{values_path.name} (current)",
                        tofile=f"{values_path.name} (updated)",
                        lineterm="",
                    )
                )
                values_diff_text = "\n".join(values_diff_lines).rstrip()

                for patch in template_patches:
                    rel_path = str(patch.file).strip()
                    staged_template_path = (staged_chart_dir / rel_path).resolve()
                    if not str(staged_template_path).startswith(str(staged_chart_dir)):
                        preview_errors.append(f"{rel_path}: staged path escapes chart directory")
                        continue
                    if not staged_template_path.exists():
                        preview_errors.append(f"{rel_path}: staged file not found")
                        continue
                    updated_template = staged_template_path.read_text(encoding="utf-8")
                    template_sections.append(
                        f"# FILE: {rel_path}\n{updated_template.rstrip()}"
                    )
        except Exception as exc:
            preview_errors.append(str(exc))
            values_preview_text = fallback_values_text
            values_diff_text = ""

        template_preview_text = "\n\n".join(template_sections).strip()
        if template_preview_text:
            template_preview_text = f"{template_preview_text}\n"
        else:
            if template_patches:
                summary = (
                    "No template preview content could be rendered from generated patches."
                )
                if preview_errors:
                    summary = f"{summary} Errors: {'; '.join(preview_errors[:3])}"
                template_preview_text = (
                    "# FILE: templates/preview-unavailable\n"
                    "# PREVIEW_STATUS: unavailable\n"
                    f"# PREVIEW_ERROR: {summary}\n"
                )
            else:
                template_preview_text = "# FILE: templates/no-changes\n# No template file changes in bundle.\n"

        return values_preview_text, template_preview_text, values_diff_text

    async def _verify_editor_bundle(
        self,
        *,
        chart: object,
        violations: list[ViolationResult],
        values_patch_text: str,
        template_diff_text: str,
        template_patches_json: str | None = None,
        artifact_key: str | None = None,
    ) -> tuple[bool, str, dict[str, Any], list[FullFixTemplatePatch], FullFixBundleVerificationResult | None]:
        _ = violations
        local_paths = self._local_chart_paths_from_chart(chart)
        if local_paths is None:
            return False, "Chart is not a local Helm chart path.", {}, [], None
        chart_dir, _ = local_paths
        requested_artifact_key = str(artifact_key or "").strip()
        artifact = self._get_ai_full_fix_artifact(requested_artifact_key)
        if requested_artifact_key and artifact is None:
            return (
                False,
                "Staged artifact is no longer available. Regenerate AI full fix.",
                {},
                [],
                None,
            )
        if artifact is not None:
            return True, "Verification removed. Staged bundle is ready to apply.", {}, [], None
        allowlist = self._template_allowlist(chart_dir)
        try:
            values_patch = parse_values_patch_yaml(values_patch_text)
        except ValueError as exc:
            return False, f"Values patch parse error: {exc!s}", {}, [], None
        template_patches: list[FullFixTemplatePatch] = []
        if str(template_patches_json or "").strip():
            try:
                template_patches = self._parse_template_patches_json(
                    template_patches_json=str(template_patches_json),
                    allowed_files=allowlist,
                )
            except ValueError as exc:
                return False, str(exc), values_patch, [], None
        if not template_patches:
            try:
                if template_diff_text.strip():
                    template_patches = parse_template_patches_from_bundle_diff(
                        diff_text=template_diff_text,
                        allowed_files=allowlist,
                    )
            except ValueError as exc:
                return False, f"Template diff parse error: {exc!s}", values_patch, [], None
        return True, "Verification removed. Bundle is ready to apply.", values_patch, template_patches, None

    async def _apply_editor_bundle(
        self,
        *,
        chart: object,
        violations: list[ViolationResult],
        values_patch: dict[str, Any],
        template_patches: list[FullFixTemplatePatch],
        verification: FullFixBundleVerificationResult | None,
        artifact_key: str | None = None,
    ) -> tuple[bool, str]:
        local_paths = self._local_chart_paths_from_chart(chart)
        if local_paths is None:
            return False, "Chart is not a local Helm chart path."
        chart_dir, values_path = local_paths
        requested_artifact_key = str(artifact_key or "").strip()
        artifact = self._get_ai_full_fix_artifact(requested_artifact_key)
        if requested_artifact_key and artifact is None:
            return False, "Staged artifact is no longer available. Regenerate AI full fix."
        if artifact is not None:
            apply_result = await asyncio.to_thread(
                promote_staged_workspace_atomic,
                chart_dir=chart_dir,
                staged_chart_dir=Path(artifact.staged_chart_dir),
                changed_rel_paths=list(artifact.changed_rel_paths),
                source_hashes=dict(artifact.source_hashes),
            )
        else:
            apply_result = await asyncio.to_thread(
                apply_full_fix_bundle_via_staged_replace,
                chart_dir=chart_dir,
                values_path=values_path,
                values_patch=values_patch,
                template_patches=template_patches,
            )
        if not apply_result.ok:
            return False, apply_result.note
        if artifact is not None and requested_artifact_key:
            self._cleanup_ai_full_fix_artifact(requested_artifact_key)
        self._set_bundle_verification_on_violations(
            violations=violations,
            verification=verification,
        )
        return True, "Applied AI full fix bundle."

    def _set_bundle_verification_on_violations(
        self,
        *,
        violations: list[ViolationResult],
        verification: FullFixBundleVerificationResult | None,
    ) -> None:
        if verification is None:
            return
        for violation in violations:
            key = self._violation_identity_key_for_bundle(violation)
            item = verification.per_violation.get(key)
            if item is not None:
                violation.fix_verification_status = item.status
                violation.fix_verification_note = item.note
                violation.wiring_suggestions = item.suggestions
            else:
                violation.fix_verification_status = verification.status
                violation.fix_verification_note = verification.note

    async def _open_ai_full_fix_modal_for_single_violation(
        self,
        violation: ViolationResult,
        chart: object,
        *,
        force_refresh: bool = False,
        preset_values_patch_text: str | None = None,
        preset_template_diff_text: str | None = None,
        preset_status_text: str | None = None,
        preset_can_apply: bool | None = None,
        preset_artifact_key: str | None = None,
        preset_execution_log_text: str | None = None,
    ) -> None:
        subtitle = (
            f"{violation.chart_name} | "
            f"{self._get_violation_team(violation)} | "
            f"{self._severity_label(violation)}"
        )
        modal = AIFullFixModal(
            title=f"{violation.rule_name} · AI Full Fix",
            subtitle=subtitle,
            values_patch_text=preset_values_patch_text or "{}\n",
            template_diff_text=preset_template_diff_text or "",
            status_text=preset_status_text or self._pending_ai_generation_status(),
            can_apply=bool(preset_can_apply),
            artifact_key=preset_artifact_key or "",
            execution_log_text=preset_execution_log_text or "",
        )

        def _on_dismiss(result: AIFullFixModalResult | None) -> None:
            if result is None:
                cache_key = self._single_ai_full_fix_cache_key(violation)
                cached_entry = self._ai_full_fix_cache.get(cache_key)
                if isinstance(cached_entry, dict) and bool(cached_entry.get("artifact_cleanup_on_close", False)):
                    artifact_key = str(cached_entry.get("artifact_key", "")).strip()
                    if artifact_key:
                        self._cleanup_ai_full_fix_artifact(artifact_key)
                    self._ai_full_fix_cache.pop(cache_key, None)
                return
            _task = asyncio.create_task(self._handle_single_ai_full_fix_action(violation, chart, result))
            self._background_tasks.add(_task)
            _task.add_done_callback(self._background_tasks.discard)

        self.app.push_screen(modal, _on_dismiss)
        if preset_status_text is None:
            chart_name = str(
                getattr(chart, "chart_name", "")
                or getattr(chart, "name", "")
                or violation.chart_name
            )

            def _status_update(text: str) -> None:
                modal.set_status(
                    self._status_with_provider_model(text),
                    can_apply=False,
                )

            flow_timeout_seconds = max(300, self._render_timeout_seconds() * 8)
            try:
                entry = await asyncio.wait_for(
                    self._build_single_ai_full_fix_entry(
                        violation=violation,
                        chart=chart,
                        force_refresh=force_refresh,
                        status_callback=_status_update,
                    ),
                    timeout=flow_timeout_seconds,
                )
            except asyncio.TimeoutError:
                timeout_message = (
                    "AI full-fix flow timed out. "
                    "LLM stage exceeded time limit."
                )
                modal.set_status(
                    self._status_with_provider_model(timeout_message),
                    can_apply=False,
                )
                self.notify(
                    f"AI full-fix flow timed out for '{chart_name}'",
                    severity="error",
                )
                return
            except Exception as exc:
                logger.exception(
                    "AI full-fix single generation failed for chart %s",
                    chart_name,
                )
                modal.set_status(
                    self._status_with_provider_model(
                        f"AI full-fix flow failed: {exc!s}",
                    ),
                    can_apply=False,
                )
                self.notify(
                    f"AI full-fix flow failed for '{chart_name}': {exc!s}",
                    severity="error",
                )
                return
            modal.set_values_patch_text(str(entry.get("values_patch_text", "{}\n")))
            modal.set_template_diff_text(str(entry.get("template_diff_text", "")))
            modal.set_status(
                str(entry.get("status_text", "AI full fix generation completed.")),
                can_apply=bool(entry.get("can_apply", False)),
            )
            modal.set_execution_context(
                artifact_key=str(entry.get("artifact_key", "")),
                execution_log_text=str(entry.get("execution_log_text", "")),
            )

    async def _handle_single_ai_full_fix_action(
        self,
        violation: ViolationResult,
        chart: object,
        result: AIFullFixModalResult,
    ) -> None:
        action = str(result.get("action", "")).strip()
        values_patch_text = str(result.get("values_patch_text", "{}\n"))
        template_diff_text = str(result.get("template_diff_text", ""))
        artifact_key = str(result.get("artifact_key", "")).strip()
        execution_log_text = str(result.get("execution_log_text", "")).strip()
        if action == "regenerate":
            cache_key = self._single_ai_full_fix_cache_key(violation)
            cached_entry = self._ai_full_fix_cache.pop(cache_key, None)
            if isinstance(cached_entry, dict):
                stale_artifact_key = str(cached_entry.get("artifact_key", "")).strip()
                if stale_artifact_key:
                    self._cleanup_ai_full_fix_artifact(stale_artifact_key)
            await self._open_ai_full_fix_modal_for_single_violation(
                violation,
                chart,
                force_refresh=True,
            )
            return
        if action == "reverify":
            can_apply = True
            status_text = "Verification removed. Bundle is ready to apply."
            await self._open_ai_full_fix_modal_for_single_violation(
                violation,
                chart,
                preset_values_patch_text=values_patch_text,
                preset_template_diff_text=template_diff_text,
                preset_status_text=status_text,
                preset_can_apply=can_apply,
                preset_artifact_key=artifact_key,
                preset_execution_log_text=execution_log_text,
            )
            return
        if action != "apply":
            return
        can_apply, status_note, values_patch, template_patches, verification = await self._verify_editor_bundle(
            chart=chart,
            violations=[violation],
            values_patch_text=values_patch_text,
            template_diff_text=template_diff_text,
            artifact_key=artifact_key,
        )
        if not can_apply:
            hint = _bundle_verification_hint(status_note)
            blocked_status = f"Apply blocked: {status_note}"
            if hint:
                blocked_status = f"{blocked_status}\nHint: {hint}"
            await self._open_ai_full_fix_modal_for_single_violation(
                violation,
                chart,
                preset_values_patch_text=values_patch_text,
                preset_template_diff_text=template_diff_text,
                preset_status_text=blocked_status,
                preset_can_apply=False,
                preset_artifact_key=artifact_key,
                preset_execution_log_text=execution_log_text,
            )
            return
        ok, note = await self._apply_editor_bundle(
            chart=chart,
            violations=[violation],
            values_patch=values_patch,
            template_patches=template_patches,
            verification=verification,
            artifact_key=artifact_key,
        )
        if not ok:
            await self._open_ai_full_fix_modal_for_single_violation(
                violation,
                chart,
                preset_values_patch_text=values_patch_text,
                preset_template_diff_text=template_diff_text,
                preset_status_text=f"Apply failed: {note}",
                preset_can_apply=False,
                preset_artifact_key=artifact_key,
                preset_execution_log_text=execution_log_text,
            )
            return
        if artifact_key:
            self._cleanup_ai_full_fix_artifact(artifact_key)
        self._ai_full_fix_cache.pop(self._single_ai_full_fix_cache_key(violation), None)
        self.notify(
            f"Applied AI full fix for '{violation.rule_name}' on '{violation.chart_name}'",
            severity="information",
        )
        self.post_message(ViolationRefreshRequested())

    @staticmethod
    def _group_violations_by_chart(
        fixable_violations: list[ViolationResult],
        resolve_chart: Callable[[ViolationResult], object | None],
    ) -> dict[str, tuple[object, list[ViolationResult]]]:
        grouped: dict[str, tuple[object, list[ViolationResult]]] = {}
        for violation in fixable_violations:
            chart = resolve_chart(violation)
            if chart is None:
                continue
            values_file = str(getattr(chart, "values_file", "") or "")
            if not values_file or values_file.startswith("cluster:"):
                continue
            chart_key = str(Path(values_file).expanduser().resolve())
            if chart_key in grouped:
                grouped[chart_key][1].append(violation)
            else:
                grouped[chart_key] = (chart, [violation])
        return grouped

    async def _open_ai_full_fix_bulk_modal(
        self,
        fixable_violations: list[ViolationResult],
        dialog_title: str,
    ) -> None:
        grouped = self._group_violations_by_chart(
            fixable_violations,
            self._find_chart_for_violation,
        )
        if not grouped:
            self.notify("No local chart bundles available for AI full fix", severity="warning")
            return
        bundles: list[ChartBundleEditorState] = []
        for chart_key, (chart, violations) in grouped.items():
            chart_name = self._bulk_chart_display_name(chart)
            bundle = ChartBundleEditorState(
                chart_key=chart_key,
                chart_name=chart_name,
                violations=[f"{item.rule_id}: {item.rule_name}" for item in violations],
                status_text=self._queued_bulk_ai_generation_status(),
                is_processing=False,
                is_waiting=True,
            )
            bundles.append(bundle)
        modal = AIFullFixBulkModal(
            title=dialog_title,
            bundles=bundles,
        )

        async def _handle_inline_action(result: AIFullFixBulkModalResult) -> None:
            await self._handle_bulk_ai_full_fix_action(
                grouped,
                dialog_title,
                result,
                modal=modal,
                keep_open=True,
            )

        modal.set_inline_action_handler(_handle_inline_action)

        populate_tasks: list[asyncio.Task[None]] = []

        def _on_dismiss(result: AIFullFixBulkModalResult | None) -> None:
            if result is None:
                # Keep in-flight generation running after close so users can continue
                # working elsewhere while cache hydration finishes in the background.
                self._cleanup_success_ai_full_fix_artifacts()
                return
            for task in populate_tasks:
                if not task.done():
                    task.cancel()
            _task = asyncio.create_task(self._handle_bulk_ai_full_fix_action(grouped, dialog_title, result))
            self._background_tasks.add(_task)
            _task.add_done_callback(self._background_tasks.discard)

        self.app.push_screen(modal, _on_dismiss)

        semaphore = asyncio.Semaphore(self._ai_fix_bulk_parallelism())

        async def _populate_bundle(chart_key: str, chart: object, violations: list[ViolationResult]) -> None:
            async with semaphore:
                chart_name = self._bulk_chart_display_name(chart)
                modal.set_bundle_status(
                    chart_key=chart_key,
                    status_text=self._pending_ai_generation_status(),
                    can_apply=False,
                )
                modal.begin_loading(
                    message=self._bulk_loading_generation_message(),
                )
                loading_ended = False
                llm_started_at = time.perf_counter()
                try:
                    def _status_update(text: str) -> None:
                        modal.set_loading_message(self._bulk_overlay_loading_message(text))
                        modal.set_bundle_status(
                            chart_key=chart_key,
                            status_text=self._status_with_provider_model(text),
                            can_apply=False,
                        )

                    flow_timeout_seconds = max(300, self._render_timeout_seconds() * 8)
                    entry = await asyncio.wait_for(
                        self._build_chart_ai_full_fix_entry(
                            chart_key=chart_key,
                            chart=chart,
                            violations=violations,
                            status_callback=_status_update,
                        ),
                        timeout=flow_timeout_seconds,
                    )
                    llm_elapsed = time.perf_counter() - llm_started_at
                    base_status = str(entry.get("status_text", "LLM response received.")).strip()
                    status_lines = [line for line in base_status.splitlines() if line.strip()]
                    status_lines.append(f"Timing: llm stage {llm_elapsed:.1f}s")
                    base_status = "\n".join(status_lines)
                    entry["status_text"] = base_status
                    entry["can_apply"] = bool(entry.get("can_apply", False))
                    modal.set_bundle_state(
                        chart_key=chart_key,
                        values_patch_text=str(entry.get("values_patch_text", "{}\n")),
                        template_diff_text=str(entry.get("template_diff_text", "")),
                        template_patches_json=str(entry.get("template_patches_json", "[]")),
                        raw_llm_output_text=str(entry.get("raw_llm_output_text", "")),
                        artifact_key=str(entry.get("artifact_key", "")),
                        execution_log_text=str(entry.get("execution_log_text", "")),
                        values_preview_text=str(entry.get("values_preview_text", "{}\n")),
                        template_preview_text=str(entry.get("template_preview_text", "")),
                        values_diff_text=str(entry.get("values_diff_text", "")),
                        status_text=base_status,
                        can_apply=bool(entry.get("can_apply", False)),
                    )
                    cache_key = self._chart_bundle_ai_full_fix_cache_key(
                        chart_key=chart_key,
                        violations=violations,
                    )
                    self._ai_full_fix_cache[cache_key] = entry
                    modal.end_loading()
                    loading_ended = True
                except asyncio.TimeoutError:
                    modal.set_bundle_status(
                        chart_key=chart_key,
                        status_text=(
                            "AI full-fix flow timed out. "
                            "LLM stage exceeded time limit."
                        ),
                        can_apply=False,
                    )
                except Exception as exc:
                    logger.exception("AI full-fix bundle generation failed for chart %s", chart_name)
                    modal.set_bundle_status(
                        chart_key=chart_key,
                        status_text=f"AI full-fix flow failed: {exc!s}",
                        can_apply=False,
                    )
                finally:
                    if not loading_ended:
                        modal.end_loading()

        for chart_key, (chart, violations) in grouped.items():
            populate_tasks.append(asyncio.create_task(_populate_bundle(chart_key, chart, violations)))
        await asyncio.gather(*populate_tasks, return_exceptions=True)
        modal.clear_loading()

    async def _handle_bulk_ai_full_fix_action(
        self,
        grouped: dict[str, tuple[object, list[ViolationResult]]],
        dialog_title: str,
        result: AIFullFixBulkModalResult,
        *,
        modal: AIFullFixBulkModal | None = None,
        keep_open: bool = False,
    ) -> None:
        action = str(result.get("action", "")).strip()
        selected_chart_key = str(result.get("selected_chart_key", "")).strip()
        payload_bundles = dict(result.get("bundles", {}))
        if action == "regenerate":
            target = grouped.get(selected_chart_key)
            if target is not None:
                chart, violations = target
                if modal is not None:
                    modal.set_bundle_status(
                        chart_key=selected_chart_key,
                        status_text=self._status_with_provider_model("Regenerating chart bundle..."),
                        can_apply=False,
                    )
                status_callback: Callable[[str], None] | None = None
                if modal is not None:
                    def _status_update(text: str) -> None:
                        modal.set_loading_message(self._bulk_overlay_loading_message(text))
                        modal.set_bundle_status(
                            chart_key=selected_chart_key,
                            status_text=self._status_with_provider_model(text),
                            can_apply=False,
                        )
                    status_callback = _status_update
                entry = await self._build_chart_ai_full_fix_entry(
                    chart_key=selected_chart_key,
                    chart=chart,
                    violations=violations,
                    force_refresh=True,
                    status_callback=status_callback,
                )
                payload = payload_bundles.setdefault(selected_chart_key, {})
                payload["values_patch_text"] = str(entry.get("values_patch_text", "{}\n"))
                payload["template_diff_text"] = str(entry.get("template_diff_text", ""))
                payload["template_patches_json"] = str(entry.get("template_patches_json", "[]"))
                payload["raw_llm_output_text"] = str(entry.get("raw_llm_output_text", ""))
                payload["artifact_key"] = str(entry.get("artifact_key", ""))
                payload["execution_log_text"] = str(entry.get("execution_log_text", ""))
                payload["values_preview_text"] = str(entry.get("values_preview_text", "{}\n"))
                payload["template_preview_text"] = str(entry.get("template_preview_text", ""))
                payload["values_diff_text"] = str(entry.get("values_diff_text", ""))
                payload["status_text"] = str(entry.get("status_text", "Regenerated"))
                payload["can_apply"] = "true" if bool(entry.get("can_apply", False)) else "false"
                payload["is_processing"] = "false"
                payload["is_waiting"] = "false"
                if modal is not None and hasattr(modal, "set_bundle_state"):
                    modal.set_bundle_state(
                        chart_key=selected_chart_key,
                        values_patch_text=str(payload.get("values_patch_text", "{}\n")),
                        template_diff_text=str(payload.get("template_diff_text", "")),
                        template_patches_json=str(payload.get("template_patches_json", "[]")),
                        raw_llm_output_text=str(payload.get("raw_llm_output_text", "")),
                        artifact_key=str(payload.get("artifact_key", "")),
                        execution_log_text=str(payload.get("execution_log_text", "")),
                        values_preview_text=str(payload.get("values_preview_text", "{}\n")),
                        template_preview_text=str(payload.get("template_preview_text", "")),
                        values_diff_text=str(payload.get("values_diff_text", "")),
                        status_text=str(payload.get("status_text", "Regenerated")),
                        can_apply=str(payload.get("can_apply", "false")).strip().lower() == "true",
                    )
            if keep_open and modal is not None:
                return
            await self._reopen_bulk_modal_from_payload(grouped, dialog_title, payload_bundles)
            return
        if action == "reverify":
            target = grouped.get(selected_chart_key)
            if target is not None:
                _chart, _violations = target
                payload = payload_bundles.get(selected_chart_key, {})
                if modal is not None:
                    modal.set_bundle_status(
                        chart_key=selected_chart_key,
                        status_text=self._status_with_provider_model("Verification removed."),
                        can_apply=False,
                    )
                can_apply = True
                previous_status_text = str(payload.get("status_text", ""))
                status_lines = [
                    "Verification: REMOVED",
                    "Details: Bundle is ready to apply.",
                ]
                timing_value = self._status_field_value(previous_status_text, "Timing")
                if timing_value:
                    status_lines.append(f"Timing: {timing_value}")
                completion_value = self._status_field_value(previous_status_text, "Completion Time")
                if completion_value:
                    status_lines.append(f"Completion Time: {completion_value}")
                status_text = "\n".join(status_lines).strip()
                status_text = self._status_with_provider_model(
                    status_text,
                    provider_name=self._status_field_value(
                        str(payload.get("status_text", "")),
                        "Provider",
                    ),
                    model_name=self._status_field_value(
                        str(payload.get("status_text", "")),
                        "Model",
                    ),
                )
                payload["status_text"] = status_text
                payload["can_apply"] = "true" if can_apply else "false"
                payload["is_processing"] = "false"
                payload["is_waiting"] = "false"
                if modal is not None:
                    modal.set_bundle_status(
                        chart_key=selected_chart_key,
                        status_text=status_text,
                        can_apply=can_apply,
                    )
            if keep_open and modal is not None:
                return
            await self._reopen_bulk_modal_from_payload(grouped, dialog_title, payload_bundles)
            return
        if action == "show-diff":
            target = grouped.get(selected_chart_key)
            if target is not None:
                chart, _ = target
                payload = payload_bundles.get(selected_chart_key, {})
                artifact_key = str(payload.get("artifact_key", "")).strip()
                artifact = self._get_ai_full_fix_artifact(artifact_key)
                if artifact is not None:
                    (
                        values_preview_text,
                        template_preview_text,
                        values_diff_text,
                        values_patch_text,
                        template_diff_text,
                    ) = self._build_direct_edit_preview_texts(
                        chart=chart,
                        artifact=artifact,
                    )
                    payload["values_preview_text"] = values_preview_text
                    payload["template_preview_text"] = template_preview_text
                    payload["values_diff_text"] = values_diff_text
                    payload["values_patch_text"] = values_patch_text
                    payload["template_diff_text"] = template_diff_text
                if modal is not None and hasattr(modal, "set_bundle_state"):
                    modal.set_bundle_state(
                        chart_key=selected_chart_key,
                        values_patch_text=str(payload.get("values_patch_text", "{}\n")),
                        template_diff_text=str(payload.get("template_diff_text", "")),
                        template_patches_json=str(payload.get("template_patches_json", "[]")),
                        raw_llm_output_text=str(payload.get("raw_llm_output_text", "")),
                        artifact_key=str(payload.get("artifact_key", "")),
                        execution_log_text=str(payload.get("execution_log_text", "")),
                        values_preview_text=str(payload.get("values_preview_text", "{}\n")),
                        template_preview_text=str(payload.get("template_preview_text", "")),
                        values_diff_text=str(payload.get("values_diff_text", "")),
                        status_text=str(payload.get("status_text", "Pending")),
                        can_apply=self._payload_can_apply_verified_subset(payload),
                    )
                chart_name = str(getattr(chart, "chart_name", "") or getattr(chart, "name", "") or "chart")
                values_diff_text = str(payload.get("values_diff_text", "")).strip()
                if not values_diff_text:
                    values_diff_text = str(payload.get("values_preview_text", "")).strip()
                template_diff_text = str(payload.get("template_diff_text", "")).strip()
                if not template_diff_text:
                    template_diff_text = str(payload.get("template_preview_text", "")).strip()
                await self._open_bulk_diff_view_modal(
                    title="Bundle Diff",
                    subtitle=f"{chart_name} | Values and templates",
                    values_diff_text=values_diff_text,
                    template_diff_text=template_diff_text,
                )
            if keep_open and modal is not None:
                return
            await self._reopen_bulk_modal_from_payload(grouped, dialog_title, payload_bundles)
            return
        if action == "raw-llm":
            target = grouped.get(selected_chart_key)
            if target is not None:
                chart, _ = target
                payload = payload_bundles.get(selected_chart_key, {})
                chart_name = str(getattr(chart, "chart_name", "") or getattr(chart, "name", "") or "chart")
                raw_text = str(
                    payload.get("execution_log_text")
                    or payload.get("raw_llm_output_text", "")
                ).strip()
                await self._open_bulk_raw_llm_output_modal(
                    title="LLM Output",
                    subtitle=f"{chart_name} | Provider response",
                    raw_text=raw_text,
                )
            if keep_open and modal is not None:
                return
            await self._reopen_bulk_modal_from_payload(grouped, dialog_title, payload_bundles)
            return
        if action != "apply":
            return
        success = 0
        skipped = 0
        failed = 0
        skipped_reasons: list[str] = []
        for chart_key, (chart, violations) in grouped.items():
            payload = payload_bundles.get(chart_key, {})
            chart_name = str(getattr(chart, "chart_name", "") or getattr(chart, "name", "") or "chart")
            if not self._payload_can_apply_verified_subset(payload):
                skipped += 1
                status_text = str(payload.get("status_text", ""))
                reason = (
                    self._status_field_value(status_text, "Verification Details")
                    or self._status_field_value(status_text, "Details")
                    or (status_text.splitlines()[0].strip() if status_text.strip() else "")
                    or "Bundle is not verified for apply."
                )
                skipped_reasons.append(f"{chart_name}: {reason}")
                continue
            can_apply, note, values_patch, template_patches, verification = await self._verify_editor_bundle(
                chart=chart,
                violations=violations,
                values_patch_text=str(payload.get("values_patch_text", "{}\n")),
                template_diff_text=str(payload.get("template_diff_text", "")),
                template_patches_json=str(payload.get("template_patches_json", "[]")),
                artifact_key=str(payload.get("artifact_key", "")),
            )
            if not can_apply:
                skipped += 1
                hint = _bundle_verification_hint(note)
                skipped_status = f"Apply skipped: {note}"
                if hint:
                    skipped_status = f"{skipped_status}\nHint: {hint}"
                payload["status_text"] = skipped_status
                payload["can_apply"] = "false"
                skipped_reasons.append(f"{chart_name}: {note}")
                continue
            ok, apply_note = await self._apply_editor_bundle(
                chart=chart,
                violations=violations,
                values_patch=values_patch,
                template_patches=template_patches,
                verification=verification,
                artifact_key=str(payload.get("artifact_key", "")),
            )
            if ok:
                success += 1
                payload["status_text"] = f"Applied: {apply_note}"
                payload["can_apply"] = "false"
                payload["artifact_key"] = ""
                payload["execution_log_text"] = ""
            else:
                failed += 1
                payload["status_text"] = f"Apply failed: {apply_note}"
                payload["can_apply"] = "false"
        summary = (
            f"AI full fix bulk apply: {success} chart(s) applied"
            + (f", {skipped} skipped" if skipped else "")
            + (f", {failed} failed" if failed else "")
        )
        if skipped and skipped_reasons:
            first_reason = skipped_reasons[0]
            if len(first_reason) > 180:
                first_reason = f"{first_reason[:177].rstrip()}..."
            summary = f"{summary}. First skip: {first_reason}"
        self.notify(
            summary,
            severity="information" if failed == 0 and skipped == 0 else "warning",
        )
        if success > 0:
            self.post_message(ViolationRefreshRequested())

    async def _reopen_bulk_modal_from_payload(
        self,
        grouped: dict[str, tuple[object, list[ViolationResult]]],
        dialog_title: str,
        payload_bundles: dict[str, dict[str, str]],
    ) -> None:
        bundles: list[ChartBundleEditorState] = []
        for chart_key, (chart, violations) in grouped.items():
            payload = payload_bundles.get(chart_key, {})
            chart_name = self._bulk_chart_display_name(chart)
            bundles.append(
                ChartBundleEditorState(
                    chart_key=chart_key,
                    chart_name=chart_name,
                    violations=[f"{item.rule_id}: {item.rule_name}" for item in violations],
                    values_patch_text=str(payload.get("values_patch_text", "{}\n")),
                    template_diff_text=str(payload.get("template_diff_text", "")),
                    template_patches_json=str(payload.get("template_patches_json", "[]")),
                    raw_llm_output_text=str(payload.get("raw_llm_output_text", "")),
                    artifact_key=str(payload.get("artifact_key", "")),
                    execution_log_text=str(payload.get("execution_log_text", "")),
                    values_preview_text=str(
                        payload.get("values_preview_text", payload.get("values_patch_text", "{}\n"))
                    ),
                    template_preview_text=str(
                        payload.get("template_preview_text", payload.get("template_diff_text", ""))
                    ),
                    values_diff_text=str(payload.get("values_diff_text", "")),
                    status_text=str(payload.get("status_text", "Pending")),
                    can_apply=str(payload.get("can_apply", "false")).strip().lower() == "true",
                    is_processing=str(payload.get("is_processing", "false")).strip().lower() == "true",
                    is_waiting=str(payload.get("is_waiting", "false")).strip().lower() == "true",
                )
            )
        modal = AIFullFixBulkModal(
            title=dialog_title,
            bundles=bundles,
        )

        async def _handle_inline_action(result: AIFullFixBulkModalResult) -> None:
            await self._handle_bulk_ai_full_fix_action(
                grouped,
                dialog_title,
                result,
                modal=modal,
                keep_open=True,
            )

        modal.set_inline_action_handler(_handle_inline_action)

        def _on_dismiss(result: AIFullFixBulkModalResult | None) -> None:
            if result is None:
                self._cleanup_success_ai_full_fix_artifacts()
                return
            _task = asyncio.create_task(self._handle_bulk_ai_full_fix_action(grouped, dialog_title, result))
            self._background_tasks.add(_task)
            _task.add_done_callback(self._background_tasks.discard)

        self.app.push_screen(modal, _on_dismiss)

    async def _open_bulk_diff_view_modal(
        self,
        *,
        title: str,
        subtitle: str,
        values_diff_text: str,
        template_diff_text: str,
    ) -> None:
        modal = BundleDiffModal(
            title=title,
            subtitle=subtitle,
            values_diff_text=values_diff_text,
            template_diff_text=template_diff_text,
        )

        loop = asyncio.get_running_loop()
        closed: asyncio.Future[None] = loop.create_future()

        def _on_dismiss(_action: str | None) -> None:
            if not closed.done():
                closed.set_result(None)

        self.app.push_screen(modal, _on_dismiss)
        await closed

    async def _open_bulk_raw_llm_output_modal(
        self,
        *,
        title: str,
        subtitle: str,
        raw_text: str,
    ) -> None:
        content = raw_text if raw_text else "# No raw LLM output captured."
        modal = FixDetailsModal(
            title=title,
            subtitle=subtitle,
            log_text=content,
            actions=(
                ("copy", "Copy Output", None),
                ("close", "Close", None),
            ),
        )

        loop = asyncio.get_running_loop()
        closed: asyncio.Future[None] = loop.create_future()

        def _on_dismiss(action: str | None) -> None:
            if action == "copy":
                if not raw_text:
                    self.notify("No raw output to copy", severity="warning")
                else:
                    self.app.copy_to_clipboard(raw_text)
                    self.notify("LLM output copied", severity="information")
            if not closed.done():
                closed.set_result(None)

        self.app.push_screen(modal, _on_dismiss)
        await closed

    def _apply_fix_to_violation(self, violation: ViolationResult, chart: object, fix: dict) -> None:
        async def do_apply() -> None:
            from kubeagle.optimizer.fixer import apply_fix
            try:
                values_path = chart.values_file  # type: ignore[union-attr]
                if values_path and Path(values_path).exists():
                    await asyncio.to_thread(apply_fix, values_path, fix)
                    self.notify(
                        f"Applied fix for '{violation.rule_name}' on '{violation.chart_name}'",
                        severity="information")
                    self.selected_violation = None
                    self._fix_yaml_cache = ""
                    preview = self.query_one("#preview-content", CustomRichLog)
                    preview.clear()
                    preview.write("[dim]Select a violation to preview its fix[/dim]")
                    self._update_action_states()
                    self.post_message(ViolationRefreshRequested())
                else:
                    self.notify("Values file not found", severity="error")
            except Exception as e:
                self.notify(f"Failed to apply fix: {e!s}", severity="error")
        self.call_later(do_apply)

    def _open_apply_all_preview_modal(
        self,
        fixable: list[ViolationResult],
        *,
        dialog_title: str,
    ) -> None:
        fixable_snapshot = [violation for violation in fixable if violation.fix_available]
        if not fixable_snapshot:
            self.notify("No fixable violations found", severity="information")
            return
        modal = _ApplyAllFixesPreviewModal(
            fixable_violations=fixable_snapshot,
            dialog_title=dialog_title,
            resolve_chart=self._find_chart_for_violation,
            generate_fix=self._get_optimizer_controller().generate_fix,
            render_timeout_seconds=self._render_timeout_seconds(),
        )

        def on_dismiss(result: _ApplyAllFixesModalResult | None) -> None:
            if result:
                self.call_later(
                    self._apply_all_fixes,
                    fixable_snapshot,
                    result["global_ratio_strategy"],
                    result["ratio_strategy_overrides"],
                    result["global_ratio_target"],
                    result["ratio_target_overrides"],
                    result["global_probe_settings"],
                    result["probe_overrides"],
                    result["global_fix_defaults"],
                )

        self.app.push_screen(modal, on_dismiss)

    def apply_all(self) -> None:
        fixable = [v for v in self._current_filtered_violations() if v.fix_available]
        if not fixable:
            self.notify("No fixable violations found", severity="information")
            return
        _task = asyncio.create_task(self._open_ai_full_fix_bulk_modal(fixable, "Fix All"))
        self._background_tasks.add(_task)
        _task.add_done_callback(self._background_tasks.discard)

    async def _apply_all_fixes(
        self,
        fixable_violations: list[ViolationResult] | None = None,
        global_ratio_strategy: str = RATIO_STRATEGY_BURSTABLE_15,
        ratio_strategy_overrides: dict[str, str] | None = None,
        global_ratio_target: str = RATIO_TARGET_REQUEST,
        ratio_target_overrides: dict[str, str] | None = None,
        global_probe_settings: dict[str, str] | None = None,
        probe_overrides: dict[str, dict[str, str]] | None = None,
        global_fix_defaults: dict[str, str] | None = None,
    ) -> None:
        from kubeagle.optimizer.fixer import apply_fix
        fixable_source = (
            fixable_violations
            if fixable_violations is not None
            else self._current_filtered_violations()
        )
        fixable = [v for v in fixable_source if v.fix_available]
        if not fixable:
            return
        app = cast("EKSHelmReporterApp", self.app)
        if not app.settings.charts_path:
            self.notify("No charts path configured", severity="error")
            return
        total = len(fixable)
        self._cancel_fixes = False
        self._applying_fixes = True
        self.set_table_loading(True)
        self.update_loading_message(f"Applying fix 1/{total}...")
        optimizer = self._get_optimizer_controller()
        success, errors, skipped = 0, 0, 0
        for i, violation in enumerate(fixable, 1):
            if self._cancel_fixes:
                self.notify(f"Cancelled after {success} fixes applied", severity="warning")
                break
            self.update_loading_message(f"Applying fix {i}/{total}...")
            try:
                chart = self._find_chart_for_violation(violation)
                if not chart:
                    skipped += 1
                    continue
                ratio_strategy = _resolve_ratio_strategy_for_violation(
                    violation,
                    global_strategy=global_ratio_strategy,
                    overrides=ratio_strategy_overrides,
                )
                ratio_target = _resolve_ratio_target_for_violation(
                    violation,
                    global_target=global_ratio_target,
                    overrides=ratio_target_overrides,
                )
                probe_settings = _resolve_probe_settings_for_violation(
                    violation,
                    global_settings=global_probe_settings,
                    overrides=probe_overrides,
                )
                fix = await asyncio.to_thread(
                    optimizer.generate_fix,
                    chart,
                    violation,
                    ratio_strategy,
                    ratio_target,
                    probe_settings,
                )
                fix = _apply_default_fix_settings(
                    violation,
                    fix,
                    global_fix_defaults,
                    chart_name=getattr(chart, "chart_name", violation.chart_name),
                )
                if not fix:
                    skipped += 1
                    continue
                values_path = chart.values_file
                if values_path and Path(values_path).exists():
                    await asyncio.to_thread(apply_fix, values_path, fix)
                    success += 1
                else:
                    skipped += 1
            except Exception:
                errors += 1
        self._applying_fixes = False
        self.set_table_loading(False)
        self._update_action_states()
        if success > 0:
            self.notify(
                f"Applied {success} fixes"
                + (f", {skipped} skipped" if skipped else "")
                + (f", {errors} failed" if errors else ""),
                severity="information" if errors == 0 else "warning")
            self.post_message(ViolationRefreshRequested())
        else:
            self.notify(f"No fixes applied: {skipped} skipped, {errors} failed", severity="warning")

    def copy_yaml(self) -> None:
        if not self._fix_yaml_cache:
            self.notify("No fix YAML to copy - select a violation first", severity="warning")
            return
        self.app.copy_to_clipboard(self._fix_yaml_cache)
        self.notify("Fix YAML copied to clipboard", severity="information")

    # ------------------------------------------------------------------
    # Button / row events
    # ------------------------------------------------------------------

    async def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        btn = event.button.id
        if btn == "apply-all-btn":
            self.apply_all()
        elif btn == "fix-selected-btn":
            await self.fix_violation()
        elif btn == "fix-all-selected-btn":
            await self.fix_all_selected()
        elif btn == "preview-fix-btn":
            self.preview_fix()
        elif btn == "retry-btn":
            self.post_message(ViolationRefreshRequested())
        elif btn == "copy-yaml-btn":
            self.copy_yaml()
        elif btn == "search-btn":
            with contextlib.suppress(Exception):
                value = self.query_one("#search-input", CustomInput).value
                self._run_search(value)
        elif btn == "clear-search-btn":
            self._clear_search()
        elif btn == "advanced-filters-btn":
            self._toggle_advanced_filters()
        elif btn == "filters-btn":
            self._open_filters_modal()

    def _select_violation_at(self, event: object) -> None:
        """Select the violation at the row indicated by *event* and update buttons."""
        event_obj = cast(Any, event)
        row_index = getattr(event_obj, "cursor_row", None)
        if not isinstance(row_index, int):
            with contextlib.suppress(Exception):
                row_index = self.query_one("#violations-table", CustomDataTable).cursor_row
        if not isinstance(row_index, int) or row_index < 0:
            return
        violation = self._get_violation_for_row(row_index)
        if violation is None:
            return
        self.selected_violation = violation
        self._update_action_states()

    def on_data_table_row_highlighted(self, event: object) -> None:
        self._select_violation_at(event)

    def on_data_table_row_selected(self, event: object) -> None:
        self._select_violation_at(event)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_violation_for_row(self, row_index: int) -> ViolationResult | None:
        if 0 <= row_index < len(self.sorted_violations):
            return self.sorted_violations[row_index]
        return None

    @staticmethod
    def _violation_selection_key(
        violation: ViolationResult | None,
    ) -> str | None:
        """Return stable selection key for preserving row focus across repaints."""
        if violation is None:
            return None
        return str(violation.id or "").strip() or None

    def _find_violation_row_by_key(
        self,
        violations: list[ViolationResult],
        selected_key: str | None,
    ) -> int | None:
        """Locate selected violation row in the latest sorted result."""
        if not selected_key or not violations:
            return None
        for index, violation in enumerate(violations):
            if self._violation_selection_key(violation) == selected_key:
                return index
        return None

    def _resolve_violation_from_key(self, key_str: str) -> ViolationResult | None:
        if key_str.startswith("row-"):
            try:
                idx = int(key_str[4:])
                return self._get_violation_for_row(idx)
            except (ValueError, TypeError):
                return None
        if key_str.startswith("v-"):
            try:
                idx = int(key_str[2:])
                if 0 <= idx < len(self.sorted_violations):
                    return self.sorted_violations[idx]
            except (ValueError, IndexError):
                pass
        return None

    def _show_error_banner(self, message: str) -> None:
        try:
            banner = self.query_one("#error-banner", CustomHorizontal)
            self.query_one("#error-text", CustomStatic).update(f"Error: {escape(message)}")
            banner.add_class("visible")
        except Exception:
            pass

    def _hide_error_banner(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#error-banner", CustomHorizontal).remove_class("visible")

    def _show_no_charts_state(self) -> None:
        try:
            table = self.query_one("#violations-table", CustomDataTable)
        except Exception:
            return
        self.sorted_violations = []
        self.selected_violation = None
        self._fix_yaml_cache = ""
        self._clear_ai_full_fix_cache()

        async def _populate() -> None:
            try:
                async with table.batch():
                    table.clear(columns=True)
                    self._configure_violations_table_header_tooltips(table)
                    self._configure_violations_table_columns(table)
                    self._add_state_row(
                        table,
                        values_by_column={
                            "Chart": "N/A",
                            "Team": "N/A",
                            "Values File Type": "N/A",
                            "Severity": "N/A",
                            "Category": "N/A",
                            "Rule": "No charts path configured",
                            "Current": "N/A",
                            "Chart Path": "N/A",
                        },
                        key="state-no-charts",
                    )
                with contextlib.suppress(Exception):
                    header = self.query_one("#violations-header", CustomStatic)
                    header.update("Violations Table (0)")
                    header.remove_class("loading")
                self._update_filter_status()
                self._update_action_states()
            finally:
                table.set_loading(False)
        self.call_later(_populate)

    def _show_no_violations_state(self) -> None:
        try:
            table = self.query_one("#violations-table", CustomDataTable)
            preview = self.query_one("#preview-content", CustomRichLog)
            header = self.query_one("#violations-header", CustomStatic)
        except Exception:
            return
        self.sorted_violations = []
        self.selected_violation = None
        self._fix_yaml_cache = ""
        self._clear_ai_full_fix_cache()

        async def _populate() -> None:
            try:
                async with table.batch():
                    table.clear(columns=True)
                    self._configure_violations_table_header_tooltips(table)
                    self._configure_violations_table_columns(table)
                    self._add_state_row(
                        table,
                        values_by_column={
                            "Rule": "[#30d158]No violations found[/#30d158]",
                        },
                        key="state-no-violations",
                    )
                preview.clear()
                preview.write("[bold #30d158]All charts passed validation![/bold #30d158]")
                preview.write("")
                preview.write("[italic]No optimization violations were detected in your Helm charts.[/italic]")
                preview.write("")
                preview.write("[b]Categories checked:[/b]")
                for _, cat_label in CATEGORIES:
                    preview.write(f"  - {cat_label}")
                preview.write("")
                preview.write("[b]Tip:[/b] Run [cyan]Full Report[/cyan] for detailed analysis.")
                header.update("Violations Table (0)")
                header.remove_class("loading")
                self._update_action_states()
            finally:
                table.set_loading(False)
        self.call_later(_populate)

    def _configure_violations_table_header_tooltips(
        self,
        table: CustomDataTable,
    ) -> None:
        """Apply header tooltips for the violations table."""
        table.set_header_tooltips(OPTIMIZER_HEADER_TOOLTIPS)
        table.set_default_tooltip("Select a row, then choose Preview Fix for details")

    def handle_escape(self) -> bool:
        """Handle escape key — returns True if consumed, False to propagate."""
        if self._applying_fixes and not self._cancel_fixes:
            self._cancel_fixes = True
            self.update_loading_message("Cancelling fixes...")
            return True
        if self.selected_violation is not None:
            self.selected_violation = None
            self._fix_yaml_cache = ""
            preview = self.query_one("#preview-content", CustomRichLog)
            preview.clear()
            preview.write("[dim]Select a violation to preview its fix[/dim]")
            self._update_action_states()
            return True
        return False


__all__ = ["ViolationRefreshRequested", "ViolationsView"]
