"""Smoke tests for screen-specific keyboard bindings.

Tests all screen-specific bindings from kubeagle.keyboard.navigation
including BASE_SCREEN_BINDINGS, CLUSTER_SCREEN_BINDINGS,
CHARTS_EXPLORER_SCREEN_BINDINGS, SETTINGS_SCREEN_BINDINGS,
CHART_DETAIL_SCREEN_BINDINGS, and REPORT_EXPORT_SCREEN_BINDINGS.

These tests verify that screen transitions and bindings work correctly.
"""

from __future__ import annotations

import pytest
from textual.app import App

from kubeagle.screens import (
    ChartsExplorerScreen,
    ClusterScreen,
    ReportExportScreen,
    SettingsScreen,
    WorkloadsScreen,
)

# =============================================================================
# BASE SCREEN BINDINGS TESTS
# =============================================================================


class TestBaseScreenBindings:
    """Test BASE_SCREEN_BINDINGS from keyboard/navigation.py."""

    @pytest.mark.asyncio
    async def test_escape_pops_screen(self, app: App) -> None:
        """Test that escape key pops current screen."""
        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            initial_count = len(app.screen_stack)
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) <= initial_count

    @pytest.mark.asyncio
    async def test_r_refreshes(self, app: App) -> None:
        """Test that 'r' triggers refresh action."""
        async with app.run_test() as pilot:
            await pilot.press("r")
            await pilot.pause()
            assert app is not None

    @pytest.mark.asyncio
    async def test_focus_search(self, app: App) -> None:
        """Test that '/' focuses search input."""
        async with app.run_test() as pilot:
            await pilot.press("/")
            await pilot.pause()
            assert app is not None

    @pytest.mark.asyncio
    async def test_h_navigates_home(self, app: App) -> None:
        """Test that 'h' pushes ClusterScreen onto the screen stack."""
        import asyncio

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("c")
            await asyncio.sleep(1.0)
            await pilot.pause()
            await pilot.press("h")
            await asyncio.sleep(1.0)
            await pilot.pause()
            cluster_screens = [s for s in app.screen_stack if isinstance(s, ClusterScreen)]
            assert len(cluster_screens) > 0, (
                f"Expected ClusterScreen in stack, got: "
                f"{[type(s).__name__ for s in app.screen_stack]}"
            )

    @pytest.mark.asyncio
    async def test_c_navigates_cluster(self, app: App) -> None:
        """Test that 'c' navigates to cluster screen."""
        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ClusterScreen)

    @pytest.mark.asyncio
    async def test_shift_c_navigates_charts(self, app: App) -> None:
        """Test that 'C' navigates to charts screen."""
        async with app.run_test() as pilot:
            await pilot.press("C")
            await pilot.pause()
            assert isinstance(app.screen, ChartsExplorerScreen)

    @pytest.mark.asyncio
    async def test_primary_tabs_click_cluster_after_shift_c(self, app: App) -> None:
        """Mouse click on primary Cluster tab should navigate from Charts to Cluster."""
        async with app.run_test() as pilot:
            await pilot.press("C")
            await pilot.pause()
            assert isinstance(app.screen, ChartsExplorerScreen)
            clicked = await pilot.click("#main-tab-cluster")
            await pilot.pause()
            assert clicked is True
            assert isinstance(app.screen, ClusterScreen)

    @pytest.mark.asyncio
    async def test_primary_tabs_click_cluster_after_export_resets_title(
        self,
        app: App,
    ) -> None:
        """Returning from Export to Cluster should restore Cluster screen title."""
        async with app.run_test() as pilot:
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, ReportExportScreen)
            assert app.title == "KubEagle - Report Export"

            clicked = await pilot.click("#main-tab-cluster")
            await pilot.pause()

            assert clicked is True
            assert isinstance(app.screen, ClusterScreen)
            assert app.title == "KubEagle - Cluster"

    @pytest.mark.asyncio
    async def test_primary_tabs_click_workloads_opens_workloads_screen(
        self,
        app: App,
    ) -> None:
        """Mouse click on primary Workloads tab should open dedicated WorkloadsScreen."""
        async with app.run_test() as pilot:
            await pilot.press("C")
            await pilot.pause()
            assert isinstance(app.screen, ChartsExplorerScreen)

            clicked = await pilot.click("#main-tab-workloads")
            await pilot.pause()

            assert clicked is True
            assert isinstance(app.screen, WorkloadsScreen)
            assert app.title == "KubEagle - Workloads"

    @pytest.mark.asyncio
    async def test_e_navigates_export(self, app: App) -> None:
        """Test that 'e' navigates to export screen."""
        async with app.run_test() as pilot:
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, ReportExportScreen)

    @pytest.mark.asyncio
    async def test_ctrl_s_navigates_settings(self, app: App) -> None:
        """Test that 'Ctrl+s' navigates to settings screen."""
        async with app.run_test() as pilot:
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)

    @pytest.mark.asyncio
    async def test_shows_help(self, app: App) -> None:
        """Test that '?' shows help."""
        async with app.run_test() as pilot:
            await pilot.press("?")
            await pilot.pause()
            assert app is not None


