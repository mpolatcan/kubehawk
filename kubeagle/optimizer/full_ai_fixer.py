"""AI full-fix generation for values + template patches."""

from __future__ import annotations

import contextlib
import difflib
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from kubeagle.models.analysis.violation import ViolationResult
from kubeagle.optimizer.llm_cli_runner import (
    LLMProvider,
    provider_supports_direct_edit,
    run_llm_direct_edit,
)
from kubeagle.optimizer.llm_patch_protocol import (
    FullFixResponse,
    FullFixTemplatePatch,
    FullFixViolationCoverage,
    with_system_prompt_override,
)

# Single-shot direct-edit policy: one provider attempt per run.
_MAX_DIRECT_EDIT_PROVIDER_ATTEMPTS = 1
_DIRECT_EDIT_IGNORED_PATH_PREFIXES: tuple[str, ...] = (
    ".claude/",
    ".codex/",
    ".cursor/",
    ".vscode/",
    ".idea/",
    ".git/",
)
_DIRECT_EDIT_IGNORED_PATH_NAMES: tuple[str, ...] = (
    ".DS_Store",
    ".claude.json",
    ".codex.json",
)

_RULE_CANONICAL_VALUES_GUIDANCE: dict[str, str] = {
    "AVL005": "Use `replicaCount` for replica scaling.",
    "RES005": (
        "Treat current CPU limit as correct; increase only request so "
        "`resources.requests.cpu` is about 85% of `resources.limits.cpu`."
    ),
    "RES006": (
        "Treat current memory limit as correct; increase only request so "
        "`resources.requests.memory` is about 85% of `resources.limits.memory`."
    ),
    "PRB001": "Use `livenessProbe` under workload container config.",
    "PRB002": "Use `readinessProbe` under workload container config.",
    "PRB003": "Use `startupProbe` under workload container config.",
}

FULL_FIX_PROMPT_TOKEN_VIOLATIONS = "{{VIOLATIONS}}"
FULL_FIX_PROMPT_TOKEN_SEED_YAML = "{{SEED_YAML}}"
FULL_FIX_PROMPT_TOKEN_ALLOWED_FILES = "{{ALLOWED_FILES}}"
FULL_FIX_PROMPT_TOKEN_RETRY_BLOCK = "{{RETRY_BLOCK}}"
FULL_FIX_PROMPT_TOKEN_CANONICAL_GUIDANCE = "{{CANONICAL_GUIDANCE}}"
FULL_FIX_PROMPT_REQUIRED_TOKENS: tuple[str, ...] = (
    FULL_FIX_PROMPT_TOKEN_VIOLATIONS,
    FULL_FIX_PROMPT_TOKEN_SEED_YAML,
    FULL_FIX_PROMPT_TOKEN_ALLOWED_FILES,
)
FULL_FIX_PROMPT_TEMPLATE_TOKENS: tuple[str, ...] = (
    *FULL_FIX_PROMPT_REQUIRED_TOKENS,
    FULL_FIX_PROMPT_TOKEN_RETRY_BLOCK,
    FULL_FIX_PROMPT_TOKEN_CANONICAL_GUIDANCE,
)

