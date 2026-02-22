"""CustomDataTable widget - standardized wrapper around Textual's DataTable."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from contextlib import asynccontextmanager, contextmanager, suppress
from typing import TYPE_CHECKING, Any, ClassVar

from textual.containers import Container
from textual.coordinate import Coordinate
from textual.events import Event, Leave, MouseMove
from textual.widgets import DataTable as TextualDataTable

from kubeagle.constants.limits import MAX_ROWS_DISPLAY
from kubeagle.keyboard import DATA_TABLE_BINDINGS

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from textual.app import ComposeResult


class CustomDataTable(Container):
    """Standardized data table wrapper around Textual's DataTable widget.

    Provides consistent styling and integration with the TUI design system.
    Wraps Textual's built-in DataTable widget with standardized CSS classes.

    CSS Classes: widget-custom-data-table

    Standard Reactive Pattern:
    - Provides is_loading, data, error reactives
    - Implements watch_* methods for UI updates

    Example:
        ```python
        from kubeagle.widgets.data.tables import CustomDataTable

        table = CustomDataTable(
            columns=[("Name", "name"), ("Version", "version")],
            id="my-table",
        )
        ```
    """

    CSS_PATH = "../../../css/widgets/custom_data_table.tcss"

    DEFAULT_CSS = """
    CustomDataTable {
        height: 1fr;
        width: 1fr;
        min-width: 0;
        min-height: 3;
        background: $surface;
    }
    CustomDataTable > DataTable {
        height: 1fr;
        width: 1fr;
        min-width: 0;
        border: none;
        background: transparent;
        overflow-x: auto;
        overflow-y: auto;
    }
    """

    BINDINGS = DATA_TABLE_BINDINGS

    _COLUMN_DEFS: ClassVar[list[tuple[str, str]]] = []
    _NUMERIC_COLUMNS: ClassVar[set[str]] = set()

    def __init__(
        self,
        columns: list[tuple[str, str]] | None = None,
        *,
        id: str | None = None,
        classes: str = "",
        disabled: bool = False,
        zebra_stripes: bool = False,
    ) -> None:
        """Initialize the custom data table wrapper.

        Args:
            columns: Optional list of (label, key) column definitions.
            id: Widget ID.
            classes: CSS classes (widget-custom-data-table is automatically added).
            disabled: Whether the data table is disabled.
            zebra_stripes: Whether to display alternating row colors.
        """
        super().__init__(id=id, classes=f"widget-custom-data-table {classes}".strip())
        self._columns = columns or []
        self._disabled = disabled
        self._zebra_stripes = zebra_stripes
        self._inner_widget: TextualDataTable | None = None

        # Standard reactive state
        self.is_loading: bool = False
        self.data: list[dict] = []
        self.error: str | None = None

        # Sort state
        self._sort_column: str | None = None
        self._sort_reverse: bool = False
        self._header_tooltips: dict[str, str] = {}
        self._default_tooltip: str | None = None

    def compose(self) -> ComposeResult:
        """Compose the data table with Textual's DataTable widget."""
        table = TextualDataTable(
            disabled=self._disabled,
            cursor_type="row",
        )
        table.styles.scrollbar_size_horizontal = 1
        table.styles.scrollbar_size_vertical = 2
        self._inner_widget = table
        yield table

        # Set zebra_stripes after widget is created (not a constructor param)
        table.zebra_stripes = self._zebra_stripes

        # Add columns after widget is created
        if self._columns:
            for label, key in self._columns:
                self.add_column(label, key=key)

    @property
    def data_table(self) -> TextualDataTable | None:
        """Get the underlying Textual DataTable widget.

        Returns:
            The composed Textual DataTable widget, or None if not yet composed.
        """
        return self._inner_widget

    @asynccontextmanager
    async def batch(self):
        """Async proxy for the inner DataTable's batch_update() context manager.

        Yields:
            The inner widget's batch context, or a no-op context if inner widget is not ready.
        """
        batch_update = (
            getattr(self._inner_widget, "batch_update", None)
            if self._inner_widget is not None
            else None
        )
        if callable(batch_update):
            with batch_update():
                yield
        else:
            yield

    @contextmanager
    def batch_update(self):
        """Sync proxy for the inner DataTable's batch_update() context manager."""
        batch_update = (
            getattr(self._inner_widget, "batch_update", None)
            if self._inner_widget is not None
            else None
        )
        if callable(batch_update):
            with batch_update():
                yield
        else:
            yield

    def set_loading(self, loading: bool) -> None:
        """Set the loading state on the inner DataTable.

        Args:
            loading: The new loading state.
        """
        if self._inner_widget is not None:
            self._inner_widget.loading = loading

    @property
    def disabled(self) -> bool:
        """Get the disabled state.

        Returns:
            True if disabled, False otherwise.
        """
        if self._inner_widget is None:
            return self._disabled
        return self._inner_widget.disabled

    @disabled.setter
    def disabled(self, val: bool) -> None:
        """Set the disabled state.

        Args:
            val: New disabled state.
        """
        self._disabled = val
        if self._inner_widget is not None:
            self._inner_widget.disabled = val

    @property
    def zebra_stripes(self) -> bool:
        """Get the zebra stripes state.

        Returns:
            True if zebra stripes are enabled, False otherwise.
        """
        return self._zebra_stripes

    @zebra_stripes.setter
    def zebra_stripes(self, value: bool) -> None:
        """Set the zebra stripes state.

        Args:
            value: New zebra stripes state.
        """
        self._zebra_stripes = value
        if self._inner_widget is not None:
            self._inner_widget.zebra_stripes = value

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

    def add_column(
        self,
        label: Any,
        *,
        width: int | None = None,
        key: str | None = None,
    ) -> Any:
        """Add a column to the data table.

        Args:
            label: Column label.
            width: Deprecated. Columns are added using auto-width behavior.
            key: Column key.

        Returns:
            The column key.
        """
        column_key = str(key) if key is not None else str(label)
        _ = width

        if not any(existing_key == column_key for _, existing_key in self._columns):
            self._columns.append((str(label), column_key))

        if self._inner_widget is not None:
            return self._inner_widget.add_column(
                label,
                width=None,
                key=column_key,
            )
        return None

    def add_row(self, *args: Any, **kwargs: Any) -> Any:
        """Add a row to the data table.

        Args:
            *args: Row values.
            **kwargs: Row values as keyword arguments.

        Returns:
            The row key, or None if MAX_ROWS_DISPLAY exceeded.
        """
        if self._inner_widget is not None:
            if self._inner_widget.row_count >= MAX_ROWS_DISPLAY:
                return None
            return self._inner_widget.add_row(*args, **kwargs)
        return None

    def add_rows(self, rows: Iterable[Iterable[Any]]) -> list[Any]:
        """Add multiple rows to the data table in one call."""
        if self._inner_widget is not None:
            # Materialize to list so we can check length and truncate.
            materialized: list[Iterable[Any]] = list(rows)
            if len(materialized) > MAX_ROWS_DISPLAY:
                logger.warning("Truncating %d rows to %d", len(materialized), MAX_ROWS_DISPLAY)
                materialized = materialized[:MAX_ROWS_DISPLAY]
            return self._inner_widget.add_rows(materialized)
        return []

    def clear(self, columns: bool = False) -> None:
        """Clear all rows from the data table.

        Args:
            columns: If True, also clear column definitions. Default is False.
        """
        if columns:
            self._columns = []
        if self._inner_widget is not None:
            self._inner_widget.clear(columns=columns)

    def set_header_tooltips(self, tooltips: Mapping[str, str] | None = None) -> None:
        """Set per-column header tooltip text.

        Args:
            tooltips: Mapping of visible column label -> tooltip text.
        """
        self._header_tooltips = {
            str(column_label): str(tooltip_text)
            for column_label, tooltip_text in (tooltips or {}).items()
            if str(tooltip_text).strip()
        }
        if not self._header_tooltips and self._inner_widget is not None:
            self._inner_widget.tooltip = self._default_tooltip

    def set_default_tooltip(self, tooltip: str | None) -> None:
        """Set default tooltip shown for non-header hover areas.

        Args:
            tooltip: Tooltip text for body hover, or None to disable.
        """
        self._default_tooltip = str(tooltip) if tooltip else None
        if self._inner_widget is not None:
            self._inner_widget.tooltip = self._default_tooltip

    def _column_label_at_index(self, column_index: int) -> str | None:
        """Return a visible column label for the given index."""
        if column_index < 0:
            return None

        if self._inner_widget is not None:
            with suppress(Exception):
                ordered_columns = list(self._inner_widget.ordered_columns)
                if column_index < len(ordered_columns):
                    label = ordered_columns[column_index].label
                    plain = getattr(label, "plain", None)
                    return str(plain) if plain is not None else str(label)

        if column_index < len(self._columns):
            return self._columns[column_index][0]
        return None

    def _resolve_header_tooltip(
        self, meta: Mapping[str, Any] | None,
    ) -> str | None:
        """Return tooltip text when hovering a configured header cell."""
        if not self._header_tooltips or not meta:
            return None

        row_index = meta.get("row")
        column_index = meta.get("column")
        if row_index != -1 or not isinstance(column_index, int):
            return None

        column_label = self._column_label_at_index(column_index)
        if column_label is None:
            return None
        return self._header_tooltips.get(column_label)

    def clear_safe(self, columns: bool = False) -> None:
        """Safely clear the table, resetting cursor position.

        Args:
            columns: If True, also clear column definitions. Default is False.
        """
        if self._inner_widget is None:
            return

        table = self._inner_widget
        saved_cursor_type = table.cursor_type
        with suppress(Exception):
            table.cursor_type = "none"

        with suppress(Exception):
            table.cursor_coordinate = Coordinate(0, 0)

        with suppress(Exception):
            self.clear(columns=columns)

        with suppress(Exception):
            table.cursor_coordinate = Coordinate(0, 0)

        with suppress(Exception):
            table.cursor_type = saved_cursor_type

    def sort(
        self,
        column_key: str,
        *,
        reverse: bool = False,
    ) -> None:
        """Sort the table by column.

        Args:
            column_key: The column key to sort by.
            reverse: If True, sort in descending order.
        """
        if self._inner_widget is not None:
            self._inner_widget.sort(column_key, reverse=reverse)

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
            if self._columns:
                default_column = self._columns[0][1]
                self.sort_by_column(default_column, reverse=False)
        else:
            self.sort_by_column(self._sort_column, not self._sort_reverse)

    def _get_column_label(self, column_key: str, original_label: str) -> str:
        """Get column label with sort indicator.

        Args:
            column_key: The column key.
            original_label: The original column label.

        Returns:
            Label with sort indicator if sorted.
        """
        if self._sort_column == column_key:
            indicator = " [+]" if not self._sort_reverse else " [-]"
            return f"{original_label}{indicator}"
        return original_label

    @property
    def row_count(self) -> int:
        """Get the number of rows.

        Returns:
            Number of rows in the table.
        """
        if self._inner_widget is not None:
            return self._inner_widget.row_count
        return 0

    @property
    def rows(self) -> Any:
        """Get the rows dictionary.

        Returns:
            Rows dictionary from the inner widget.
        """
        if self._inner_widget is not None:
            return self._inner_widget.rows
        return {}

    @property
    def columns(self) -> Any:
        """Get the columns dictionary.

        Returns:
            Columns dictionary from the inner widget.
        """
        if self._inner_widget is not None:
            return self._inner_widget.columns
        return {}

    @property
    def cursor_row(self) -> int | None:
        """Get the current cursor row.

        Returns:
            Cursor row index or None.
        """
        if self._inner_widget is not None:
            coord = self._inner_widget.cursor_coordinate
            if coord is not None:
                return coord.row
        return None

    @cursor_row.setter
    def cursor_row(self, row: int | None) -> None:
        """Set the cursor row.

        Args:
            row: Row index or None.
        """
        if self._inner_widget is not None and row is not None:
            with suppress(Exception):
                max_row = self._inner_widget.row_count - 1
                safe_row = max(0, min(row, max_row))
                self._inner_widget.cursor_coordinate = Coordinate(safe_row, 0)

    def get_row_data(self, index: int) -> tuple[Any, ...] | None:
        """Get row data at a specific index.

        Args:
            index: The row index.

        Returns:
            Row data tuple or None if index is out of range.
        """
        if self._inner_widget is None or index < 0:
            return None
        with suppress(Exception):
            for i, row in enumerate(self._inner_widget.ordered_rows):
                if i == index:
                    return self._extract_row_data(row)
                if i > index:
                    break
        return None

    def _extract_row_data(self, row: Any) -> tuple[Any, ...]:
        """Extract tuple data from a row object.

        Args:
            row: Row object from ordered_rows.

        Returns:
            Tuple of row values.
        """
        if hasattr(row, '_data'):
            return row._data
        # If it's already a tuple, return it
        if isinstance(row, tuple):
            return row
        # Fallback: try to convert to tuple
        return tuple(row)

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

    def on_data_table_header_selected(self, event: TextualDataTable.HeaderSelected) -> None:
        """Handle DataTable header click events (sorting disabled)."""
        self.on_column_selected(event)

    def on_data_table_column_selected(self, event: TextualDataTable.ColumnSelected) -> None:
        """Handle DataTable column select events (sorting disabled)."""
        self.on_column_selected(event)

    def on_mouse_move(self, event: MouseMove) -> None:
        """Update table tooltip when hovering configured header cells."""
        table = self._inner_widget
        if table is None:
            return
        style = getattr(event, "style", None)
        meta = getattr(style, "meta", None)
        new_tooltip = self._resolve_header_tooltip(meta) or self._default_tooltip
        if new_tooltip != getattr(self, "_last_tooltip", None):
            self._last_tooltip = new_tooltip
            table.tooltip = new_tooltip

    def on_leave(self, _: Leave) -> None:
        """Clear tooltip when leaving the table wrapper."""
        self._last_tooltip = None
        if self._inner_widget is not None:
            self._inner_widget.tooltip = None

    def get_row_key_at(self, index: int) -> Any:
        """Get the row key at a specific index.

        Args:
            index: The row index.

        Returns:
            The RowKey at the given index, or None if unavailable.
        """
        if self._inner_widget is None or index < 0:
            return None
        try:
            for i, row in enumerate(self._inner_widget.ordered_rows):
                if i == index:
                    return row.key
        except Exception:
            return None
        return None

    class RowSelected(Event):
        """Event emitted when a row is selected."""

        def __init__(self, data_table: CustomDataTable) -> None:
            """Initialize the RowSelected event.

            Args:
                data_table: The data table that emitted the event.
            """
            super().__init__()
            self.data_table = data_table
