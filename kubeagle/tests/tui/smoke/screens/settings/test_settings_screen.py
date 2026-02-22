"""Smoke tests for SettingsScreen - widget composition and keybindings.

This module tests:
- Screen class attributes and properties
- Widget composition verification
- Keybinding verification
- Settings input handling
- Theme changes
- Preference persistence

Note: Tests avoid app.run_test() due to Textual testing overhead.
Tests focus on class attributes and method existence verification.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from kubeagle.screens.settings import SettingsScreen

# =============================================================================
# Widget Composition Tests
# =============================================================================


class TestSettingsScreenWidgetComposition:
    """Test SettingsScreen widget composition."""

    def test_screen_has_correct_bindings(self) -> None:
        """Test that SettingsScreen has correct bindings."""
        assert hasattr(SettingsScreen, 'BINDINGS')
        assert len(SettingsScreen.BINDINGS) > 0

    def test_screen_has_css_path(self) -> None:
        """Test that SettingsScreen has CSS_PATH."""
        assert hasattr(SettingsScreen, 'CSS_PATH')
        assert "settings" in SettingsScreen.CSS_PATH.lower()

    def test_screen_has_all_setting_inputs(self) -> None:
        """Test that SettingsScreen has compose method."""
        assert hasattr(SettingsScreen, 'compose')

    def test_screen_has_on_mount(self) -> None:
        """Test that SettingsScreen has on_mount method."""
        assert hasattr(SettingsScreen, 'on_mount')

    def test_screen_compose_includes_optimizer_analysis_inputs(self) -> None:
        """Settings compose should include optimizer analysis controls."""
        source = inspect.getsource(SettingsScreen.compose)
        assert "id=\"optimizer-analysis-source-input\"" in source
        assert "id=\"helm-template-timeout-input\"" in source
        assert "id=\"ai-fix-llm-provider-select\"" in source
        assert "id=\"ai-fix-codex-model-select\"" in source
        assert "id=\"ai-fix-claude-model-select\"" in source
        assert "id=\"ai-fix-full-fix-prompt-input\"" in source

    def test_optimizer_controls_render_inside_general_section(self) -> None:
        """Optimizer controls should remain in General Settings pane."""
        source = inspect.getsource(SettingsScreen.compose)
        general_section_marker = "id=\"general-settings-section\""
        marker_index = source.index(general_section_marker)
        for control_id in (
            "optimizer-analysis-source-input",
            "helm-template-timeout-input",
        ):
            assert source.index(f"id=\"{control_id}\"") < marker_index

    def test_ai_fix_controls_render_inside_threshold_settings_wrapper(self) -> None:
        """AI fix controls should render in Threshold Settings wrapper."""
        source = inspect.getsource(SettingsScreen.compose)
        threshold_marker = "id=\"threshold-settings-section\""
        threshold_index = source.index(threshold_marker)

        for control_id in (
            "ai-fix-llm-provider-select",
            "ai-fix-codex-model-select",
            "ai-fix-claude-model-select",
            "ai-fix-full-fix-prompt-input",
        ):
            assert source.index(f"id=\"{control_id}\"") < threshold_index

    def test_ai_fix_prompt_is_editor_style(self) -> None:
        """AI fix prompt should enable line numbers for editor-like editing."""
        source = inspect.getsource(SettingsScreen.compose)
        assert "id=\"ai-fix-full-fix-prompt-input\"" in source
        assert "show_line_numbers=True" in source

    def test_general_settings_pane_is_vertically_scrollable(self) -> None:
        """General settings pane should allow vertical scrolling."""
        css_path = Path("kubeagle/css/screens/settings_screen.tcss")
        css = css_path.read_text(encoding="utf-8")
        general_block = css.split("#general-settings-section {", 1)[1].split("}", 1)[0]
        assert "overflow-y: auto;" in general_block


# =============================================================================
# SettingsScreen Keybinding Tests
# =============================================================================


class TestSettingsScreenKeybindings:
    """Test SettingsScreen-specific keybindings."""

    def test_has_pop_screen_binding(self) -> None:
        """Test that escape binding exists."""
        bindings = SettingsScreen.BINDINGS
        escape_bindings = [b for b in bindings if b[0] == "escape"]
        assert len(escape_bindings) > 0

    def test_has_save_binding(self) -> None:
        """Test that Ctrl+S save binding exists."""
        bindings = SettingsScreen.BINDINGS
        save_bindings = [b for b in bindings if "ctrl+s" in b[0].lower()]
        assert len(save_bindings) > 0

    def test_has_reset_defaults_binding(self) -> None:
        """Test that Ctrl+R reset defaults binding exists."""
        bindings = SettingsScreen.BINDINGS
        reset_bindings = [b for b in bindings if "ctrl+r" in b[0].lower()]
        assert len(reset_bindings) > 0

    def test_has_refresh_binding(self) -> None:
        """Test that 'r' refresh binding exists."""
        bindings = SettingsScreen.BINDINGS
        refresh_bindings = [b for b in bindings if b[0] == "r"]
        assert len(refresh_bindings) > 0

    def test_has_help_binding(self) -> None:
        """Test that '?' help binding exists."""
        bindings = SettingsScreen.BINDINGS
        help_bindings = [b for b in bindings if b[0] == "?"]
        assert len(help_bindings) > 0

    def test_has_navigation_bindings(self) -> None:
        """Test that navigation bindings exist."""
        bindings = SettingsScreen.BINDINGS
        nav_keys = ["h", "c", "C", "e"]
        nav_bindings = [b for b in bindings if b[0] in nav_keys]
        assert len(nav_bindings) > 0


# =============================================================================
# Settings Management Tests
# =============================================================================


class TestSettingsScreenSettingsManagement:
    """Test SettingsScreen settings management functionality."""

    def test_screen_has_get_input_value_method(self) -> None:
        """Test that _get_input_value method exists in class."""
        assert hasattr(SettingsScreen, '_get_input_value')

    def test_screen_has_get_int_value_method(self) -> None:
        """Test that _get_int_value method exists in class."""
        assert hasattr(SettingsScreen, '_get_int_value')

    def test_screen_has_get_float_value_method(self) -> None:
        """Test that _get_float_value method exists in class."""
        assert hasattr(SettingsScreen, '_get_float_value')

    def test_screen_has_save_settings_method(self) -> None:
        """Test that _save_settings method exists in class."""
        assert hasattr(SettingsScreen, '_save_settings')

    def test_screen_has_cancel_method(self) -> None:
        """Test that _cancel method exists in class."""
        assert hasattr(SettingsScreen, '_cancel')


# =============================================================================
# Status and Loading Tests
# =============================================================================


class TestSettingsScreenStatusAndLoading:
    """Test SettingsScreen status and loading indicators."""

    def test_screen_has_update_status_method(self) -> None:
        """Test that _update_status method exists in class."""
        assert hasattr(SettingsScreen, '_update_status')

    def test_screen_has_clear_status_method(self) -> None:
        """Test that _clear_status method exists in class."""
        assert hasattr(SettingsScreen, '_clear_status')

    def test_screen_has_show_loading_method(self) -> None:
        """Test that _show_loading method exists in class."""
        assert hasattr(SettingsScreen, '_show_loading')


# =============================================================================
# Button Handler Tests
# =============================================================================


class TestSettingsScreenButtonHandlers:
    """Test SettingsScreen button event handlers."""

    def test_screen_has_on_button_pressed_handler(self) -> None:
        """Test that on_button_pressed method exists in class."""
        assert hasattr(SettingsScreen, 'on_button_pressed')

    def test_screen_has_save_settings_action(self) -> None:
        """Test that action_save_settings method exists in class."""
        assert hasattr(SettingsScreen, 'action_save_settings')

    def test_screen_has_cancel_action(self) -> None:
        """Test that action_cancel method exists in class."""
        assert hasattr(SettingsScreen, 'action_cancel')


# =============================================================================
# Navigation Methods Tests
# =============================================================================


class TestSettingsScreenNavigation:
    """Test SettingsScreen navigation methods."""

    def test_screen_has_nav_home_method(self) -> None:
        """Test that nav_home method exists in class."""
        assert hasattr(SettingsScreen, 'action_nav_home')

    def test_screen_has_nav_cluster_method(self) -> None:
        """Test that nav_cluster method exists in class."""
        assert hasattr(SettingsScreen, 'action_nav_cluster')

    def test_screen_has_nav_charts_method(self) -> None:
        """Test that nav_charts method exists in class."""
        assert hasattr(SettingsScreen, 'action_nav_charts')

    def test_screen_has_nav_optimizer_method(self) -> None:
        """Test that nav_optimizer method exists in class."""
        assert hasattr(SettingsScreen, 'action_nav_optimizer')

    def test_screen_has_nav_export_method(self) -> None:
        """Test that nav_export method exists in class."""
        assert hasattr(SettingsScreen, 'action_nav_export')

    def test_screen_has_nav_settings_method(self) -> None:
        """Test that nav_settings method exists in class."""
        assert hasattr(SettingsScreen, 'action_nav_settings')


# =============================================================================
# Help and Refresh Tests
# =============================================================================


class TestSettingsScreenHelpAndRefresh:
    """Test SettingsScreen help and refresh functionality."""

    def test_screen_has_show_help_method(self) -> None:
        """Test that show_help method exists in class."""
        assert hasattr(SettingsScreen, 'action_show_help')

    def test_screen_has_refresh_method(self) -> None:
        """Test that refresh method exists in class."""
        assert hasattr(SettingsScreen, 'action_refresh')


# =============================================================================
# Screen Properties Tests
# =============================================================================


class TestSettingsScreenProperties:
    """Test SettingsScreen property accessors."""

    def test_screen_class_attributes(self) -> None:
        """Test that SettingsScreen has correct class attributes."""
        assert hasattr(SettingsScreen, 'BINDINGS')
        assert len(SettingsScreen.BINDINGS) > 0

    def test_screen_has_css_path(self) -> None:
        """Test that SettingsScreen has CSS_PATH."""
        assert hasattr(SettingsScreen, 'CSS_PATH')


# =============================================================================
# Save and Cancel Tests
# =============================================================================


class TestSettingsScreenSaveCancel:
    """Test SettingsScreen save and cancel functionality."""

    def test_has_save_settings_method(self) -> None:
        """Test that _save_settings method exists."""
        assert hasattr(SettingsScreen, '_save_settings')

    def test_has_cancel_method(self) -> None:
        """Test that _cancel method exists."""
        assert hasattr(SettingsScreen, '_cancel')


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestSettingsScreenButtonHandlers",
    "TestSettingsScreenHelpAndRefresh",
    "TestSettingsScreenKeybindings",
    "TestSettingsScreenNavigation",
    "TestSettingsScreenProperties",
    "TestSettingsScreenSaveCancel",
    "TestSettingsScreenSettingsManagement",
    "TestSettingsScreenStatusAndLoading",
    "TestSettingsScreenWidgetComposition",
]