DEFAULT_FULL_FIX_SYSTEM_PROMPT_TEMPLATE = (
    "You are editing Helm chart files directly on disk.\n"
    "The current process CWD is an isolated staged copy of the chart. "
    "Edit files in-place only inside this staged copy.\n\n"
    "Goal:\n"
    "Address all listed violations with minimal safe changes.\n\n"
    "Violations:\n"
    f"{FULL_FIX_PROMPT_TOKEN_VIOLATIONS}\n\n"
    "Seed deterministic values patch (optional guidance):\n"
    f"{FULL_FIX_PROMPT_TOKEN_SEED_YAML}\n\n"
    "STRICT edit scope (existing files only):\n"
    f"{FULL_FIX_PROMPT_TOKEN_ALLOWED_FILES}\n\n"
    "Hard constraints:\n"
    "- Never use absolute paths.\n"
    "- Never use `..` path traversal.\n"
    "- Edit only allowlisted files.\n"
    "- Do not create, delete, or rename files.\n"
    "- Put concrete configuration values in the selected values file from STRICT edit scope (for example `values.yaml` or `values-automation.yaml`).\n"
    "- In templates, wire only through .Values references (for example with toYaml/include); do not hardcode final config values.\n"
    "- Use canonical Kubernetes/value key names and nesting (for example `replicaCount`, `resources.requests/limits`, probe keys).\n"
    "- Do not invent alias keys or suffixed names (for example `resourcesAutomation`, `replicaCountAutomation`).\n"
    "- Keep key casing and hierarchy aligned with existing `.Values` usage in templates.\n"
    "- For probe rules, modify only containers[*] probe wiring; never initContainers[*].\n"
    "- Keep helper/include usage chart-specific; do not invent generic helper names.\n"
    "- This is a single-shot run: complete all listed violations in this pass; do not defer work.\n"
    "- If a violation needs wiring, update both values.yaml keys and template `.Values` references in the same run.\n"
    "- Focus only on wiring and fixing changes; do not include verification steps or verification commentary.\n"
    "- Do not make no-op or unrelated edits; change only what is required for the listed violations.\n"
    "- Treat seed YAML as guidance only; prefer listed violations and existing chart wiring patterns when they conflict.\n"
    "Canonical key guidance for selected rules:\n"
    f"{FULL_FIX_PROMPT_TOKEN_CANONICAL_GUIDANCE}\n"
    f"{FULL_FIX_PROMPT_TOKEN_RETRY_BLOCK}\n"
    "Output only a concise execution summary text (no JSON, no markdown fences).\n"
    "Include changed file paths in summary if any."
)


@dataclass(slots=True)
class AIFullFixStagedArtifact:
    """Staged chart workspace produced by direct-edit flow."""

    stage_root: Path
    staged_chart_dir: Path
    rel_values_path: str
    changed_rel_paths: list[str] = field(default_factory=list)
    source_hashes: dict[str, str] = field(default_factory=dict)
    provider: str = ""
    execution_log: str = ""


@dataclass(slots=True)
class AIFullFixResult:
    """Result of AI full-fix generation."""

    ok: bool
    status: str  # ok|no_change|error
    provider: str = ""
    prompt: str = ""
    response: FullFixResponse | None = None
    note: str = ""
    tried_providers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_output_text: str = ""
    staged_artifact: AIFullFixStagedArtifact | None = None


