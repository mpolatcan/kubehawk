"""Widgets module for the KubEagle TUI.

This module provides all reusable widgets organized into submodules:
- containers: Container widgets (CustomCollapsible, CustomContainer)
- data: Data display widgets (tables, KPI)
- display: Display widgets (CustomDigits, CustomMarkdownViewer, CustomProgressBar, CustomRichLog, CustomStatic)
- feedback: Button, dialogs
- input: Input widgets (CustomInput, CustomTextArea)
- selection: Selection widgets (CustomRadioSet, CustomSelect, CustomSelectionList, CustomSwitch)
- special: Specialized widgets (CustomTree)
- structure: Structure widgets (CustomFooter, CustomHeader)
- tabs: Tab widgets (CustomTab, CustomTabs, CustomTabbedContent, CustomTabPane)
"""

# Base classes
from kubeagle.widgets._base import (
    BaseWidget,
    StatefulWidget,
)

# Container widgets
from kubeagle.widgets.containers import (
    CustomCollapsible,
    CustomContainer,
    CustomHorizontal,
    CustomVertical,
)

# Data display widgets
from kubeagle.widgets.data import (
    CustomDataTable,
    CustomKPI,
    CustomTableBase,
    CustomTableMixin,
)

# Display widgets
from kubeagle.widgets.display import (
    CustomDigits,
    CustomMarkdownViewer,
    CustomProgressBar,
    CustomRichLog,
    CustomStatic,
)

# Feedback widgets
from kubeagle.widgets.feedback import (
    CustomButton,
    CustomConfirmDialog,
    CustomLoadingIndicator,
)

# Input widgets
from kubeagle.widgets.input import (
    CustomInput,
    CustomTextArea,
)

# Selection widgets
from kubeagle.widgets.selection import (
    CustomRadioSet,
    CustomSelect,
    CustomSelectionList,
    CustomSwitch,
)

# Special widgets
from kubeagle.widgets.special import (
    CustomTree,
)

# Structure widgets
from kubeagle.widgets.structure import (
    CustomFooter,
    CustomHeader,
)

# Tab widgets
from kubeagle.widgets.tabs import (
    CustomTab,
    CustomTabbedContent,
    CustomTabPane,
    CustomTabs,
)

__all__ = [
    # Base classes
    "BaseWidget",
    # Feedback
    "CustomButton",
    "CustomCollapsible",
    "CustomConfirmDialog",
    # Containers
    "CustomContainer",
    "CustomDataTable",
    "CustomDigits",
    "CustomFooter",
    # Structure
    "CustomHeader",
    "CustomHorizontal",
    # Input
    "CustomInput",
    # KPI
    "CustomKPI",
    "CustomLoadingIndicator",
    "CustomMarkdownViewer",
    "CustomProgressBar",
    # Selection
    "CustomRadioSet",
    "CustomRichLog",
    "CustomSelect",
    "CustomSelectionList",
    # Display
    "CustomStatic",
    "CustomSwitch",
    # Tabs
    "CustomTab",
    "CustomTabPane",
    "CustomTabbedContent",
    # Data tables
    "CustomTableBase",
    "CustomTableMixin",
    "CustomTabs",
    "CustomTextArea",
    "CustomTree",
    "CustomVertical",
    "StatefulWidget",
]
