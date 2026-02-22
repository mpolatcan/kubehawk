"""Cluster screen configuration - tab IDs, column definitions, and widget ID constants."""

from __future__ import annotations

# =============================================================================
# Tab IDs
# =============================================================================

TAB_NODES = "tab-nodes"
TAB_PODS = "tab-pods"
TAB_EVENTS = "tab-events"
# Backward-compatible alias for callers that still reference the old summary tab.
TAB_OVERVIEW = TAB_EVENTS
TAB_PDBS = "tab-pdbs"
TAB_SINGLE_REPLICA = "tab-single-replica"
TAB_HEALTH = "tab-health"
TAB_NODE_DIST = "tab-node-dist"
TAB_GROUPS = "tab-groups"
TAB_STATS = "tab-stats"
TAB_IDS: list[str] = [
    TAB_NODES,
    TAB_PODS,
    TAB_EVENTS,
]

# Tab Titles
TAB_TITLES: dict[str, str] = {
    TAB_NODES: "Nodes",
    TAB_PODS: "Workloads",
    TAB_EVENTS: "Events",
}

TAB_LABELS_FULL: dict[str, str] = {
    TAB_NODES: "Nodes",
    TAB_PODS: "Workloads",
    TAB_EVENTS: "Events",
}

TAB_LABELS_COMPACT: dict[str, str] = {
    TAB_NODES: "Nodes",
    TAB_PODS: "Workloads",
    TAB_EVENTS: "Events",
}

# =============================================================================
# Table Column Definitions: list[tuple[str, int]] = [(name, width), ...]
# =============================================================================

NODE_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("Name", 35),
    ("Node Group", 28),
    ("Pod Usage", 20),
    ("CPU Req/Alloc (m)", 24),
    ("Mem Req/Alloc (GiB)", 26),
    ("CPU Lim/Alloc (m)", 24),
    ("Mem Lim/Alloc (GiB)", 26),
]

EVENTS_DETAIL_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("Type", 10),
    ("Reason", 20),
    ("Object", 30),
    ("Count", 8),
    ("Message", 80),
]

PDBS_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("Namespace", 20),
    ("Name", 25),
    ("Min Available", 15),
    ("Max Unavailable", 18),
    ("Expected Pods", 15),
    ("Current Healthy", 16),
    ("Disruptions Allowed", 20),
    ("Unhealthy Policy", 18),
    ("Status", 15),
    ("Issues", 30),
]

NODE_GROUPS_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("Node Group", 28),
    ("Nodes", 8),
    ("CPU Req % (Avg/Max/P95)", 24),
    ("Mem Req % (Avg/Max/P95)", 24),
    ("CPU Lim % (Avg/Max/P95)", 24),
    ("Mem Lim % (Avg/Max/P95)", 24),
]

# =============================================================================
# Table Header Tooltips
# =============================================================================

CLUSTER_TABLE_HEADER_TOOLTIPS: dict[str, dict[str, str]] = {
    "events-detail-table": {
        "Type": "Kubernetes event type (Normal or Warning).",
        "Reason": "Short machine-readable reason for the event.",
        "Object": "Kubernetes object involved in the event.",
        "Count": "How many times this event has occurred.",
        "Message": "Full event message emitted by Kubernetes.",
    },
    "nodes-table": {
        "Name": "Kubernetes node name.",
        "Node Group": "Owning node group for this node.",
        "Pod Usage": "Current pod pressure as pod-count/capacity with utilization percentage when capacity is available.",
        "CPU Req/Alloc (m)": "CPU requests over allocatable CPU as percentage and req/alloc pair in millicores.",
        "Mem Req/Alloc (GiB)": "Memory requests over allocatable memory as percentage and req/alloc pair in GiB.",
        "CPU Lim/Alloc (m)": "CPU limits over allocatable CPU as percentage and limit/alloc pair in millicores.",
        "Mem Lim/Alloc (GiB)": "Memory limits over allocatable memory as percentage and limit/alloc pair in GiB.",
    },
    "node-groups-table": {
        "Node Group": "Node group name.",
        "Nodes": "Number of nodes in this node group.",
        "CPU Req % (Avg/Max/P95)": "CPU request utilization triplet in Avg/Max/P95 order.",
        "Mem Req % (Avg/Max/P95)": "Memory request utilization triplet in Avg/Max/P95 order.",
        "CPU Lim % (Avg/Max/P95)": "CPU limit utilization triplet in Avg/Max/P95 order.",
        "Mem Lim % (Avg/Max/P95)": "Memory limit utilization triplet in Avg/Max/P95 order.",
    },
    "pdbs-table": {
        "Namespace": "Namespace that owns this PodDisruptionBudget.",
        "Name": "PodDisruptionBudget name.",
        "Min Available": "Minimum healthy pods required during disruptions.",
        "Max Unavailable": "Maximum pods allowed to be unavailable during disruptions.",
        "Expected Pods": "Expected pod replicas matched by this PDB.",
        "Current Healthy": "Currently healthy pods matched by this PDB.",
        "Disruptions Allowed": "Additional pods that may be voluntarily disrupted now.",
        "Unhealthy Policy": "Policy used when unhealthy pods are present.",
        "Status": "Overall evaluation status for this PDB.",
        "Issues": "Detected issues and guidance for this PDB.",
    },
    "single-replica-table": {
        "Namespace": "Namespace that owns this workload.",
        "Name": "Workload resource name.",
        "Kind": "Kubernetes workload kind (Deployment, StatefulSet, etc.).",
        "Replicas": "Configured replica count.",
        "Ready": "Ready replicas compared with desired replicas.",
        "Helm Release": "Helm release managing this workload.",
        "Status": "Single-replica risk status for this workload.",
    },
    "all-workloads-table": {
        "Namespace": "Namespace that owns this workload.",
        "Kind": "Kubernetes workload kind (Deployment, StatefulSet, DaemonSet, Job, CronJob).",
        "Name": "Kubernetes workload resource name.",
        "Desired": "Desired replicas or parallelism when applicable.",
        "Ready": "Ready replicas/active executions when applicable.",
        "Helm Release": "Helm release managing this workload, if any.",
        "PDB": "Whether a PodDisruptionBudget selector matches this workload template.",
        "Status": "Current workload status derived from runtime fields.",
    },
}

# Event limit
MAX_EVENTS_DISPLAY = 100
