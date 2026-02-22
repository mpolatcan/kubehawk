"""Timeout constants for the TUI.

All timeout and interval values for API requests, async operations, and refresh cycles.
"""

from typing import Final

# ============================================================================
# API/Cluster timeouts (string format for kubectl)
# ============================================================================

CLUSTER_REQUEST_TIMEOUT: Final = "30s"

# Process-level command timeouts (must be greater than request timeout)
KUBECTL_COMMAND_TIMEOUT: Final = 45
HELM_COMMAND_TIMEOUT: Final = 30

# ============================================================================
# Async operation timeouts (float, in seconds)
# ============================================================================

CLUSTER_CHECK_TIMEOUT: Final = 12.0
CHART_ANALYSIS_TIMEOUT: Final = 180.0

__all__ = [
    "CHART_ANALYSIS_TIMEOUT",
    "CLUSTER_CHECK_TIMEOUT",
    "CLUSTER_REQUEST_TIMEOUT",
    "HELM_COMMAND_TIMEOUT",
    "KUBECTL_COMMAND_TIMEOUT",
]
