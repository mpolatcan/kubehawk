"""Data table widgets for the TUI application."""

from kubeagle.widgets.data.tables.custom_data_table import CustomDataTable
from kubeagle.widgets.data.tables.custom_table import (
    CustomTableBase,
    CustomTableMixin,
)

__all__ = [
    "CustomDataTable",
    "CustomTableBase",
    "CustomTableMixin",
]