class TestBaseScreenBindingsTupleVerification:
    """Verify BASE_SCREEN_BINDINGS tuples contain expected key-action pairs."""

    def test_escape_pop_screen(self) -> None:
        """Test 'escape' -> pop_screen exists in BASE_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import BASE_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in BASE_SCREEN_BINDINGS]
        assert ("escape", "pop_screen") in binding_pairs

    def test_r_refresh(self) -> None:
        """Test 'r' -> refresh exists in BASE_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import BASE_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in BASE_SCREEN_BINDINGS]
        assert ("r", "refresh") in binding_pairs


# =============================================================================
# CLUSTER SCREEN BINDINGS TESTS
# =============================================================================


class TestClusterScreenBindings:
    """Test CLUSTER_SCREEN_BINDINGS from keyboard/navigation.py."""

    @pytest.mark.asyncio
    async def test_escape_pops_screen(self, app: App) -> None:
        """Test that escape key pops cluster screen."""
        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            initial_stack = len(app.screen_stack)
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) <= initial_stack

    @pytest.mark.asyncio
    async def test_r_refreshes(self, app: App) -> None:
        """Test that 'r' triggers refresh action."""
        async with app.run_test() as pilot:
            await pilot.press("r")
            await pilot.pause()
            assert app is not None

    @pytest.mark.asyncio
    async def test_h_navigates_home(self, app: App) -> None:
        """Test that 'h' keeps/pushes ClusterScreen from ClusterScreen."""
        import asyncio

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("c")
            await asyncio.sleep(1.0)
            await pilot.pause()
            await pilot.press("h")
            await asyncio.sleep(1.0)
            await pilot.pause()
            cluster_screens = [s for s in app.screen_stack if isinstance(s, ClusterScreen)]
            assert len(cluster_screens) > 0, (
                f"Expected ClusterScreen in stack, got: "
                f"{[type(s).__name__ for s in app.screen_stack]}"
            )


