"""Smoke tests for OptimizerScreen - unified violations + recommendations view.

This module tests:
- Screen class attributes and properties
- Widget composition verification (ViolationsView, RecommendationsView, view-select)
- Keybinding verification
- Loading state management
- View switching
- Action methods
- Message handlers
- Worker mixin integration

Note: Tests using app.run_test() are kept minimal due to Textual testing overhead.
"""

from __future__ import annotations

from textual.widgets import Select

from kubeagle.screens.detail import OptimizerScreen
from kubeagle.screens.detail.components import (
    RecommendationsView,
    ViolationsView,
)
from kubeagle.screens.detail.config import (
    OPTIMIZER_HEADER_TOOLTIPS,
    OPTIMIZER_TABLE_COLUMNS,
)

# =============================================================================
# Widget Composition Tests
# =============================================================================


class TestOptimizerScreenWidgetComposition:
    """Test OptimizerScreen widget composition."""

    def test_screen_has_correct_bindings(self) -> None:
        """Test that OptimizerScreen has correct bindings."""
        assert hasattr(OptimizerScreen, "BINDINGS")
        assert len(OptimizerScreen.BINDINGS) > 0

    def test_screen_has_css_path(self) -> None:
        """Test that OptimizerScreen has CSS_PATH."""
        assert hasattr(OptimizerScreen, "CSS_PATH")
        assert "optimizer" in OptimizerScreen.CSS_PATH.lower()

    def test_screen_can_be_instantiated(self) -> None:
        """Test that OptimizerScreen can be created."""
        screen = OptimizerScreen(testing=True)
        assert screen is not None
        assert screen._testing is True

    def test_screen_can_be_instantiated_with_team_filter(self) -> None:
        """Test that OptimizerScreen can be created with team filter."""
        screen = OptimizerScreen(team_filter="team-alpha", testing=True)
        assert screen is not None
        assert screen.team_filter == "team-alpha"

    def test_screen_default_initial_view_is_violations(self) -> None:
        """Test that default initial_view is 'violations'."""
        screen = OptimizerScreen(testing=True)
        assert screen._initial_view == "violations"
        assert screen._current_view == "violations"

    def test_screen_initial_view_recommendations(self) -> None:
        """Test that initial_view can be set to 'recommendations'."""
        screen = OptimizerScreen(testing=True, initial_view="recommendations")
        assert screen._initial_view == "recommendations"
        assert screen._current_view == "recommendations"

    def test_screen_include_cluster_default(self) -> None:
        """Test that include_cluster defaults to True."""
        screen = OptimizerScreen(testing=True)
        assert screen._include_cluster is True

    def test_screen_include_cluster_false(self) -> None:
        """Test that include_cluster can be set to False."""
        screen = OptimizerScreen(testing=True, include_cluster=False)
        assert screen._include_cluster is False


# =============================================================================
# Compose Verification Tests
# =============================================================================


