"""Data display widgets for the TUI application."""

from kubeagle.widgets.data.kpi import CustomKPI
from kubeagle.widgets.data.tables import (
    CustomDataTable,
    CustomTableBase,
    CustomTableMixin,
)

__all__ = [
    "CustomDataTable",
    "CustomKPI",
    "CustomTableBase",
    "CustomTableMixin",
]
