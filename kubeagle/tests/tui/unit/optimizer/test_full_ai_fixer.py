"""Unit tests for direct-edit AI full-fix generation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from kubeagle.constants.enums import Severity
from kubeagle.models.analysis.violation import ViolationResult
from kubeagle.optimizer.full_ai_fixer import (
    FULL_FIX_PROMPT_TOKEN_ALLOWED_FILES,
    FULL_FIX_PROMPT_TOKEN_SEED_YAML,
    FULL_FIX_PROMPT_TOKEN_VIOLATIONS,
    generate_ai_full_fix_for_chart,
    get_default_full_fix_system_prompt_template,
)
from kubeagle.optimizer.llm_cli_runner import LLMProvider


def _build_violation(rule_id: str = "PRB001") -> ViolationResult:
    return ViolationResult(
        id=rule_id,
        chart_name="demo",
        rule_name="Missing Probe",
        rule_id=rule_id,
        category="probes",
        severity=Severity.WARNING,
        description="missing probe",
        current_value="none",
        recommended_value="add probe",
        fix_available=True,
    )


def _prepare_chart(tmp_path: Path) -> tuple[Path, Path]:
    chart_dir = tmp_path / "chart"
    templates = chart_dir / "templates"
    templates.mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(
        "apiVersion: v2\nname: demo\nversion: 0.1.0\n",
        encoding="utf-8",
    )
    (chart_dir / "templates" / "deployment.yaml").write_text(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: demo\n",
        encoding="utf-8",
    )
    values_path = chart_dir / "values.yaml"
    values_path.write_text("replicaCount: 1\n", encoding="utf-8")
    return chart_dir, values_path


def test_default_full_fix_template_exposes_rule_guidance_lines() -> None:
    """Default editable template should list concrete per-rule guidance."""
    template = get_default_full_fix_system_prompt_template()

    assert FULL_FIX_PROMPT_TOKEN_VIOLATIONS in template
    assert FULL_FIX_PROMPT_TOKEN_SEED_YAML in template
    assert FULL_FIX_PROMPT_TOKEN_ALLOWED_FILES in template
    assert "- PRB001: Use `livenessProbe` under workload container config." in template
    assert "- RES005:" in template
    assert "- RES006:" in template
    assert "- RES007:" in template
    # Verify rule ordering constraint is present
    assert "RULE ORDERING" in template


def test_generate_ai_full_fix_direct_edit_uses_template_mode_when_tokens_present(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Configured prompt with template tokens should be rendered as full prompt."""
    chart_dir, values_path = _prepare_chart(tmp_path)
    prompts: list[str] = []

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.provider_supports_direct_edit",
        lambda provider: provider == LLMProvider.CODEX,
    )

    def _fake_direct_runner(**kwargs):
        prompts.append(str(kwargs.get("prompt", "")))
        staged_dir = Path(kwargs["cwd"])
        (staged_dir / "values.yaml").write_text("replicaCount: 2\n", encoding="utf-8")
        return SimpleNamespace(
            ok=True,
            log_text="direct edit ok",
            error_message="",
            changed_rel_paths=["values.yaml"],
            stdout_tail="",
            stderr_tail="",
        )

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.run_llm_direct_edit",
        _fake_direct_runner,
    )

    template = (
        "Custom prompt header.\n"
        f"Violations:\n{FULL_FIX_PROMPT_TOKEN_VIOLATIONS}\n"
        f"Seed:\n{FULL_FIX_PROMPT_TOKEN_SEED_YAML}\n"
        f"Scope:\n{FULL_FIX_PROMPT_TOKEN_ALLOWED_FILES}\n"
    )

    result = generate_ai_full_fix_for_chart(
        chart_dir=chart_dir,
        values_path=values_path,
        violations=[_build_violation("AVL005")],
        preferred_provider=LLMProvider.CODEX,
        full_fix_system_prompt=template,
    )

    assert result.ok is True
    assert prompts
    assert "Custom prompt header." in prompts[0]
    assert "AVL005 (Missing Probe)" in prompts[0]
    assert "values.yaml" in prompts[0]
    assert "templates/deployment.yaml" in prompts[0]


