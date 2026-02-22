"""Smoke tests for ReportExportScreen - widget composition and keybindings.

This module tests:
- Screen class attributes and properties
- Widget composition verification
- Keybinding verification
- Loading state management
- Export format selection and execution

Note: Tests using app.run_test() are kept minimal due to Textual testing overhead.
"""

from __future__ import annotations

from kubeagle.screens.reports import ReportExportScreen

# =============================================================================
# Widget Composition Tests
# =============================================================================


class TestReportExportScreenWidgetComposition:
    """Test ReportExportScreen widget composition."""

    def test_screen_has_correct_bindings(self) -> None:
        """Test that ReportExportScreen has correct bindings."""
        assert hasattr(ReportExportScreen, 'BINDINGS')
        assert len(ReportExportScreen.BINDINGS) > 0

    def test_screen_has_css_path(self) -> None:
        """Test that ReportExportScreen has CSS_PATH."""
        assert hasattr(ReportExportScreen, 'CSS_PATH')
        assert "report_export" in ReportExportScreen.CSS_PATH.lower()

    def test_screen_can_be_instantiated(self) -> None:
        """Test that ReportExportScreen can be created."""
        screen = ReportExportScreen()
        assert screen is not None


# =============================================================================
# ReportExportScreen Keybinding Tests
# =============================================================================


class TestReportExportScreenKeybindings:
    """Test ReportExportScreen-specific keybindings."""

    def test_has_pop_screen_binding(self) -> None:
        """Test that escape binding exists."""
        bindings = ReportExportScreen.BINDINGS
        escape_bindings = [b for b in bindings if b[0] == "escape"]
        assert len(escape_bindings) > 0

    def test_has_refresh_binding(self) -> None:
        """Test that 'r' refresh binding exists."""
        bindings = ReportExportScreen.BINDINGS
        refresh_bindings = [b for b in bindings if b[0] == "r"]
        assert len(refresh_bindings) > 0

    def test_has_export_report_binding(self) -> None:
        """Test that ctrl+e export report binding exists."""
        bindings = ReportExportScreen.BINDINGS
        export_bindings = [b for b in bindings if b[0] == "ctrl+e"]
        assert len(export_bindings) > 0

    def test_has_copy_clipboard_binding(self) -> None:
        """Test that 'y' copy clipboard binding exists."""
        bindings = ReportExportScreen.BINDINGS
        copy_bindings = [b for b in bindings if b[0] == "y"]
        assert len(copy_bindings) > 0

    def test_has_help_binding(self) -> None:
        """Test that '?' help binding exists."""
        bindings = ReportExportScreen.BINDINGS
        help_bindings = [b for b in bindings if b[0] == "?"]
        assert len(help_bindings) > 0

    def test_has_home_binding(self) -> None:
        """Test that 'h' home binding exists."""
        bindings = ReportExportScreen.BINDINGS
        home_bindings = [b for b in bindings if b[0] == "h"]
        assert len(home_bindings) > 0

    def test_has_cluster_binding(self) -> None:
        """Test that 'c' cluster binding exists."""
        bindings = ReportExportScreen.BINDINGS
        cluster_bindings = [b for b in bindings if b[0] == "c"]
        assert len(cluster_bindings) > 0

    def test_has_charts_binding(self) -> None:
        """Test that 'C' charts binding exists."""
        bindings = ReportExportScreen.BINDINGS
        charts_bindings = [b for b in bindings if b[0] == "C"]
        assert len(charts_bindings) > 0

    def test_has_no_optimizer_binding(self) -> None:
        """Test that 'o' optimizer binding does not exist."""
        bindings = ReportExportScreen.BINDINGS
        optimizer_bindings = [b for b in bindings if b[0] == "o"]
        assert len(optimizer_bindings) == 0

# =============================================================================
# Loading State Tests
# =============================================================================


