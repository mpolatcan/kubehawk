"""Tab widgets for KubEagle TUI.

This module provides tab-based navigation widgets:
- CustomTab: Single tab widget
- CustomTabs: Tab navigation container
- CustomTabbedContent: Tabbed content container
- CustomTabPane: Individual tab pane content
"""

from kubeagle.widgets.tabs.custom_tab_pane import CustomTabPane
from kubeagle.widgets.tabs.custom_tabbed_content import CustomTabbedContent
from kubeagle.widgets.tabs.custom_tabs import CustomTab, CustomTabs

__all__ = [
    "CustomTab",
    "CustomTabPane",
    "CustomTabbedContent",
    "CustomTabs",
]
