"""Smoke tests for ChartsExplorerScreen - widget composition, keybindings, and properties.

This module tests:
- Screen class attributes and properties
- Widget composition verification (all widget IDs present)
- Keybinding verification (all expected keys bound)
- Loading state management methods
- Reactive state defaults
- Action method existence
- View tab and sort select composition

Note: Tests using app.run_test() are kept minimal due to Textual testing overhead.
"""

from __future__ import annotations

from textual.widgets import Select

from kubeagle.constants.enums import QoSClass
from kubeagle.models.charts.chart_info import ChartInfo
from kubeagle.screens.charts_explorer import ChartsExplorerScreen
from kubeagle.screens.charts_explorer.charts_explorer_screen import (
    ChartsExplorerDataLoaded,
    ChartsExplorerDataLoadFailed,
)
from kubeagle.screens.charts_explorer.config import (
    EXPLORER_HEADER_TOOLTIPS,
    SortBy,
    ViewFilter,
)
from kubeagle.widgets import (
    CustomButton,
    CustomDataTable,
    CustomFooter,
    CustomHeader,
    CustomHorizontal,
    CustomInput,
    CustomKPI,
    CustomLoadingIndicator,
    CustomProgressBar,
    CustomStatic,
    CustomTabs,
    CustomVertical,
)

# =============================================================================
# Widget Composition Tests
# =============================================================================


