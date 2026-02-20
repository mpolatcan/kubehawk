"""Structured prompt/response contract for LLM-generated file patches."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

_CODE_BLOCK_PATTERN = re.compile(
    r"```(?:json|javascript|js|txt|yaml|yml)?\s*([\s\S]*?)\s*```",
    re.IGNORECASE,
)
_MAX_SYSTEM_PROMPT_OVERRIDE_CHARS = 12000


class StructuredPatchFile(BaseModel):
    """Single file patch payload."""

    file: str
    purpose: str = ""
    unified_diff: str


class StructuredPatchResponse(BaseModel):
    """Normalized patch response from LLM CLI output."""

    schema_version: Literal["patch_response.v1"] = "patch_response.v1"
    result: Literal["ok", "no_change", "error"]
    summary: str
    patches: list[StructuredPatchFile] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str = ""


class FullFixTemplatePatch(BaseModel):
    """Single template patch payload for full-fix response."""

    file: str
    purpose: str = ""
    unified_diff: str = ""
    updated_content: str = ""

    @model_validator(mode="after")
    def _validate_patch_content(self) -> FullFixTemplatePatch:
        if not self.unified_diff.strip() and not self.updated_content.strip():
            raise ValueError("template patch must include unified_diff or updated_content")
        return self


class FullFixViolationCoverage(BaseModel):
    """Per-violation coverage report from chart-bundled full fix."""

    rule_id: str
    status: Literal["addressed", "unchanged", "not_applicable", "error"] = "addressed"
    note: str = ""


class FullFixResponse(BaseModel):
    """Normalized full-fix response from LLM CLI output."""

    schema_version: Literal["full_fix_response.v1"] = "full_fix_response.v1"
    result: Literal["ok", "no_change", "error"]
    summary: str
    values_patch: dict[str, Any] = Field(default_factory=dict)
    template_patches: list[FullFixTemplatePatch] = Field(default_factory=list)
    violation_coverage: list[FullFixViolationCoverage] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str = ""


def normalize_system_prompt_override(raw_override: str | None) -> str:
    """Normalize optional system prompt override text."""
    normalized = str(raw_override or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    return normalized[:_MAX_SYSTEM_PROMPT_OVERRIDE_CHARS]


def with_system_prompt_override(
    base_prompt: str,
    *,
    system_prompt_override: str | None = None,
) -> str:
    """Prepend configured system override instructions to an existing prompt."""
    override = normalize_system_prompt_override(system_prompt_override)
    normalized_base = str(base_prompt or "").strip()
    if not override:
        return normalized_base
    return (
        "Additional system instructions (configured override):\n"
        f"{override}\n\n"
        "Treat the override above as strict requirements while also following "
        "the JSON contract and safety rules below.\n\n"
        f"{normalized_base}"
    ).strip()


def build_structured_patch_prompt(
    *,
    task: str,
    allowed_files: list[str],
    context_blocks: list[tuple[str, str]] | None = None,
    system_prompt_override: str | None = None,
) -> str:
    """Build strict contract prompt so response is always machine-parseable."""
    allowed_list = "\n".join(f"- {path}" for path in allowed_files) or "- (none)"

    context_lines: list[str] = []
    if context_blocks:
        for title, content in context_blocks:
            safe_title = title.strip() or "Context"
            context_lines.extend(
                [
                    f"## {safe_title}",
                    content.rstrip(),
                    "",
                ]
            )

    contract = (
        "{\n"
        '  "schema_version": "patch_response.v1",\n'
        '  "result": "ok | no_change | error",\n'
        '  "summary": "short explanation",\n'
        '  "patches": [\n'
        "    {\n"
        '      "file": "relative/path.yaml",\n'
        '      "purpose": "why this patch",\n'
        '      "unified_diff": "--- a/file\\n+++ b/file\\n@@ ..."\n'
        "    }\n"
        "  ],\n"
        '  "warnings": ["optional warnings"],\n'
        '  "error": "non-empty only when result=error"\n'
        "}"
    )

    prompt_parts = [
        "You are generating patch proposals for Helm chart files.",
        "Return output as a single JSON object only.",
        "Do not use markdown, code fences, prose, or extra keys.",
        "",
        "Task:",
        task.strip(),
        "",
        "Allowed files (strict allowlist):",
        allowed_list,
        "",
        "JSON response contract:",
        contract,
        "",
        "Rules:",
        "- Every `patches[].file` must be one of the allowed files.",
        "- Every `patches[].unified_diff` must be a valid unified diff for that same file.",
        "- If no change is needed: set `result` to `no_change` and `patches` to [].",
        "- If unable to produce safe patch: set `result` to `error` and explain in `error`.",
    ]
    if context_lines:
        prompt_parts.extend(["", *context_lines])

    return with_system_prompt_override(
        "\n".join(prompt_parts).strip(),
        system_prompt_override=system_prompt_override,
    )


def parse_structured_patch_response(raw_text: str) -> StructuredPatchResponse:
    """Parse strict JSON response (or recover from fenced JSON) into model."""
    payloads = _parse_json_payloads(raw_text)
    last_error: ValidationError | None = None
    for payload in payloads:
        try:
            return StructuredPatchResponse.model_validate(payload)
        except ValidationError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise ValueError(f"LLM response schema validation failed: {last_error}") from last_error
    raise ValueError("LLM response is not valid JSON.")


def _parse_json_payloads(raw_text: str) -> list[dict[str, Any]]:
    """Parse JSON object candidates from strict output, fenced blocks, or wrapped prose."""
    normalized = (raw_text or "").strip()
    if not normalized:
        raise ValueError("Empty LLM response.")

    candidates: list[str] = [normalized]
    for match in _CODE_BLOCK_PATTERN.finditer(normalized):
        block = match.group(1).strip()
        if block:
            candidates.append(block)

    seen: set[str] = set()
    payloads: list[dict[str, Any]] = []
    decode_errors: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)

        payload, error = _try_decode_json_object(candidate)
        if payload is not None:
            payloads.append(payload)
        elif error:
            decode_errors.append(error)

        for extracted in _extract_balanced_json_objects(candidate):
            if extracted in seen:
                continue
            seen.add(extracted)
            payload, error = _try_decode_json_object(extracted)
            if payload is not None:
                payloads.append(payload)
            elif error:
                decode_errors.append(error)

    if payloads:
        return payloads
    if decode_errors:
        raise ValueError(f"LLM JSON payload is invalid: {decode_errors[-1]}")
    raise ValueError("LLM response is not valid JSON.")


def _try_decode_json_object(candidate: str) -> tuple[dict[str, Any] | None, str]:
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "top-level JSON value must be an object"
    return payload, ""


def _extract_balanced_json_objects(text: str) -> list[str]:
    """Extract balanced JSON objects from wrapped text in discovery order."""
    objects: list[str] = []
    for start in range(len(text)):
        if text[start] != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == "\"":
                    in_string = False
                continue
            if char == "\"":
                in_string = True
                continue
            if char == "{":
                depth += 1
                continue
            if char == "}":
                depth -= 1
                if depth == 0:
                    objects.append(text[start : index + 1])
                    break
    return objects


def format_structured_patch_preview_markdown(
    response: StructuredPatchResponse,
) -> str:
    """Render parsed patch response for dialog preview."""
    lines = [
        "### AI Patch Result",
        f"- **Result:** `{response.result.upper()}`",
        f"- **Summary:** {response.summary}",
    ]
    if response.warnings:
        lines.extend(
            [
                "",
                "### Warnings",
                *[f"- {warning}" for warning in response.warnings],
            ]
        )
    if response.error:
        lines.extend(
            [
                "",
                "### Error",
                response.error,
            ]
        )
    if response.patches:
        lines.append("")
        lines.append("### Patch Preview")
        for patch in response.patches:
            lines.extend(
                [
                    f"- **File:** `{patch.file}`",
                    f"- **Purpose:** {patch.purpose or 'No purpose provided.'}",
                    "```diff",
                    patch.unified_diff.rstrip(),
                    "```",
                    "",
                ]
            )
    return "\n".join(lines).strip()