class TestOptimizerScreenCompose:
    """Test OptimizerScreen compose yields expected widgets."""

    @staticmethod
    def _flatten(widgets: list) -> list:
        """Flatten widget tree by traversing _pending_children on containers."""
        result = []
        for w in widgets:
            result.append(w)
            pending = getattr(w, "_pending_children", [])
            if pending:
                result.extend(
                    TestOptimizerScreenCompose._flatten(list(pending))
                )
        return result

    def test_compose_includes_violations_view(self) -> None:
        """Test that compose yields a ViolationsView with id='violations-view'."""
        screen = OptimizerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        matches = [
            w
            for w in all_widgets
            if isinstance(w, ViolationsView) and w.id == "violations-view"
        ]
        assert len(matches) == 1

    def test_compose_includes_recommendations_view(self) -> None:
        """Test that compose yields a RecommendationsView with id='recommendations-view'."""
        screen = OptimizerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        matches = [
            w
            for w in all_widgets
            if isinstance(w, RecommendationsView)
            and w.id == "recommendations-view"
        ]
        assert len(matches) == 1

    def test_compose_includes_view_select(self) -> None:
        """Test that violations view composes a Select widget with id='view-select'."""
        screen = OptimizerScreen(testing=True)
        widgets = list(screen.compose())
        violations_views = [
            w
            for w in widgets
            if isinstance(w, ViolationsView) and w.id == "violations-view"
        ]
        assert len(violations_views) == 1

        all_widgets = self._flatten(list(violations_views[0].compose()))
        selects = [
            w
            for w in all_widgets
            if isinstance(w, Select) and w.id == "view-select"
        ]
        assert len(selects) == 1

    def test_view_select_has_view_bar_parent(self) -> None:
        """Test that view-select is inside a view-bar container."""
        from kubeagle.widgets import CustomHorizontal
        screen = OptimizerScreen(testing=True)
        widgets = list(screen.compose())
        view_bars = [w for w in widgets if isinstance(w, CustomHorizontal) and w.id == "view-bar"]
        assert len(view_bars) == 1

    def test_compose_does_not_include_old_category_select(self) -> None:
        """Test that old category-select widget is not in top-level compose."""
        screen = OptimizerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        selects = [
            w
            for w in all_widgets
            if isinstance(w, Select) and w.id == "category-select"
        ]
        assert len(selects) == 0

    def test_compose_does_not_include_old_severity_select(self) -> None:
        """Test that old severity-select widget is not in top-level compose."""
        screen = OptimizerScreen(testing=True)
        widgets = list(screen.compose())
        all_widgets = self._flatten(widgets)
        selects = [
            w
            for w in all_widgets
            if isinstance(w, Select) and w.id == "severity-select"
        ]
        assert len(selects) == 0

    def test_violations_view_configures_header_tooltips(self) -> None:
        """ViolationsView should wire header tooltips for its table columns."""
        from unittest.mock import MagicMock

        view = ViolationsView()
        table = MagicMock()

        view._configure_violations_table_header_tooltips(table)

        table.set_header_tooltips.assert_called_once_with(OPTIMIZER_HEADER_TOOLTIPS)

    def test_violations_view_locked_columns_are_restored(self) -> None:
        """Chart, Team, Values File Type should remain visible in optimizer table."""
        view = ViolationsView()
        view._filter_options = {
            "column": [(name, name) for name, _ in OPTIMIZER_TABLE_COLUMNS],
        }
        view._visible_column_names = {"Rule"}
        view._sync_filter_selection_with_options()

        visible = set(view._iter_visible_column_names())
        assert "Chart" in visible
        assert "Team" in visible
        assert "Values File Type" in visible

    def test_violations_view_locked_columns_are_pinned(self) -> None:
        """Optimizer table should pin through the right-most locked column."""
        view = ViolationsView()
        assert view._locked_fixed_column_count(view._visible_column_indices()) == 3


# =============================================================================
# OptimizerScreen Keybinding Tests
# =============================================================================


