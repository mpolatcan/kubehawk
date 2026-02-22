"""Unit tests for SettingsPresenter - settings management and validation logic.

This module tests:
- Settings loading and retrieval
- Input validation methods
- Settings persistence
- Theme handling
- Error handling for validation
- Mocked dependencies for isolation
- All public methods of SettingsPresenter

Tests use mocks to isolate the presenter from actual file system operations.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from kubeagle.screens.settings.presenter import (
    SettingsPresenter,
)

# =============================================================================
# Test Fixtures
# =============================================================================


class MockSettingsScreen:
    """Mock SettingsScreen for testing SettingsPresenter."""

    def __init__(self) -> None:
        """Initialize mock screen."""
        self.app = MagicMock()

        # Mock settings
        self._mock_settings = MagicMock()
        self._mock_settings.charts_path = "/test/charts"
        self._mock_settings.active_charts_path = "/test/active.yaml"
        self._mock_settings.codeowners_path = "/test/CODEOWNERS"
        self._mock_settings.theme = "InsiderOne-Dark"
        self._mock_settings.refresh_interval = 60
        self._mock_settings.auto_refresh = False
        self._mock_settings.export_path = "/test/export"
        self._mock_settings.event_age_hours = 24.0
        self._mock_settings.high_cpu_threshold = 80
        self._mock_settings.high_memory_threshold = 80
        self._mock_settings.high_pod_threshold = 50
        self._mock_settings.limit_request_ratio_threshold = 3.0
        self._mock_settings.high_pod_percentage_threshold = 50
        self._mock_settings.use_cluster_values = False
        self._mock_settings.use_cluster_mode = False
        self._mock_settings.optimizer_analysis_source = "auto"
        self._mock_settings.verify_fixes_with_render = True
        self._mock_settings.helm_template_timeout_seconds = 30
        self._mock_settings.ai_fix_llm_provider = "codex"
        self._mock_settings.ai_fix_codex_model = "auto"
        self._mock_settings.ai_fix_claude_model = "auto"
        self._mock_settings.ai_fix_full_fix_system_prompt = "full fix safely"
        self._mock_settings.ai_fix_bulk_parallelism = 2

        self.app.settings = self._mock_settings


# =============================================================================
# SettingsPresenter Initialization Tests
# =============================================================================


class TestSettingsPresenterInitialization:
    """Test SettingsPresenter initialization."""

    def test_init_sets_screen_reference(self) -> None:
        """Test that __init__ stores screen reference."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert presenter._screen is mock_screen

    def test_init_loads_settings(self) -> None:
        """Test that __init__ loads settings from app."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert presenter._settings is not None

    def test_init_sets_settings_attribute(self) -> None:
        """Test that __init__ sets settings property."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert hasattr(presenter, 'settings')


# =============================================================================
# SettingsPresenter Property Tests
# =============================================================================


class TestSettingsPresenterProperties:
    """Test SettingsPresenter property accessors."""

    def test_settings_property(self) -> None:
        """Test settings property returns current settings."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert presenter.settings is presenter._settings
        assert presenter.settings is mock_screen.app.settings

    def test_settings_property_returns_app_settings(self) -> None:
        """Test settings property returns app settings object."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        # Should have all expected attributes
        assert hasattr(presenter.settings, 'charts_path')
        assert hasattr(presenter.settings, 'theme')
        assert hasattr(presenter.settings, 'refresh_interval')


# =============================================================================
# SettingsPresenter Load Settings Tests
# =============================================================================


