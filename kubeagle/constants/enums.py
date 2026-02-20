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


# Lowercase aliases for backward compatibility
node_status = NodeStatus
qos_class = QoSClass
severity = Severity


# =============================================================================
# Application State Enums
# =============================================================================

class AppState(Enum):
    """Application state values."""

    IDLE = "idle"
    LOADING = "loading"
    ERROR = "error"
    STALE = "stale"


class LoadingState(Enum):
    """Loading state values (alias for AppState)."""

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


class FetchSources(Enum):
    """Data source identifiers."""

    NODES = "nodes"
    EVENTS = "events"
    POD_DISRUPTION_BUDGETS = "pod_disruption_budgets"
    HELM_RELEASES = "helm_releases"
    NODE_RESOURCES = "node_resources"
    POD_DISTRIBUTION = "pod_distribution"
    CLUSTER_CONNECTION = "cluster_connection"


class TabState(Enum):
    """Tab state values for lazy loading tabs."""

    IDLE = auto()  # Not yet loaded
    LOADING = auto()  # Currently fetching
    LOADED = auto()  # Data available
    ERROR = auto()  # Error occurred


# =============================================================================
# Theme Enums
# =============================================================================

class ThemeMode(Enum):
    """Theme mode values."""

    DARK = "dark"
    LIGHT = "light"


# =============================================================================
# Sort and Filter Enums
# =============================================================================

class SortDirection(Enum):
    """Sort direction for data tables."""

    ASC = "asc"
    DESC = "desc"


class FilterOperator(Enum):
    """Filter operators for search and filtering."""

    EQUALS = "eq"
    NOT_EQUALS = "ne"
    CONTAINS = "contains"
    STARTS_WITH = "startswith"
    ENDS_WITH = "endswith"


class DataRefreshMode(Enum):
    """Data refresh mode for auto-refresh functionality."""

    MANUAL = "manual"
    AUTO = "auto"
    INTERVAL = "interval"


class NavigationMode(Enum):
    """Navigation mode for screen layouts."""

    TREE = "tree"
    LIST = "list"
    GRID = "grid"


class SortField(Enum):
    """Sort fields for charts and data tables."""

    NAME = "name"
    VERSION = "version"
    TEAM = "team"
    STATUS = "status"
    CREATED = "created"


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
    # Status
    "NodeStatus",
    "QoSClass",
    "Severity",
    "node_status",
    "qos_class",
    "severity",
    # App state
    "AppState",
    "LoadingState",
    # Fetch
    "FetchState",
    "FetchSources",
    "TabState",
    # Theme
    "ThemeMode",
    # Sort and filter
    "SortDirection",
    "FilterOperator",
    "DataRefreshMode",
    "NavigationMode",
    "SortField",
    "ViewFilter",
    "SortBy",
    "WidgetCategory",
]