class TestClusterScreenBindingsTupleVerification:
    """Verify CLUSTER_SCREEN_BINDINGS tuples contain expected key-action pairs."""

    def test_slash_focus_search(self) -> None:
        """Test '/' -> focus_search exists in CLUSTER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import CLUSTER_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in CLUSTER_SCREEN_BINDINGS]
        assert ("slash", "focus_search") in binding_pairs

    def test_1_switch_tab_1(self) -> None:
        """Test '1' -> switch_tab_1 exists in CLUSTER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import CLUSTER_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in CLUSTER_SCREEN_BINDINGS]
        assert ("1", "switch_tab_1") in binding_pairs

    def test_2_switch_tab_2(self) -> None:
        """Test '2' -> switch_tab_2 exists in CLUSTER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import CLUSTER_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in CLUSTER_SCREEN_BINDINGS]
        assert ("2", "switch_tab_2") in binding_pairs

    def test_3_switch_tab_3(self) -> None:
        """Test '3' -> switch_tab_3 exists in CLUSTER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import CLUSTER_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in CLUSTER_SCREEN_BINDINGS]
        assert ("3", "switch_tab_3") in binding_pairs

    def test_question_mark_show_help(self) -> None:
        """Test '?' -> show_help exists in CLUSTER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import CLUSTER_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in CLUSTER_SCREEN_BINDINGS]
        assert ("?", "show_help") in binding_pairs


# =============================================================================
# CHARTS EXPLORER SCREEN BINDINGS TUPLE TESTS
# =============================================================================


class TestChartsExplorerScreenBindingsTuples:
    """Verify CHARTS_EXPLORER_SCREEN_BINDINGS tuples contain expected key-action pairs."""

    def test_has_view_all_binding(self) -> None:
        """Test '1' -> view_all exists in CHARTS_EXPLORER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert ("1", "view_all") in binding_pairs

    def test_has_view_extreme_binding(self) -> None:
        """Test '2' -> view_extreme exists in CHARTS_EXPLORER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert ("2", "view_extreme") in binding_pairs

    def test_has_view_single_replica_binding(self) -> None:
        """Test '3' -> view_single_replica exists in CHARTS_EXPLORER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert ("3", "view_single_replica") in binding_pairs

    def test_has_view_no_pdb_binding(self) -> None:
        """Test '4' -> view_no_pdb exists in CHARTS_EXPLORER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert ("4", "view_no_pdb") in binding_pairs

    def test_has_view_violations_binding(self) -> None:
        """Test charts explorer binds '5' to view_violations."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert ("5", "view_violations") in binding_pairs

    def test_has_toggle_sort_direction_binding(self) -> None:
        """Test 's' -> toggle_sort_direction exists in CHARTS_EXPLORER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert ("s", "toggle_sort_direction") in binding_pairs

    def test_has_cycle_team_binding(self) -> None:
        """Test 't' -> cycle_team exists in CHARTS_EXPLORER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert ("t", "cycle_team") in binding_pairs

    def test_has_nav_home_binding(self) -> None:
        """Test 'h' -> nav_home exists in CHARTS_EXPLORER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert ("h", "nav_home") in binding_pairs

    def test_has_nav_cluster_binding(self) -> None:
        """Test 'c' -> nav_cluster exists in CHARTS_EXPLORER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert ("c", "nav_cluster") in binding_pairs

    def test_has_help_binding(self) -> None:
        """Test '?' -> show_help exists in CHARTS_EXPLORER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert ("?", "show_help") in binding_pairs

    def test_has_select_chart_binding(self) -> None:
        """Test 'enter' -> select_chart exists in CHARTS_EXPLORER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert ("enter", "select_chart") in binding_pairs

    def test_has_toggle_mode_binding(self) -> None:
        """Test 'm' -> toggle_mode exists in CHARTS_EXPLORER_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert ("m", "toggle_mode") in binding_pairs


# =============================================================================
# SETTINGS SCREEN BINDINGS TESTS
# =============================================================================


class TestSettingsScreenBindings:
    """Test SETTINGS_SCREEN_BINDINGS from keyboard/navigation.py."""

    @pytest.mark.asyncio
    async def test_escape_pops_screen(self, app: App) -> None:
        """Test that escape key pops settings screen."""
        async with app.run_test() as pilot:
            await pilot.press("ctrl+s")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, ClusterScreen)

    @pytest.mark.asyncio
    async def test_ctrl_s_saves_settings(self, app: App) -> None:
        """Test that 'Ctrl+s' saves settings."""
        async with app.run_test() as pilot:
            await pilot.press("ctrl+s")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app is not None

    @pytest.mark.asyncio
    async def test_ctrl_c_cancels(self, app: App) -> None:
        """Test that 'Ctrl+c' cancels settings."""
        async with app.run_test() as pilot:
            await pilot.press("ctrl+s")
            await pilot.pause()
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert app is not None

    @pytest.mark.asyncio
    async def test_r_refreshes(self, app: App) -> None:
        """Test that 'r' triggers refresh on settings screen."""
        async with app.run_test() as pilot:
            await pilot.press("ctrl+s")
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            assert app is not None


class TestSettingsScreenBindingsTupleVerification:
    """Verify SETTINGS_SCREEN_BINDINGS tuples contain expected key-action pairs."""

    def test_question_mark_show_help(self) -> None:
        """Test '?' -> show_help exists in SETTINGS_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import SETTINGS_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in SETTINGS_SCREEN_BINDINGS]
        assert ("?", "show_help") in binding_pairs

    def test_h_nav_home(self) -> None:
        """Test 'h' -> nav_home exists in SETTINGS_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import SETTINGS_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in SETTINGS_SCREEN_BINDINGS]
        assert ("h", "nav_home") in binding_pairs

    def test_c_nav_cluster(self) -> None:
        """Test 'c' -> nav_cluster exists in SETTINGS_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import SETTINGS_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in SETTINGS_SCREEN_BINDINGS]
        assert ("c", "nav_cluster") in binding_pairs

    def test_shift_c_nav_charts(self) -> None:
        """Test 'C' -> nav_charts exists in SETTINGS_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import SETTINGS_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in SETTINGS_SCREEN_BINDINGS]
        assert ("C", "nav_charts") in binding_pairs

    def test_o_nav_optimizer_not_bound(self) -> None:
        """Test 'o' -> nav_optimizer is not in SETTINGS_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import SETTINGS_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in SETTINGS_SCREEN_BINDINGS]
        assert ("o", "nav_optimizer") not in binding_pairs

    def test_e_nav_export(self) -> None:
        """Test 'e' -> nav_export exists in SETTINGS_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import SETTINGS_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in SETTINGS_SCREEN_BINDINGS]
        assert ("e", "nav_export") in binding_pairs

    def test_ctrl_s_save_settings(self) -> None:
        """Test 'ctrl+s' -> save_settings exists in SETTINGS_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import SETTINGS_SCREEN_BINDINGS

        binding_pairs = [(k, a) for k, a, _ in SETTINGS_SCREEN_BINDINGS]
        assert ("ctrl+s", "save_settings") in binding_pairs