class TestOptimizerScreenKeybindings:
    """Test OptimizerScreen-specific keybindings."""

    def test_has_pop_screen_binding(self) -> None:
        """Test that escape binding exists."""
        bindings = OptimizerScreen.BINDINGS
        escape_bindings = [b for b in bindings if b[0] == "escape"]
        assert len(escape_bindings) > 0

    def test_has_refresh_binding(self) -> None:
        """Test that 'r' refresh binding exists."""
        bindings = OptimizerScreen.BINDINGS
        refresh_bindings = [b for b in bindings if b[0] == "r"]
        assert len(refresh_bindings) > 0

    def test_has_home_binding(self) -> None:
        """Test that 'h' home binding exists."""
        bindings = OptimizerScreen.BINDINGS
        home_bindings = [b for b in bindings if b[0] == "h"]
        assert len(home_bindings) > 0

    def test_has_help_binding(self) -> None:
        """Test that '?' help binding exists."""
        bindings = OptimizerScreen.BINDINGS
        help_bindings = [b for b in bindings if b[0] == "?"]
        assert len(help_bindings) > 0

    def test_has_apply_all_binding(self) -> None:
        """Test that 'a' apply all binding exists."""
        bindings = OptimizerScreen.BINDINGS
        apply_bindings = [b for b in bindings if b[0] == "a"]
        assert len(apply_bindings) > 0

    def test_has_fix_violation_binding(self) -> None:
        """Test that 'f' fix violation binding exists."""
        bindings = OptimizerScreen.BINDINGS
        fix_bindings = [b for b in bindings if b[0] == "f"]
        assert len(fix_bindings) > 0

    def test_has_preview_fix_binding(self) -> None:
        """Test that 'p' preview fix binding exists."""
        bindings = OptimizerScreen.BINDINGS
        preview_bindings = [b for b in bindings if b[0] == "p"]
        assert len(preview_bindings) > 0

    def test_has_charts_binding(self) -> None:
        """Test that 'C' charts binding exists."""
        bindings = OptimizerScreen.BINDINGS
        charts_bindings = [b for b in bindings if b[0] == "C"]
        assert len(charts_bindings) > 0

    def test_has_export_binding(self) -> None:
        """Test that 'e' export binding exists."""
        bindings = OptimizerScreen.BINDINGS
        export_bindings = [b for b in bindings if b[0] == "e"]
        assert len(export_bindings) > 0

    def test_has_view_violations_binding(self) -> None:
        """Test that '1' view violations binding exists."""
        bindings = OptimizerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "1"]
        assert len(matches) > 0

    def test_has_view_recommendations_binding(self) -> None:
        """Test that '2' view recommendations binding exists."""
        bindings = OptimizerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "2"]
        assert len(matches) > 0

    def test_has_copy_yaml_binding(self) -> None:
        """Test that 'y' copy yaml binding exists."""
        bindings = OptimizerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "y"]
        assert len(matches) > 0

    def test_has_focus_sort_binding(self) -> None:
        """Test that 'S' focus sort binding exists."""
        bindings = OptimizerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "S"]
        assert len(matches) > 0

    def test_has_focus_sort_lowercase_binding(self) -> None:
        """Test that 's' focus sort binding exists."""
        bindings = OptimizerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "s"]
        assert len(matches) > 0

    def test_has_cycle_severity_binding(self) -> None:
        """Test that 'v' cycle severity binding exists."""
        bindings = OptimizerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "v"]
        assert len(matches) > 0

    def test_has_go_to_chart_binding(self) -> None:
        """Test that 'g' go to chart binding exists."""
        bindings = OptimizerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "g"]
        assert len(matches) > 0

    def test_has_search_binding(self) -> None:
        """Test that 'slash' search binding exists."""
        bindings = OptimizerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "slash"]
        assert len(matches) > 0

    def test_has_settings_binding(self) -> None:
        """Test that 'ctrl+s' settings binding exists."""
        bindings = OptimizerScreen.BINDINGS
        matches = [b for b in bindings if b[0] == "ctrl+s"]
        assert len(matches) > 0

    def test_data_table_bindings_exclude_manual_column_sizing(self) -> None:
        """Global table bindings should not expose manual column sizing actions."""
        from kubeagle.keyboard import DATA_TABLE_BINDINGS

        actions = {binding[1] for binding in DATA_TABLE_BINDINGS}
        assert "previous_column" not in actions
        assert "next_column" not in actions
        assert "shrink_column" not in actions
        assert "expand_column" not in actions
        assert "reset_column_widths" not in actions


# =============================================================================
# Loading State Tests
# =============================================================================