def generate_ai_full_fix_for_violation(
    *,
    chart_dir: Path,
    values_path: Path,
    violation: ViolationResult,
    seed_fix_payload: dict[str, Any] | None = None,
    timeout_seconds: int = 120,
    preferred_provider: LLMProvider | None = None,
    provider_models: dict[LLMProvider, str | None] | None = None,
    full_fix_system_prompt: str | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> AIFullFixResult:
    """Generate AI full-fix for a single violation."""
    return generate_ai_full_fix_for_chart(
        chart_dir=chart_dir,
        values_path=values_path,
        violations=[violation],
        seed_fix_payload=seed_fix_payload,
        timeout_seconds=timeout_seconds,
        preferred_provider=preferred_provider,
        provider_models=provider_models,
        full_fix_system_prompt=full_fix_system_prompt,
        status_callback=status_callback,
    )


def generate_ai_full_fix_for_chart(
    *,
    chart_dir: Path,
    values_path: Path,
    violations: list[ViolationResult],
    seed_fix_payload: dict[str, Any] | None = None,
    timeout_seconds: int = 120,
    preferred_provider: LLMProvider | None = None,
    provider_models: dict[LLMProvider, str | None] | None = None,
    full_fix_system_prompt: str | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> AIFullFixResult:
    """Generate one bundled AI patch for all violations in a chart."""
    _notify = status_callback or (lambda _msg: None)
    chart_dir = chart_dir.expanduser().resolve()
    values_path = values_path.expanduser().resolve()
    if not chart_dir.exists():
        return AIFullFixResult(
            ok=False,
            status="error",
            note=f"Chart directory not found: {chart_dir}",
        )
    if not values_path.exists():
        return AIFullFixResult(
            ok=False,
            status="error",
            note=f"Values file not found: {values_path}",
        )

    violations = list(violations)
    if not violations:
        return AIFullFixResult(
            ok=False,
            status="error",
            note="No violations provided for AI full-fix generation.",
        )

    allowed_files = _allowed_template_files(chart_dir)
    if not allowed_files:
        return AIFullFixResult(
            ok=False,
            status="error",
            note="No template files found under chart templates/ directory.",
        )
    _notify("Trying direct-edit mode...")
    return _generate_ai_full_fix_direct_edit(
        chart_dir=chart_dir,
        values_path=values_path,
        violations=violations,
        seed_fix_payload=seed_fix_payload,
        allowed_files=allowed_files,
        timeout_seconds=timeout_seconds,
        preferred_provider=preferred_provider,
        provider_models=provider_models,
        full_fix_system_prompt=full_fix_system_prompt,
        status_callback=status_callback,
    )


def get_default_full_fix_system_prompt_template() -> str:
    """Return the editable default full-fix system prompt template."""
    return DEFAULT_FULL_FIX_SYSTEM_PROMPT_TEMPLATE.replace(
        FULL_FIX_PROMPT_TOKEN_CANONICAL_GUIDANCE,
        _all_canonical_values_guidance_block(),
    )


def is_full_fix_prompt_template(text: str | None) -> bool:
    """Return True when text looks like a full prompt template with tokens."""
    normalized = str(text or "").strip()
    return any(token in normalized for token in FULL_FIX_PROMPT_TEMPLATE_TOKENS)


def validate_full_fix_prompt_template(text: str | None) -> str | None:
    """Validate placeholder coverage when full prompt template mode is used."""
    normalized = str(text or "").strip()
    if not normalized or not is_full_fix_prompt_template(normalized):
        return None
    missing = [token for token in FULL_FIX_PROMPT_REQUIRED_TOKENS if token not in normalized]
    if not missing:
        return None
    return (
        "AI fix system prompt template is missing required placeholders: "
        f"{', '.join(missing)}."
    )


def is_default_full_fix_system_prompt_template(text: str | None) -> bool:
    """Return True when text matches the built-in default template."""
    normalized = str(text or "").strip()
    if normalized == get_default_full_fix_system_prompt_template().strip():
        return True
    # Backward compatibility for persisted raw template with canonical token.
    return normalized == DEFAULT_FULL_FIX_SYSTEM_PROMPT_TEMPLATE.strip()


def _generate_ai_full_fix_direct_edit(
    *,
    chart_dir: Path,
    values_path: Path,
    violations: list[ViolationResult],
    seed_fix_payload: dict[str, Any] | None,
    allowed_files: list[str],
    timeout_seconds: int,
    preferred_provider: LLMProvider | None,
    provider_models: dict[LLMProvider, str | None] | None,
    full_fix_system_prompt: str | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> AIFullFixResult:
    _notify = status_callback or (lambda _msg: None)
    tried: list[str] = []
    errors: list[str] = []
    last_log_text = ""
    rel_values_path = _resolve_values_relative_path(chart_dir=chart_dir, values_path=values_path)
    allowed_scope = set(allowed_files)
    allowed_scope.add(rel_values_path)
    for provider in _provider_order_direct_edit(preferred_provider):
        tried.append(provider.value)
        if not provider_supports_direct_edit(provider):
            errors.append(f"{provider.value}: direct-edit backend unavailable, skipping provider.")
            continue
        model = None
        if provider_models is not None and provider in provider_models:
            raw_model = str(provider_models[provider] or "").strip()
            model = raw_model or None

        retry_error = ""
        for attempt in range(1, _MAX_DIRECT_EDIT_PROVIDER_ATTEMPTS + 1):
            _notify(f"Direct-edit: {provider.value} (attempt {attempt})...")
            stage_root, staged_chart_dir = _create_staged_workspace(chart_dir)
            source_guard_root, source_guard_chart_dir = _create_staged_workspace(chart_dir)
            direct_prompt = _build_direct_edit_prompt(
                chart_dir=chart_dir,
                rel_values_path=rel_values_path,
                violations=violations,
                seed_fix_payload=seed_fix_payload,
                allowed_files=allowed_files,
                retry_error=retry_error,
                system_prompt_override=full_fix_system_prompt,
            )
            direct_result = run_llm_direct_edit(
                provider=provider,
                prompt=direct_prompt,
                timeout_seconds=max(1, int(timeout_seconds)),
                cwd=staged_chart_dir,
                model=model,
                attempts=attempt,
            )
            last_log_text = direct_result.log_text
            source_touched, _, _ = _detect_workspace_delta(
                before_hashes=_snapshot_relative_hashes(source_guard_chart_dir),
                after_hashes=_snapshot_relative_hashes(chart_dir),
            )
            if source_touched:
                _restore_workspace_from_snapshot(
                    target_root=chart_dir,
                    snapshot_root=source_guard_chart_dir,
                    touched_paths=source_touched,
                )
                changed_sample = ", ".join(source_touched[:3])
                extra = "..." if len(source_touched) > 3 else ""
                retry_error = (
                    "Unsafe source-chart mutation detected and reverted "
                    f"({changed_sample}{extra})."
                )
                errors.append(f"{provider.value}: {retry_error}")
                _cleanup_stage_root(source_guard_root)
                if attempt < _MAX_DIRECT_EDIT_PROVIDER_ATTEMPTS:
                    _cleanup_stage_root(stage_root)
                    continue
                errors.append(
                    f"{provider.value}: retained failed workspace for debugging at {stage_root}"
                )
                break
            touched_paths, created_paths, deleted_paths = _detect_workspace_changes(
                original_chart_dir=chart_dir,
                staged_chart_dir=staged_chart_dir,
            )
            discarded_out_of_scope = _discard_out_of_scope_workspace_changes(
                original_chart_dir=chart_dir,
                staged_chart_dir=staged_chart_dir,
                touched_paths=touched_paths,
                allowed_scope=allowed_scope,
            )
            if discarded_out_of_scope:
                sample = ", ".join(discarded_out_of_scope[:3])
                extra = "..." if len(discarded_out_of_scope) > 3 else ""
                _notify(f"Scope guard: discarded out-of-scope edits ({sample}{extra}).")
                touched_paths, created_paths, deleted_paths = _detect_workspace_changes(
                    original_chart_dir=chart_dir,
                    staged_chart_dir=staged_chart_dir,
                )
            changed_rel_paths = sorted(
                [path for path in touched_paths if path in allowed_scope]
            )
            scope_error = _validate_direct_edit_scope(
                touched_paths=touched_paths,
                created_paths=created_paths,
                deleted_paths=deleted_paths,
                allowed_scope=allowed_scope,
                rel_values_path=rel_values_path,
            )
            if not direct_result.ok:
                retry_error = direct_result.error_message or "direct-edit command failed."
                errors.append(f"{provider.value}: {retry_error}")
                _cleanup_stage_root(source_guard_root)
                if attempt < _MAX_DIRECT_EDIT_PROVIDER_ATTEMPTS:
                    _cleanup_stage_root(stage_root)
                    continue
                errors.append(
                    f"{provider.value}: retained failed workspace for debugging at {stage_root}"
                )
                break
            if scope_error:
                retry_error = scope_error
                errors.append(f"{provider.value}: {scope_error}")
                _cleanup_stage_root(source_guard_root)
                if attempt < _MAX_DIRECT_EDIT_PROVIDER_ATTEMPTS:
                    _cleanup_stage_root(stage_root)
                    continue
                errors.append(
                    f"{provider.value}: retained failed workspace for debugging at {stage_root}"
                )
                break
            if not changed_rel_paths:
                _cleanup_stage_root(source_guard_root)
                _cleanup_stage_root(stage_root)
                response = FullFixResponse(
                    result="no_change",
                    summary="Direct-edit run completed with no file changes.",
                    values_patch={},
                    template_patches=[],
                    violation_coverage=[
                        FullFixViolationCoverage(
                            rule_id=item.rule_id,
                            status="unchanged",
                            note="No file changes generated.",
                        )
                        for item in violations
                    ],
                )
                return AIFullFixResult(
                    ok=True,
                    status="no_change",
                    provider=provider.value,
                    prompt=direct_prompt,
                    response=response,
                    note=f"Direct-edit mode completed with `{provider.value}` and produced no changes.",
                    tried_providers=tried,
                    errors=errors,
                    raw_output_text=direct_result.log_text,
                )

            response, response_error = _build_response_from_staged_workspace(
                chart_dir=chart_dir,
                staged_chart_dir=staged_chart_dir,
                rel_values_path=rel_values_path,
                changed_rel_paths=changed_rel_paths,
                violations=violations,
            )
            if response_error:
                retry_error = response_error
                errors.append(f"{provider.value}: {response_error}")
                _cleanup_stage_root(source_guard_root)
                if attempt < _MAX_DIRECT_EDIT_PROVIDER_ATTEMPTS:
                    _cleanup_stage_root(stage_root)
                    continue
                errors.append(
                    f"{provider.value}: retained failed workspace for debugging at {stage_root}"
                )
                break
            if response is None:
                retry_error = "Internal error: staged response generation returned no payload."
                errors.append(f"{provider.value}: {retry_error}")
                _cleanup_stage_root(source_guard_root)
                if attempt < _MAX_DIRECT_EDIT_PROVIDER_ATTEMPTS:
                    _cleanup_stage_root(stage_root)
                    continue
                errors.append(
                    f"{provider.value}: retained failed workspace for debugging at {stage_root}"
                )
                break
            source_hashes = {
                rel_path: _hash_file_sha256((chart_dir / rel_path).resolve())
                for rel_path in changed_rel_paths
            }
            _cleanup_stage_root(source_guard_root)
            execution_log = (
                f"{direct_result.log_text}\n\nStaged Workspace: {stage_root}\n"
                f"Staged Chart: {staged_chart_dir}"
            ).strip()
            artifact = AIFullFixStagedArtifact(
                stage_root=stage_root,
                staged_chart_dir=staged_chart_dir,
                rel_values_path=rel_values_path,
                changed_rel_paths=changed_rel_paths,
                source_hashes=source_hashes,
                provider=provider.value,
                execution_log=execution_log,
            )
            return AIFullFixResult(
                ok=True,
                status=response.result,
                provider=provider.value,
                prompt=direct_prompt,
                response=response,
                note=f"Direct-edit full fix generated using `{provider.value}`.",
                tried_providers=tried,
                errors=errors,
                raw_output_text=execution_log,
                staged_artifact=artifact,
            )

    return AIFullFixResult(
        ok=False,
        status="error",
        note="Direct-edit generation failed. JSON fallback is disabled for standardized flow.",
        tried_providers=tried,
        errors=errors,
        raw_output_text=last_log_text,
    )


def _provider_order(preferred_provider: LLMProvider | None) -> tuple[LLMProvider, ...]:
    if preferred_provider == LLMProvider.CLAUDE:
        return (LLMProvider.CLAUDE,)
    if preferred_provider == LLMProvider.CODEX:
        return (LLMProvider.CODEX,)
    return (LLMProvider.CODEX, LLMProvider.CLAUDE)


def _provider_order_direct_edit(preferred_provider: LLMProvider | None) -> tuple[LLMProvider, ...]:
    return _provider_order(preferred_provider)


def _allowed_template_files(chart_dir: Path) -> list[str]:
    templates_dir = chart_dir / "templates"
    if not templates_dir.exists():
        return []
    return [
        str(path.relative_to(chart_dir))
        for path in sorted(templates_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in {".yaml", ".yml", ".tpl"}
    ]


def _build_direct_edit_prompt(
    *,
    chart_dir: Path,
    rel_values_path: str,
    violations: list[ViolationResult],
    seed_fix_payload: dict[str, Any] | None,
    allowed_files: list[str],
    retry_error: str,
    system_prompt_override: str | None = None,
) -> str:
    values_file_guidance = (
        f"Target values file for this run (write concrete values here): {rel_values_path}"
    )
    allowed_list = "\n".join(
        [values_file_guidance, *(f"- {path}" for path in [rel_values_path, *allowed_files])]
    )
    violation_lines = "\n".join(
        (
            f"- {item.rule_id} ({item.rule_name}): "
            f"current={item.current_value}; recommended={item.recommended_value}"
        )
        for item in violations
    )
    retry_block = ""
    if retry_error.strip():
        retry_block = (
            "Previous attempt failed validation:\n"
            f"- {retry_error.strip()}\n"
            "Apply constrained edits only and avoid any out-of-scope file changes.\n"
        )
    seed_yaml = yaml.safe_dump(seed_fix_payload or {}, sort_keys=False).rstrip() or "{}"
    base_prompt = DEFAULT_FULL_FIX_SYSTEM_PROMPT_TEMPLATE.replace(
        FULL_FIX_PROMPT_TOKEN_CANONICAL_GUIDANCE,
        _canonical_values_guidance_block(violations),
    )
    configured = str(system_prompt_override or "").strip()
    if configured and is_full_fix_prompt_template(configured):
        template = configured
        return (
            template.replace(FULL_FIX_PROMPT_TOKEN_VIOLATIONS, violation_lines)
            .replace(FULL_FIX_PROMPT_TOKEN_SEED_YAML, seed_yaml)
            .replace(FULL_FIX_PROMPT_TOKEN_ALLOWED_FILES, allowed_list)
            .replace(FULL_FIX_PROMPT_TOKEN_CANONICAL_GUIDANCE, _canonical_values_guidance_block(violations))
            .replace(FULL_FIX_PROMPT_TOKEN_RETRY_BLOCK, retry_block.strip())
            .strip()
        )
    rendered_base_prompt = (
        base_prompt.replace(FULL_FIX_PROMPT_TOKEN_VIOLATIONS, violation_lines)
        .replace(FULL_FIX_PROMPT_TOKEN_SEED_YAML, seed_yaml)
        .replace(FULL_FIX_PROMPT_TOKEN_ALLOWED_FILES, allowed_list)
        .replace(FULL_FIX_PROMPT_TOKEN_CANONICAL_GUIDANCE, _canonical_values_guidance_block(violations))
        .replace(FULL_FIX_PROMPT_TOKEN_RETRY_BLOCK, retry_block.strip())
        .strip()
    )
    return with_system_prompt_override(
        rendered_base_prompt,
        system_prompt_override=configured,
    )


def _canonical_values_guidance_for_violations(
    violations: list[ViolationResult],
) -> list[str]:
    seen: set[str] = set()
    guidance_lines: list[str] = []
    for item in violations:
        rule_id = str(item.rule_id or "").upper().strip()
        if not rule_id or rule_id in seen:
            continue
        seen.add(rule_id)
        guidance = _RULE_CANONICAL_VALUES_GUIDANCE.get(rule_id)
        if guidance:
            guidance_lines.append(f"- {rule_id}: {guidance}")
    return guidance_lines


def _canonical_values_guidance_block(violations: list[ViolationResult]) -> str:
    guidance_lines = _canonical_values_guidance_for_violations(violations)
    if guidance_lines:
        return "\n".join(guidance_lines)
    return "- Use existing chart key names from values/template wiring and standard Kubernetes field naming."


def _all_canonical_values_guidance_block() -> str:
    lines = [f"- {rule_id}: {guidance}" for rule_id, guidance in sorted(_RULE_CANONICAL_VALUES_GUIDANCE.items())]
    if lines:
        return "\n".join(lines)
    return "- Use existing chart key names from values/template wiring and standard Kubernetes field naming."


def _create_staged_workspace(chart_dir: Path) -> tuple[Path, Path]:
    stage_root = Path(tempfile.mkdtemp(prefix="kubeagle-direct-edit-"))
    staged_chart_dir = stage_root / chart_dir.name
    shutil.copytree(chart_dir, staged_chart_dir)
    return stage_root, staged_chart_dir


def _cleanup_stage_root(stage_root: Path) -> None:
    with contextlib.suppress(OSError):
        shutil.rmtree(stage_root)


def _resolve_values_relative_path(*, chart_dir: Path, values_path: Path) -> str:
    try:
        rel_path = values_path.relative_to(chart_dir)
    except ValueError as exc:
        raise ValueError("Values file must be inside chart directory.") from exc
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise ValueError("Values file path is unsafe for staged direct-edit flow.")
    return rel_path.as_posix()


def _snapshot_relative_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(root).as_posix()
        with contextlib.suppress(OSError):
            hashes[rel_path] = _hash_file_sha256(file_path)
    return hashes


def _detect_workspace_delta(
    *,
    before_hashes: dict[str, str],
    after_hashes: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    touched: list[str] = []
    created: list[str] = []
    deleted: list[str] = []
    all_paths = sorted(set(before_hashes) | set(after_hashes))
    for rel_path in all_paths:
        if _is_ignored_direct_edit_path(rel_path):
            continue
        before = before_hashes.get(rel_path)
        after = after_hashes.get(rel_path)
        if before == after:
            continue
        touched.append(rel_path)
        if before is None:
            created.append(rel_path)
        elif after is None:
            deleted.append(rel_path)
    return touched, created, deleted


def _restore_workspace_from_snapshot(
    *,
    target_root: Path,
    snapshot_root: Path,
    touched_paths: list[str],
) -> None:
    for rel_path in touched_paths:
        target_path = (target_root / rel_path).resolve()
        snapshot_path = (snapshot_root / rel_path).resolve()
        if not str(target_path).startswith(str(target_root)):
            continue
        if snapshot_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                shutil.copy2(snapshot_path, target_path)
            continue
        if target_path.exists():
            with contextlib.suppress(OSError):
                target_path.unlink()


def _detect_workspace_changes(
    *,
    original_chart_dir: Path,
    staged_chart_dir: Path,
) -> tuple[list[str], list[str], list[str]]:
    return _detect_workspace_delta(
        before_hashes=_snapshot_relative_hashes(original_chart_dir),
        after_hashes=_snapshot_relative_hashes(staged_chart_dir),
    )


def _discard_out_of_scope_workspace_changes(
    *,
    original_chart_dir: Path,
    staged_chart_dir: Path,
    touched_paths: list[str],
    allowed_scope: set[str],
) -> list[str]:
    out_of_scope_paths = sorted({path for path in touched_paths if path not in allowed_scope})
    if not out_of_scope_paths:
        return []
    _restore_workspace_from_snapshot(
        target_root=staged_chart_dir,
        snapshot_root=original_chart_dir,
        touched_paths=out_of_scope_paths,
    )
    return out_of_scope_paths


def _is_ignored_direct_edit_path(rel_path: str) -> bool:
    normalized = str(rel_path or "").strip().replace("\\", "/")
    if not normalized:
        return True
    if normalized in _DIRECT_EDIT_IGNORED_PATH_NAMES:
        return True
    return any(normalized.startswith(prefix) for prefix in _DIRECT_EDIT_IGNORED_PATH_PREFIXES)


def _validate_direct_edit_scope(
    *,
    touched_paths: list[str],
    created_paths: list[str],
    deleted_paths: list[str],
    allowed_scope: set[str],
    rel_values_path: str,
) -> str:
    for rel_path in touched_paths:
        if rel_path not in allowed_scope:
            return f"Out-of-scope file edit detected: {rel_path}"
    if created_paths:
        return f"File creation is forbidden in direct-edit mode: {', '.join(created_paths[:5])}"
    if deleted_paths:
        return f"File deletion is forbidden in direct-edit mode: {', '.join(deleted_paths[:5])}"
    if rel_values_path not in allowed_scope:
        return "Values file path was not allowlisted correctly."
    return ""


def _build_response_from_staged_workspace(
    *,
    chart_dir: Path,
    staged_chart_dir: Path,
    rel_values_path: str,
    changed_rel_paths: list[str],
    violations: list[ViolationResult],
) -> tuple[FullFixResponse | None, str]:
    values_patch: dict[str, Any] = {}
    if rel_values_path in changed_rel_paths:
        values_patch, values_error = _build_values_patch_from_staged(
            chart_dir=chart_dir,
            staged_chart_dir=staged_chart_dir,
            rel_values_path=rel_values_path,
        )
        if values_error:
            return None, values_error

    template_patches: list[FullFixTemplatePatch] = []
    for rel_path in changed_rel_paths:
        if not rel_path.startswith("templates/"):
            continue
        original_path = (chart_dir / rel_path).resolve()
        staged_path = (staged_chart_dir / rel_path).resolve()
        if not staged_path.exists():
            return None, f"Staged template file missing: {rel_path}"
        try:
            original_text = original_path.read_text(encoding="utf-8")
            updated_text = staged_path.read_text(encoding="utf-8")
        except OSError as exc:
            return None, f"Failed reading staged template content `{rel_path}`: {exc!s}"
        updated_content = updated_text if updated_text.endswith("\n") else f"{updated_text}\n"
        diff_lines = list(
            difflib.unified_diff(
                original_text.splitlines(),
                updated_content.splitlines(),
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
                lineterm="",
            )
        )
        template_patches.append(
            FullFixTemplatePatch(
                file=rel_path,
                purpose="Edited directly by LLM in staged workspace.",
                unified_diff="\n".join(diff_lines).rstrip(),
                updated_content=updated_content,
            )
        )

    result = "ok" if changed_rel_paths else "no_change"
    coverage_status = "addressed" if result == "ok" else "unchanged"
    coverage_note = (
        "Changes were produced in staged direct-edit workspace."
        if result == "ok"
        else "No file changes produced."
    )
    response = FullFixResponse(
        result=result,
        summary=(
            f"Direct-edit mode changed {len(changed_rel_paths)} file(s)."
            if result == "ok"
            else "Direct-edit mode produced no file changes."
        ),
        values_patch=values_patch,
        template_patches=template_patches,
        violation_coverage=[
            FullFixViolationCoverage(
                rule_id=item.rule_id,
                status=coverage_status,
                note=coverage_note,
            )
            for item in violations
        ],
    )
    return response, ""


def _build_values_patch_from_staged(
    *,
    chart_dir: Path,
    staged_chart_dir: Path,
    rel_values_path: str,
) -> tuple[dict[str, Any], str]:
    original_path = (chart_dir / rel_values_path).resolve()
    staged_path = (staged_chart_dir / rel_values_path).resolve()
    if not staged_path.exists():
        return {}, "Staged values file is missing."
    try:
        original_raw = original_path.read_text(encoding="utf-8")
        staged_raw = staged_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"Failed to read values files for staged diff: {exc!s}"
    try:
        original_parsed = yaml.safe_load(original_raw) or {}
        staged_parsed = yaml.safe_load(staged_raw) or {}
    except yaml.YAMLError as exc:
        return {}, f"Invalid YAML in staged values file: {exc!s}"
    if not isinstance(original_parsed, dict) or not isinstance(staged_parsed, dict):
        return {}, "values.yaml root must remain a mapping."
    return _mapping_overlay_patch(original_parsed, staged_parsed), ""


def _mapping_overlay_patch(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key, after_value in after.items():
        if key not in before:
            patch[key] = after_value
            continue
        before_value = before[key]
        if isinstance(before_value, dict) and isinstance(after_value, dict):
            nested = _mapping_overlay_patch(before_value, after_value)
            if nested:
                patch[key] = nested
            continue
        if before_value != after_value:
            patch[key] = after_value
    return patch


def _hash_file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
