"""Unit tests for structured LLM patch contract module."""

from __future__ import annotations

import pytest

from kubeagle.optimizer.llm_patch_protocol import (
    build_structured_patch_prompt,
    format_structured_patch_preview_markdown,
    parse_structured_patch_response,
    with_system_prompt_override,
)


def test_build_structured_patch_prompt_contains_allowlist_and_contract() -> None:
    """Prompt should include strict contract instructions and allowed files."""
    prompt = build_structured_patch_prompt(
        task="Add liveness probe wiring.",
        allowed_files=["templates/deployment.yaml", "templates/statefulset.yaml"],
        context_blocks=[
            ("Violation", "Rule: PRB001"),
            ("Suggested Keys", "livenessProbe.httpGet.path"),
        ],
    )

    assert "Return output as a single JSON object only." in prompt
    assert "schema_version" in prompt
    assert "- templates/deployment.yaml" in prompt
    assert "- templates/statefulset.yaml" in prompt
    assert "## Violation" in prompt


def test_build_structured_patch_prompt_applies_system_override() -> None:
    """Structured prompt should prepend configured system override text."""
    prompt = build_structured_patch_prompt(
        task="Add liveness probe wiring.",
        allowed_files=["templates/deployment.yaml"],
        system_prompt_override="Always preserve existing helper includes.",
    )

    assert "Additional system instructions (configured override):" in prompt
    assert "Always preserve existing helper includes." in prompt


def test_parse_structured_patch_response_accepts_plain_json() -> None:
    """Parser should accept direct JSON object output."""
    raw = (
        '{'
        '"schema_version":"patch_response.v1",'
        '"result":"ok",'
        '"summary":"wired liveness",'
        '"patches":[{"file":"templates/deployment.yaml","purpose":"add probe","unified_diff":"--- a/templates/deployment.yaml\\n+++ b/templates/deployment.yaml\\n@@ -1,1 +1,2 @@\\n+livenessProbe:"}],'
        '"warnings":[],"error":""'
        '}'
    )

    parsed = parse_structured_patch_response(raw)

    assert parsed.result == "ok"
    assert len(parsed.patches) == 1
    assert parsed.patches[0].file == "templates/deployment.yaml"


def test_parse_structured_patch_response_accepts_fenced_json() -> None:
    """Parser should recover JSON from markdown fence if provider wraps output."""
    raw = (
        "```json\n"
        '{'
        '"schema_version":"patch_response.v1",'
        '"result":"no_change",'
        '"summary":"already wired",'
        '"patches":[],"warnings":["none"],"error":""'
        "}\n"
        "```"
    )

    parsed = parse_structured_patch_response(raw)

    assert parsed.result == "no_change"
    assert parsed.warnings == ["none"]


def test_parse_structured_patch_response_accepts_wrapped_json_with_prose() -> None:
    """Parser should recover object JSON when provider adds prose around output."""
    raw = (
        "Here is the result:\n"
        '{'
        '"schema_version":"patch_response.v1",'
        '"result":"ok",'
        '"summary":"wrapped",'
        '"patches":[{"file":"templates/deployment.yaml","purpose":"wire","unified_diff":"--- a/templates/deployment.yaml\\n+++ b/templates/deployment.yaml"}],'
        '"warnings":[],"error":""'
        "}\n"
        "Thanks."
    )
    parsed = parse_structured_patch_response(raw)
    assert parsed.result == "ok"
    assert parsed.summary == "wrapped"


def test_parse_structured_patch_response_uses_first_schema_valid_object() -> None:
    """Parser should skip unrelated JSON object and parse contract-compatible object."""
    raw = (
        '{"meta":"diagnostics"}\n'
        '{'
        '"schema_version":"patch_response.v1",'
        '"result":"ok",'
        '"summary":"valid object",'
        '"patches":[{"file":"templates/deployment.yaml","purpose":"wire","unified_diff":"--- a/templates/deployment.yaml\\n+++ b/templates/deployment.yaml"}],'
        '"warnings":[],"error":""'
        "}"
    )
    parsed = parse_structured_patch_response(raw)
    assert parsed.result == "ok"
    assert parsed.summary == "valid object"


def test_parse_structured_patch_response_rejects_invalid_payload() -> None:
    """Parser should fail on non-contract outputs."""
    with pytest.raises(ValueError):
        parse_structured_patch_response("not-json")


def test_format_structured_patch_preview_markdown() -> None:
    """Formatter should produce dialog-friendly diff preview."""
    parsed = parse_structured_patch_response(
        '{'
        '"schema_version":"patch_response.v1",'
        '"result":"ok",'
        '"summary":"added wiring",'
        '"patches":[{"file":"templates/deployment.yaml","purpose":"wire values","unified_diff":"--- a/templates/deployment.yaml\\n+++ b/templates/deployment.yaml\\n@@ -1,1 +1,2 @@\\n+livenessProbe:"}],'
        '"warnings":["check indent"],"error":""'
        '}'
    )

    markdown = format_structured_patch_preview_markdown(parsed)

    assert "### AI Patch Result" in markdown
    assert "**Result:** `OK`" in markdown
    assert "```diff" in markdown
    assert "livenessProbe" in markdown


def test_with_system_prompt_override_returns_base_when_override_empty() -> None:
    """Helper should keep original prompt unchanged when override is empty."""
    base_prompt = "Return JSON only."
    assert with_system_prompt_override(base_prompt, system_prompt_override="") == base_prompt


