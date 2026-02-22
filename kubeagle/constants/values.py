"""Scalar constants for the TUI.

All application-level constants with proper type hints using Final.
"""

from typing import Final

# ============================================================================
# Application
# ============================================================================

APP_TITLE: Final = "KubEagle"

# ============================================================================
# Colors (hex strings for Theme compatibility)
# ============================================================================

COLOR_SECONDARY: Final = "#6C757D"  # Gray
COLOR_ACCENT: Final = "#17A2B8"  # Teal

# ============================================================================
# Health status (markup for rich text display)
# ============================================================================

HEALTHY: Final = "[green]HEALTHY[/green]"
DEGRADED: Final = "[yellow]DEGRADED[/yellow]"
UNHEALTHY: Final = "[red]UNHEALTHY[/red]"

# ============================================================================
# Settings screen placeholders
# ============================================================================

PLACEHOLDER_CHARTS_PATH: Final = "/path/to/helm/charts"
PLACEHOLDER_ACTIVE_CHARTS: Final = "active-charts.txt (optional)"
PLACEHOLDER_CODEOWNERS: Final = "CODEOWNERS (optional)"
PLACEHOLDER_REFRESH_INTERVAL: Final = "30"
PLACEHOLDER_EXPORT_PATH: Final = "./reports"
PLACEHOLDER_EVENT_AGE: Final = "1.0"
PLACEHOLDER_THRESHOLD: Final = "80"
PLACEHOLDER_LIMIT_REQUEST: Final = "3.0"
PLACEHOLDER_AI_FIX_BULK_PARALLELISM: Final = "2"

__all__ = [
    "APP_TITLE",
    "COLOR_ACCENT",
    "COLOR_SECONDARY",
    "DEGRADED",
    "HEALTHY",
    "PLACEHOLDER_ACTIVE_CHARTS",
    "PLACEHOLDER_AI_FIX_BULK_PARALLELISM",
    "PLACEHOLDER_CHARTS_PATH",
    "PLACEHOLDER_CODEOWNERS",
    "PLACEHOLDER_EVENT_AGE",
    "PLACEHOLDER_EXPORT_PATH",
    "PLACEHOLDER_LIMIT_REQUEST",
    "PLACEHOLDER_REFRESH_INTERVAL",
    "PLACEHOLDER_THRESHOLD",
    "UNHEALTHY",
]
