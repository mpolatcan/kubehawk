"""Detail view screens package."""

from __future__ import annotations

from kubeagle.screens.detail.chart_detail_screen import (
    ChartDetailScreen,
)
from kubeagle.screens.detail.config import (
    FIXES_TABLE_COLUMNS,
    TAB_FIXES,
    TAB_TITLES,
    TAB_VIOLATIONS,
    VIOLATIONS_TABLE_COLUMNS,
)

__all__ = [
    "FIXES_TABLE_COLUMNS",
    "TAB_FIXES",
    "TAB_TITLES",
    "TAB_VIOLATIONS",
    "VIOLATIONS_TABLE_COLUMNS",
    "ChartDetailScreen",
    "OptimizerScreen",
]


def __getattr__(name: str):
    if name == "OptimizerScreen":
        from kubeagle.screens.detail.optimizer_screen import (
            OptimizerScreen,
        )

        return OptimizerScreen
    raise AttributeError(name)
