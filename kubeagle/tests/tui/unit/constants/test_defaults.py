"""Unit tests for default values in constants/defaults.py.

Tests cover:
- All default value constants
- Correct types (str, int, float, bool)
- Expected specific values
- Non-empty strings where appropriate
"""

from __future__ import annotations

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
    REFRESH_INTERVAL_DEFAULT,
    THEME_DEFAULT,
)

# =============================================================================
# UI defaults
# =============================================================================


class TestUIDefaults:
    """Test UI-related default values."""

    def test_theme_default_type(self) -> None:
        assert isinstance(THEME_DEFAULT, str)

    def test_theme_default_value(self) -> None:
        assert THEME_DEFAULT == "InsiderOne-Dark"

    def test_refresh_interval_default_type(self) -> None:
        assert isinstance(REFRESH_INTERVAL_DEFAULT, int)

    def test_refresh_interval_default_value(self) -> None:
        assert REFRESH_INTERVAL_DEFAULT == 30

    def test_refresh_interval_default_positive(self) -> None:
        assert REFRESH_INTERVAL_DEFAULT > 0


# =============================================================================
# Threshold defaults
# =============================================================================


class TestThresholdDefaults:
    """Test threshold-related default values."""

    def test_event_age_hours_default_type(self) -> None:
        assert isinstance(EVENT_AGE_HOURS_DEFAULT, float)

    def test_event_age_hours_default_value(self) -> None:
        assert EVENT_AGE_HOURS_DEFAULT == 1.0

    def test_event_age_hours_default_positive(self) -> None:
        assert EVENT_AGE_HOURS_DEFAULT > 0

    def test_limit_request_ratio_threshold_default_type(self) -> None:
        assert isinstance(LIMIT_REQUEST_RATIO_THRESHOLD_DEFAULT, float)

    def test_limit_request_ratio_threshold_default_value(self) -> None:
        assert LIMIT_REQUEST_RATIO_THRESHOLD_DEFAULT == 2.0

    def test_limit_request_ratio_threshold_default_positive(self) -> None:
        assert LIMIT_REQUEST_RATIO_THRESHOLD_DEFAULT > 0


class TestOptimizerVerificationDefaults:
    """Test optimizer verification default values."""

    def test_optimizer_analysis_source_default_type(self) -> None:
        assert isinstance(OPTIMIZER_ANALYSIS_SOURCE_DEFAULT, str)

    def test_optimizer_analysis_source_default_value(self) -> None:
        assert OPTIMIZER_ANALYSIS_SOURCE_DEFAULT == "auto"

    def test_helm_template_timeout_seconds_default_type(self) -> None:
        assert isinstance(HELM_TEMPLATE_TIMEOUT_SECONDS_DEFAULT, int)

    def test_helm_template_timeout_seconds_default_value(self) -> None:
        assert HELM_TEMPLATE_TIMEOUT_SECONDS_DEFAULT == 30

    def test_ai_fix_llm_provider_default_type(self) -> None:
        assert isinstance(AI_FIX_LLM_PROVIDER_DEFAULT, str)

    def test_ai_fix_llm_provider_default_value(self) -> None:
        assert AI_FIX_LLM_PROVIDER_DEFAULT == "codex"

    def test_ai_fix_codex_model_default_type(self) -> None:
        assert isinstance(AI_FIX_CODEX_MODEL_DEFAULT, str)

    def test_ai_fix_codex_model_default_value(self) -> None:
        assert AI_FIX_CODEX_MODEL_DEFAULT == "auto"

    def test_ai_fix_claude_model_default_type(self) -> None:
        assert isinstance(AI_FIX_CLAUDE_MODEL_DEFAULT, str)

    def test_ai_fix_claude_model_default_value(self) -> None:
        assert AI_FIX_CLAUDE_MODEL_DEFAULT == "auto"

    def test_ai_fix_full_fix_system_prompt_default(self) -> None:
        assert AI_FIX_FULL_FIX_SYSTEM_PROMPT_DEFAULT == ""

    def test_ai_fix_bulk_parallelism_default(self) -> None:
        assert AI_FIX_BULK_PARALLELISM_DEFAULT == 2


# =============================================================================
# __all__ exports
# =============================================================================


class TestDefaultsExports:
    """Test that __all__ exports are correct."""

    def test_all_exports_importable(self) -> None:
        import kubeagle.constants.defaults as mod

        for name in mod.__all__:
            assert hasattr(mod, name), f"{name} listed in __all__ but not defined"
