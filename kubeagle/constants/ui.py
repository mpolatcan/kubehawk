"""UI-related constants (enums, screen configurations).

This module re-exports UI-related constants from the new constants module
for backward compatibility.
"""

from kubeagle.constants import (
    DARK_THEME,
    INSIDERONE_DARK_THEME,
    LIGHT_THEME,
)
from kubeagle.constants.enums import (
    AppState,
    FetchState,
    NodeStatus,
    QoSClass,
    Severity,
    ThemeMode,
)

__all__ = [
    "CATEGORIES",
    "DARK_THEME",
    "INSIDERONE_DARK_THEME",
    "LIGHT_THEME",
    "SEVERITIES",
    "AppState",
    "FetchState",
    "NodeStatus",
    "QoSClass",
    "Severity",
    "ThemeMode",
]

# Optimizer screen constants (kept here for compatibility)
CATEGORIES = ["resources", "probes", "availability", "security"]
SEVERITIES = ["error", "warning", "info"]
