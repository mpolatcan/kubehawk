"""Screen-specific keyboard bindings and navigation helpers.

This module contains:
1. Screen-specific bindings (BASE_SCREEN_BINDINGS, *_SCREEN_BINDINGS)
2. ScreenNavigator class for navigation
3. navigate_* standalone functions for convenience
"""

from typing import Annotated, Any

from textual.app import App

# ============================================================================
# SCREEN NAVIGATOR CLASS
# ============================================================================

class ScreenNavigator:
    """Helper class for screen navigation.

    This class provides methods for navigating between screens
    in a consistent manner. Can be used as a mixin or composition.

    Usage:
        # As a mixin (add methods to screen class)
        class MyScreen(ScreenNavigator, BaseScreen):
            def action_nav_home(self) -> None:
                self._navigate_home()

        # As standalone helper
        navigator = ScreenNavigator(app)
        await navigator.navigate_to_charts()
    """

    def __init__(self, app: App | None = None) -> None:
        """Initialize the navigator.

        Args:
            app: The Textual app instance. Required for standalone usage.
        """
        self._app: App | None = app

    @property
    def app(self) -> App:
        """Get the app instance, raising if not set."""
        if self._app is not None:
            return self._app
        # When used as mixin with Screen, use Screen.app
        try:
            return super().app  # type: ignore[misc]
        except AttributeError as err:
            raise RuntimeError("App not set. Initialize with app= or use as mixin.") from err

    def _navigate_home(self) -> None:
        """Navigate to primary landing screen (Cluster summary)."""
        app_nav = getattr(self.app, "action_nav_home", None)
        if callable(app_nav):
            app_nav()
            return
        from kubeagle.screens.cluster import ClusterScreen

        self.app.push_screen(ClusterScreen())

    def _navigate_cluster(self) -> None:
        """Navigate to cluster screen."""
        app_nav = getattr(self.app, "action_nav_cluster", None)
        if callable(app_nav):
            app_nav()
            return
        from kubeagle.screens.cluster import ClusterScreen

        self.app.push_screen(ClusterScreen())

    def _navigate_charts(self, testing: bool = False) -> None:
        """Navigate to charts explorer screen."""
        app_nav = getattr(self.app, "action_nav_charts", None)
        if callable(app_nav) and not testing:
            app_nav()
            return
        from kubeagle.screens.charts_explorer import ChartsExplorerScreen

        current_screen = self.app.screen
        if isinstance(current_screen, ChartsExplorerScreen):
            current_screen.action_show_charts_tab()
            return

        self.app.push_screen(ChartsExplorerScreen(testing=testing))

    def _navigate_optimizer(self, testing: bool = False) -> None:
        """Navigate to charts explorer violations tab."""
        app_nav = getattr(self.app, "action_nav_optimizer", None)
        if callable(app_nav) and not testing:
            app_nav()
            return
        from kubeagle.screens.charts_explorer import ChartsExplorerScreen
        from kubeagle.screens.detail import OptimizerScreen

        current_screen = self.app.screen
        if isinstance(current_screen, ChartsExplorerScreen):
            return

        self.app.push_screen(
            OptimizerScreen(
                testing=testing,
                include_cluster=not getattr(self.app, "skip_eks", False),
            )
        )

    def _navigate_export(self) -> None:
        """Navigate to export screen."""
        app_nav = getattr(self.app, "action_nav_export", None)
        if callable(app_nav):
            app_nav()
            return
        from kubeagle.screens.reports import ReportExportScreen

        self.app.push_screen(ReportExportScreen())

    def _navigate_settings(self) -> None:
        """Navigate to settings screen."""
        app_nav = getattr(self.app, "action_nav_settings", None)
        if callable(app_nav):
            app_nav()
            return
        from kubeagle.screens.settings import SettingsScreen

        self.app.push_screen(SettingsScreen())

    def _navigate_recommendations(self) -> None:
        """Navigate to charts explorer violations/recommendations view."""
        app_nav = getattr(self.app, "action_nav_recommendations", None)
        if callable(app_nav):
            app_nav()
            return
        from kubeagle.screens.charts_explorer import ChartsExplorerScreen
        from kubeagle.screens.detail import OptimizerScreen

        current_screen = self.app.screen
        if isinstance(current_screen, ChartsExplorerScreen):
            current_screen.action_show_recommendations_tab()
            return

        self.app.push_screen(OptimizerScreen(initial_view="recommendations"))

    def action_nav_home(self) -> None:
        """Navigate to home screen."""
        self._navigate_home()

    def action_nav_cluster(self) -> None:
        """Navigate to cluster screen."""
        self._navigate_cluster()

    def action_nav_charts(self) -> None:
        """Navigate to charts screen."""
        self._navigate_charts()

    def action_nav_optimizer(self) -> None:
        """Navigate to optimizer screen."""
        self._navigate_optimizer()

    def action_nav_export(self) -> None:
        """Navigate to export screen."""
        self._navigate_export()

    def action_nav_settings(self) -> None:
        """Navigate to settings screen."""
        self._navigate_settings()

    def action_nav_recommendations(self) -> None:
        """Navigate to violations/recommendations view."""
        self._navigate_recommendations()

    def action_show_help(self) -> None:
        """Show help dialog."""
        self.app.notify(
            "Keybindings:\n"
            "  ESC - Back\n"
            "  r - Refresh\n"
            "  / - Search\n"
            "  H - Summary\n"
            "  C - Charts\n"
            "  Shift+R - Violations + Recommendations\n"
            "  E - Export\n"
            "  Ctrl+S - Settings\n"
            "  ? - Help",
            severity="information",
            timeout=30,
        )


