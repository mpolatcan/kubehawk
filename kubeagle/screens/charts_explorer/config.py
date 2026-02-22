"""Charts Explorer screen configuration - enums, column definitions, and options."""

from __future__ import annotations

from kubeagle.constants.enums import SortBy, ViewFilter

# =============================================================================
# Select Widget Options (label, value)
# =============================================================================

VIEW_TAB_OPTIONS: list[tuple[str, ViewFilter, str]] = [
    ("All Charts", ViewFilter.ALL, "charts-view-tab-all"),
    ("Extreme Ratios", ViewFilter.EXTREME_RATIOS, "charts-view-tab-extreme"),
    ("Single Replica", ViewFilter.SINGLE_REPLICA, "charts-view-tab-single"),
    ("Missing PDB", ViewFilter.NO_PDB, "charts-view-tab-no-pdb"),
    ("Optimizer", ViewFilter.WITH_VIOLATIONS, "charts-view-tab-violations"),
]

VIEW_FILTER_BY_TAB_ID: dict[str, ViewFilter] = {
    tab_id: view_filter for _, view_filter, tab_id in VIEW_TAB_OPTIONS
}

VIEW_TAB_ID_BY_FILTER: dict[ViewFilter, str] = {
    view_filter: tab_id for _, view_filter, tab_id in VIEW_TAB_OPTIONS
}

SORT_OPTIONS: list[tuple[str, SortBy]] = [
    ("Chart", SortBy.CHART),
    ("Team", SortBy.TEAM),
    ("QoS", SortBy.QOS),
    ("CPU Request", SortBy.CPU_REQUEST),
    ("CPU Limit", SortBy.CPU_LIMIT),
    ("CPU Ratio", SortBy.CPU_RATIO),
    ("Memory Request", SortBy.MEMORY_REQUEST),
    ("Memory Limit", SortBy.MEMORY_LIMIT),
    ("Memory Ratio", SortBy.MEMORY_RATIO),
    ("Replicas", SortBy.REPLICAS),
    ("Values File", SortBy.VALUES_FILE),
    ("Violations", SortBy.VIOLATIONS),
]

# Tab IDs
TAB_CHARTS = "tab-charts"
TAB_VIOLATIONS = "tab-violations"
# Recommendations are now embedded in the violations view.
# Keep this alias for navigation/backward compatibility.
TAB_RECOMMENDATIONS = TAB_VIOLATIONS


# =============================================================================
# Table Column Definitions
# =============================================================================

EXPLORER_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("Chart", 25),
    ("Namespace", 16),
    ("Team", 15),
    ("Values File Type", 12),
    ("QoS", 12),
    ("CPU R/L", 30),
    ("Mem R/L", 32),
    ("Replicas", 9),
    ("Probes", 16),
    ("Affinity", 14),
    ("PDB", 6),
    ("Chart Path", 52),
]

EXPLORER_HEADER_TOOLTIPS: dict[str, str] = {
    "Chart": "Helm chart name.",
    "Namespace": "Kubernetes namespace for cluster-backed Helm releases.",
    "Team": "Owning team mapped from CODEOWNERS/chart metadata.",
    "Values File Type": "Source kind for values (service/default/shared/other).",
    "QoS": "Kubernetes pod QoS class derived from CPU/memory requests and limits.",
    "CPU R/L": "CPU request/limit with inline limit/request ratio.",
    "Mem R/L": "Memory request/limit with inline limit/request ratio.",
    "Replicas": "Configured replica count.",
    "Probes": "Health probe presence summary (Liveness/Readiness/Startup).",
    "Affinity": "Pod scheduling constraints (anti-affinity/topology spread).",
    "PDB": "PodDisruptionBudget presence/status.",
    "Chart Path": "Filesystem path of the chart.",
}


# =============================================================================
# Thresholds
# =============================================================================

EXTREME_RATIO_THRESHOLD: float = 2.0
