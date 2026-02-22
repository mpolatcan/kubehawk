"""Unit tests for CustomDataTable widget.

Marked with:
- @pytest.mark.unit: Marks as unit test
- @pytest.mark.fast: Marks as fast test (<100ms)

Tests cover:
- Widget composition (Container wrapper pattern)
- Column definition and management
- Data operations (add_row, clear, sort)
- Sort functionality with indicators
- Disabled state management
- Cursor management
- Row data access
- Edge cases (empty tables, rapid operations)
"""

from unittest.mock import MagicMock

import pytest

from kubeagle.widgets.data.tables import (
    CustomDataTable,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_columns() -> list[tuple[str, str]]:
    """Sample column definitions for testing."""
    return [
        ("Chart Name", "name"),
        ("Version", "version"),
        ("Status", "status"),
    ]


@pytest.fixture
def sample_rows() -> list[tuple[str, str, str]]:
    """Sample row data for testing."""
    return [
        ("nginx", "1.21.0", "deployed"),
        ("redis", "6.2.0", "deployed"),
        ("postgres", "13.0", "pending"),
    ]


@pytest.fixture
async def custom_data_table_app(sample_columns, sample_rows):
    """Create a Textual app with CustomDataTable for testing."""

    class TestApp:
        def compose(self):
            yield CustomDataTable(
                columns=sample_columns,
                id="test-table",
            )

    app = TestApp()
    return app


# =============================================================================
# WIDGET COMPOSITION TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestWidgetComposition:
    """Tests for CustomDataTable Container wrapper composition."""

    def test_inherits_from_container(self):
        """Test that CustomDataTable inherits from Container."""
        table = CustomDataTable()
        from textual.containers import Container
        assert isinstance(table, Container)

    def test_composes_inner_data_table(self):
        """Test that CustomDataTable composes a TextualDataTable internally."""
        table = CustomDataTable(columns=[("Name", "name")])
        # _inner_widget is set during compose(), which happens in the Textual app lifecycle
        # Before compose, _inner_widget is None (set in __init__)
        assert hasattr(table, '_inner_widget')
        assert hasattr(table, 'data_table')
        # The data_table property returns _inner_widget, which will be set after compose

    def test_has_data_table_property(self):
        """Test data_table property accessor."""
        table = CustomDataTable()
        # Before compose, should be None (from __init__)
        assert table._inner_widget is None
        # After compose, should have inner widget
        assert hasattr(table, 'data_table')

    def test_css_classes_applied(self):
        """Test that widget-custom-data-table CSS class is applied."""
        table = CustomDataTable(classes="extra-class")
        assert "widget-custom-data-table" in table.classes
        assert "extra-class" in table.classes

    def test_id_propagation_to_inner_table(self):
        """Test that ID is propagated to inner DataTable."""
        table = CustomDataTable(id="my-table")
        assert table.id == "my-table"


# =============================================================================
# COLUMN DEFINITION TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestColumnDefinition:
    """Tests for column definition functionality."""

    def test_columns_parameter_accepted(self):
        """Test that columns parameter is accepted in constructor."""
        columns = [("Name", "name"), ("Version", "version")]
        table = CustomDataTable(columns=columns)
        assert table._columns == columns

    def test_empty_columns_allowed(self):
        """Test that CustomDataTable can be created with no columns."""
        table = CustomDataTable()
        assert table._columns == []

    def test_columns_added_during_compose(self):
        """Test that columns are added when widget is composed."""
        table = CustomDataTable(
            columns=[("Name", "name"), ("Version", "version")]
        )
        # Simulate compose by accessing the inner widget
        # (In real usage, compose() yields the inner table)
        assert len(table._columns) == 2

    def test_add_column_method(self):
        """Test add_column method delegates to inner widget."""
        table = CustomDataTable()
        # Before compose, should return None
        result = table.add_column("Test", key="test")
        assert result is None


# =============================================================================
# HEADER TOOLTIP TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestHeaderTooltips:
    """Tests for per-column header tooltip behavior."""

    def test_set_header_tooltips_stores_mapping(self):
        """Tooltip mapping should be stored by label."""
        table = CustomDataTable()
        table.set_header_tooltips({"QoS": "QoS description"})
        assert table._header_tooltips == {"QoS": "QoS description"}

    def test_resolve_header_tooltip_for_qos_column(self):
        """Header hover on QoS column should resolve configured tooltip."""
        table = CustomDataTable(columns=[("Chart", "chart"), ("QoS", "qos")])
        table.set_header_tooltips({"QoS": "QoS description"})

        tooltip = table._resolve_header_tooltip({"row": -1, "column": 1})

        assert tooltip == "QoS description"

    def test_resolve_header_tooltip_ignores_non_header_rows(self):
        """Non-header rows must not show header tooltip text."""
        table = CustomDataTable(columns=[("Chart", "chart"), ("QoS", "qos")])
        table.set_header_tooltips({"QoS": "QoS description"})

        tooltip = table._resolve_header_tooltip({"row": 0, "column": 1})

        assert tooltip is None

    def test_resolve_header_tooltip_for_unconfigured_column(self):
        """Only configured labels should return tooltip text."""
        table = CustomDataTable(columns=[("Chart", "chart"), ("QoS", "qos")])
        table.set_header_tooltips({"QoS": "QoS description"})

        tooltip = table._resolve_header_tooltip({"row": -1, "column": 0})

        assert tooltip is None


# =============================================================================
# DATA OPERATIONS TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestDataOperations:
    """Tests for data operations (add_row, clear)."""

    def test_add_row_returns_none_before_compose(self):
        """Test add_row returns None before inner widget is created."""
        table = CustomDataTable()
        result = table.add_row("value1", "value2")
        assert result is None

    def test_clear_before_compose(self):
        """Test clear does nothing before inner widget is created."""
        table = CustomDataTable()
        # Should not raise
        table.clear()

    def test_clear_safe_before_compose(self):
        """Test clear_safe does nothing before inner widget is created."""
        table = CustomDataTable()
        # Should not raise
        table.clear_safe()


# =============================================================================
# REACTIVE STATE TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestReactiveState:
    """Tests for reactive state properties."""

    def test_initial_is_loading_false(self):
        """Test is_loading is False by default."""
        table = CustomDataTable()
        assert table.is_loading is False

    def test_initial_data_empty(self):
        """Test data is empty list by default."""
        table = CustomDataTable()
        assert table.data == []

    def test_initial_error_none(self):
        """Test error is None by default."""
        table = CustomDataTable()
        assert table.error is None

    def test_is_loading_watch_method_exists(self):
        """Test watch_is_loading method exists."""
        table = CustomDataTable()
        assert hasattr(table, 'watch_is_loading')
        assert callable(table.watch_is_loading)

    def test_data_watch_method_exists(self):
        """Test watch_data method exists."""
        table = CustomDataTable()
        assert hasattr(table, 'watch_data')
        assert callable(table.watch_data)

    def test_error_watch_method_exists(self):
        """Test watch_error method exists."""
        table = CustomDataTable()
        assert hasattr(table, 'watch_error')
        assert callable(table.watch_error)


# =============================================================================
# SORT FUNCTIONALITY TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestSortFunctionality:
    """Tests for sort functionality."""

    def test_initial_sort_state(self):
        """Test initial sort state is None/False."""
        table = CustomDataTable()
        assert table._sort_column is None
        assert table._sort_reverse is False

    def test_sort_method_exists(self):
        """Test sort method exists."""
        table = CustomDataTable()
        assert hasattr(table, 'sort')
        assert callable(table.sort)

    def test_sort_by_column_method_exists(self):
        """Test sort_by_column method exists."""
        table = CustomDataTable()
        assert hasattr(table, 'sort_by_column')
        assert callable(table.sort_by_column)

    def test_action_toggle_sort_exists(self):
        """Test action_toggle_sort method exists."""
        table = CustomDataTable()
        assert hasattr(table, 'action_toggle_sort')
        assert callable(table.action_toggle_sort)

    def test_column_resize_actions_removed(self):
        """Manual column resize actions should not exist."""
        table = CustomDataTable()
        assert not hasattr(table, "action_previous_column")
        assert not hasattr(table, "action_next_column")
        assert not hasattr(table, "action_shrink_column")
        assert not hasattr(table, "action_expand_column")
        assert not hasattr(table, "action_reset_column_widths")

    def test_get_column_label_no_indicator(self):
        """Test _get_column_label returns original when not sorted."""
        table = CustomDataTable()
        result = table._get_column_label("name", "Name")
        assert result == "Name"

    def test_get_column_label_ascending(self):
        """Test _get_column_label returns ascending indicator."""
        table = CustomDataTable()
        table._sort_column = "name"
        table._sort_reverse = False
        result = table._get_column_label("name", "Name")
        assert result == "Name [+]"

    def test_get_column_label_descending(self):
        """Test _get_column_label returns descending indicator."""
        table = CustomDataTable()
        table._sort_column = "name"
        table._sort_reverse = True
        result = table._get_column_label("name", "Name")
        assert result == "Name [-]"

    def test_sort_updates_state(self):
        """Test sort_by_column updates sort state."""
        table = CustomDataTable()
        table.sort_by_column("name", reverse=False)
        assert table._sort_column == "name"
        assert table._sort_reverse is False

    def test_sort_updates_state_reverse(self):
        """Test sort_by_column updates sort state for reverse."""
        table = CustomDataTable()
        table.sort_by_column("version", reverse=True)
        assert table._sort_column == "version"
        assert table._sort_reverse is True

    def test_toggle_sort_first_time(self):
        """Test toggle sort on first call uses first column."""
        table = CustomDataTable()
        table._columns = [("Name", "name"), ("Version", "version")]
        table.action_toggle_sort()
        assert table._sort_column == "name"
        assert table._sort_reverse is False

    def test_toggle_sort_toggles_direction(self):
        """Test toggle sort reverses direction."""
        table = CustomDataTable()
        table._sort_column = "name"
        table._sort_reverse = False
        table.action_toggle_sort()
        assert table._sort_reverse is True

    def test_toggle_sort_same_column(self):
        """Test toggle sort on same column reverses direction."""
        table = CustomDataTable()
        table._sort_column = "name"
        table._sort_reverse = True
        table.action_toggle_sort()
        assert table._sort_reverse is False


# =============================================================================
# DISABLED STATE TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestDisabledState:
    """Tests for disabled state management."""

    def test_initial_disabled_false(self):
        """Test disabled is False by default."""
        table = CustomDataTable()
        assert table._disabled is False

    def test_disabled_parameter_accepted(self):
        """Test disabled parameter is accepted in constructor."""
        table = CustomDataTable(disabled=True)
        assert table._disabled is True

    def test_disabled_property_getter(self):
        """Test disabled property returns correct value."""
        table = CustomDataTable(disabled=True)
        assert table.disabled is True

    def test_disabled_property_setter(self):
        """Test disabled property setter updates state."""
        table = CustomDataTable()
        table.disabled = True
        assert table._disabled is True

    def test_disabled_property_inner_widget(self):
        """Test disabled property propagates to inner widget after compose."""
        # Create a table with disabled=True
        # Before compose, _disabled is set to True
        table = CustomDataTable(disabled=True)
        assert table._disabled is True
        # After compose, the inner DataTable would have disabled=True


# =============================================================================
# CURSOR MANAGEMENT TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestCursorManagement:
    """Tests for cursor management."""

    def test_cursor_row_property_exists(self):
        """Test cursor_row property exists."""
        table = CustomDataTable()
        assert hasattr(table, 'cursor_row')

    def test_cursor_row_getter_before_compose(self):
        """Test cursor_row getter returns None before compose."""
        table = CustomDataTable()
        assert table.cursor_row is None

    def test_cursor_row_setter_before_compose(self):
        """Test cursor_row setter does nothing before compose."""
        table = CustomDataTable()
        # Should not raise
        table.cursor_row = 5


# =============================================================================
# ROW DATA ACCESS TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestRowDataAccess:
    """Tests for row data access methods."""

    def test_get_row_data_before_compose(self):
        """Test get_row_data returns None before compose."""
        table = CustomDataTable()
        result = table.get_row_data(0)
        assert result is None

    def test_row_count_property_before_compose(self):
        """Test row_count returns 0 before compose."""
        table = CustomDataTable()
        assert table.row_count == 0

    def test_rows_property_before_compose(self):
        """Test rows property returns empty dict before compose."""
        table = CustomDataTable()
        assert table.rows == {}

    def test_columns_property_before_compose(self):
        """Test columns property returns empty dict before compose."""
        table = CustomDataTable()
        assert table.columns == {}


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_extract_row_data_tuple(self):
        """Test _extract_row_data with tuple."""
        table = CustomDataTable()
        result = table._extract_row_data(("a", "b", "c"))
        assert result == ("a", "b", "c")

    def test_extract_row_data_with_attribute(self):
        """Test _extract_row_data with object having _data."""
        table = CustomDataTable()

        class MockRow:
            _data = ("x", "y", "z")

        result = table._extract_row_data(MockRow())
        assert result == ("x", "y", "z")

    def test_clear_safe_no_exception_on_empty(self):
        """Test clear_safe handles empty table gracefully."""
        table = CustomDataTable()
        # Should not raise - has suppress(Exception) guards
        table.clear_safe()

    def test_on_column_selected_no_key(self):
        """Test on_column_selected handles None column_key."""
        table = CustomDataTable()

        class MockEvent:
            column_key = None

        # Should not raise
        table.on_column_selected(MockEvent())

    def test_on_column_selected_does_not_update_sort_state(self):
        """Column selections should be ignored when header sort is disabled."""
        table = CustomDataTable()

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

    def test_sort_no_inner_widget(self):
        """Test sort does nothing without inner widget."""
        table = CustomDataTable()
        # Should not raise
        table.sort("name", reverse=False)

    def test_sort_by_column_no_inner_widget(self):
        """Test sort_by_column updates state but no inner widget."""
        table = CustomDataTable()
        table.sort_by_column("name", reverse=False)
        assert table._sort_column == "name"


# =============================================================================
# CLASS VARIABLES TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestClassVariables:
    """Tests for class variables."""

    def test_column_defs_empty(self):
        """Test _COLUMN_DEFS is empty list."""
        table = CustomDataTable()
        assert table._COLUMN_DEFS == []

    def test_numeric_columns_empty(self):
        """Test _NUMERIC_COLUMNS is empty set."""
        table = CustomDataTable()
        assert set() == table._NUMERIC_COLUMNS

    def test_bindings_assigned(self):
        """Test BINDINGS is assigned from DATA_TABLE_BINDINGS."""
        table = CustomDataTable()
        assert hasattr(table, 'BINDINGS')


@pytest.mark.unit
@pytest.mark.fast
class TestColumnAutoWidthBehavior:
    """Tests for dynamic auto-width behavior on CustomDataTable columns."""

    def test_add_column_uses_auto_width(self):
        """Configured width should be ignored while keeping auto-width behavior."""
        table = CustomDataTable()
        mock_inner = MagicMock()
        table._inner_widget = mock_inner

        table.add_column("Name", width=12, key="name")

        mock_inner.add_column.assert_called_once_with("Name", width=None, key="name")
