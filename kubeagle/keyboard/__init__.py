"""Keyboard bindings module.

This module provides all keyboard bindings for the KubEagle TUI.
Bindings are organized into three categories:

- app: App-level bindings (APP_BINDINGS)
- navigation: Screen-specific bindings (*_SCREEN_BINDINGS)
- tables: DataTable bindings (DATA_TABLE_BINDINGS)
"""

from kubeagle.keyboard.app import APP_BINDINGS
from kubeagle.keyboard.navigation import (
    BASE_SCREEN_BINDINGS,
    CHART_DETAIL_SCREEN_BINDINGS,
    CHARTS_EXPLORER_SCREEN_BINDINGS,
    CLUSTER_SCREEN_BINDINGS,
    REPORT_EXPORT_SCREEN_BINDINGS,
    SETTINGS_SCREEN_BINDINGS,
    WORKLOADS_SCREEN_BINDINGS,
)
from kubeagle.keyboard.tables import DATA_TABLE_BINDINGS

__all__ = [
    "APP_BINDINGS",
    # Screen-specific bindings
    "BASE_SCREEN_BINDINGS",
    "CHARTS_EXPLORER_SCREEN_BINDINGS",
    "CHART_DETAIL_SCREEN_BINDINGS",
    "CLUSTER_SCREEN_BINDINGS",
    # Table bindings
    "DATA_TABLE_BINDINGS",
    "REPORT_EXPORT_SCREEN_BINDINGS",
    "SETTINGS_SCREEN_BINDINGS",
    "WORKLOADS_SCREEN_BINDINGS",
]