class TestChartsExplorerScreenWidgetComposition:
    """Test ChartsExplorerScreen widget composition."""

    def test_screen_has_correct_bindings(self) -> None:
        """Test that ChartsExplorerScreen has correct bindings."""
        assert hasattr(ChartsExplorerScreen, "BINDINGS")
        assert len(ChartsExplorerScreen.BINDINGS) > 0

    def test_screen_has_css_path(self) -> None:
        """Test that ChartsExplorerScreen has CSS_PATH."""
        assert hasattr(ChartsExplorerScreen, "CSS_PATH")
        css_path = ChartsExplorerScreen.CSS_PATH
        if isinstance(css_path, list):
            assert any("charts_explorer" in str(item).lower() for item in css_path)
        else:
            assert "charts_explorer" in str(css_path).lower()

    def test_screen_can_be_instantiated(self) -> None:
        """Test that ChartsExplorerScreen can be created."""
        screen = ChartsExplorerScreen(testing=True)
        assert screen is not None
        assert screen._testing is True

    def test_screen_can_be_instantiated_with_initial_view(self) -> None:
        """Test that ChartsExplorerScreen can be created with initial_view."""
        screen = ChartsExplorerScreen(
            initial_view=ViewFilter.NO_PDB, testing=True,
        )
        assert screen is not None
        assert screen._initial_view == ViewFilter.NO_PDB

    def test_screen_title_property(self) -> None:
        """Test screen_title returns correct value."""
        screen = ChartsExplorerScreen(testing=True)
        assert screen.screen_title == "Charts Explorer"

    def test_charts_property_initially_empty(self) -> None:
        """Test charts list starts empty."""
        screen = ChartsExplorerScreen(testing=True)
        assert screen.charts == []

    def test_filtered_charts_property_initially_empty(self) -> None:
        """Test filtered_charts list starts empty."""
        screen = ChartsExplorerScreen(testing=True)
        assert screen.filtered_charts == []

    @staticmethod
    def _flatten(widgets: list) -> list:
        """Flatten widget tree by traversing _pending_children on containers."""
        result = []
        for w in widgets:
            result.append(w)
            pending = getattr(w, "_pending_children", [])
            if pending:
                result.extend(
                    TestChartsExplorerScreenWidgetComposition._flatten(list(pending))
                )
        return result

    def test_compose_yields_header(self) -> None:
        """Test compose yields CustomHeader."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        headers = [w for w in all_widgets if isinstance(w, CustomHeader)]
        assert len(headers) == 1

    def test_compose_yields_footer(self) -> None:
        """Test compose yields CustomFooter."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        footers = [w for w in all_widgets if isinstance(w, CustomFooter)]
        assert len(footers) == 1

    def test_compose_yields_explorer_table(self) -> None:
        """Test compose yields CustomDataTable with id='explorer-table'."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        tables = [
            w for w in all_widgets
            if isinstance(w, CustomDataTable) and w.id == "explorer-table"
        ]
        assert len(tables) == 1

    def test_compose_yields_search_input(self) -> None:
        """Test compose yields CustomInput with id='search-input'."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        inputs = [
            w for w in all_widgets
            if isinstance(w, CustomInput) and w.id == "charts-search-input"
        ]
        assert len(inputs) == 1

    def test_compose_yields_summary_bar(self) -> None:
        """Test compose yields CustomHorizontal with id='summary-bar'."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        bars = [
            w for w in all_widgets
            if isinstance(w, CustomHorizontal) and w.id == "charts-summary-bar"
        ]
        assert len(bars) == 1

    def test_summary_bar_is_below_explorer_table(self) -> None:
        """Test summary bar is composed below the explorer table in the panel."""
        screen = ChartsExplorerScreen(testing=True)
        all_widgets = self._flatten(list(screen.compose()))
        explorer_table_index = next(
            i for i, widget in enumerate(all_widgets)
            if isinstance(widget, CustomDataTable) and widget.id == "explorer-table"
        )
        summary_index = next(
            i for i, widget in enumerate(all_widgets)
            if isinstance(widget, CustomHorizontal) and widget.id == "charts-summary-bar"
        )
        assert summary_index > explorer_table_index

    def test_compose_yields_split_main_content(self) -> None:
        """Test compose yields CustomHorizontal with id='charts-main-content'."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        containers = [
            w for w in all_widgets
            if isinstance(w, CustomHorizontal) and w.id == "charts-main-content"
        ]
        assert len(containers) == 1

    def test_compose_does_not_yield_chart_detail_panel(self) -> None:
        """Chart details should be shown in a modal, not inline panel."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        assert not any(widget.id == "chart-detail-panel" for widget in all_widgets)

    def test_compose_does_not_yield_chart_detail_body(self) -> None:
        """Chart details should be shown in a modal, not inline markdown body."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        assert not any(widget.id == "chart-detail-body" for widget in all_widgets)

    def test_compose_yields_summary_kpis(self) -> None:
        """Test compose yields optimizer-style summary KPI widgets."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        kpis = [
            w for w in all_widgets
            if isinstance(w, CustomKPI)
            and w.id in {
                "kpi-total",
                "kpi-extreme",
                "kpi-single",
                "kpi-no-pdb",
            }
        ]
        assert len(kpis) == 4

    def test_compose_yields_loading_overlay(self) -> None:
        """Test compose yields CustomVertical with id='loading-overlay'."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        overlays = [
            w for w in all_widgets
            if isinstance(w, CustomVertical) and w.id == "loading-overlay"
        ]
        assert len(overlays) == 1

    def test_compose_yields_loading_indicator(self) -> None:
        """Test compose yields CustomLoadingIndicator with id='loading-indicator'."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        indicators = [
            w for w in all_widgets
            if isinstance(w, CustomLoadingIndicator) and w.id == "loading-indicator"
        ]
        assert len(indicators) == 1

    def test_compose_yields_retry_button(self) -> None:
        """Test compose yields CustomButton with id='retry-btn'."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        buttons = [
            w for w in all_widgets
            if isinstance(w, CustomButton) and w.id == "charts-retry-btn"
        ]
        assert len(buttons) == 1

    def test_configure_explorer_table_header_tooltips_uses_config_mapping(self) -> None:
        """Charts screen should apply configured header tooltip mapping."""
        from unittest.mock import MagicMock

        screen = ChartsExplorerScreen(testing=True)
        table = MagicMock(spec=CustomDataTable)

        screen._configure_explorer_table_header_tooltips(table)

        table.set_header_tooltips.assert_called_once_with(EXPLORER_HEADER_TOOLTIPS)
        table.set_default_tooltip.assert_called_once_with(
            "Double-click a row to open chart details",
        )


