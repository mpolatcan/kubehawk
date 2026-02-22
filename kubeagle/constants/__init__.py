"""Constants module for KubEagle TUI.

Centralized constants organized by domain:
- enums.py: All Enum class definitions
- values.py: Scalar constants (strings, numbers with Final)
- timeouts.py: Timeout values (seconds)
- limits.py: Limit values (max/min)
- defaults.py: Default values for settings
- screens/: Screen-specific constants

Note: Keyboard bindings are now defined in kubeagle.keyboard module.
"""

from kubeagle.constants.defaults import (
    EVENT_AGE_HOURS_DEFAULT,
    LIMIT_REQUEST_RATIO_THRESHOLD_DEFAULT,
    REFRESH_INTERVAL_DEFAULT,
    THEME_DEFAULT,
)
from kubeagle.constants.enums import (
    AppState,
    FetchState,
    NodeStatus,
    QoSClass,
    Severity,
    ThemeMode,
)
from kubeagle.constants.limits import (
    MAX_EVENTS_DISPLAY,
    MAX_ROWS_DISPLAY,
    REFRESH_INTERVAL_MIN,
    THRESHOLD_MAX,
    THRESHOLD_MIN,
)
from kubeagle.constants.screens.cluster import (
    STATUS_NEVER,
    STATUS_UNKNOWN,
    TAB_EVENTS,
    TAB_GROUPS,
    TAB_HEALTH,
    TAB_IDS,
    TAB_NODE_DIST,
    TAB_NODES,
    TAB_OVERVIEW,
    TAB_PDBS,
    TAB_PODS,
    TAB_SINGLE_REPLICA,
    TAB_STATS,
)
from kubeagle.constants.screens.common import (
    DARK_THEME,
    INSIDERONE_DARK_THEME,
    LIGHT_THEME,
)
from kubeagle.constants.timeouts import (
    CLUSTER_CHECK_TIMEOUT,
    CLUSTER_REQUEST_TIMEOUT,
)
from kubeagle.constants.values import (
    APP_TITLE,
    COLOR_ACCENT,
    COLOR_SECONDARY,
)

__all__ = [
    # Application
    "APP_TITLE",
    "CLUSTER_CHECK_TIMEOUT",
    # Timeouts
    "CLUSTER_REQUEST_TIMEOUT",
    "COLOR_ACCENT",
    # Colors
    "COLOR_SECONDARY",
    # Themes
    "DARK_THEME",
    "EVENT_AGE_HOURS_DEFAULT",
    "INSIDERONE_DARK_THEME",
    "LIGHT_THEME",
    "LIMIT_REQUEST_RATIO_THRESHOLD_DEFAULT",
    "MAX_EVENTS_DISPLAY",
    "MAX_ROWS_DISPLAY",
    "REFRESH_INTERVAL_DEFAULT",
    "REFRESH_INTERVAL_MIN",
    "STATUS_NEVER",
    "STATUS_UNKNOWN",
    "TAB_EVENTS",
    "TAB_GROUPS",
    "TAB_HEALTH",
    # Screen constants
    "TAB_IDS",
    "TAB_NODES",
    "TAB_NODE_DIST",
    "TAB_OVERVIEW",
    "TAB_PDBS",
    "TAB_PODS",
    "TAB_SINGLE_REPLICA",
    "TAB_STATS",
    "THEME_DEFAULT",
    "THRESHOLD_MAX",
    "THRESHOLD_MIN",
    # Enums
    "AppState",
    "FetchState",
    "NodeStatus",
    "QoSClass",
    "Severity",
    "ThemeMode",
]