# ============================================================================
# STANDALONE NAVIGATION FUNCTIONS
# ============================================================================

def navigate_to_home(app: App) -> None:
    """Navigate to primary landing screen (Cluster summary).

    Args:
        app: The Textual app instance.
    """
    app_nav = getattr(app, "action_nav_home", None)
    if callable(app_nav):
        app_nav()
        return
    from kubeagle.screens.cluster import ClusterScreen

    app.push_screen(ClusterScreen())


def navigate_to_cluster(app: App) -> None:
    """Navigate to cluster screen.

    Args:
        app: The Textual app instance.
    """
    app_nav = getattr(app, "action_nav_cluster", None)
    if callable(app_nav):
        app_nav()
        return
    from kubeagle.screens.cluster import ClusterScreen

    app.push_screen(ClusterScreen())


def navigate_to_charts(app: App, testing: bool = False) -> None:
    """Navigate to charts explorer screen.

    Args:
        app: The Textual app instance.
        testing: If True, creates screen in testing mode (skips worker).
    """
    app_nav = getattr(app, "action_nav_charts", None)
    if callable(app_nav) and not testing:
        app_nav()
        return
    from kubeagle.screens.charts_explorer import ChartsExplorerScreen

    current_screen = app.screen
    if isinstance(current_screen, ChartsExplorerScreen):
        current_screen.action_show_charts_tab()
        return

    app.push_screen(ChartsExplorerScreen(testing=testing))


def navigate_to_optimizer(app: App, testing: bool = False) -> None:
    """Navigate to charts explorer violations tab.

    Args:
        app: The Textual app instance.
        testing: If True, creates screen in testing mode (skips worker).
    """
    app_nav = getattr(app, "action_nav_optimizer", None)
    if callable(app_nav) and not testing:
        app_nav()
        return
    from kubeagle.screens.charts_explorer import ChartsExplorerScreen
    from kubeagle.screens.detail import OptimizerScreen

    current_screen = app.screen
    if isinstance(current_screen, ChartsExplorerScreen):
        return

    app.push_screen(
        OptimizerScreen(
            testing=testing,
            include_cluster=not getattr(app, "skip_eks", False),
        )
    )


def navigate_to_export(app: App) -> None:
    """Navigate to export screen.

    Args:
        app: The Textual app instance.
    """
    app_nav = getattr(app, "action_nav_export", None)
    if callable(app_nav):
        app_nav()
        return
    from kubeagle.screens.reports import ReportExportScreen

    app.push_screen(ReportExportScreen())


def navigate_to_settings(app: App) -> None:
    """Navigate to settings screen.

    Args:
        app: The Textual app instance.
    """
    app_nav = getattr(app, "action_nav_settings", None)
    if callable(app_nav):
        app_nav()
        return
    from kubeagle.screens.settings import SettingsScreen

    app.push_screen(SettingsScreen())


def navigate_to_recommendations(app: App) -> None:
    """Navigate to charts explorer violations/recommendations view.

    Args:
        app: The Textual app instance.
    """
    app_nav = getattr(app, "action_nav_recommendations", None)
    if callable(app_nav):
        app_nav()
        return
    from kubeagle.screens.charts_explorer import ChartsExplorerScreen
    from kubeagle.screens.detail import OptimizerScreen

    current_screen = app.screen
    if isinstance(current_screen, ChartsExplorerScreen):
        current_screen.action_show_recommendations_tab()
        return

    app.push_screen(OptimizerScreen(initial_view="recommendations"))


# ============================================================================
# SCREEN BINDINGS
# ============================================================================

BASE_SCREEN_BINDINGS: list[
    Annotated[tuple[str, str, str], "key, action, description"]
] = [
    ("escape", "pop_screen", "Back"),
    ("r", "refresh", "Refresh"),
    ("h", "nav_home", "Summary"),
    ("c", "nav_cluster", "Cluster"),
    ("C", "nav_charts", "Charts"),
    ("e", "nav_export", "Export"),
    ("ctrl+s", "nav_settings", "Settings"),
    ("?", "show_help", "Help"),
]

# ============================================================================
# Cluster Screen Bindings
# ============================================================================

CLUSTER_SCREEN_BINDINGS: list[
    Annotated[tuple[str, str, str], "key, action, description"]
] = [
    ("escape", "pop_screen", "Back"),
    ("r", "refresh", "Refresh"),
    ("slash", "focus_search", "Search"),
    ("1", "switch_tab_1", "Nodes"),
    ("2", "switch_tab_2", "Workloads"),
    ("3", "switch_tab_3", "Events"),
    ("?", "show_help", "Help"),
    ("h", "nav_home", "Summary"),
]

