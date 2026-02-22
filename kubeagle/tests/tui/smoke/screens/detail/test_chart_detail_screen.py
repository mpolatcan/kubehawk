"""Smoke tests for ChartDetailScreen - widget composition and keybindings.

This module tests:
- Screen class attributes and properties
- Widget composition verification
- Keybinding verification
- Loading state management
- Error state handling

Note: Tests using app.run_test() are kept minimal due to Textual testing overhead.
"""

from __future__ import annotations

from kubeagle.constants.enums import QoSClass
from kubeagle.models.charts.chart_info import ChartInfo
from kubeagle.screens.detail import ChartDetailScreen


def create_sample_chart_info(name: str = "test-chart", team: str = "team-alpha") -> ChartInfo:
    """Create a sample ChartInfo with all required fields."""
    return ChartInfo(
        name=name,
        team=team,
        values_file="values.yaml",
        cpu_request=100,
        cpu_limit=200,
        memory_request=128,
        memory_limit=256,
        qos_class=QoSClass.BURSTABLE,
        has_liveness=True,
        has_readiness=True,
        has_startup=False,
        has_anti_affinity=True,
        has_topology_spread=False,
        has_topology=False,
        pdb_enabled=True,
        pdb_template_exists=True,
        pdb_min_available=1,
        pdb_max_unavailable=None,
        replicas=2,
        priority_class=None,
    )


# =============================================================================
# Widget Composition Tests
# =============================================================================


class TestChartDetailScreenWidgetComposition:
    """Test ChartDetailScreen widget composition."""

    def test_screen_has_correct_bindings(self) -> None:
        """Test that ChartDetailScreen has correct bindings."""
        assert hasattr(ChartDetailScreen, 'BINDINGS')
        assert len(ChartDetailScreen.BINDINGS) > 0

    def test_screen_has_css_path(self) -> None:
        """Test that ChartDetailScreen has CSS_PATH."""
        assert hasattr(ChartDetailScreen, 'CSS_PATH')
        assert "chart_detail" in ChartDetailScreen.CSS_PATH.lower()

    def test_screen_can_be_instantiated_with_chart(self) -> None:
        """Test that ChartDetailScreen can be created with ChartInfo."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert screen is not None
        assert screen.chart_name == "test-chart"

    def test_screen_has_screen_title_property(self) -> None:
        """Test that screen_title property returns correct title."""
        chart = create_sample_chart_info(name="my-chart", team="my-team")
        screen = ChartDetailScreen(chart)
        assert screen.screen_title == "my-chart"


# =============================================================================
# ChartDetailScreen Keybinding Tests
# =============================================================================


class TestChartDetailScreenKeybindings:
    """Test ChartDetailScreen-specific keybindings."""

    def test_has_pop_screen_binding(self) -> None:
        """Test that escape binding exists."""
        bindings = ChartDetailScreen.BINDINGS
        escape_bindings = [b for b in bindings if b[0] == "escape"]
        assert len(escape_bindings) > 0

    def test_has_refresh_binding(self) -> None:
        """Test that 'r' refresh binding exists."""
        bindings = ChartDetailScreen.BINDINGS
        refresh_bindings = [b for b in bindings if b[0] == "r"]
        assert len(refresh_bindings) > 0

    def test_has_help_binding(self) -> None:
        """Test that 'h' help binding exists."""
        bindings = ChartDetailScreen.BINDINGS
        help_bindings = [b for b in bindings if b[0] == "h"]
        assert len(help_bindings) > 0

    def test_binding_descriptions_exist(self) -> None:
        """Test that all bindings have descriptions."""
        for binding in ChartDetailScreen.BINDINGS:
            assert len(binding) == 3  # (key, action, description)


# =============================================================================
# Loading State Tests
# =============================================================================


class TestChartDetailScreenLoadingStates:
    """Test ChartDetailScreen loading state management."""

    def test_show_loading_overlay_method_exists(self) -> None:
        """Test that show_loading_overlay method exists."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, 'show_loading_overlay')
        assert callable(screen.show_loading_overlay)

    def test_hide_loading_overlay_method_exists(self) -> None:
        """Test that hide_loading_overlay method exists."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, 'hide_loading_overlay')
        assert callable(screen.hide_loading_overlay)

    def test_chart_data_property(self) -> None:
        """Test that chart_data property is set correctly."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert screen.chart_data is chart


# =============================================================================
# Message Handler Tests
# =============================================================================


class TestChartDetailScreenMessageHandlers:
    """Test ChartDetailScreen message handlers."""

    def test_has_data_loaded_handler(self) -> None:
        """Test that on_chart_detail_data_loaded handler exists."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, 'on_chart_detail_data_loaded')
        assert callable(screen.on_chart_detail_data_loaded)

    def test_has_data_load_failed_handler(self) -> None:
        """Test that on_chart_detail_data_load_failed handler exists."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, 'on_chart_detail_data_load_failed')
        assert callable(screen.on_chart_detail_data_load_failed)

    def test_has_load_data_method(self) -> None:
        """Test that load_data method exists."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, 'load_data')
        assert callable(screen.load_data)


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestChartDetailScreenErrorHandling:
    """Test ChartDetailScreen error handling methods."""

    def test_has_show_error_method(self) -> None:
        """Test that _show_error method exists."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, '_show_error')
        assert callable(screen._show_error)

    def test_update_resources_section_method_exists(self) -> None:
        """Test that _update_resources_section method exists."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, '_update_resources_section')
        assert callable(screen._update_resources_section)

    def test_update_probes_section_method_exists(self) -> None:
        """Test that _update_probes_section method exists."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, '_update_probes_section')
        assert callable(screen._update_probes_section)

    def test_update_availability_section_method_exists(self) -> None:
        """Test that _update_availability_section method exists."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, '_update_availability_section')
        assert callable(screen._update_availability_section)

    def test_update_configuration_section_method_exists(self) -> None:
        """Test that _update_configuration_section method exists."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, '_update_configuration_section')
        assert callable(screen._update_configuration_section)


# =============================================================================
# Action Methods Tests
# =============================================================================


class TestChartDetailScreenActionMethods:
    """Test ChartDetailScreen action methods."""

    def test_has_action_refresh(self) -> None:
        """Test that action_refresh method exists."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, 'action_refresh')
        assert callable(screen.action_refresh)

    def test_has_action_show_help(self) -> None:
        """Test that action_show_help method exists."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, 'action_show_help')
        assert callable(screen.action_show_help)


# =============================================================================
# Worker Mixin Tests
# =============================================================================


class TestChartDetailScreenWorkerMixin:
    """Test ChartDetailScreen worker mixin integration."""

    def test_inherits_worker_mixin(self) -> None:
        """Test that ChartDetailScreen inherits from WorkerMixin."""
        chart = create_sample_chart_info()
        screen = ChartDetailScreen(chart)
        assert hasattr(screen, 'start_worker')
        assert hasattr(screen, '_start_load_worker')


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestChartDetailScreenActionMethods",
    "TestChartDetailScreenErrorHandling",
    "TestChartDetailScreenKeybindings",
    "TestChartDetailScreenLoadingStates",
    "TestChartDetailScreenMessageHandlers",
    "TestChartDetailScreenWidgetComposition",
    "TestChartDetailScreenWorkerMixin",
]
