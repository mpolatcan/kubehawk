"""Display widgets for KubEagle TUI.

This module provides display widgets that show content:
- CustomDigits: Numeric display widget
- CustomMarkdownViewer: Scrollable markdown viewer widget
- CustomProgressBar: Progress indicator widget
- CustomRichLog: Rich log display widget
- CustomStatic: Static text display widget
"""

from kubeagle.widgets.display.custom_digits import CustomDigits
from kubeagle.widgets.display.custom_markdown_viewer import (
    CustomMarkdownViewer,
)
from kubeagle.widgets.display.custom_progress_bar import (
    CustomProgressBar,
)
from kubeagle.widgets.display.custom_rich_log import CustomRichLog
from kubeagle.widgets.display.custom_static import CustomStatic

__all__ = [
    "CustomDigits",
    "CustomMarkdownViewer",
    "CustomProgressBar",
    "CustomRichLog",
    "CustomStatic",
]