def test_generate_ai_full_fix_direct_edit_keeps_legacy_override_mode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Configured text without tokens should keep legacy prepend override flow."""
    chart_dir, values_path = _prepare_chart(tmp_path)
    prompts: list[str] = []

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.provider_supports_direct_edit",
        lambda provider: provider == LLMProvider.CODEX,
    )

    def _fake_direct_runner(**kwargs):
        prompts.append(str(kwargs.get("prompt", "")))
        staged_dir = Path(kwargs["cwd"])
        (staged_dir / "values.yaml").write_text("replicaCount: 2\n", encoding="utf-8")
        return SimpleNamespace(
            ok=True,
            log_text="direct edit ok",
            error_message="",
            changed_rel_paths=["values.yaml"],
            stdout_tail="",
            stderr_tail="",
        )

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.run_llm_direct_edit",
        _fake_direct_runner,
    )

    result = generate_ai_full_fix_for_chart(
        chart_dir=chart_dir,
        values_path=values_path,
        violations=[_build_violation("AVL005")],
        preferred_provider=LLMProvider.CODEX,
        full_fix_system_prompt="Always keep helper names chart-specific.",
    )

    assert result.ok is True
    assert prompts
    assert "Additional system instructions (configured override):" in prompts[0]
    assert "Always keep helper names chart-specific." in prompts[0]
    assert "STRICT edit scope (existing files only):" in prompts[0]


def test_generate_ai_full_fix_direct_edit_success_builds_staged_artifact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Direct-edit mode should return staged artifact and content-derived patches."""
    chart_dir, values_path = _prepare_chart(tmp_path)
    prompts: list[str] = []

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.provider_supports_direct_edit",
        lambda provider: provider == LLMProvider.CODEX,
    )

    def _fake_direct_runner(**kwargs):
        prompts.append(str(kwargs.get("prompt", "")))
        staged_dir = Path(kwargs["cwd"])
        (staged_dir / "values.yaml").write_text("replicaCount: 2\n", encoding="utf-8")
        (staged_dir / "templates" / "deployment.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: demo\nspec:\n  replicas: 2\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            ok=True,
            log_text="direct edit ok",
            error_message="",
            changed_rel_paths=["values.yaml", "templates/deployment.yaml"],
            stdout_tail="",
            stderr_tail="",
        )

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.run_llm_direct_edit",
        _fake_direct_runner,
    )

    result = generate_ai_full_fix_for_chart(
        chart_dir=chart_dir,
        values_path=values_path,
        violations=[_build_violation("AVL005")],
        preferred_provider=LLMProvider.CODEX,
    )

    assert result.ok is True
    assert result.provider == "codex"
    assert result.staged_artifact is not None
    assert "values.yaml" in result.staged_artifact.changed_rel_paths
    assert result.response is not None
    assert result.response.values_patch.get("replicaCount") == 2
    assert any(p.file == "templates/deployment.yaml" for p in result.response.template_patches)
    assert any("Do not invent alias keys or suffixed names" in prompt for prompt in prompts)
    assert any("resourcesAutomation" in prompt for prompt in prompts)
    assert all(str(chart_dir) not in prompt for prompt in prompts)


def test_generate_ai_full_fix_direct_edit_scope_violation_returns_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Out-of-scope direct edits should be discarded without failing generation."""
    chart_dir, values_path = _prepare_chart(tmp_path)

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.provider_supports_direct_edit",
        lambda _provider: True,
    )

    def _fake_direct_runner(**kwargs):
        staged_dir = Path(kwargs["cwd"])
        (staged_dir / "Chart.yaml").write_text(
            "apiVersion: v2\nname: mutated\nversion: 0.1.0\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            ok=True,
            log_text="edited out-of-scope file",
            error_message="",
            changed_rel_paths=["Chart.yaml"],
            stdout_tail="",
            stderr_tail="",
        )

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.run_llm_direct_edit",
        _fake_direct_runner,
    )

    result = generate_ai_full_fix_for_chart(
        chart_dir=chart_dir,
        values_path=values_path,
        violations=[_build_violation("PRB001")],
        preferred_provider=LLMProvider.CODEX,
    )

    assert result.ok is True
    assert result.status == "no_change"
    assert result.response is not None
    assert result.response.values_patch == {}
    assert (chart_dir / "Chart.yaml").read_text(encoding="utf-8") == "apiVersion: v2\nname: demo\nversion: 0.1.0\n"


def test_generate_ai_full_fix_discards_out_of_scope_but_keeps_allowed_changes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Mixed edits should keep allowed file changes and drop out-of-scope mutations."""
    chart_dir, values_path = _prepare_chart(tmp_path)

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.provider_supports_direct_edit",
        lambda provider: provider == LLMProvider.CODEX,
    )

    def _fake_direct_runner(**kwargs):
        staged_dir = Path(kwargs["cwd"])
        (staged_dir / "Chart.yaml").write_text(
            "apiVersion: v2\nname: mutated\nversion: 0.1.0\n",
            encoding="utf-8",
        )
        (staged_dir / "values.yaml").write_text("replicaCount: 3\n", encoding="utf-8")
        return SimpleNamespace(
            ok=True,
            log_text="mixed in-scope and out-of-scope edits",
            error_message="",
            changed_rel_paths=["Chart.yaml", "values.yaml"],
            stdout_tail="",
            stderr_tail="",
        )

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.run_llm_direct_edit",
        _fake_direct_runner,
    )

    result = generate_ai_full_fix_for_chart(
        chart_dir=chart_dir,
        values_path=values_path,
        violations=[_build_violation("AVL005")],
        preferred_provider=LLMProvider.CODEX,
    )

    assert result.ok is True
    assert result.status == "ok"
    assert result.response is not None
    assert result.response.values_patch.get("replicaCount") == 3
    assert result.staged_artifact is not None
    assert "values.yaml" in result.staged_artifact.changed_rel_paths
    assert "Chart.yaml" not in result.staged_artifact.changed_rel_paths