# =============================================================================
# View Controls Composition Tests
# =============================================================================


class TestChartsExplorerScreenViewControls:
    """Test ChartsExplorerScreen view/sort control composition."""

    @staticmethod
    def _flatten(widgets: list) -> list:
        """Flatten widget tree by traversing _pending_children on containers."""
        result = []
        for w in widgets:
            result.append(w)
            pending = getattr(w, "_pending_children", [])
            if pending:
                result.extend(
                    TestChartsExplorerScreenViewControls._flatten(list(pending))
                )
        return result

    def test_compose_yields_view_tabs(self) -> None:
        """Test compose yields CustomTabs with id='charts-view-tabs'."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        tabs = [
            w for w in all_widgets
            if isinstance(w, CustomTabs) and w.id == "charts-view-tabs"
        ]
        assert len(tabs) == 1

    def test_compose_yields_sort_select(self) -> None:
        """Test compose yields Select with id='sort-select'."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        selects = [
            w for w in all_widgets
            if isinstance(w, Select) and w.id == "charts-sort-select"
        ]
        assert len(selects) == 1

    def test_compose_yields_sort_selects_total(self) -> None:
        """Test compose yields at least one Select widget for sort controls."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        selects = [w for w in all_widgets if isinstance(w, Select)]
        assert len(selects) >= 1

    def test_filter_row_exists(self) -> None:
        """Test compose yields top filter row container."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        bars = [
            w for w in all_widgets
            if isinstance(w, CustomHorizontal) and w.id == "charts-filter-row"
        ]
        assert len(bars) == 1

    def test_top_controls_row_exists(self) -> None:
        """Test compose yields top controls row under main tabs."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        rows = [
            w for w in all_widgets
            if isinstance(w, CustomHorizontal) and w.id == "charts-top-controls-row"
        ]
        assert len(rows) == 1

    def test_compose_places_view_tabs_above_table_title(self) -> None:
        """Test view tabs are composed above the table title."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        tabs_index = next(
            index
            for index, widget in enumerate(all_widgets)
            if isinstance(widget, CustomTabs) and widget.id == "charts-view-tabs"
        )
        table_title_index = next(
            index
            for index, widget in enumerate(all_widgets)
            if isinstance(widget, CustomStatic) and widget.id == "explorer-table-title"
        )
        assert tabs_index < table_title_index


# =============================================================================
# Button Composition Tests
# =============================================================================


