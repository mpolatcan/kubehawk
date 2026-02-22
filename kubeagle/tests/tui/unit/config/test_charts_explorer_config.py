"""Unit tests for ChartsExplorer configuration constants.

This module tests:
- ViewFilter enum values and completeness
- EXPLORER_TABLE_COLUMNS (count, types, widths)
- EXTREME_RATIO_THRESHOLD constant

All constants are imported from screens.charts_explorer.config.
"""

from __future__ import annotations

from kubeagle.screens.charts_explorer.config import (
    EXPLORER_HEADER_TOOLTIPS,
    EXPLORER_TABLE_COLUMNS,
    EXTREME_RATIO_THRESHOLD,
    VIEW_TAB_OPTIONS,
    ViewFilter,
)
# =============================================================================
# ViewFilter Enum Tests
# =============================================================================


class TestViewFilterEnum:
    """Test ViewFilter enum values."""

    def test_all_value(self) -> None:
        """Test ViewFilter.ALL has correct value."""
        assert ViewFilter.ALL.value == "all"

    def test_extreme_ratios_value(self) -> None:
        """Test ViewFilter.EXTREME_RATIOS has correct value."""
        assert ViewFilter.EXTREME_RATIOS.value == "extreme_ratios"

    def test_single_replica_value(self) -> None:
        """Test ViewFilter.SINGLE_REPLICA has correct value."""
        assert ViewFilter.SINGLE_REPLICA.value == "single_replica"

    def test_no_pdb_value(self) -> None:
        """Test ViewFilter.NO_PDB has correct value."""
        assert ViewFilter.NO_PDB.value == "no_pdb"

    def test_with_violations_value(self) -> None:
        """Test ViewFilter.WITH_VIOLATIONS has correct value."""
        assert ViewFilter.WITH_VIOLATIONS.value == "with_violations"

    def test_enum_has_5_members(self) -> None:
        """Test ViewFilter has exactly 5 members."""
        assert len(ViewFilter) == 5

    def test_all_values_unique(self) -> None:
        """Test all ViewFilter values are unique."""
        values = [v.value for v in ViewFilter]
        assert len(values) == len(set(values))


# =============================================================================
# VIEW_TAB_OPTIONS Tests
# =============================================================================


class TestViewTabOptions:
    """Test VIEW_TAB_OPTIONS list labels and structure."""

    def test_has_5_options(self) -> None:
        """VIEW_TAB_OPTIONS should include 5 tab definitions."""
        assert len(VIEW_TAB_OPTIONS) == 5

    def test_optimizer_tab_label_is_short(self) -> None:
        """Optimizer tab should use concise label text."""
        optimizer_label = next(
            label for label, value, _ in VIEW_TAB_OPTIONS if value == ViewFilter.WITH_VIOLATIONS
        )
        assert optimizer_label == "Optimizer"


# =============================================================================
# EXPLORER_TABLE_COLUMNS Tests
# =============================================================================


class TestExplorerTableColumns:
    """Test EXPLORER_TABLE_COLUMNS definitions."""

    def test_has_12_columns(self) -> None:
        """Test EXPLORER_TABLE_COLUMNS has exactly 12 columns."""
        assert len(EXPLORER_TABLE_COLUMNS) == 12

    def test_all_tuples_with_correct_types(self) -> None:
        """Test each column is a (str, int) tuple."""
        for col in EXPLORER_TABLE_COLUMNS:
            assert isinstance(col, tuple), f"Column {col} must be a tuple"
            assert len(col) == 2, f"Column {col} must have 2 elements"
            assert isinstance(col[0], str), f"Column name {col[0]} must be a string"
            assert isinstance(col[1], int), f"Column width {col[1]} must be an int"

    def test_all_widths_positive(self) -> None:
        """Test all width values are greater than 0."""
        for col_name, col_width in EXPLORER_TABLE_COLUMNS:
            assert col_width > 0, f"Width for '{col_name}' must be > 0"

    def test_all_names_non_empty(self) -> None:
        """Test all column names are non-empty."""
        for col_name, _ in EXPLORER_TABLE_COLUMNS:
            assert len(col_name) > 0

    def test_first_column_is_chart(self) -> None:
        """Test first column is Chart."""
        assert EXPLORER_TABLE_COLUMNS[0][0] == "Chart"

    def test_third_column_is_team(self) -> None:
        """Test third column is Team."""
        assert EXPLORER_TABLE_COLUMNS[2][0] == "Team"

    def test_fourth_column_is_values_file_type(self) -> None:
        """Test fourth column is Values File Type."""
        assert EXPLORER_TABLE_COLUMNS[3][0] == "Values File Type"

    def test_fifth_column_is_qos(self) -> None:
        """Test fifth column is QoS."""
        assert EXPLORER_TABLE_COLUMNS[4][0] == "QoS"

    def test_last_column_is_chart_path(self) -> None:
        """Test last column is Chart Path."""
        assert EXPLORER_TABLE_COLUMNS[-1][0] == "Chart Path"

    def test_column_names_unique(self) -> None:
        """Test all column names are unique."""
        names = [col[0] for col in EXPLORER_TABLE_COLUMNS]
        assert len(names) == len(set(names))


# =============================================================================
# Constants Tests
# =============================================================================


class TestChartsExplorerConstants:
    """Test Charts Explorer constants."""

    def test_extreme_ratio_threshold_is_float(self) -> None:
        """Test EXTREME_RATIO_THRESHOLD is a float."""
        assert isinstance(EXTREME_RATIO_THRESHOLD, float)

    def test_extreme_ratio_threshold_value(self) -> None:
        """Test EXTREME_RATIO_THRESHOLD equals 2.0."""
        assert EXTREME_RATIO_THRESHOLD == 2.0

    def test_explorer_header_tooltips_keys_match_columns(self) -> None:
        """Explorer header tooltips should exist for every table column."""
        column_names = {name for name, _ in EXPLORER_TABLE_COLUMNS}
        tooltip_names = set(EXPLORER_HEADER_TOOLTIPS.keys())
        assert tooltip_names == column_names

    def test_explorer_header_tooltips_values_non_empty(self) -> None:
        """Explorer header tooltip values should all be non-empty text."""
        for column_name, tooltip_text in EXPLORER_HEADER_TOOLTIPS.items():
            assert isinstance(column_name, str)
            assert isinstance(tooltip_text, str)
            assert tooltip_text.strip()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestChartsExplorerConstants",
    "TestExplorerTableColumns",
    "TestViewFilterEnum",
    "TestViewTabOptions",
]
