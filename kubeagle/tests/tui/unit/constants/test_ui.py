"""Unit tests for UI constants in constants/ui.py.

Tests cover:
- Re-exported theme names (DARK_THEME, LIGHT_THEME)
- Re-exported enums
- CATEGORIES and SEVERITIES lists
"""

from __future__ import annotations

from enum import Enum

from kubeagle.constants.ui import (
    CATEGORIES,
    DARK_THEME,
    LIGHT_THEME,
    SEVERITIES,
    AppState,
    FetchState,
    NodeStatus,
    QoSClass,
    Severity,
    ThemeMode,
)

# =============================================================================
# Re-exported enums
# =============================================================================


class TestUIReExportedEnums:
    """Test that UI module re-exports the expected enums."""

    def test_app_state_is_enum(self) -> None:
        assert issubclass(AppState, Enum)

    def test_fetch_state_is_enum(self) -> None:
        assert issubclass(FetchState, Enum)

    def test_node_status_is_enum(self) -> None:
        assert issubclass(NodeStatus, Enum)

    def test_qos_class_is_enum(self) -> None:
        assert issubclass(QoSClass, Enum)

    def test_severity_is_enum(self) -> None:
        assert issubclass(Severity, Enum)

    def test_theme_mode_is_enum(self) -> None:
        assert issubclass(ThemeMode, Enum)


# =============================================================================
# Theme names
# =============================================================================


class TestThemeNames:
    """Test registered app theme name constants."""

    def test_dark_theme_type(self) -> None:
        assert isinstance(DARK_THEME, str)

    def test_light_theme_type(self) -> None:
        assert isinstance(LIGHT_THEME, str)

    def test_dark_theme_value(self) -> None:
        assert DARK_THEME == "KubEagle-Dark"

    def test_light_theme_value(self) -> None:
        assert LIGHT_THEME == "KubEagle-Light"


# =============================================================================
# CATEGORIES and SEVERITIES
# =============================================================================


class TestCategoriesAndSeverities:
    """Test optimizer screen constant lists."""

    def test_categories_type(self) -> None:
        assert isinstance(CATEGORIES, list)

    def test_categories_non_empty(self) -> None:
        assert len(CATEGORIES) > 0

    def test_categories_values(self) -> None:
        assert CATEGORIES == ["resources", "probes", "availability", "security"]

    def test_categories_all_strings(self) -> None:
        for cat in CATEGORIES:
            assert isinstance(cat, str)

    def test_severities_type(self) -> None:
        assert isinstance(SEVERITIES, list)

    def test_severities_non_empty(self) -> None:
        assert len(SEVERITIES) > 0

    def test_severities_values(self) -> None:
        assert SEVERITIES == ["error", "warning", "info"]

    def test_severities_all_strings(self) -> None:
        for sev in SEVERITIES:
            assert isinstance(sev, str)


# =============================================================================
# __all__ exports
# =============================================================================


class TestUIExports:
    """Test that __all__ exports are correct."""

    def test_all_exports_importable(self) -> None:
        import kubeagle.constants.ui as mod

        for name in mod.__all__:
            assert hasattr(mod, name), f"{name} listed in __all__ but not defined"
