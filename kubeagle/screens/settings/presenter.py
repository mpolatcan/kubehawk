"""Settings screen presenter - settings management and validation logic."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from kubeagle.models.state.config_manager import (
    AppSettings,
    ConfigManager,
    ConfigSaveError,
)
from kubeagle.optimizer.full_ai_fixer import (
    is_default_full_fix_system_prompt_template,
    validate_full_fix_prompt_template,
)

logger = logging.getLogger(__name__)

AI_FIX_CODEX_ALLOWED_MODELS: set[str] = {
    "auto",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2-codex",
    "gpt-5.2",
    "gpt-5.1-codex-max",
    "gpt-5-codex",
    "gpt-5",
    "o3",
}

AI_FIX_CLAUDE_ALLOWED_MODELS: set[str] = {
    "auto",
    "default",
    "sonnet",
    "opus",
    "haiku",
}
AI_FIX_SYSTEM_PROMPT_MAX_CHARS = 12000


class SettingsPresenter:
    """Presenter for SettingsScreen - handles settings management and validation."""

    def __init__(self, screen: Any) -> None:
        """Initialize the presenter.

        Args:
            screen: The parent SettingsScreen instance.
        """
        self._screen = screen
        self._settings: AppSettings = getattr(screen.app, "settings", AppSettings())

    @property
    def settings(self) -> AppSettings:
        """Get current settings."""
        return self._settings

    def load_settings(self) -> None:
        """Load settings from app."""
        self._settings = getattr(self._screen.app, "settings", AppSettings())

    def get_value(self, setting_id: str) -> str | int | float | bool:
        """Get a setting value by ID."""
        mapping = {
            "charts-path-input": self._settings.charts_path,
            "active-charts-input": self._settings.active_charts_path,
            "codeowners-input": self._settings.codeowners_path,
            "theme-input": self._settings.theme,
            "refresh-interval-input": self._settings.refresh_interval,
            "auto-refresh-switch": self._settings.auto_refresh,
            "export-path-input": self._settings.export_path,
            "event-age-input": self._settings.event_age_hours,
            "high-cpu-input": self._settings.high_cpu_threshold,
            "high-memory-input": self._settings.high_memory_threshold,
            "high-pod-input": self._settings.high_pod_threshold,
            "limit-request-input": self._settings.limit_request_ratio_threshold,
            "high-pod-percent-input": self._settings.high_pod_percentage_threshold,
            "optimizer-analysis-source-input": self._settings.optimizer_analysis_source,
            "helm-template-timeout-input": self._settings.helm_template_timeout_seconds,
            "ai-fix-llm-provider-select": self._settings.ai_fix_llm_provider,
            "ai-fix-codex-model-select": self._settings.ai_fix_codex_model,
            "ai-fix-claude-model-select": self._settings.ai_fix_claude_model,
            "ai-fix-full-fix-prompt-input": self._settings.ai_fix_full_fix_system_prompt,
            "ai-fix-bulk-parallelism-input": self._settings.ai_fix_bulk_parallelism,
            "progressive-parallelism-select": self._settings.progressive_parallelism,
            "progressive-yield-interval-select": self._settings.progressive_yield_interval,
            "use-cluster-values-switch": self._settings.use_cluster_values,
            "use-cluster-mode-switch": self._settings.use_cluster_mode,
            "verify-fixes-render-switch": self._settings.verify_fixes_with_render,
            "fix-cpu-request-switch": "cpu_request" in self._settings.fixed_resource_fields,
            "fix-cpu-limit-switch": "cpu_limit" in self._settings.fixed_resource_fields,
            "fix-memory-request-switch": "memory_request" in self._settings.fixed_resource_fields,
            "fix-memory-limit-switch": "memory_limit" in self._settings.fixed_resource_fields,
        }
        return mapping.get(setting_id, "")

    def validate_and_save(self, input_values: dict[str, str], switch_values: dict[str, bool]) -> tuple[bool, str]:
        """Validate inputs and save settings.

        Collects ALL validation errors before returning, so the user can fix
        them all at once rather than one at a time.

        Args:
            input_values: Dictionary of input field values.
            switch_values: Dictionary of switch field values.

        Returns:
            Tuple of (success, message).
        """
        from kubeagle.constants.defaults import (
            AI_FIX_BULK_PARALLELISM_DEFAULT,
            AI_FIX_CLAUDE_MODEL_DEFAULT,
            AI_FIX_CODEX_MODEL_DEFAULT,
            AI_FIX_FULL_FIX_SYSTEM_PROMPT_DEFAULT,
            AI_FIX_LLM_PROVIDER_DEFAULT,
            EVENT_AGE_HOURS_DEFAULT,
            HELM_TEMPLATE_TIMEOUT_SECONDS_DEFAULT,
            LIMIT_REQUEST_RATIO_THRESHOLD_DEFAULT,
            OPTIMIZER_ANALYSIS_SOURCE_DEFAULT,
            PROGRESSIVE_PARALLELISM_DEFAULT,
            PROGRESSIVE_YIELD_INTERVAL_DEFAULT,
            REFRESH_INTERVAL_DEFAULT,
            THEME_DEFAULT,
        )
        from kubeagle.constants.limits import (
            AI_FIX_BULK_PARALLELISM_MAX,
            AI_FIX_BULK_PARALLELISM_MIN,
            PROGRESSIVE_PARALLELISM_MAX,
            PROGRESSIVE_PARALLELISM_MIN,
            PROGRESSIVE_YIELD_INTERVAL_MAX,
            PROGRESSIVE_YIELD_INTERVAL_MIN,
            REFRESH_INTERVAL_MIN,
        )

        errors: list[str] = []

        # Parse values
        charts_path = self._normalize_path(input_values.get("charts-path-input", ""))
        active_charts_path = self._normalize_path(input_values.get("active-charts-input", ""))
        codeowners_path = self._normalize_path(input_values.get("codeowners-input", ""))
        theme = str(input_values.get("theme-input", THEME_DEFAULT) or THEME_DEFAULT).strip()
        refresh_interval = self._parse_int(input_values.get("refresh-interval-input", ""), REFRESH_INTERVAL_DEFAULT)
        auto_refresh = switch_values.get("auto-refresh-switch", False)
        export_path = input_values.get("export-path-input", "")
        event_age_hours = self._parse_float(input_values.get("event-age-input", ""), EVENT_AGE_HOURS_DEFAULT)
        limit_request_ratio_threshold = self._parse_float(input_values.get("limit-request-input", ""), LIMIT_REQUEST_RATIO_THRESHOLD_DEFAULT)
        optimizer_analysis_source = (
            str(
                input_values.get(
                    "optimizer-analysis-source-input",
                    OPTIMIZER_ANALYSIS_SOURCE_DEFAULT,
                )
            )
            .strip()
            .lower()
        )
        helm_template_timeout_seconds = self._parse_int(
            input_values.get("helm-template-timeout-input", ""),
            HELM_TEMPLATE_TIMEOUT_SECONDS_DEFAULT,
        )
        ai_fix_llm_provider = str(
            input_values.get(
                "ai-fix-llm-provider-select",
                AI_FIX_LLM_PROVIDER_DEFAULT,
            )
        ).strip().lower()
        ai_fix_codex_model = str(
            input_values.get(
                "ai-fix-codex-model-select",
                AI_FIX_CODEX_MODEL_DEFAULT,
            )
        ).strip().lower()
        ai_fix_claude_model = str(
            input_values.get(
                "ai-fix-claude-model-select",
                AI_FIX_CLAUDE_MODEL_DEFAULT,
            )
        ).strip().lower()
        use_cluster_values = switch_values.get("use-cluster-values-switch", False)
        use_cluster_mode = switch_values.get("use-cluster-mode-switch", False)
        verify_fixes_with_render = switch_values.get("verify-fixes-render-switch", True)

        # Collect fixed resource fields from switches
        fixed_resource_fields: list[str] = []
        _fixed_switch_map = {
            "fix-cpu-request-switch": "cpu_request",
            "fix-cpu-limit-switch": "cpu_limit",
            "fix-memory-request-switch": "memory_request",
            "fix-memory-limit-switch": "memory_limit",
        }
        for switch_id, field_name in _fixed_switch_map.items():
            if switch_values.get(switch_id, field_name in {"cpu_limit", "memory_limit"}):
                fixed_resource_fields.append(field_name)
        ai_fix_full_fix_system_prompt = str(
            input_values.get(
                "ai-fix-full-fix-prompt-input",
                AI_FIX_FULL_FIX_SYSTEM_PROMPT_DEFAULT,
            )
            or ""
        ).strip()
        ai_fix_bulk_parallelism = self._parse_int(
            input_values.get("ai-fix-bulk-parallelism-input", ""),
            AI_FIX_BULK_PARALLELISM_DEFAULT,
        )
        progressive_parallelism = self._parse_int(
            input_values.get("progressive-parallelism-select", ""),
            PROGRESSIVE_PARALLELISM_DEFAULT,
        )
        progressive_yield_interval = self._parse_int(
            input_values.get("progressive-yield-interval-select", ""),
            PROGRESSIVE_YIELD_INTERVAL_DEFAULT,
        )

        # Validate charts path
        if not charts_path:
            errors.append("Charts path is required. Please enter the path to your Helm charts directory.")
        elif not Path(charts_path).is_dir():
            errors.append(f"Invalid charts path: '{charts_path}'. Path must exist and be a directory.")

        # Validate active charts path
        if active_charts_path and not Path(active_charts_path).is_file():
            errors.append(f"Invalid active charts file: '{active_charts_path}'. Path must be a file.")
        if codeowners_path and not Path(codeowners_path).is_file():
            errors.append(f"Invalid CODEOWNERS file: '{codeowners_path}'. Path must be a file.")

        # Validate refresh interval
        if refresh_interval < REFRESH_INTERVAL_MIN:
            errors.append(f"Refresh interval must be at least {REFRESH_INTERVAL_MIN} seconds.")
            refresh_interval = REFRESH_INTERVAL_DEFAULT

        if not (event_age_hours > 0):
            errors.append("Event age filter must be positive.")
            event_age_hours = EVENT_AGE_HOURS_DEFAULT

        if not (limit_request_ratio_threshold > 0):
            errors.append("Limit/Request ratio threshold must be positive.")
            limit_request_ratio_threshold = LIMIT_REQUEST_RATIO_THRESHOLD_DEFAULT

        if optimizer_analysis_source not in {"auto", "rendered", "values"}:
            errors.append("Optimizer analysis source must be one of: auto, rendered, values.")
            optimizer_analysis_source = OPTIMIZER_ANALYSIS_SOURCE_DEFAULT

        if helm_template_timeout_seconds <= 0:
            errors.append("Helm template timeout must be a positive integer.")
            helm_template_timeout_seconds = HELM_TEMPLATE_TIMEOUT_SECONDS_DEFAULT
        if ai_fix_llm_provider not in {"codex", "claude"}:
            errors.append("AI fix provider must be one of: codex, claude.")
            ai_fix_llm_provider = AI_FIX_LLM_PROVIDER_DEFAULT
        if ai_fix_codex_model not in AI_FIX_CODEX_ALLOWED_MODELS:
            errors.append(
                "Codex model must be one of: "
                "auto, gpt-5.3-codex, gpt-5.3-codex-spark, gpt-5.2-codex, gpt-5.2, "
                "gpt-5.1-codex-max, gpt-5-codex, gpt-5, o3."
            )
            ai_fix_codex_model = AI_FIX_CODEX_MODEL_DEFAULT
        if ai_fix_claude_model not in AI_FIX_CLAUDE_ALLOWED_MODELS:
            errors.append(
                "Claude model must be one of: "
                "auto, default, sonnet, opus, haiku."
            )
            ai_fix_claude_model = AI_FIX_CLAUDE_MODEL_DEFAULT
        if len(ai_fix_full_fix_system_prompt) > AI_FIX_SYSTEM_PROMPT_MAX_CHARS:
            errors.append(
                f"AI fix system prompt is too long (max {AI_FIX_SYSTEM_PROMPT_MAX_CHARS} characters)."
            )
            ai_fix_full_fix_system_prompt = AI_FIX_FULL_FIX_SYSTEM_PROMPT_DEFAULT
        if (
            ai_fix_bulk_parallelism < AI_FIX_BULK_PARALLELISM_MIN
            or ai_fix_bulk_parallelism > AI_FIX_BULK_PARALLELISM_MAX
        ):
            errors.append(
                "AI fix bulk parallelism must be between "
                f"{AI_FIX_BULK_PARALLELISM_MIN}-{AI_FIX_BULK_PARALLELISM_MAX}."
            )
            ai_fix_bulk_parallelism = AI_FIX_BULK_PARALLELISM_DEFAULT
        if (
            progressive_parallelism < PROGRESSIVE_PARALLELISM_MIN
            or progressive_parallelism > PROGRESSIVE_PARALLELISM_MAX
        ):
            errors.append(
                "Progressive parallelism must be between "
                f"{PROGRESSIVE_PARALLELISM_MIN}-{PROGRESSIVE_PARALLELISM_MAX}."
            )
            progressive_parallelism = PROGRESSIVE_PARALLELISM_DEFAULT
        if (
            progressive_yield_interval < PROGRESSIVE_YIELD_INTERVAL_MIN
            or progressive_yield_interval > PROGRESSIVE_YIELD_INTERVAL_MAX
        ):
            errors.append(
                "Progressive yield interval must be between "
                f"{PROGRESSIVE_YIELD_INTERVAL_MIN}-{PROGRESSIVE_YIELD_INTERVAL_MAX}."
            )
            progressive_yield_interval = PROGRESSIVE_YIELD_INTERVAL_DEFAULT
        template_error = validate_full_fix_prompt_template(ai_fix_full_fix_system_prompt)
        if template_error:
            errors.append(template_error)

        # If path errors exist, don't save
        if errors:
            return False, "\n".join(errors)

        if is_default_full_fix_system_prompt_template(ai_fix_full_fix_system_prompt):
            ai_fix_full_fix_system_prompt = AI_FIX_FULL_FIX_SYSTEM_PROMPT_DEFAULT

        # Update settings
        self._settings.charts_path = charts_path
        self._settings.active_charts_path = active_charts_path
        self._settings.codeowners_path = codeowners_path
        self._settings.theme = theme
        self._settings.refresh_interval = refresh_interval
        self._settings.auto_refresh = auto_refresh
        self._settings.export_path = export_path
        self._settings.event_age_hours = event_age_hours
        self._settings.limit_request_ratio_threshold = limit_request_ratio_threshold
        self._settings.use_cluster_values = use_cluster_values
        self._settings.use_cluster_mode = use_cluster_mode
        self._settings.optimizer_analysis_source = optimizer_analysis_source
        self._settings.verify_fixes_with_render = verify_fixes_with_render
        self._settings.helm_template_timeout_seconds = helm_template_timeout_seconds
        self._settings.ai_fix_llm_provider = ai_fix_llm_provider
        self._settings.ai_fix_codex_model = ai_fix_codex_model
        self._settings.ai_fix_claude_model = ai_fix_claude_model
        self._settings.ai_fix_full_fix_system_prompt = ai_fix_full_fix_system_prompt
        self._settings.ai_fix_bulk_parallelism = ai_fix_bulk_parallelism
        self._settings.progressive_parallelism = progressive_parallelism
        self._settings.progressive_yield_interval = progressive_yield_interval
        self._settings.fixed_resource_fields = fixed_resource_fields

        # Save to file
        try:
            ConfigManager.save(self._settings)
            return True, "Settings saved successfully!"
        except ConfigSaveError as e:
            return False, f"Failed to save settings: {e}"

    def _parse_int(self, value: str, default: int) -> int:
        """Parse integer from string."""
        try:
            return int(value)
        except ValueError:
            return default

    def _parse_float(self, value: str, default: float) -> float:
        """Parse float from string."""
        try:
            return float(value)
        except ValueError:
            return default

    @staticmethod
    def _normalize_path(value: str) -> str:
        """Normalize path input to an absolute string for stable cross-session loads.

        Recovers common accidental UI suffixes when the trimmed path exists.
        """
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        normalized_path = Path(raw_value).expanduser().absolute()
        if normalized_path.exists():
            return str(normalized_path)

        lower_raw = raw_value.lower()
        for suffix in ("clear", "apply", "cancel"):
            if not lower_raw.endswith(suffix):
                continue
            trimmed_raw = raw_value[: -len(suffix)].rstrip()
            if not trimmed_raw:
                continue
            trimmed_path = Path(trimmed_raw).expanduser().absolute()
            if trimmed_path.exists():
                return str(trimmed_path)

        return str(normalized_path)