# ============================================================================
# Workloads Screen Bindings
# ============================================================================

WORKLOADS_SCREEN_BINDINGS: list[
    Annotated[tuple[str, str, str], "key, action, description"]
] = [
    ("escape", "pop_screen", "Back"),
    ("r", "refresh", "Refresh"),
    ("slash", "focus_search", "Search"),
    ("1", "switch_tab_1", "All"),
    ("2", "switch_tab_2", "Extreme"),
    ("3", "switch_tab_3", "Single Replica"),
    ("4", "switch_tab_4", "Missing PDB"),
    ("5", "switch_tab_5", "Node Analysis"),
    ("?", "show_help", "Help"),
    ("h", "nav_home", "Summary"),
]

# ============================================================================
# Settings Screen Bindings
# ============================================================================

SETTINGS_SCREEN_BINDINGS: list[
    Annotated[tuple[str, str, str], "key, action, description"]
] = [
    ("escape", "pop_screen", "Back"),
    ("ctrl+s", "save_settings", "Save"),
    ("ctrl+r", "reset_defaults", "Reset Defaults"),
    ("?", "show_help", "Help"),
    ("h", "nav_home", "Summary"),
    ("c", "nav_cluster", "Cluster"),
    ("C", "nav_charts", "Charts"),
    ("e", "nav_export", "Export"),
    ("r", "refresh", "Refresh"),
]

# ============================================================================
# Report Export Screen Bindings
# ============================================================================

REPORT_EXPORT_SCREEN_BINDINGS: list[
    Annotated[tuple[str, str, str], "key, action, description"]
] = [
    ("escape", "pop_screen", "Back"),
    ("r", "refresh", "Refresh"),
    ("ctrl+e", "export_report", "Export Report"),
    ("y", "copy_clipboard", "Copy (Yank)"),
    ("?", "show_help", "Help"),
    ("h", "nav_home", "Summary"),
    ("c", "nav_cluster", "Cluster"),
    ("C", "nav_charts", "Charts"),
]

# ============================================================================
# Detail Screen Bindings
# ============================================================================

CHART_DETAIL_SCREEN_BINDINGS: list[
    Annotated[tuple[str, str, str], "key, action, description"]
] = [
    ("escape", "pop_screen", "Back"),
    ("r", "refresh", "Refresh"),
    ("n", "next_chart", "Next"),
    ("p", "prev_chart", "Prev"),
    ("h", "nav_home", "Summary"),
    ("c", "nav_cluster", "Cluster"),
    ("C", "nav_charts", "Charts"),
    ("e", "nav_export", "Export"),
    ("ctrl+s", "nav_settings", "Settings"),
    ("?", "show_help", "Help"),
]

# ============================================================================
# Charts Explorer Screen Bindings
# ============================================================================

CHARTS_EXPLORER_SCREEN_BINDINGS: list[
    Annotated[tuple[str, str, str], "key, action, description"]
] = [
    ("escape", "pop_screen", "Back"),
    ("r", "refresh", "Refresh"),
    ("slash", "focus_search", "Search"),
    ("enter", "select_chart", "Preview Chart"),
    ("m", "toggle_mode", "Toggle Mode"),
    ("a", "toggle_active_filter", "Active Only"),
    ("1", "view_all", "All Charts"),
    ("2", "view_extreme", "Extreme Ratios"),
    ("3", "view_single_replica", "Single Replica"),
    ("4", "view_no_pdb", "Missing PDB"),
    ("5", "view_violations", "Violations"),
    ("s", "toggle_sort_direction", "Sort"),
    ("t", "cycle_team", "Team"),
    ("v", "view_team_violations", "Team Violations"),
    ("f", "fix_violation", "Fix Chart"),
    ("p", "preview_fix", "Preview"),
    ("y", "copy_yaml", "Copy YAML"),
    ("g", "go_to_chart", "Go to Chart"),
    ("x", "export_team_report", "Export Report"),
    ("h", "nav_home", "Summary"),
    ("c", "nav_cluster", "Cluster"),
    ("e", "nav_export", "Export"),
    ("ctrl+s", "nav_settings", "Settings"),
    ("?", "show_help", "Help"),
]

__all__ = [
    # Screen bindings
    "BASE_SCREEN_BINDINGS",
    "CHARTS_EXPLORER_SCREEN_BINDINGS",
    "CHART_DETAIL_SCREEN_BINDINGS",
    "CLUSTER_SCREEN_BINDINGS",
    "REPORT_EXPORT_SCREEN_BINDINGS",
    "SETTINGS_SCREEN_BINDINGS",
    "WORKLOADS_SCREEN_BINDINGS",
    # Screen Navigator
    "ScreenNavigator",
    "navigate_to_charts",
    "navigate_to_cluster",
    "navigate_to_export",
    # Navigation functions
    "navigate_to_home",
    "navigate_to_optimizer",
    "navigate_to_recommendations",
    "navigate_to_settings",
]
