"""Screen-specific constants subpackage.

Re-exports all screen-specific constants for convenient imports.
"""

from kubeagle.constants.screens.charts_explorer import (
    CHARTS_EXPLORER_TITLE,
)
from kubeagle.constants.screens.cluster import (
    CLUSTER_EVENT_WINDOW_DEFAULT,
    CLUSTER_EVENT_WINDOW_OPTIONS,
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
from kubeagle.constants.screens.settings import (
    SETTINGS_SECTION_AI_FIX,
    SETTINGS_SECTION_GENERAL,
    SETTINGS_SECTION_THRESHOLDS,
)

__all__ = [
    # Charts Explorer
    "CHARTS_EXPLORER_TITLE",
    "CLUSTER_EVENT_WINDOW_DEFAULT",
    "CLUSTER_EVENT_WINDOW_OPTIONS",
    # Themes
    "DARK_THEME",
    "INSIDERONE_DARK_THEME",
    "LIGHT_THEME",
    "SETTINGS_SECTION_AI_FIX",
    # Settings
    "SETTINGS_SECTION_GENERAL",
    "SETTINGS_SECTION_THRESHOLDS",
    "STATUS_NEVER",
    "STATUS_UNKNOWN",
    "TAB_EVENTS",
    "TAB_GROUPS",
    "TAB_HEALTH",
    # Cluster
    "TAB_IDS",
    "TAB_NODES",
    "TAB_NODE_DIST",
    "TAB_OVERVIEW",
    "TAB_PDBS",
    "TAB_PODS",
    "TAB_SINGLE_REPLICA",
    "TAB_STATS",
]