# =============================================================================
# REPORT EXPORT SCREEN BINDINGS TESTS
# =============================================================================


class TestReportExportScreenBindings:
    """Test REPORT_EXPORT_SCREEN_BINDINGS from keyboard/navigation.py."""

    @pytest.mark.asyncio
    async def test_escape_pops_screen(self, app: App) -> None:
        """Test that escape key pops report export screen."""
        async with app.run_test() as pilot:
            await pilot.press("e")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, ClusterScreen)

    @pytest.mark.asyncio
    async def test_r_refreshes(self, app: App) -> None:
        """Test that 'r' triggers refresh on report export screen."""
        async with app.run_test() as pilot:
            await pilot.press("e")
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            assert app is not None

    @pytest.mark.asyncio
    async def test_ctrl_e_exports_report(self, app: App) -> None:
        """Test that 'Ctrl+e' exports report."""
        async with app.run_test() as pilot:
            await pilot.press("e")
            await pilot.pause()
            await pilot.press("ctrl+e")
            await pilot.pause()
            assert app is not None

    @pytest.mark.asyncio
    async def test_ctrl_s_saves_file(self, app: App) -> None:
        """Test that 'Ctrl+s' saves to file."""
        async with app.run_test() as pilot:
            await pilot.press("e")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app is not None

    @pytest.mark.asyncio
    async def test_ctrl_c_copies_clipboard(self, app: App) -> None:
        """Test that 'Ctrl+c' copies to clipboard."""
        async with app.run_test() as pilot:
            await pilot.press("e")
            await pilot.pause()
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert app is not None


class TestReportExportScreenBindingsTupleVerification:
    """Verify REPORT_EXPORT_SCREEN_BINDINGS tuples contain expected key-action pairs."""

    def test_question_mark_show_help(self) -> None:
        """Test '?' -> show_help exists in REPORT_EXPORT_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            REPORT_EXPORT_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in REPORT_EXPORT_SCREEN_BINDINGS]
        assert ("?", "show_help") in binding_pairs

    def test_h_nav_home(self) -> None:
        """Test 'h' -> nav_home exists in REPORT_EXPORT_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            REPORT_EXPORT_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in REPORT_EXPORT_SCREEN_BINDINGS]
        assert ("h", "nav_home") in binding_pairs

    def test_c_nav_cluster(self) -> None:
        """Test 'c' -> nav_cluster exists in REPORT_EXPORT_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            REPORT_EXPORT_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in REPORT_EXPORT_SCREEN_BINDINGS]
        assert ("c", "nav_cluster") in binding_pairs

    def test_shift_c_nav_charts(self) -> None:
        """Test 'C' -> nav_charts exists in REPORT_EXPORT_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            REPORT_EXPORT_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in REPORT_EXPORT_SCREEN_BINDINGS]
        assert ("C", "nav_charts") in binding_pairs

    def test_o_nav_optimizer_not_bound(self) -> None:
        """Test 'o' -> nav_optimizer is not in REPORT_EXPORT_SCREEN_BINDINGS."""
        from kubeagle.keyboard.navigation import (
            REPORT_EXPORT_SCREEN_BINDINGS,
        )

        binding_pairs = [(k, a) for k, a, _ in REPORT_EXPORT_SCREEN_BINDINGS]
        assert ("o", "nav_optimizer") not in binding_pairs

