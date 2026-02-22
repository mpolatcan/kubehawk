"""Unit tests for Detail (Optimizer) screen configuration constants.

This module tests:
- Tab ID constants (uniqueness, values)
- Tab title mappings (completeness, types)
- Table column definitions (counts, types, widths)
- format_violation_row helper function

All constants are imported from screens.detail.config.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from kubeagle.screens.detail.config import (
    FIXES_TABLE_COLUMNS,
    OPTIMIZER_HEADER_TOOLTIPS,
    OPTIMIZER_TABLE_COLUMNS,
    TAB_FIXES,
    TAB_TITLES,
    TAB_VIOLATIONS,
    VIOLATIONS_TABLE_COLUMNS,
    format_violation_row,
)

# =============================================================================
# Tab ID Tests
# =============================================================================


class TestDetailConfigTabIDs:
    """Test detail config tab ID constants."""

    def test_tab_violations_value(self) -> None:
        """Test TAB_VIOLATIONS has correct value."""
        assert TAB_VIOLATIONS == "tab-violations"

    def test_tab_fixes_value(self) -> None:
        """Test TAB_FIXES has correct value."""
        assert TAB_FIXES == "tab-fixes"

    def test_all_tab_ids_unique(self) -> None:
        """Test that all 2 TAB_* constants are unique."""
        all_tabs = [TAB_VIOLATIONS, TAB_FIXES]
        assert len(all_tabs) == 2
        assert len(set(all_tabs)) == 2, "All tab IDs must be unique"

    def test_tab_titles_has_all_tabs(self) -> None:
        """Test TAB_TITLES has entries for all 2 tab IDs."""
        all_tabs = [TAB_VIOLATIONS, TAB_FIXES]
        for tab_id in all_tabs:
            assert tab_id in TAB_TITLES, f"TAB_TITLES missing entry for {tab_id}"

    def test_tab_titles_all_strings(self) -> None:
        """Test all values in TAB_TITLES are non-empty strings."""
        for tab_id, title in TAB_TITLES.items():
            assert isinstance(title, str), f"Title for {tab_id} must be a string"
            assert len(title) > 0, f"Title for {tab_id} must not be empty"

    def test_tab_titles_count(self) -> None:
        """Test TAB_TITLES has exactly 2 entries."""
        assert len(TAB_TITLES) == 2


# =============================================================================
# Column Definition Tests
# =============================================================================


class TestDetailConfigColumns:
    """Test detail config table column definitions."""

    def test_violations_table_columns_count(self) -> None:
        """Test VIOLATIONS_TABLE_COLUMNS has 5 columns."""
        assert len(VIOLATIONS_TABLE_COLUMNS) == 5

    def test_fixes_table_columns_count(self) -> None:
        """Test FIXES_TABLE_COLUMNS has 3 columns."""
        assert len(FIXES_TABLE_COLUMNS) == 3

    def test_optimizer_table_columns_count(self) -> None:
        """Test OPTIMIZER_TABLE_COLUMNS has 8 columns."""
        assert len(OPTIMIZER_TABLE_COLUMNS) == 8

    def test_all_columns_are_tuples(self) -> None:
        """Test each column is a (str, int) tuple."""
        all_column_defs = [
            VIOLATIONS_TABLE_COLUMNS,
            FIXES_TABLE_COLUMNS,
            OPTIMIZER_TABLE_COLUMNS,
        ]
        for columns in all_column_defs:
            for col in columns:
                assert isinstance(col, tuple), f"Column {col} must be a tuple"
                assert len(col) == 2, f"Column {col} must have exactly 2 elements"
                assert isinstance(col[0], str), f"Column name {col[0]} must be a string"
                assert isinstance(col[1], int), f"Column width {col[1]} must be an int"

    def test_all_widths_positive(self) -> None:
        """Test all width values are greater than 0."""
        all_column_defs = [
            VIOLATIONS_TABLE_COLUMNS,
            FIXES_TABLE_COLUMNS,
            OPTIMIZER_TABLE_COLUMNS,
        ]
        for columns in all_column_defs:
            for col_name, col_width in columns:
                assert col_width > 0, f"Width for '{col_name}' must be > 0, got {col_width}"

    def test_all_column_names_non_empty(self) -> None:
        """Test all column names are non-empty strings."""
        all_column_defs = [
            VIOLATIONS_TABLE_COLUMNS,
            FIXES_TABLE_COLUMNS,
            OPTIMIZER_TABLE_COLUMNS,
        ]
        for columns in all_column_defs:
            for col_name, _col_width in columns:
                assert len(col_name) > 0, "Column name must not be empty"

    def test_violations_columns_expected_names(self) -> None:
        """Test VIOLATIONS_TABLE_COLUMNS has expected column names."""
        names = [col[0] for col in VIOLATIONS_TABLE_COLUMNS]
        assert "Severity" in names
        assert "Category" in names
        assert "Chart" in names
        assert "Description" in names
        assert "Recommendation" in names

    def test_fixes_columns_expected_names(self) -> None:
        """Test FIXES_TABLE_COLUMNS has expected column names."""
        names = [col[0] for col in FIXES_TABLE_COLUMNS]
        assert "Chart" in names
        assert "Violation" in names
        assert "Fix" in names

    def test_optimizer_columns_expected_order(self) -> None:
        """Test OPTIMIZER_TABLE_COLUMNS order matches optimizer table layout."""
        names = [col[0] for col in OPTIMIZER_TABLE_COLUMNS]
        assert names == [
            "Chart",
            "Team",
            "Values File Type",
            "Severity",
            "Category",
            "Rule",
            "Current",
            "Chart Path",
        ]

    def test_optimizer_header_tooltips_keys_match_columns(self) -> None:
        """Optimizer header tooltips should exist for every optimizer table column."""
        column_names = {name for name, _ in OPTIMIZER_TABLE_COLUMNS}
        tooltip_names = set(OPTIMIZER_HEADER_TOOLTIPS.keys())
        assert tooltip_names == column_names

    def test_optimizer_header_tooltips_values_non_empty(self) -> None:
        """Optimizer header tooltips should contain non-empty descriptions."""
        for column_name, tooltip_text in OPTIMIZER_HEADER_TOOLTIPS.items():
            assert isinstance(column_name, str)
            assert isinstance(tooltip_text, str)
            assert tooltip_text.strip()


# =============================================================================
# format_violation_row Tests
# =============================================================================


class TestFormatViolationRow:
    """Test format_violation_row helper function."""

    def test_format_violation_row_returns_tuple(self) -> None:
        """Test format_violation_row returns a tuple."""
        violation = MagicMock()
        violation.severity.value = "error"
        violation.category = "CPU"
        violation.chart_name = "my-chart"
        violation.description = "Missing CPU limits"
        violation.recommended_value = "Set CPU limits"
        result = format_violation_row(violation)
        assert isinstance(result, tuple)

    def test_format_violation_row_has_5_elements(self) -> None:
        """Test format_violation_row returns a 5-element tuple."""
        violation = MagicMock()
        violation.severity.value = "error"
        violation.category = "CPU"
        violation.chart_name = "my-chart"
        violation.description = "Missing CPU limits"
        violation.recommended_value = "Set CPU limits"
        result = format_violation_row(violation)
        assert len(result) == 5

    def test_format_violation_row_error_severity_markup(self) -> None:
        """Test format_violation_row applies red markup for ERROR severity."""
        violation = MagicMock()
        violation.severity.value = "error"
        violation.category = "CPU"
        violation.chart_name = "my-chart"
        violation.description = "Test"
        violation.recommended_value = "Fix"
        result = format_violation_row(violation)
        assert "#ff3b30" in result[0]
        assert "ERROR" in result[0]

    def test_format_violation_row_warning_severity_markup(self) -> None:
        """Test format_violation_row applies yellow markup for WARNING severity."""
        violation = MagicMock()
        violation.severity.value = "warning"
        violation.category = "Memory"
        violation.chart_name = "my-chart"
        violation.description = "Test"
        violation.recommended_value = "Fix"
        result = format_violation_row(violation)
        assert "#ff9f0a" in result[0]
        assert "WARNING" in result[0]

    def test_format_violation_row_truncates_long_values(self) -> None:
        """Test format_violation_row truncates values exceeding max length."""
        violation = MagicMock()
        violation.severity.value = "error"
        violation.category = "A" * 50
        violation.chart_name = "B" * 50
        violation.description = "C" * 100
        violation.recommended_value = "D" * 100
        result = format_violation_row(violation)
        assert len(result[1]) <= 15
        assert len(result[2]) <= 25
        assert len(result[3]) <= 50
        assert len(result[4]) <= 40

    def test_format_violation_row_none_fields(self) -> None:
        """Test format_violation_row handles None fields gracefully."""
        violation = MagicMock()
        violation.severity.value = "error"
        violation.category = None
        violation.chart_name = None
        violation.description = None
        violation.recommended_value = None
        result = format_violation_row(violation)
        assert result[1] == "N/A"
        assert result[2] == "N/A"
        assert result[3] == "N/A"
        assert result[4] == "N/A"


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestDetailConfigColumns",
    "TestDetailConfigTabIDs",
    "TestFormatViolationRow",
]