class TestChartsExplorerScreenButtons:
    """Test ChartsExplorerScreen button composition."""

    @staticmethod
    def _flatten(widgets: list) -> list:
        """Flatten widget tree by traversing _pending_children on containers."""
        result = []
        for w in widgets:
            result.append(w)
            pending = getattr(w, "_pending_children", [])
            if pending:
                result.extend(
                    TestChartsExplorerScreenButtons._flatten(list(pending))
                )
        return result

    def test_compose_yields_filter_button(self) -> None:
        """Test compose yields CustomButton with id='filter-btn'."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        buttons = [
            w for w in all_widgets
            if isinstance(w, CustomButton) and w.id == "charts-filter-btn"
        ]
        assert len(buttons) == 1

    def test_compose_yields_search_button(self) -> None:
        """Test compose yields CustomButton with id='search-btn'."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        buttons = [
            w for w in all_widgets
            if isinstance(w, CustomButton) and w.id == "charts-search-btn"
        ]
        assert len(buttons) == 1

    def test_compose_yields_clear_button(self) -> None:
        """Test compose yields CustomButton with id='clear-btn'."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        buttons = [
            w for w in all_widgets
            if isinstance(w, CustomButton) and w.id == "charts-clear-btn"
        ]
        assert len(buttons) == 1

    def test_compose_yields_mode_button(self) -> None:
        """Mode button is rendered in the top controls row."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        buttons = [
            w for w in all_widgets
            if isinstance(w, CustomButton) and w.id == "charts-mode-btn"
        ]
        assert len(buttons) == 1

    def test_compose_yields_refresh_button(self) -> None:
        """Refresh button is rendered next to the mode toggle in top controls."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        buttons = [
            w for w in all_widgets
            if isinstance(w, CustomButton) and w.id == "charts-refresh-btn"
        ]
        assert len(buttons) == 1

    def test_compose_yields_top_progress_bar(self) -> None:
        """Top controls row contains charts loading progress bar."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        bars = [
            w for w in all_widgets
            if isinstance(w, CustomProgressBar) and w.id == "charts-progress-bar"
        ]
        assert len(bars) == 1

    def test_compose_yields_top_progress_text(self) -> None:
        """Top controls row contains charts loading status text."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        labels = [
            w for w in all_widgets
            if isinstance(w, CustomStatic) and w.id == "charts-loading-text"
        ]
        assert len(labels) == 1

    def test_compose_does_not_yield_active_button(self) -> None:
        """Active button is moved into the combined filter dialog."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        buttons = [
            w for w in all_widgets
            if isinstance(w, CustomButton) and w.id == "charts-active-btn"
        ]
        assert len(buttons) == 0

    def test_compose_does_not_yield_team_filter_button(self) -> None:
        """Team filter button is moved into the combined filter dialog."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        buttons = [
            w for w in all_widgets
            if isinstance(w, CustomButton) and w.id == "charts-team-filter-btn"
        ]
        assert len(buttons) == 0

    def test_compose_does_not_yield_column_filter_button(self) -> None:
        """Columns filter button is moved into the combined filter dialog."""
        screen = ChartsExplorerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        buttons = [
            w for w in all_widgets
            if isinstance(w, CustomButton) and w.id == "charts-column-filter-btn"
        ]
        assert len(buttons) == 0


# =============================================================================
# Keybinding Tests
# =============================================================================


class TestChartsExplorerScreenKeybindings:
    """Test ChartsExplorerScreen-specific keybindings."""

    def test_has_escape_binding(self) -> None:
        """Test that escape binding exists."""
        bindings = ChartsExplorerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "escape"]
        assert len(matches) > 0

    def test_has_refresh_binding(self) -> None:
        """Test that 'r' refresh binding exists."""
        bindings = ChartsExplorerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "r"]
        assert len(matches) > 0

    def test_has_search_binding(self) -> None:
        """Test that slash search binding exists."""
        bindings = ChartsExplorerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "slash"]
        assert len(matches) > 0

    def test_has_enter_binding(self) -> None:
        """Test that enter binding exists."""
        bindings = ChartsExplorerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "enter"]
        assert len(matches) > 0

    def test_has_mode_binding(self) -> None:
        """Test that 'm' mode binding exists."""
        bindings = ChartsExplorerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "m"]
        assert len(matches) > 0

    def test_has_active_binding(self) -> None:
        """Test that 'a' active binding exists."""
        bindings = ChartsExplorerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "a"]
        assert len(matches) > 0

    def test_has_view_bindings_1_through_5(self) -> None:
        """Test that view filter bindings 1-5 exist."""
        bindings = ChartsExplorerScreen.BINDINGS
        for key in ["1", "2", "3", "4", "5"]:
            matches = [b for b in bindings if b[0] == key]
            assert len(matches) > 0, f"Missing binding for key '{key}'"

    def test_has_sort_direction_binding(self) -> None:
        """Test that 's' sort-direction binding exists."""
        bindings = ChartsExplorerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "s"]
        assert len(matches) > 0

    def test_has_team_binding(self) -> None:
        """Test that 't' team binding exists."""
        bindings = ChartsExplorerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "t"]
        assert len(matches) > 0

    def test_has_violations_binding(self) -> None:
        """Test that 'v' violations binding exists."""
        bindings = ChartsExplorerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "v"]
        assert len(matches) > 0

    def test_has_export_binding(self) -> None:
        """Test that 'x' export binding exists."""
        bindings = ChartsExplorerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "x"]
        assert len(matches) > 0

    def test_has_home_binding(self) -> None:
        """Test that 'h' home binding exists."""
        bindings = ChartsExplorerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "h"]
        assert len(matches) > 0

    def test_has_help_binding(self) -> None:
        """Test that '?' help binding exists."""
        bindings = ChartsExplorerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "?"]
        assert len(matches) > 0


# =============================================================================
# Reactive State Tests
# =============================================================================


class TestChartsExplorerScreenReactiveState:
    """Test ChartsExplorerScreen reactive state defaults."""

    def test_use_cluster_mode_defaults_false(self) -> None:
        """Test use_cluster_mode defaults to False."""
        screen = ChartsExplorerScreen(testing=True)
        assert screen.use_cluster_mode is False

    def test_show_active_only_defaults_false(self) -> None:
        """Test show_active_only defaults to False."""
        screen = ChartsExplorerScreen(testing=True)
        assert screen.show_active_only is False

    def test_current_view_defaults_all(self) -> None:
        """Test current_view defaults to ViewFilter.ALL."""
        screen = ChartsExplorerScreen(testing=True)
        assert screen.current_view == ViewFilter.ALL

    def test_current_sort_defaults_chart(self) -> None:
        """Test current_sort defaults to SortBy.CHART."""
        screen = ChartsExplorerScreen(testing=True)
        assert screen.current_sort == SortBy.CHART

    def test_sort_desc_defaults_false(self) -> None:
        """Test sort_desc defaults to False."""
        screen = ChartsExplorerScreen(testing=True)
        assert screen.sort_desc is False

    def test_current_team_defaults_none(self) -> None:
        """Test current_team defaults to None."""
        screen = ChartsExplorerScreen(testing=True)
        assert screen.current_team is None


# =============================================================================
# Loading State Tests
# =============================================================================


class TestChartsExplorerScreenLoadingStates:
    """Test ChartsExplorerScreen loading state management."""

    def test_show_loading_overlay_method_exists(self) -> None:
        """Test that show_loading_overlay method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "show_loading_overlay")
        assert callable(screen.show_loading_overlay)

    def test_hide_loading_overlay_method_exists(self) -> None:
        """Test that hide_loading_overlay method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "hide_loading_overlay")
        assert callable(screen.hide_loading_overlay)

    def test_show_error_state_method_exists(self) -> None:
        """Test that show_error_state method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "show_error_state")
        assert callable(screen.show_error_state)

    def test_load_data_method_exists(self) -> None:
        """Test that load_data method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "load_data")
        assert callable(screen.load_data)


# =============================================================================
# Action Method Tests
# =============================================================================


class TestChartsExplorerScreenActionMethods:
    """Test ChartsExplorerScreen action methods exist."""

    def test_has_action_select_chart(self) -> None:
        """Test that action_select_chart method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_select_chart")
        assert callable(screen.action_select_chart)

    def test_has_action_toggle_mode(self) -> None:
        """Test that action_toggle_mode method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_toggle_mode")
        assert callable(screen.action_toggle_mode)

    def test_has_action_toggle_active_filter(self) -> None:
        """Test that action_toggle_active_filter method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_toggle_active_filter")
        assert callable(screen.action_toggle_active_filter)

    def test_has_action_refresh(self) -> None:
        """Test that action_refresh method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_refresh")
        assert callable(screen.action_refresh)

    def test_has_action_focus_search(self) -> None:
        """Test that action_focus_search method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_focus_search")
        assert callable(screen.action_focus_search)

    def test_has_action_view_all(self) -> None:
        """Test that action_view_all method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_view_all")
        assert callable(screen.action_view_all)

    def test_has_action_view_extreme(self) -> None:
        """Test that action_view_extreme method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_view_extreme")
        assert callable(screen.action_view_extreme)

    def test_has_action_view_single_replica(self) -> None:
        """Test that action_view_single_replica method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_view_single_replica")
        assert callable(screen.action_view_single_replica)

    def test_has_action_view_no_pdb(self) -> None:
        """Test that action_view_no_pdb method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_view_no_pdb")
        assert callable(screen.action_view_no_pdb)

    def test_has_action_view_violations(self) -> None:
        """Test that action_view_violations method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_view_violations")
        assert callable(screen.action_view_violations)

    def test_has_action_toggle_sort_direction(self) -> None:
        """Test that action_toggle_sort_direction method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_toggle_sort_direction")
        assert callable(screen.action_toggle_sort_direction)

    def test_has_action_cycle_team(self) -> None:
        """Test that action_cycle_team method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_cycle_team")
        assert callable(screen.action_cycle_team)

    def test_has_action_view_team_violations(self) -> None:
        """Test that action_view_team_violations method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_view_team_violations")
        assert callable(screen.action_view_team_violations)

    def test_has_action_export_team_report(self) -> None:
        """Test that action_export_team_report method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_export_team_report")
        assert callable(screen.action_export_team_report)

    def test_has_action_show_help(self) -> None:
        """Test that action_show_help method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "action_show_help")
        assert callable(screen.action_show_help)


