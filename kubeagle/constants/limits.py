"""Limit and threshold constants for the TUI.

All limit values, thresholds, and validation ranges.
"""

from typing import Final

# ============================================================================
# Display limits
# ============================================================================

MAX_ROWS_DISPLAY: Final = 1000
MAX_EVENTS_DISPLAY: Final = 100

# ============================================================================
# Validation limits
# ============================================================================

REFRESH_INTERVAL_MIN: Final = 5
THRESHOLD_MIN: Final = 1
THRESHOLD_MAX: Final = 100
AI_FIX_BULK_PARALLELISM_MIN: Final = 1
AI_FIX_BULK_PARALLELISM_MAX: Final = 8
PROGRESSIVE_YIELD_INTERVAL_MIN: Final = 1
PROGRESSIVE_YIELD_INTERVAL_MAX: Final = 16
PROGRESSIVE_PARALLELISM_MIN: Final = 1
PROGRESSIVE_PARALLELISM_MAX: Final = 16

# ============================================================================
# Controller limits
# ============================================================================

MAX_WORKERS: Final = 8

__all__ = [
    "AI_FIX_BULK_PARALLELISM_MAX",
    "AI_FIX_BULK_PARALLELISM_MIN",
    "MAX_EVENTS_DISPLAY",
    "MAX_ROWS_DISPLAY",
    "MAX_WORKERS",
    "PROGRESSIVE_PARALLELISM_MAX",
    "PROGRESSIVE_PARALLELISM_MIN",
    "PROGRESSIVE_YIELD_INTERVAL_MAX",
    "PROGRESSIVE_YIELD_INTERVAL_MIN",
    "REFRESH_INTERVAL_MIN",
    "THRESHOLD_MAX",
    "THRESHOLD_MIN",
]
