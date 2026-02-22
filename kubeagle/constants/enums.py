"""All enum definitions for the TUI.

This module consolidates all enumerations used throughout the application.
"""

from enum import Enum, auto

# =============================================================================
# Status Enums
# =============================================================================

class NodeStatus(Enum):
    """Node status values from Kubernetes API."""

    READY = "Ready"
    NOT_READY = "NotReady"
    UNKNOWN = "Unknown"


class QoSClass(Enum):
    """Kubernetes QoS class values."""

    GUARANTEED = "Guaranteed"
    BURSTABLE = "Burstable"
    BEST_EFFORT = "BestEffort"


class Severity(Enum):
    """Severity levels for violations and recommendations."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


# =============================================================================
# Application State Enums
# =============================================================================

class AppState(Enum):
    """Application state values."""

    IDLE = "idle"
    LOADING = "loading"
    ERROR = "error"
    STALE = "stale"


# =============================================================================
# Fetch State Enums
# =============================================================================

class FetchState(Enum):
    """Data fetch state values."""

    LOADING = "loading"
    SUCCESS = "success"
    ERROR = "error"


# =============================================================================
# Theme Enums
# =============================================================================

class ThemeMode(Enum):
    """Theme mode values."""

    DARK = "dark"
    LIGHT = "light"


class ViewFilter(Enum):
    """View filter presets for Charts Explorer."""

    ALL = "all"
    EXTREME_RATIOS = "extreme_ratios"
    SINGLE_REPLICA = "single_replica"
    NO_PDB = "no_pdb"
    WITH_VIOLATIONS = "with_violations"


class SortBy(Enum):
    """Sort modes for Charts Explorer table."""

    CHART = "chart"
    TEAM = "team"
    QOS = "qos"
    CPU_REQUEST = "cpu_request"
    CPU_LIMIT = "cpu_limit"
    CPU_RATIO = "cpu_ratio"
    MEMORY_REQUEST = "memory_request"
    MEMORY_LIMIT = "memory_limit"
    MEMORY_RATIO = "memory_ratio"
    REPLICAS = "replicas"
    VALUES_FILE = "values_file"
    VIOLATIONS = "violations"


class WidgetCategory(Enum):
    """Categories for organizing widgets."""

    DATA_DISPLAY = auto()
    FEEDBACK = auto()
    FILTER = auto()
    DIALOG = auto()
    NAVIGATION = auto()
    LAYOUT = auto()


__all__ = [
    # App state
    "AppState",
    # Fetch
    "FetchState",
    # Status
    "NodeStatus",
    "QoSClass",
    "Severity",
    "SortBy",
    # Theme
    "ThemeMode",
    "ViewFilter",
    "WidgetCategory",
]