# =============================================================================
# Internal Methods Tests
# =============================================================================


class TestChartsExplorerScreenInternalMethods:
    """Test ChartsExplorerScreen internal methods exist."""

    def test_has_apply_filters_and_populate(self) -> None:
        """Test that _apply_filters_and_populate method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "_apply_filters_and_populate")
        assert callable(screen._apply_filters_and_populate)

    def test_has_populate_table(self) -> None:
        """Test that _populate_table method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "_populate_table")
        assert callable(screen._populate_table)

    def test_row_chart_map_follows_sorted_order(self) -> None:
        """Row mapping should follow sorted chart order via dict(enumerate)."""
        screen = ChartsExplorerScreen(testing=True)
        dynamodb_admin = ChartInfo(
            name="dynamodb-admin",
            team="Platform",
            values_file="/tmp/platform-values.yaml",
            cpu_request=100,
            cpu_limit=200,
            memory_request=128,
            memory_limit=256,
            qos_class=QoSClass.BURSTABLE,
            has_liveness=True,
            has_readiness=True,
            has_startup=True,
            has_anti_affinity=False,
            has_topology_spread=False,
            has_topology=False,
            pdb_enabled=False,
            pdb_template_exists=False,
            pdb_min_available=None,
            pdb_max_unavailable=None,
            replicas=1,
            priority_class=None,
        )
        architect = ChartInfo(
            name="architect",
            team="Platform",
            values_file="/tmp/architect-values.yaml",
            cpu_request=100,
            cpu_limit=200,
            memory_request=128,
            memory_limit=256,
            qos_class=QoSClass.BURSTABLE,
            has_liveness=True,
            has_readiness=True,
            has_startup=True,
            has_anti_affinity=False,
            has_topology_spread=False,
            has_topology=False,
            pdb_enabled=False,
            pdb_template_exists=False,
            pdb_min_available=None,
            pdb_max_unavailable=None,
            replicas=1,
            priority_class=None,
        )

        # Sort unsorted list and build row map via dict(enumerate).
        unsorted = [dynamodb_admin, architect]
        sorted_charts = screen._presenter.sort_charts(
            unsorted, sort_by=SortBy.CHART, descending=False
        )
        row_chart_map = dict(enumerate(sorted_charts))

        assert row_chart_map[0].name == "architect"
        assert row_chart_map[1].name == "dynamodb-admin"

    def test_has_clear_all_filters(self) -> None:
        """Test that _clear_all_filters method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "_clear_all_filters")
        assert callable(screen._clear_all_filters)

    def test_has_update_sort_direction_button(self) -> None:
        """Test that _update_sort_direction_button method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "_update_sort_direction_button")
        assert callable(screen._update_sort_direction_button)

    def test_has_update_summary(self) -> None:
        """Test that _update_summary method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "_update_summary")
        assert callable(screen._update_summary)

    def test_has_open_filters_modal(self) -> None:
        """Test that _open_filters_modal method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "_open_filters_modal")
        assert callable(screen._open_filters_modal)

    def test_has_presenter_attribute(self) -> None:
        """Test that _presenter attribute exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "_presenter")

    def test_update_mode_button_uses_cluster_label(self) -> None:
        """Mode button should show explicit Cluster label in cluster mode."""
        screen = ChartsExplorerScreen(testing=True)
        mode_button = CustomButton("", id="charts-mode-btn")
        screen.query_one = lambda *_args, **_kwargs: mode_button  # type: ignore[assignment]
        screen.use_cluster_mode = True
        screen._update_mode_button()
        assert "Cluster" in str(mode_button.label)

    def test_namespace_column_hidden_in_local_mode(self) -> None:
        """Namespace column should be hidden when mode is local."""
        screen = ChartsExplorerScreen(testing=True)
        screen.use_cluster_mode = False
        screen._sync_mode_column_state()
        assert "Namespace" not in screen._iter_visible_column_names()

    def test_namespace_column_visible_in_cluster_mode(self) -> None:
        """Namespace column should be visible when mode is cluster."""
        screen = ChartsExplorerScreen(testing=True)
        screen.use_cluster_mode = True
        screen._sync_mode_column_state()
        assert "Namespace" in screen._iter_visible_column_names()

    def test_locked_columns_are_restored_when_visibility_drifts(self) -> None:
        """Chart, Team, and Values File Type columns should remain locked/visible."""
        screen = ChartsExplorerScreen(testing=True)
        screen.use_cluster_mode = False
        screen._visible_column_names = {"QoS"}
        screen._sync_mode_column_state()
        visible = set(screen._iter_visible_column_names())
        assert "Chart" in visible
        assert "Team" in visible
        assert "Values File Type" in visible

    def test_locked_columns_use_fixed_column_count_in_cluster_mode(self) -> None:
        """Cluster mode should pin through the right-most locked column."""
        screen = ChartsExplorerScreen(testing=True)
        screen.use_cluster_mode = True
        screen._sync_mode_column_state()
        assert screen._locked_fixed_column_count(screen._visible_column_indices()) == 4

    def test_cluster_values_preview_uses_deployed_values_content(self) -> None:
        """Cluster-backed chart preview should show fetched deployed values content."""
        screen = ChartsExplorerScreen(testing=True)
        chart = ChartInfo(
            name="svc-a",
            namespace="team-a",
            team="Platform",
            values_file="cluster:team-a",
            deployed_values_content="replicaCount: 2\n",
            cpu_request=100,
            cpu_limit=200,
            memory_request=128,
            memory_limit=256,
            qos_class=QoSClass.BURSTABLE,
            has_liveness=True,
            has_readiness=True,
            has_startup=False,
            has_anti_affinity=False,
            has_topology_spread=False,
            has_topology=False,
            pdb_enabled=True,
            pdb_template_exists=False,
            pdb_min_available=None,
            pdb_max_unavailable=None,
            replicas=2,
            priority_class=None,
        )
        assert screen._load_values_file_content(chart) == "replicaCount: 2\n"

    def test_stale_generation_data_loaded_event_is_ignored(self) -> None:
        """Data events from superseded mode-generation should not update UI state."""
        screen = ChartsExplorerScreen(testing=True)
        chart = ChartInfo(
            name="svc-a",
            namespace="team-a",
            team="Platform",
            values_file="cluster:team-a",
            deployed_values_content="replicaCount: 2\n",
            cpu_request=100,
            cpu_limit=200,
            memory_request=128,
            memory_limit=256,
            qos_class=QoSClass.BURSTABLE,
            has_liveness=True,
            has_readiness=True,
            has_startup=False,
            has_anti_affinity=False,
            has_topology_spread=False,
            has_topology=False,
            pdb_enabled=True,
            pdb_template_exists=False,
            pdb_min_available=None,
            pdb_max_unavailable=None,
            replicas=2,
            priority_class=None,
        )
        screen._mode_generation = 3
        called = False

        def _sync(_: list[ChartInfo], __: set[str] | None) -> None:
            nonlocal called
            called = True

        screen._sync_loaded_charts_state = _sync  # type: ignore[assignment]
        screen.on_charts_explorer_data_loaded(
            ChartsExplorerDataLoaded(
                [chart],
                mode_generation=2,
            )
        )
        assert called is False

    def test_stale_generation_failure_event_is_ignored(self) -> None:
        """Failure messages from cancelled mode-generation should not flash error UI."""
        screen = ChartsExplorerScreen(testing=True)
        screen._mode_generation = 2
        called = False

        def _show_error_state(_: str) -> None:
            nonlocal called
            called = True

        screen.show_error_state = _show_error_state  # type: ignore[assignment]
        screen.on_charts_explorer_data_load_failed(
            ChartsExplorerDataLoadFailed("boom", mode_generation=1)
        )
        assert called is False


# =============================================================================
# Reactive Watcher Tests
# =============================================================================


class TestChartsExplorerScreenWatchers:
    """Test ChartsExplorerScreen reactive watchers exist."""

    def test_has_watch_show_active_only(self) -> None:
        """Test that watch_show_active_only method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "watch_show_active_only")
        assert callable(screen.watch_show_active_only)

    def test_has_watch_current_view(self) -> None:
        """Test that watch_current_view method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "watch_current_view")
        assert callable(screen.watch_current_view)

    def test_has_watch_current_sort(self) -> None:
        """Test that watch_current_sort method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "watch_current_sort")
        assert callable(screen.watch_current_sort)

    def test_has_watch_sort_desc(self) -> None:
        """Test that watch_sort_desc method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "watch_sort_desc")
        assert callable(screen.watch_sort_desc)

    def test_has_watch_current_team(self) -> None:
        """Test that watch_current_team method exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "watch_current_team")
        assert callable(screen.watch_current_team)