class TestOptimizerScreenLoadingStates:
    """Test OptimizerScreen loading state management."""

    def test_show_loading_overlay_method_exists(self) -> None:
        """Test that show_loading_overlay method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "show_loading_overlay")
        assert callable(screen.show_loading_overlay)

    def test_hide_loading_overlay_method_exists(self) -> None:
        """Test that hide_loading_overlay method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "hide_loading_overlay")
        assert callable(screen.hide_loading_overlay)

    def test_show_error_state_method_exists(self) -> None:
        """Test that show_error_state method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "show_error_state")
        assert callable(screen.show_error_state)


# =============================================================================
# Message Handler Tests
# =============================================================================


class TestOptimizerScreenMessageHandlers:
    """Test OptimizerScreen message handlers."""

    def test_has_data_loaded_handler(self) -> None:
        """Test that on_optimizer_data_loaded handler exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "on_optimizer_data_loaded")
        assert callable(screen.on_optimizer_data_loaded)

    def test_has_data_load_failed_handler(self) -> None:
        """Test that on_optimizer_data_load_failed handler exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "on_optimizer_data_load_failed")
        assert callable(screen.on_optimizer_data_load_failed)

    def test_has_violation_refresh_requested_handler(self) -> None:
        """Test that on_violation_refresh_requested handler exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "on_violation_refresh_requested")
        assert callable(screen.on_violation_refresh_requested)


# =============================================================================
# View Switching Tests
# =============================================================================


class TestOptimizerScreenViewSwitching:
    """Test OptimizerScreen view switching logic."""

    def test_has_switch_view_method(self) -> None:
        """Test that _switch_view method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "_switch_view")
        assert callable(screen._switch_view)

    def test_has_action_view_violations(self) -> None:
        """Test that action_view_violations method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_view_violations")
        assert callable(screen.action_view_violations)

    def test_has_action_view_recommendations(self) -> None:
        """Test that action_view_recommendations method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_view_recommendations")
        assert callable(screen.action_view_recommendations)

    def test_has_on_select_changed_handler(self) -> None:
        """Test that on_select_changed method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "on_select_changed")
        assert callable(screen.on_select_changed)


# =============================================================================
# Action Methods Tests
# =============================================================================


