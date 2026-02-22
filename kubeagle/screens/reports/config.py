"""Reports screen configuration - report export constants."""

from __future__ import annotations

# Default values
DEFAULT_REPORT_FORMAT = "full"
DEFAULT_REPORT_TYPE = "combined"
DEFAULT_FILENAME = "eks-helm-report.md"

# Responsive breakpoints for report export screen layout
REPORT_EXPORT_WIDE_MIN_WIDTH = 140
REPORT_EXPORT_MEDIUM_MIN_WIDTH = 100
REPORT_EXPORT_SHORT_MIN_HEIGHT = 34

# Preview and feedback behavior
PREVIEW_CHAR_LIMIT = 5000
STATUS_CLEAR_DELAY = 5.0
