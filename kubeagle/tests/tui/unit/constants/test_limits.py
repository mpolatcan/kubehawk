"""Unit tests for limit constants in constants/limits.py.

Tests cover:
- All limit values
- Correct types (int)
- Positive values
- Logical relationships between related limits
"""

from __future__ import annotations

from kubeagle.constants.limits import (
    AI_FIX_BULK_PARALLELISM_MAX,
    AI_FIX_BULK_PARALLELISM_MIN,
    MAX_EVENTS_DISPLAY,
    MAX_ROWS_DISPLAY,
    MAX_WORKERS,
    REFRESH_INTERVAL_MIN,
    THRESHOLD_MAX,
    THRESHOLD_MIN,
)

# =============================================================================
# Display limits
# =============================================================================


class TestDisplayLimits:
    """Test display-related limit constants."""

    def test_max_rows_display_type(self) -> None:
        assert isinstance(MAX_ROWS_DISPLAY, int)

    def test_max_rows_display_value(self) -> None:
        assert MAX_ROWS_DISPLAY == 1000

    def test_max_rows_display_positive(self) -> None:
        assert MAX_ROWS_DISPLAY > 0

    def test_max_events_display_type(self) -> None:
        assert isinstance(MAX_EVENTS_DISPLAY, int)

    def test_max_events_display_value(self) -> None:
        assert MAX_EVENTS_DISPLAY == 100

    def test_max_events_display_positive(self) -> None:
        assert MAX_EVENTS_DISPLAY > 0


# =============================================================================
# Validation limits
# =============================================================================


class TestValidationLimits:
    """Test validation limit constants."""

    def test_refresh_interval_min_type(self) -> None:
        assert isinstance(REFRESH_INTERVAL_MIN, int)

    def test_refresh_interval_min_value(self) -> None:
        assert REFRESH_INTERVAL_MIN == 5

    def test_refresh_interval_min_positive(self) -> None:
        assert REFRESH_INTERVAL_MIN > 0

    def test_threshold_min_type(self) -> None:
        assert isinstance(THRESHOLD_MIN, int)

    def test_threshold_min_value(self) -> None:
        assert THRESHOLD_MIN == 1

    def test_threshold_max_type(self) -> None:
        assert isinstance(THRESHOLD_MAX, int)

    def test_threshold_max_value(self) -> None:
        assert THRESHOLD_MAX == 100

    def test_threshold_min_less_than_max(self) -> None:
        assert THRESHOLD_MIN < THRESHOLD_MAX

    def test_ai_fix_bulk_parallelism_min_value(self) -> None:
        assert AI_FIX_BULK_PARALLELISM_MIN == 1

    def test_ai_fix_bulk_parallelism_max_value(self) -> None:
        assert AI_FIX_BULK_PARALLELISM_MAX == 8

    def test_ai_fix_bulk_parallelism_bounds_valid(self) -> None:
        assert AI_FIX_BULK_PARALLELISM_MIN < AI_FIX_BULK_PARALLELISM_MAX


# =============================================================================
# Controller limits
# =============================================================================


class TestControllerLimits:
    """Test controller limit constants."""

    def test_max_workers_type(self) -> None:
        assert isinstance(MAX_WORKERS, int)

    def test_max_workers_value(self) -> None:
        assert MAX_WORKERS == 8

    def test_max_workers_positive(self) -> None:
        assert MAX_WORKERS > 0


# =============================================================================
# __all__ exports
# =============================================================================


class TestLimitsExports:
    """Test that __all__ exports are correct."""

    def test_all_exports_importable(self) -> None:
        import kubeagle.constants.limits as mod

        for name in mod.__all__:
            assert hasattr(mod, name), f"{name} listed in __all__ but not defined"