class TestSettingsPresenterLoadSettings:
    """Test SettingsPresenter settings loading."""

    def test_load_settings_exists(self) -> None:
        """Test that load_settings method exists."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert hasattr(presenter, 'load_settings')
        assert callable(presenter.load_settings)


# =============================================================================
# SettingsPresenter Get Value Tests
# =============================================================================


class TestSettingsPresenterGetValue:
    """Test SettingsPresenter get_value method."""

    def test_get_value_exists(self) -> None:
        """Test that get_value method exists."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert hasattr(presenter, 'get_value')
        assert callable(presenter.get_value)

    def test_get_value_charts_path(self) -> None:
        """Test getting charts path value."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("charts-path-input")

        assert value == "/test/charts"

    def test_get_value_theme(self) -> None:
        """Test getting theme value."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("theme-input")

        assert value == "InsiderOne-Dark"

    def test_get_value_refresh_interval(self) -> None:
        """Test getting refresh interval value."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("refresh-interval-input")

        assert value == 60

    def test_get_value_auto_refresh(self) -> None:
        """Test getting auto refresh value."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("auto-refresh-switch")

        assert value is False

    def test_get_value_optimizer_analysis_source(self) -> None:
        """Test getting optimizer analysis source value."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("optimizer-analysis-source-input")

        assert value == "auto"

    def test_get_value_verify_fixes_with_render(self) -> None:
        """Test getting verify fixes with render switch value."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("verify-fixes-render-switch")

        assert value is True

    def test_get_value_helm_template_timeout(self) -> None:
        """Test getting helm template timeout setting value."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("helm-template-timeout-input")

        assert value == 30

    def test_get_value_ai_fix_llm_provider(self) -> None:
        """Test getting AI fix provider setting value."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("ai-fix-llm-provider-select")

        assert value == "codex"

    def test_get_value_ai_fix_codex_model(self) -> None:
        """Test getting Codex model setting value."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("ai-fix-codex-model-select")

        assert value == "auto"

    def test_get_value_ai_fix_claude_model(self) -> None:
        """Test getting Claude model setting value."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("ai-fix-claude-model-select")

        assert value == "auto"

    def test_get_value_ai_fix_full_fix_system_prompt(self) -> None:
        """Test getting full-fix system prompt override value."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("ai-fix-full-fix-prompt-input")

        assert value == "full fix safely"

    def test_get_value_ai_fix_bulk_parallelism(self) -> None:
        """Test getting AI bulk fix parallelism setting value."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("ai-fix-bulk-parallelism-input")

        assert value == 2

    def test_get_value_unknown_setting(self) -> None:
        """Test getting unknown setting returns empty string."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        value = presenter.get_value("unknown-setting")

        assert value == ""


# =============================================================================
# SettingsPresenter Validation Tests
# =============================================================================


class TestSettingsPresenterValidation:
    """Test SettingsPresenter validation methods."""

    def test_validate_and_save_exists(self) -> None:
        """Test that validate_and_save method exists."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert hasattr(presenter, 'validate_and_save')
        assert callable(presenter.validate_and_save)


# =============================================================================
# SettingsPresenter Parse Tests
# =============================================================================


class TestSettingsPresenterParse:
    """Test SettingsPresenter parse methods."""

    def test_parse_int_exists(self) -> None:
        """Test that _parse_int method exists."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert hasattr(presenter, '_parse_int')
        assert callable(presenter._parse_int)

    def test_parse_float_exists(self) -> None:
        """Test that _parse_float method exists."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert hasattr(presenter, '_parse_float')
        assert callable(presenter._parse_float)

    def test_parse_int_valid(self) -> None:
        """Test parsing valid integer."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert presenter._parse_int("42", 10) == 42
        assert presenter._parse_int("0", 10) == 0
        assert presenter._parse_int("-5", 10) == -5

    def test_parse_int_invalid(self) -> None:
        """Test parsing invalid integer returns default."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert presenter._parse_int("invalid", 10) == 10
        assert presenter._parse_int("", 10) == 10
        assert presenter._parse_int("12.34", 10) == 10

    def test_parse_float_valid(self) -> None:
        """Test parsing valid float."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert presenter._parse_float("3.14", 1.0) == 3.14
        assert presenter._parse_float("0.5", 1.0) == 0.5
        assert presenter._parse_float("-2.5", 1.0) == -2.5

    def test_parse_float_invalid(self) -> None:
        """Test parsing invalid float returns default."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        assert presenter._parse_float("invalid", 1.0) == 1.0
        assert presenter._parse_float("", 1.0) == 1.0
        assert presenter._parse_float("abc", 1.0) == 1.0


# =============================================================================
# SettingsPresenter Edge Cases Tests
# =============================================================================


class TestSettingsPresenterEdgeCases:
    """Test SettingsPresenter edge cases."""

    def test_parse_with_whitespace(self) -> None:
        """Test parsing values with whitespace."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        # _parse_int and _parse_float should handle whitespace
        result = presenter._parse_int(" 42 ", 10)
        assert result == 42

    def test_parse_negative_values(self) -> None:
        """Test parsing negative values."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        # Negative refresh interval should be validated
        assert presenter._parse_int("-10", 60) == -10

    def test_settings_property_immutability(self) -> None:
        """Test that settings property returns reference."""
        mock_screen = MockSettingsScreen()
        presenter = SettingsPresenter(mock_screen)

        # Should return the same object
        assert presenter.settings is presenter._settings


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestSettingsPresenterEdgeCases",
    "TestSettingsPresenterGetValue",
    "TestSettingsPresenterInitialization",
    "TestSettingsPresenterLoadSettings",
    "TestSettingsPresenterParse",
    "TestSettingsPresenterProperties",
    "TestSettingsPresenterValidation",
]