# =============================================================================
# Event Handler Tests
# =============================================================================


class TestChartsExplorerScreenEventHandlers:
    """Test ChartsExplorerScreen event handlers exist."""

    def test_has_on_view_tab_activated(self) -> None:
        """Test that _on_view_tab_activated handler exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "_on_view_tab_activated")
        assert callable(screen._on_view_tab_activated)

    def test_has_on_sort_changed(self) -> None:
        """Test that _on_sort_changed handler exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "_on_sort_changed")
        assert callable(screen._on_sort_changed)

    def test_has_open_filters_modal(self) -> None:
        """Test that unified filters modal opener exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "_open_filters_modal")
        assert callable(screen._open_filters_modal)

    def test_has_on_input_changed(self) -> None:
        """Test that on_input_changed handler exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "on_input_changed")
        assert callable(screen.on_input_changed)

    def test_has_on_input_submitted(self) -> None:
        """Test that on_input_submitted handler exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "on_input_submitted")
        assert callable(screen.on_input_submitted)

    def test_has_on_button_pressed(self) -> None:
        """Test that on_button_pressed handler exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "on_button_pressed")
        assert callable(screen.on_button_pressed)

    def test_has_on_data_table_row_selected(self) -> None:
        """Test that on_data_table_row_selected handler exists."""
        screen = ChartsExplorerScreen(testing=True)
        assert hasattr(screen, "on_data_table_row_selected")
        assert callable(screen.on_data_table_row_selected)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestChartsExplorerScreenActionMethods",
    "TestChartsExplorerScreenButtons",
    "TestChartsExplorerScreenEventHandlers",
    "TestChartsExplorerScreenInternalMethods",
    "TestChartsExplorerScreenKeybindings",
    "TestChartsExplorerScreenLoadingStates",
    "TestChartsExplorerScreenReactiveState",
    "TestChartsExplorerScreenViewControls",
    "TestChartsExplorerScreenWatchers",
    "TestChartsExplorerScreenWidgetComposition",
]