class TestOptimizerScreenActionMethods:
    """Test OptimizerScreen action methods."""

    def test_has_action_refresh(self) -> None:
        """Test that action_refresh method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_refresh")
        assert callable(screen.action_refresh)

    def test_has_action_apply_all(self) -> None:
        """Test that action_apply_all method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_apply_all")
        assert callable(screen.action_apply_all)

    def test_has_action_fix_violation(self) -> None:
        """Test that action_fix_violation method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_fix_violation")
        assert callable(screen.action_fix_violation)

    def test_has_action_preview_fix(self) -> None:
        """Test that action_preview_fix method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_preview_fix")
        assert callable(screen.action_preview_fix)

    def test_has_action_focus_search(self) -> None:
        """Test that action_focus_search method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_focus_search")
        assert callable(screen.action_focus_search)

    def test_has_action_copy_yaml(self) -> None:
        """Test that action_copy_yaml method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_copy_yaml")
        assert callable(screen.action_copy_yaml)

    def test_has_action_focus_sort(self) -> None:
        """Test that action_focus_sort method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_focus_sort")
        assert callable(screen.action_focus_sort)

    def test_has_action_cycle_severity(self) -> None:
        """Test that action_cycle_severity method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_cycle_severity")
        assert callable(screen.action_cycle_severity)

    def test_has_action_go_to_chart(self) -> None:
        """Test that action_go_to_chart method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_go_to_chart")
        assert callable(screen.action_go_to_chart)

    def test_has_action_pop_screen(self) -> None:
        """Test that action_pop_screen method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_pop_screen")
        assert callable(screen.action_pop_screen)

    def test_has_action_show_help(self) -> None:
        """Test that action_show_help method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_show_help")
        assert callable(screen.action_show_help)


# =============================================================================
# Navigation Action Tests
# =============================================================================


class TestOptimizerScreenNavigationActions:
    """Test OptimizerScreen navigation action methods."""

    def test_has_action_nav_home(self) -> None:
        """Test that action_nav_home method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_nav_home")
        assert callable(screen.action_nav_home)

    def test_has_action_nav_charts(self) -> None:
        """Test that action_nav_charts method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_nav_charts")
        assert callable(screen.action_nav_charts)

    def test_has_action_nav_export(self) -> None:
        """Test that action_nav_export method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_nav_export")
        assert callable(screen.action_nav_export)

    def test_has_action_nav_settings(self) -> None:
        """Test that action_nav_settings method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "action_nav_settings")
        assert callable(screen.action_nav_settings)


# =============================================================================
# Removed Features Tests
# =============================================================================


class TestOptimizerScreenRemovedFeatures:
    """Test that old features are no longer on OptimizerScreen directly."""

    def test_no_violations_property(self) -> None:
        """Test that violations property is NOT on screen (moved to ViolationsView)."""
        screen = OptimizerScreen(testing=True)
        assert not hasattr(screen, "violations")

    def test_no_charts_property(self) -> None:
        """Test that charts property is NOT on screen (moved to ViolationsView)."""
        screen = OptimizerScreen(testing=True)
        assert not hasattr(screen, "charts")

    def test_no_sorted_violations_property(self) -> None:
        """Test that sorted_violations is NOT on screen (moved to ViolationsView)."""
        screen = OptimizerScreen(testing=True)
        assert not hasattr(screen, "sorted_violations")

    def test_no_category_filter_property(self) -> None:
        """Test that category_filter is NOT on screen (moved to ViolationsView)."""
        screen = OptimizerScreen(testing=True)
        assert not hasattr(screen, "category_filter")

    def test_no_severity_filter_property(self) -> None:
        """Test that severity_filter is NOT on screen (moved to ViolationsView)."""
        screen = OptimizerScreen(testing=True)
        assert not hasattr(screen, "severity_filter")

    def test_no_selected_violation_property(self) -> None:
        """Test that selected_violation is NOT on screen (moved to ViolationsView)."""
        screen = OptimizerScreen(testing=True)
        assert not hasattr(screen, "selected_violation")

    def test_no_get_filtered_violations_method(self) -> None:
        """Test that get_filtered_violations is NOT on screen (moved to ViolationsView)."""
        screen = OptimizerScreen(testing=True)
        assert not hasattr(screen, "get_filtered_violations")

    def test_no_populate_violations_table_method(self) -> None:
        """Test that populate_violations_table is NOT on screen (moved to ViolationsView)."""
        screen = OptimizerScreen(testing=True)
        assert not hasattr(screen, "populate_violations_table")

    def test_no_extract_yaml_paths_method(self) -> None:
        """Test that _extract_yaml_paths is NOT on screen (moved to ViolationsView)."""
        assert not hasattr(OptimizerScreen, "_extract_yaml_paths")


# =============================================================================
# Worker Mixin Tests
# =============================================================================


class TestOptimizerScreenWorkerMixin:
    """Test OptimizerScreen worker mixin integration."""

    def test_inherits_worker_mixin(self) -> None:
        """Test that OptimizerScreen inherits from WorkerMixin."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "start_worker")
        assert hasattr(screen, "_start_load_worker")

    def test_has_load_data_worker(self) -> None:
        """Test that _load_data_worker method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "_load_data_worker")
        assert callable(screen._load_data_worker)

    def test_has_optimizer_reset_and_reload(self) -> None:
        """Test that _optimizer_reset_and_reload method exists."""
        screen = OptimizerScreen(testing=True)
        assert hasattr(screen, "_optimizer_reset_and_reload")
        assert callable(screen._optimizer_reset_and_reload)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestOptimizerScreenActionMethods",
    "TestOptimizerScreenCompose",
    "TestOptimizerScreenKeybindings",
    "TestOptimizerScreenLoadingStates",
    "TestOptimizerScreenMessageHandlers",
    "TestOptimizerScreenNavigationActions",
    "TestOptimizerScreenRemovedFeatures",
    "TestOptimizerScreenViewSwitching",
    "TestOptimizerScreenWidgetComposition",
    "TestOptimizerScreenWorkerMixin",
]