class TestReportExportScreenLoadingStates:
    """Test ReportExportScreen loading state management."""

    def test_show_loading_overlay_method_exists(self) -> None:
        """Test that show_loading_overlay method exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'show_loading_overlay')
        assert callable(screen.show_loading_overlay)

    def test_hide_loading_overlay_method_exists(self) -> None:
        """Test that hide_loading_overlay method exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'hide_loading_overlay')
        assert callable(screen.hide_loading_overlay)

    def test_has_report_data_property(self) -> None:
        """Test that _report_data property exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, '_report_data')
        assert screen._report_data is None


# =============================================================================
# Message Handler Tests
# =============================================================================


class TestReportExportScreenMessageHandlers:
    """Test ReportExportScreen message handlers."""

    def test_has_data_loaded_handler(self) -> None:
        """Test that on_report_data_loaded handler exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'on_report_data_loaded')
        assert callable(screen.on_report_data_loaded)

    def test_has_data_load_failed_handler(self) -> None:
        """Test that on_report_data_load_failed handler exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'on_report_data_load_failed')
        assert callable(screen.on_report_data_load_failed)


# =============================================================================
# Format Selection Tests
# =============================================================================


class TestReportExportScreenFormatSelection:
    """Test ReportExportScreen format selection properties."""

    def test_has_report_format_property(self) -> None:
        """Test that report_format reactive property exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'report_format')
        assert screen.report_format == "full"

    def test_has_report_type_property(self) -> None:
        """Test that report_type reactive property exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'report_type')
        assert screen.report_type == "combined"

    def test_has_preview_content_property(self) -> None:
        """Test that preview_content reactive property exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'preview_content')
        assert screen.preview_content == ""

    def test_has_export_status_property(self) -> None:
        """Test that export_status reactive property exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'export_status')
        assert screen.export_status == ""


# =============================================================================
# Report Generation Tests
# =============================================================================


class TestReportExportScreenReportGeneration:
    """Test ReportExportScreen report generation methods."""

    def test_has_generate_report_method(self) -> None:
        """Test that generate_report method exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'generate_report')
        assert callable(screen.generate_report)

    def test_has_filter_report_data_method(self) -> None:
        """Test that _filter_report_data method exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, '_filter_report_data')
        assert callable(screen._filter_report_data)

    def test_has_generate_preview_method(self) -> None:
        """Test that _generate_preview method exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, '_generate_preview')
        assert callable(screen._generate_preview)


# =============================================================================
# Export Action Tests
# =============================================================================


class TestReportExportScreenExportActions:
    """Test ReportExportScreen export action methods."""

    def test_has_action_refresh(self) -> None:
        """Test that action_refresh method exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'action_refresh')
        assert callable(screen.action_refresh)

    def test_has_action_export_report(self) -> None:
        """Test that action_export_report method exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'action_export_report')
        assert callable(screen.action_export_report)

    def test_has_action_copy_clipboard(self) -> None:
        """Test that action_copy_clipboard method exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'action_copy_clipboard')
        assert callable(screen.action_copy_clipboard)


# =============================================================================
# Radio Button Handler Tests
# =============================================================================


# =============================================================================
# Input Handler Tests
# =============================================================================


class TestReportExportScreenInputHandlers:
    """Test ReportExportScreen input change handlers."""

    def test_has_custom_input_changed_handler(self) -> None:
        """Test that on_custom_input_changed handler exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'on_custom_input_changed')
        assert callable(screen.on_custom_input_changed)


# =============================================================================
# Button Handler Tests
# =============================================================================


class TestReportExportScreenButtonHandlers:
    """Test ReportExportScreen button press handlers."""

    def test_has_button_pressed_handler(self) -> None:
        """Test that on_button_pressed handler exists."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'on_button_pressed')
        assert callable(screen.on_button_pressed)


# =============================================================================
# Worker Mixin Tests
# =============================================================================


class TestReportExportScreenWorkerMixin:
    """Test ReportExportScreen worker mixin integration."""

    def test_inherits_worker_mixin(self) -> None:
        """Test that ReportExportScreen inherits from WorkerMixin."""
        screen = ReportExportScreen()
        assert hasattr(screen, 'start_worker')
        assert hasattr(screen, '_start_load_worker')


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestReportExportScreenButtonHandlers",
    "TestReportExportScreenExportActions",
    "TestReportExportScreenFormatSelection",
    "TestReportExportScreenInputHandlers",
    "TestReportExportScreenKeybindings",
    "TestReportExportScreenLoadingStates",
    "TestReportExportScreenMessageHandlers",
    "TestReportExportScreenReportGeneration",
    "TestReportExportScreenWidgetComposition",
    "TestReportExportScreenWorkerMixin",
]
