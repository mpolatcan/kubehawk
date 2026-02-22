"""Tests for CustomTableBase widget.

Tests cover:
- CustomTableBase instantiation and inheritance
- Reactive property changes (is_loading, data, error)
- Sorting functionality
- Clear safe methods
- Column definitions and labels

The CustomTableBase is the base class for all table widgets.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from textual.widgets import DataTable

from kubeagle.widgets.data.tables.custom_table import (
    CustomTableBase,
    CustomTableMixin,
)

# =============================================================================
# CustomTableBase Widget Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestCustomTableBase:
    """Tests for CustomTableBase widget."""

    def test_custom_table_inherits_data_table(self) -> None:
        """Test CustomTableBase inherits from DataTable."""
        table = CustomTableBase()
        assert isinstance(table, DataTable)

    def test_custom_table_has_bindings(self) -> None:
        """Test CustomTableBase has DATA_TABLE_BINDINGS."""
        table = CustomTableBase()
        assert hasattr(table, "BINDINGS")
        assert table.BINDINGS is not None

    def test_custom_table_is_loading_reactive(self) -> None:
        """Test is_loading reactive attribute."""
        table = CustomTableBase()
        assert hasattr(table, "is_loading")

    def test_custom_table_data_reactive(self) -> None:
        """Test data reactive attribute."""
        table = CustomTableBase()
        assert hasattr(table, "data")

    def test_custom_table_error_reactive(self) -> None:
        """Test error reactive attribute."""
        table = CustomTableBase()
        assert hasattr(table, "error")

    def test_custom_table_column_defs_empty(self) -> None:
        """Test column definitions are empty by default."""
        table = CustomTableBase()
        assert table._COLUMN_DEFS == []

    def test_custom_table_numeric_columns_empty(self) -> None:
        """Test numeric columns set is empty by default."""
        table = CustomTableBase()
        assert set() == table._NUMERIC_COLUMNS

    def test_custom_table_clear_safe_method_exists(self) -> None:
        """Test clear_safe method exists."""
        table = CustomTableBase()
        assert hasattr(table, "clear_safe")
        assert callable(table.clear_safe)

    def test_custom_table_sort_by_column_method_exists(self) -> None:
        """Test sort_by_column method exists."""
        table = CustomTableBase()
        assert hasattr(table, "sort_by_column")
        assert callable(table.sort_by_column)

    def test_custom_table_action_toggle_sort_method_exists(self) -> None:
        """Test action_toggle_sort method exists."""
        table = CustomTableBase()
        assert hasattr(table, "action_toggle_sort")
        assert callable(table.action_toggle_sort)

    def test_custom_table_column_resize_actions_removed(self) -> None:
        """Manual column resize actions should not exist."""
        table = CustomTableBase()
        assert not hasattr(table, "action_previous_column")
        assert not hasattr(table, "action_next_column")
        assert not hasattr(table, "action_shrink_column")
        assert not hasattr(table, "action_expand_column")
        assert not hasattr(table, "action_reset_column_widths")

    def test_on_column_selected_does_not_update_sort_state(self) -> None:
        """Column selections should be ignored when header sort is disabled."""
        table = CustomTableBase()

        class MockEvent:
            column_key = "name"

            def __init__(self) -> None:
                self.stopped = False
                self.prevented = False

            def stop(self) -> None:
                self.stopped = True

            def prevent_default(self) -> None:
                self.prevented = True

        event = MockEvent()
        table.on_column_selected(event)

        assert table._sort_column is None
        assert table._sort_reverse is False
        assert event.stopped is True
        assert event.prevented is True


@pytest.mark.unit
@pytest.mark.fast
class TestCustomTableBaseColumnWidthBehavior:
    """Tests for auto-width behavior in CustomTableBase.add_column."""

    def test_add_column_uses_auto_width(self) -> None:
        """Configured widths should be ignored in favor of auto-width."""
        table = CustomTableBase()
        with patch.object(DataTable, "add_column", return_value="name") as add_column_mock:
            table.add_column("Name", width=12, key="name")

        add_column_mock.assert_called_once_with(
            "Name",
            width=None,
            key="name",
            default=None,
        )


@pytest.mark.unit
@pytest.mark.asyncio
class TestCustomTableBaseReactive:
    """Tests for CustomTableBase reactive property changes."""

    async def test_watch_is_loading_does_not_raise(self) -> None:
        """Test watch_is_loading handles changes without error."""
        table = CustomTableBase()
        table.watch_is_loading(True)
        table.watch_is_loading(False)

    async def test_watch_data_does_not_raise(self) -> None:
        """Test watch_data handles changes without error."""
        table = CustomTableBase()
        test_data = [{"Name": "test"}]
        table.watch_data(test_data)

    async def test_watch_error_handles_none(self) -> None:
        """Test watch_error handles None value."""
        table = CustomTableBase()
        table.watch_error(None)

    async def test_watch_error_handles_message(self) -> None:
        """Test watch_error handles error message."""
        table = CustomTableBase()
        table.watch_error("Error occurred")


# =============================================================================
# CustomTableMixin Backward Compatibility Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestCustomTableMixin:
    """Tests for CustomTableMixin backward compatibility."""

    def test_custom_table_mixin_is_custom_table_base(self) -> None:
        """Test CustomTableMixin is alias for CustomTableBase."""
        assert CustomTableMixin is CustomTableBase


# =============================================================================
# Column Label Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestGetColumnLabel:
    """Tests for _get_column_label method."""

    def test_get_column_label_no_sort(self) -> None:
        """Test column label without sort."""
        table = CustomTableBase()
        label = table._get_column_label("name", "Name")
        assert label == "Name"

    def test_get_column_label_sorted_ascending(self) -> None:
        """Test column label when sorted ascending."""
        table = CustomTableBase()
        table._sort_column = "name"
        table._sort_reverse = False
        label = table._get_column_label("name", "Name")
        assert label == "Name [+]"

    def test_get_column_label_sorted_descending(self) -> None:
        """Test column label when sorted descending."""
        table = CustomTableBase()
        table._sort_column = "name"
        table._sort_reverse = True
        label = table._get_column_label("name", "Name")
        assert label == "Name [-]"


# =============================================================================
# Sort Value Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestSortValue:
    """Tests for _sort_value method."""

    def test_sort_value_string_column(self) -> None:
        """Test sort value for string column."""
        table = CustomTableBase()
        # Use object.__setattr__ to assign to ClassVar for testing
        object.__setattr__(table, "_COLUMN_DEFS", [("Name", "name")])
        row = ("test",)
        result = table._sort_value(row, "name")
        assert isinstance(result, tuple)

    def test_sort_value_numeric_column(self) -> None:
        """Test sort value for numeric column."""
        table = CustomTableBase()
        # Use object.__setattr__ to assign to ClassVar for testing
        object.__setattr__(table, "_NUMERIC_COLUMNS", {"value"})
        object.__setattr__(table, "_COLUMN_DEFS", [("Value", "value")])
        row = (42,)
        result = table._sort_value(row, "value")
        assert isinstance(result, tuple)
        assert result[0] == 42.0

    def test_sort_value_numeric_column_invalid(self) -> None:
        """Test sort value for invalid numeric column."""
        table = CustomTableBase()
        # Use object.__setattr__ to assign to ClassVar for testing
        object.__setattr__(table, "_NUMERIC_COLUMNS", {"value"})
        object.__setattr__(table, "_COLUMN_DEFS", [("Value", "value")])
        row = ("invalid",)
        result = table._sort_value(row, "value")
        assert result[0] == float("inf")
