"""Cluster screen constants."""

from typing import Final

# ============================================================================
# Tab IDs and Names
# ============================================================================

TAB_IDS: list[str] = [
    "tab-overview",
    "tab-nodes",
    "tab-pods",
    "tab-events",
    "tab-pdbs",
    "tab-single-replica",
    "tab-health",
    "tab-node-dist",
    "tab-groups",
    "tab-stats",
]

TAB_OVERVIEW: Final = "1: Overview"
TAB_NODES: Final = "2: Nodes"
TAB_PODS: Final = "3: Pods"
TAB_EVENTS: Final = "4: Events"
TAB_PDBS: Final = "5: PDBs"
TAB_SINGLE_REPLICA: Final = "6: Single Replica"
TAB_HEALTH: Final = "7: Health"
TAB_NODE_DIST: Final = "8: Node Dist"
TAB_GROUPS: Final = "9: Groups"
TAB_STATS: Final = "0: Stats"

# ============================================================================
# Status bar
# ============================================================================

STATUS_NEVER: Final = "Never"
STATUS_UNKNOWN: Final = "Unknown"

# ============================================================================
# Event window options
# ============================================================================

CLUSTER_EVENT_WINDOW_OPTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("Last 15m", "0.25"),
    ("Last 30m", "0.5"),
    ("Last 1h", "1.0"),
    ("Last 2h", "2.0"),
)
CLUSTER_EVENT_WINDOW_DEFAULT: Final = "0.25"

__all__ = [
    "CLUSTER_EVENT_WINDOW_DEFAULT",
    "CLUSTER_EVENT_WINDOW_OPTIONS",
    "STATUS_NEVER",
    "STATUS_UNKNOWN",
    "TAB_EVENTS",
    "TAB_GROUPS",
    "TAB_HEALTH",
    "TAB_IDS",
    "TAB_NODES",
    "TAB_NODE_DIST",
    "TAB_OVERVIEW",
    "TAB_PDBS",
    "TAB_PODS",
    "TAB_SINGLE_REPLICA",
    "TAB_STATS",
]
