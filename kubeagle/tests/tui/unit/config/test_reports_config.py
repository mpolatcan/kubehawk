"""Unit tests for Reports screen configuration constants.

This module tests:
- Default value constants
- Responsive breakpoint constants
- Preview and feedback constants

All constants are imported from screens.reports.config.
"""

from __future__ import annotations

from kubeagle.screens.reports.config import (
    DEFAULT_FILENAME,
    DEFAULT_REPORT_FORMAT,
    DEFAULT_REPORT_TYPE,
    PREVIEW_CHAR_LIMIT,
    REPORT_EXPORT_MEDIUM_MIN_WIDTH,
    REPORT_EXPORT_SHORT_MIN_HEIGHT,
    REPORT_EXPORT_WIDE_MIN_WIDTH,
    STATUS_CLEAR_DELAY,
)

# =============================================================================
# Default Value Tests
# =============================================================================


class TestReportsConfigDefaults:
    """Test reports config default value constants."""

    def test_default_report_format_value(self) -> None:
        """Test DEFAULT_REPORT_FORMAT has expected value."""
        assert DEFAULT_REPORT_FORMAT == "full"

    def test_default_report_type_value(self) -> None:
        """Test DEFAULT_REPORT_TYPE has expected value."""
        assert DEFAULT_REPORT_TYPE == "combined"

    def test_default_filename_value(self) -> None:
        """Test DEFAULT_FILENAME has expected value."""
        assert DEFAULT_FILENAME == "eks-helm-report.md"

    def test_default_filename_is_string(self) -> None:
        """Test DEFAULT_FILENAME is a non-empty string."""
        assert isinstance(DEFAULT_FILENAME, str)
        assert len(DEFAULT_FILENAME) > 0

    def test_default_filename_has_extension(self) -> None:
        """Test DEFAULT_FILENAME has a file extension."""
        assert "." in DEFAULT_FILENAME


# =============================================================================
# Responsive Breakpoint Tests
# =============================================================================


class TestReportsConfigBreakpoints:
    """Test reports config responsive breakpoint constants."""

    def test_wide_min_width_value(self) -> None:
        """Test REPORT_EXPORT_WIDE_MIN_WIDTH has expected value."""
        assert REPORT_EXPORT_WIDE_MIN_WIDTH == 140

    def test_medium_min_width_value(self) -> None:
        """Test REPORT_EXPORT_MEDIUM_MIN_WIDTH has expected value."""
        assert REPORT_EXPORT_MEDIUM_MIN_WIDTH == 100

    def test_short_min_height_value(self) -> None:
        """Test REPORT_EXPORT_SHORT_MIN_HEIGHT has expected value."""
        assert REPORT_EXPORT_SHORT_MIN_HEIGHT == 34

    def test_breakpoints_are_positive(self) -> None:
        """Test all breakpoint values are positive integers."""
        for val in (REPORT_EXPORT_WIDE_MIN_WIDTH, REPORT_EXPORT_MEDIUM_MIN_WIDTH, REPORT_EXPORT_SHORT_MIN_HEIGHT):
            assert isinstance(val, int)
            assert val > 0


# =============================================================================
# Preview / Feedback Tests
# =============================================================================


class TestReportsConfigPreview:
    """Test reports config preview and feedback constants."""

    def test_preview_char_limit_value(self) -> None:
        """Test PREVIEW_CHAR_LIMIT has expected value."""
        assert PREVIEW_CHAR_LIMIT == 5000

    def test_status_clear_delay_value(self) -> None:
        """Test STATUS_CLEAR_DELAY has expected value."""
        assert STATUS_CLEAR_DELAY == 5.0

    def test_preview_char_limit_positive(self) -> None:
        """Test PREVIEW_CHAR_LIMIT is a positive integer."""
        assert isinstance(PREVIEW_CHAR_LIMIT, int)
        assert PREVIEW_CHAR_LIMIT > 0

    def test_status_clear_delay_positive(self) -> None:
        """Test STATUS_CLEAR_DELAY is a positive float."""
        assert isinstance(STATUS_CLEAR_DELAY, float)
        assert STATUS_CLEAR_DELAY > 0


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestReportsConfigBreakpoints",
    "TestReportsConfigDefaults",
    "TestReportsConfigPreview",
]