def test_generate_ai_full_fix_direct_edit_ignores_provider_metadata_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Provider metadata files should not force a retry."""
    chart_dir, values_path = _prepare_chart(tmp_path)
    attempts: list[int] = []

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.provider_supports_direct_edit",
        lambda provider: provider == LLMProvider.CODEX,
    )

    def _fake_direct_runner(**kwargs):
        attempts.append(int(kwargs.get("attempts", 0)))
        staged_dir = Path(kwargs["cwd"])
        (staged_dir / ".claude").mkdir(parents=True, exist_ok=True)
        (staged_dir / ".claude" / "session.json").write_text("{}", encoding="utf-8")
        (staged_dir / "values.yaml").write_text("replicaCount: 3\n", encoding="utf-8")
        return SimpleNamespace(
            ok=True,
            log_text="direct edit ok",
            error_message="",
            changed_rel_paths=["values.yaml", ".claude/session.json"],
            stdout_tail="",
            stderr_tail="",
        )

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.run_llm_direct_edit",
        _fake_direct_runner,
    )

    result = generate_ai_full_fix_for_chart(
        chart_dir=chart_dir,
        values_path=values_path,
        violations=[_build_violation("AVL005")],
        preferred_provider=LLMProvider.CODEX,
    )

    assert result.ok is True
    assert result.provider == "codex"
    assert result.staged_artifact is not None
    assert result.response is not None
    assert result.response.values_patch.get("replicaCount") == 3
    assert ".claude/session.json" not in result.staged_artifact.changed_rel_paths
    assert attempts == [1]


def test_generate_ai_full_fix_direct_edit_reverts_source_chart_mutation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Source chart edits during direct-edit must be reverted and return an error."""
    chart_dir, values_path = _prepare_chart(tmp_path)
    original_values = values_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.provider_supports_direct_edit",
        lambda provider: provider == LLMProvider.CODEX,
    )

    def _fake_direct_runner(**kwargs):
        _ = kwargs
        values_path.write_text("replicaCount: 999\n", encoding="utf-8")
        return SimpleNamespace(
            ok=True,
            log_text="unsafe source mutation",
            error_message="",
            changed_rel_paths=["values.yaml"],
            stdout_tail="",
            stderr_tail="",
        )

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.run_llm_direct_edit",
        _fake_direct_runner,
    )

    result = generate_ai_full_fix_for_chart(
        chart_dir=chart_dir,
        values_path=values_path,
        violations=[_build_violation("PRB001")],
        preferred_provider=LLMProvider.CODEX,
    )

    assert result.ok is False
    assert result.status == "error"
    assert result.response is None
    assert values_path.read_text(encoding="utf-8") == original_values
    assert any("Unsafe source-chart mutation detected and reverted" in error for error in result.errors)


def test_generate_ai_full_fix_direct_edit_honors_preferred_provider_without_cross_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Preferred Claude provider should run a single direct-edit attempt only."""
    chart_dir, values_path = _prepare_chart(tmp_path)
    direct_calls: list[str] = []

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.provider_supports_direct_edit",
        lambda _provider: True,
    )

    def _fake_direct_runner(**kwargs):
        provider = kwargs["provider"]
        direct_calls.append(provider.value)
        return SimpleNamespace(
            ok=False,
            log_text="direct-edit failed",
            error_message="direct-edit failed",
            changed_rel_paths=[],
            stdout_tail="",
            stderr_tail="",
        )

    monkeypatch.setattr(
        "kubeagle.optimizer.full_ai_fixer.run_llm_direct_edit",
        _fake_direct_runner,
    )

    result = generate_ai_full_fix_for_chart(
        chart_dir=chart_dir,
        values_path=values_path,
        violations=[_build_violation("PRB001")],
        preferred_provider=LLMProvider.CLAUDE,
    )

    assert result.ok is False
    assert result.status == "error"
    assert result.response is None
    assert direct_calls == ["claude"]
