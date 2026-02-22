"""CustomTableBase - base class for DataTable widgets with sortable column functionality.

This module provides CustomTableBase which can be inherited directly.
For backward compatibility, CustomTableMixin is kept as an alias.

Use CustomTableBase for new implementations.
The sort utilities here provide column sorting functionality for DataTable widgets.

CSS Classes: widget-custom-table
"""

from __future__ import annotations

from contextlib import contextmanager, suppress
from typing import Any, ClassVar

from textual.coordinate import Coordinate
from textual.widgets import DataTable

from kubeagle.keyboard import DATA_TABLE_BINDINGS


class CustomTableBase(DataTable):
    """Base class providing sortable column functionality for DataTable widgets.

    This is the non-deprecated base class for table widgets.
    Inherit from this class directly for new implementations.

    CSS Classes: widget-custom-table

    Standard Reactive Pattern:
    - Provides is_loading, data, error reactives
    - Implements watch_* methods for UI updates
    """

    BINDINGS = DATA_TABLE_BINDINGS

    # Standard reactive attributes for data loading
    is_loading: Any = False
    data: Any = []
    error: Any = None

    _COLUMN_DEFS: ClassVar[list[tuple[str, str]]] = []
    _NUMERIC_COLUMNS: ClassVar[set[str]] = set()
    _DEFAULT_CLASSES: ClassVar[str] = "widget-custom-table"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the custom table base."""
        self._sort_column: str | None = None
        self._sort_reverse: bool = False
        # Apply default classes if not provided
        if "classes" not in kwargs or not kwargs.get("classes"):
            kwargs["classes"] = self._DEFAULT_CLASSES
        super().__init__(*args, **kwargs)

    @contextmanager
    def batch_update(self):
        """Sync context manager that batches app updates to avoid intermediate repaints."""
        try:
            app_batch = self.app.batch_update()
        except Exception:
            yield
            return
        with app_batch:
            yield

    def add_column(
        self,
        label: Any,
        *,
        width: int | None = None,
        key: str | None = None,
        default: Any | None = None,
    ) -> Any:
        """Add a column using Textual DataTable auto-width behavior."""
        column_key = str(key) if key is not None else str(label)
        _ = width
        return super().add_column(
            label,
            width=None,
            key=column_key,
            default=default,
        )

    def watch_is_loading(self, loading: bool) -> None:
        """Update UI based on loading state.

        Args:
            loading: The new loading state.
        """
        pass

    def watch_data(self, data: list[dict]) -> None:
        """Update UI when data changes only if content actually changed.

        Args:
            data: The new data value.
        """
        new_sig = (id(data), len(data) if data else 0)
        if getattr(self, "_last_data_signature", None) != new_sig:
            self._last_data_signature = new_sig
            self.refresh()

    def watch_error(self, error: str | None) -> None:
        """Handle error state changes.

        Args:
            error: The error message or None if cleared.
        """
        pass

    def clear_safe(self) -> None:
        """Safely clear the table, resetting cursor position."""
        saved_cursor_type = self.cursor_type
        with suppress(Exception):
            self.cursor_type = "none"

        with suppress(Exception):
            self.cursor_coordinate = Coordinate(0, 0)

        with suppress(Exception):
            self.clear()

        with suppress(Exception):
            self.cursor_coordinate = Coordinate(0, 0)

        with suppress(Exception):
            self.cursor_type = saved_cursor_type

    def _get_column_label(self, column_key: str, original_label: str) -> str:
        """Get column label with sort indicator."""
        if self._sort_column == column_key:
            return f"{original_label} [+]" if not self._sort_reverse else f"{original_label} [-]"
        return original_label

    def _column_index_map(self) -> dict[str, int]:
        """Return a cached mapping from column key to column index."""
        cache = getattr(self, "_col_idx_cache", None)
        if cache is None:
            cache = {key: i for i, (_, key) in enumerate(self._COLUMN_DEFS)}
            self._col_idx_cache: dict[str, int] = cache
        return cache

    def _sort_value(
        self, row_data: tuple[Any, ...], column_key: str
    ) -> tuple[Any, ...]:
        """Extract sort key from row data, handling numeric columns."""
        column_index = self._column_index_map().get(column_key)

        if column_index is None or column_index >= len(row_data):
            return row_data

        value = row_data[column_index]
        if column_key in self._NUMERIC_COLUMNS:
            try:
                return (float(value), row_data)
            except (ValueError, TypeError):
                return (float("inf"), row_data)
        return (str(value).lower(), row_data)

    def sort_by_column(self, column_key: str, reverse: bool = False) -> None:
        """Sort table by column.

        Args:
            column_key: The column key to sort by.
            reverse: If True, sort in descending order.
        """
        self._sort_column = column_key
        self._sort_reverse = reverse
        self.sort(column_key, reverse=reverse)

    def action_toggle_sort(self) -> None:
        """Toggle sort on current column or default column."""
        if self._sort_column is None:
            if self._COLUMN_DEFS:
                default_column = self._COLUMN_DEFS[0][1]
                self.sort_by_column(default_column, reverse=False)
        else:
            self.sort_by_column(self._sort_column, not self._sort_reverse)

    def on_column_selected(self, event: Any) -> None:
        """Handle column clicks.

        Column header click sorting is intentionally disabled. We still consume
        the event to avoid bubbling side effects.
        """
        stop = getattr(event, "stop", None)
        if callable(stop):
            stop()
        prevent_default = getattr(event, "prevent_default", None)
        if callable(prevent_default):
            prevent_default()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle header selection (sorting disabled)."""
        self.on_column_selected(event)

    def on_data_table_column_selected(self, event: DataTable.ColumnSelected) -> None:
        """Handle column selection (sorting disabled)."""
        self.on_column_selected(event)


# Backward compatibility alias - deprecated, use CustomTableBase instead
CustomTableMixin = CustomTableBase
