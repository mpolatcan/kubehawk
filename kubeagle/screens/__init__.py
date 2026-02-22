"""KubEagle TUI Screens.

This package contains all screen modules for the TUI application.

Domain Structure:
    - charts_explorer/ - Unified charts browser (replaces charts/ and teams/)
    - cluster/        - Cluster overview and analysis
    - workloads/      - Runtime workloads inventory and coverage
    - reports/        - Report export
    - detail/         - Chart detail views and shared detail components
    - settings/       - Settings screen
    - mixins/         - Reusable screen mixins

Note: Navigation and keybindings are now in the keyboard/ package:
    - kubeagle.keyboard.navigation - ScreenNavigator and navigate_* functions
    - kubeagle.keyboard.*_SCREEN_BINDINGS - Keybinding constants

Example Usage:
    from kubeagle.screens.charts_explorer import ChartsExplorerScreen
    from kubeagle.screens.cluster import ClusterScreen
    from kubeagle.keyboard.navigation import navigate_to_charts
"""

from __future__ import annotations

# Keybindings (re-export for convenience)
from kubeagle.keyboard import BASE_SCREEN_BINDINGS
from kubeagle.keyboard.navigation import (
    CHART_DETAIL_SCREEN_BINDINGS,
    CHARTS_EXPLORER_SCREEN_BINDINGS,
    CLUSTER_SCREEN_BINDINGS,
    REPORT_EXPORT_SCREEN_BINDINGS,
    SETTINGS_SCREEN_BINDINGS,
    ScreenNavigator,
    navigate_to_charts,
    navigate_to_cluster,
    navigate_to_export,
    navigate_to_home,
    navigate_to_optimizer,
    navigate_to_recommendations,
    navigate_to_settings,
)
from kubeagle.screens.base_screen import BaseScreen

# Charts Explorer domain (replaces charts/ and teams/)
from kubeagle.screens.charts_explorer import ChartsExplorerScreen

# Cluster domain
from kubeagle.screens.cluster import ClusterScreen

# Detail domain
from kubeagle.screens.detail import ChartDetailScreen

# Reports domain
from kubeagle.screens.reports import ReportExportScreen

# Settings domain
from kubeagle.screens.settings import SettingsScreen

# Workloads domain
from kubeagle.screens.workloads import WorkloadsScreen

__all__ = [
    # Keybindings
    "BASE_SCREEN_BINDINGS",
    "CHARTS_EXPLORER_SCREEN_BINDINGS",
    "CHART_DETAIL_SCREEN_BINDINGS",
    "CLUSTER_SCREEN_BINDINGS",
    "REPORT_EXPORT_SCREEN_BINDINGS",
    "SETTINGS_SCREEN_BINDINGS",
    # Base
    "BaseScreen",
    # Detail
    "ChartDetailScreen",
    # Charts Explorer
    "ChartsExplorerScreen",
    # Cluster
    "ClusterScreen",
    "OptimizerScreen",
    # Reports
    "ReportExportScreen",
    # Navigation
    "ScreenNavigator",
    # Settings
    "SettingsScreen",
    # Workloads
    "WorkloadsScreen",
    "navigate_to_charts",
    "navigate_to_cluster",
    "navigate_to_export",
    "navigate_to_home",
    "navigate_to_optimizer",
    "navigate_to_recommendations",
    "navigate_to_settings",
]


def __getattr__(name: str):
    if name == "OptimizerScreen":
        from kubeagle.screens.detail import OptimizerScreen

        return OptimizerScreen
    raise AttributeError(name)