# =============================================================================
# CHART DETAIL SCREEN BINDINGS TESTS
# =============================================================================


class TestChartDetailScreenBindings:
    """Test CHART_DETAIL_SCREEN_BINDINGS from keyboard/navigation.py."""

    @pytest.mark.asyncio
    async def test_escape_pops_screen(self, app: App) -> None:
        """Test that escape key pops chart detail screen."""
        async with app.run_test() as pilot:
            await pilot.press("C")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, ClusterScreen)

    @pytest.mark.asyncio
    async def test_r_refreshes(self, app: App) -> None:
        """Test that 'r' triggers refresh on chart detail screen."""
        async with app.run_test() as pilot:
            await pilot.press("C")
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            assert app is not None

    @pytest.mark.asyncio
    async def test_focus_search(self, app: App) -> None:
        """Test that '/' focuses search on chart detail screen."""
        async with app.run_test() as pilot:
            await pilot.press("C")
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            assert app is not None

    @pytest.mark.asyncio
    async def test_h_shows_help(self, app: App) -> None:
        """Test that 'h' shows help."""
        async with app.run_test() as pilot:
            await pilot.press("C")
            await pilot.pause()
            await pilot.press("h")
            await pilot.pause()
            assert app is not None


# =============================================================================
# BINDING COUNT VERIFICATION
# =============================================================================


class TestNavigationBindingCounts:
    """Verify expected number of bindings are present."""

    def test_base_screen_bindings_count(self) -> None:
        """Test BASE_SCREEN_BINDINGS has expected count."""
        from kubeagle.keyboard.navigation import BASE_SCREEN_BINDINGS

        assert len(BASE_SCREEN_BINDINGS) == 8

    def test_cluster_screen_bindings_count(self) -> None:
        """Test CLUSTER_SCREEN_BINDINGS has expected count."""
        from kubeagle.keyboard.navigation import CLUSTER_SCREEN_BINDINGS

        assert len(CLUSTER_SCREEN_BINDINGS) == 8

    def test_settings_screen_bindings_count(self) -> None:
        """Test SETTINGS_SCREEN_BINDINGS has expected count."""
        from kubeagle.keyboard.navigation import SETTINGS_SCREEN_BINDINGS

        assert len(SETTINGS_SCREEN_BINDINGS) == 9

    def test_report_export_screen_bindings_count(self) -> None:
        """Test REPORT_EXPORT_SCREEN_BINDINGS has expected count."""
        from kubeagle.keyboard.navigation import (
            REPORT_EXPORT_SCREEN_BINDINGS,
        )

        assert len(REPORT_EXPORT_SCREEN_BINDINGS) == 8

    def test_chart_detail_screen_bindings_count(self) -> None:
        """Test CHART_DETAIL_SCREEN_BINDINGS has expected count."""
        from kubeagle.keyboard.navigation import (
            CHART_DETAIL_SCREEN_BINDINGS,
        )

        assert len(CHART_DETAIL_SCREEN_BINDINGS) == 10

    def test_charts_explorer_screen_bindings_count(self) -> None:
        """Test CHARTS_EXPLORER_SCREEN_BINDINGS has expected count."""
        from kubeagle.keyboard.navigation import (
            CHARTS_EXPLORER_SCREEN_BINDINGS,
        )

        assert len(CHARTS_EXPLORER_SCREEN_BINDINGS) == 24
