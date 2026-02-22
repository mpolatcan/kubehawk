"""Detail screen presenter - shared data loading for unified optimizer screen.

Contains helper functions for building recommendations from violations
and fetching cluster-level recommendations. Used by OptimizerScreen's
data loading worker to produce both violations and recommendations in
a single pass.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from textual.message import Message

if TYPE_CHECKING:
    from kubeagle.models.analysis.violation import ViolationResult

logger = logging.getLogger(__name__)


# ============================================================================
# Worker Messages for Cross-thread Communication
# ============================================================================


class OptimizerDataLoaded(Message):
    """Message indicating optimizer data has been loaded."""

    def __init__(
        self,
        violations: list[ViolationResult],
        recommendations: list[dict[str, Any]],
        charts: list,
        total_charts: int,
        duration_ms: float,
        optimizer_generation: int | None = None,
    ) -> None:
        super().__init__()
        self.violations = violations
        self.recommendations = recommendations
        self.charts = charts
        self.total_charts = total_charts
        self.duration_ms = duration_ms
        self.optimizer_generation = optimizer_generation


class OptimizerDataLoadFailed(Message):
    """Message indicating optimizer data loading failed."""

    def __init__(
        self,
        error: str,
        optimizer_generation: int | None = None,
    ) -> None:
        super().__init__()
        self.error = error
        self.optimizer_generation = optimizer_generation


# ============================================================================
# Recommendation Building Helpers
# ============================================================================

# Maps optimizer rule_id -> recommendation metadata for grouping violations
_RULE_REC_META: dict[str, dict[str, str]] = {
    "AVL001": {
        "id": "charts-no-pdb",
        "category": "reliability",
        "title_tpl": "Charts Without PDBs Enabled: {count} charts ({pct:.1f}%)",
        "recommended_action": "Enable PDB and allow safe drain behavior",
        "yaml_example": """pdb:
  enabled: true
  maxUnavailable: 1
  unhealthyPodEvictionPolicy: AlwaysAllow""",
    },
    "AVL002": {
        "id": "charts-no-aa",
        "category": "reliability",
        "title_tpl": "Missing Anti-Affinity: {count} charts ({pct:.1f}%)",
        "recommended_action": "Add pod anti-affinity for high availability",
        "yaml_example": """affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchLabels:
              app: my-app
          topologyKey: kubernetes.io/hostname""",
    },
    "AVL003": {
        "id": "charts-blocking-pdb",
        "category": "reliability",
        "title_tpl": "Blocking PDB Configuration: {count} charts ({pct:.1f}%)",
        "recommended_action": "Fix PDB to allow at least 1 eviction during drains",
        "yaml_example": """pdb:
  enabled: true
  maxUnavailable: 1
  unhealthyPodEvictionPolicy: AlwaysAllow""",
    },
    "AVL004": {
        "id": "charts-no-topology-spread",
        "category": "reliability",
        "title_tpl": "Missing Topology Spread (Multi-Replica): {count} charts ({pct:.1f}%)",
        "recommended_action": "Add topology spread constraints for multi-replica workloads",
        "yaml_example": """topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule
    labelSelector:
      matchLabels:
        app: {{ .Chart.Name }}""",
    },
    "AVL005": {
        "id": "single-replica-charts",
        "category": "reliability",
        "title_tpl": "Single Replica Charts: {count} charts ({pct:.1f}%)",
        "recommended_action": "Increase replicas to 2-3 for fault tolerance",
        "yaml_example": """replicaCount: 3

# AND add PDB
pdb:
  enabled: true
  minAvailable: 1""",
    },
    "PRB001": {
        "id": "charts-no-liveness",
        "category": "reliability",
        "title_tpl": "Missing Liveness Probe: {count} charts ({pct:.1f}%)",
        "recommended_action": "Add liveness probes",
        "yaml_example": """livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 15
  periodSeconds: 20""",
    },
    "PRB002": {
        "id": "charts-no-readiness",
        "category": "reliability",
        "title_tpl": "Missing Readiness Probe: {count} charts ({pct:.1f}%)",
        "recommended_action": "Add readiness probes",
        "yaml_example": """readinessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10""",
    },
    "PRB003": {
        "id": "charts-no-startup",
        "category": "reliability",
        "title_tpl": "Missing Startup Probe: {count} charts ({pct:.1f}%)",
        "recommended_action": "Add startup probes for slow-starting containers",
        "yaml_example": """startupProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 5
  failureThreshold: 30""",
    },
    "RES002": {
        "id": "charts-no-cpu-limits",
        "category": "resource",
        "title_tpl": "Missing CPU Limits: {count} charts ({pct:.1f}%)",
        "recommended_action": "Add CPU limits for proper resource management",
        "yaml_example": """resources:
  limits:
    cpu: 500m""",
    },
    "RES003": {
        "id": "charts-no-memory-limits",
        "category": "resource",
        "title_tpl": "Missing Memory Limits: {count} charts ({pct:.1f}%)",
        "recommended_action": "Add memory limits to prevent OOM kills",
        "yaml_example": """resources:
  limits:
    memory: 512Mi""",
    },
    "RES004": {
        "id": "charts-no-resource-requests",
        "category": "resource",
        "title_tpl": "No Resource Requests: {count} charts ({pct:.1f}%)",
        "recommended_action": "Add resource requests for proper scheduling",
        "yaml_example": """resources:
  requests:
    cpu: 100m
    memory: 128Mi""",
    },
    "RES005": {
        "id": "charts-high-cpu-ratio",
        "category": "resource",
        "title_tpl": "High CPU Limit/Request Ratio: {count} charts ({pct:.1f}%)",
        "recommended_action": "Reduce CPU limit to <=2x the request",
        "yaml_example": """resources:
  requests:
    cpu: 100m
  limits:
    cpu: 200m  # Keep ratio <= 2x""",
    },
    "RES006": {
        "id": "charts-high-memory-ratio",
        "category": "resource",
        "title_tpl": "High Memory Limit/Request Ratio: {count} charts ({pct:.1f}%)",
        "recommended_action": "Reduce memory limit to <=2x the request",
        "yaml_example": """resources:
  requests:
    memory: 128Mi
  limits:
    memory: 256Mi  # Keep ratio <= 2x""",
    },
    "RES007": {
        "id": "charts-low-cpu",
        "category": "resource",
        "title_tpl": "Very Low CPU Request: {count} charts ({pct:.1f}%)",
        "recommended_action": "Review and increase CPU requests if appropriate",
        "yaml_example": """resources:
  requests:
    cpu: 100m""",
    },
    "RES008": {
        "id": "charts-no-memory-request",
        "category": "resource",
        "title_tpl": "No Memory Request: {count} charts ({pct:.1f}%)",
        "recommended_action": "Add memory request for proper scheduling",
        "yaml_example": """resources:
  requests:
    memory: 128Mi""",
    },
    "RES009": {
        "id": "charts-low-memory",
        "category": "resource",
        "title_tpl": "Very Low Memory Request: {count} charts ({pct:.1f}%)",
        "recommended_action": "Review and increase memory requests if appropriate",
        "yaml_example": """resources:
  requests:
    memory: 128Mi""",
    },
    "SEC001": {
        "id": "charts-running-as-root",
        "category": "security",
        "title_tpl": "Running As Root: {count} charts ({pct:.1f}%)",
        "recommended_action": "Configure securityContext to run as non-root user",
        "yaml_example": """securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000""",
    },
}

# Optimizer severity -> recommendation severity
_SEVERITY_MAP: dict[str, str] = {
    "error": "critical",
    "warning": "warning",
    "info": "info",
}


def truncated_list(items: list[str], limit: int = 15) -> str:
    """Format a list with truncation indicator."""
    lines = "\n".join(items[:limit])
    if len(items) > limit:
        lines += f"\n  ... and {len(items) - limit} more"
    return lines


def build_helm_recommendations(
    violations: list[ViolationResult],
    charts: list[Any],
) -> list[dict[str, Any]]:
    """Build helm recommendations by grouping violations by rule_id.

    Also produces summary-level recommendations (low PDB coverage,
    BestEffort QoS) that aren't tied to a single optimizer rule.

    Args:
        violations: List of ViolationResult from optimizer.
        charts: List of ChartInfo objects.

    Returns:
        List of recommendation dicts.
    """
    recs: list[dict[str, Any]] = []
    total_charts = len(charts) if charts else 1

    # Build chart name -> ChartInfo lookup
    chart_by_name: dict[str, Any] = {c.name: c for c in charts}

    # Summary: Low PDB Coverage
    charts_with_pdb = [c for c in charts if c.pdb_enabled]
    pdb_coverage_pct = len(charts_with_pdb) / total_charts * 100
    if pdb_coverage_pct < 50:
        recs.append({
            "id": "low-pdb-coverage",
            "category": "reliability",
            "severity": "critical",
            "title": f"Low PDB Coverage: Only {pdb_coverage_pct:.1f}% of charts have PDBs enabled ({len(charts_with_pdb)}/{total_charts})",
            "description": (
                "PDBs protect applications during node drains, upgrades, and autoscaler operations.\n"
                "Without PDBs, all pods on a node can be evicted simultaneously."
            ),
            "affected_resources": [c.name for c in charts if not c.pdb_enabled],
            "recommended_action": "Enable PDBs in values.yaml with appropriate settings",
            "yaml_example": "pdb:\n  enabled: true\n  minAvailable: 1  # or maxUnavailable: 1",
        })

    # Summary: BestEffort QoS
    charts_best_effort = [c for c in charts if c.qos_class.value == "BestEffort"]
    if charts_best_effort:
        pct = len(charts_best_effort) / total_charts * 100
        recs.append({
            "id": "charts-best-effort",
            "category": "resource",
            "severity": "info",
            "title": f"Charts with BestEffort QoS: {len(charts_best_effort)} charts ({pct:.1f}%)",
            "description": (
                "These charts have no resource requests or limits:\n"
                + truncated_list([f"  - {c.team}/{c.name}" for c in charts_best_effort])
            ),
            "affected_resources": [c.name for c in charts_best_effort],
            "recommended_action": "Add resource requests and limits for proper scheduling",
            "yaml_example": "resources:\n  requests:\n    cpu: 100m\n    memory: 128Mi\n  limits:\n    cpu: 500m\n    memory: 512Mi",
        })

    # Group violations by rule_id and convert to recommendations
    grouped: dict[str, list] = {}
    for v in violations:
        if v.rule_id not in grouped:
            grouped[v.rule_id] = []
        grouped[v.rule_id].append(v)

    for rule_id, rule_violations in grouped.items():
        meta = _RULE_REC_META.get(rule_id)
        if not meta:
            continue

        affected_charts: list[str] = []
        seen: set[str] = set()
        for v in rule_violations:
            if v.chart_name not in seen:
                seen.add(v.chart_name)
                affected_charts.append(v.chart_name)

        count = len(affected_charts)
        pct = count / total_charts * 100

        desc_lines: list[str] = []
        for chart_name in affected_charts:
            chart_obj = chart_by_name.get(chart_name)
            if chart_obj:
                desc_lines.append(f"  - {chart_obj.team}/{chart_obj.name}")
            else:
                desc_lines.append(f"  - {chart_name}")

        severity = _SEVERITY_MAP.get(rule_violations[0].severity.value, "info")

        recs.append({
            "id": meta["id"],
            "category": meta["category"],
            "severity": severity,
            "title": meta["title_tpl"].format(count=count, pct=pct),
            "description": f"{rule_violations[0].description}:\n" + truncated_list(desc_lines),
            "affected_resources": affected_charts,
            "recommended_action": meta["recommended_action"],
            "yaml_example": meta["yaml_example"],
        })

    return recs


async def get_cluster_recommendations(context: str | None = None) -> list[dict[str, Any]]:
    """Get cluster-related recommendations (PDBs, replicas, node resources).

    Args:
        context: Optional kubectl context to use.

    Returns:
        List of recommendation dicts.
    """
    recs: list[dict[str, Any]] = []

    try:
        import shutil

        if not await asyncio.to_thread(shutil.which, "kubectl"):
            return recs

        from kubeagle.controllers import ClusterController

        controller = ClusterController(context=context)

        try:
            connected = await asyncio.wait_for(
                controller.check_cluster_connection(), timeout=5.0,
            )
        except (asyncio.TimeoutError, Exception):
            return recs

        if not connected:
            return recs

        # Fetch independent data sources in parallel
        pdbs, single_replicas, node_resources = await asyncio.gather(
            controller.fetch_pdbs(),
            controller.fetch_single_replica_workloads(),
            controller.fetch_node_resources(),
        )

        # Blocking PDBs
        blocking_pdbs = [p for p in pdbs if p.is_blocking]
        recs.extend({
                "id": f"pdb-blocking-{pdb.namespace}-{pdb.name}",
                "category": "eks",
                "severity": "critical",
                "title": f"PDB '{pdb.namespace}/{pdb.name}' blocking node drains",
                "description": (
                    f"This PDB has configuration issues that prevent pod evictions:\n"
                    f"{pdb.blocking_reason or 'Unknown issue'}"
                ),
                "affected_resources": [f"{pdb.namespace}/{pdb.name}"],
                "recommended_action": "Fix PDB configuration to allow at least 1 disruption",
                "yaml_example": (
                    f"apiVersion: policy/v1\nkind: PodDisruptionBudget\nmetadata:\n"
                    f"  name: {pdb.name}\n  namespace: {pdb.namespace}\nspec:\n"
                    f"  maxUnavailable: 1\n  # OR\n  minAvailable: 50%"
                ),
            } for pdb in blocking_pdbs)

        # Single replica workloads
        by_namespace: dict[str, list] = {}
        for wl in single_replicas:
            if wl.namespace not in by_namespace:
                by_namespace[wl.namespace] = []
            by_namespace[wl.namespace].append(wl)

        for ns, workloads in by_namespace.items():
            if workloads:
                recs.append({
                    "id": f"single-replica-{ns}",
                    "category": "reliability",
                    "severity": "warning",
                    "title": f"Single replica workloads in namespace '{ns}'",
                    "description": (
                        f"Found {len(workloads)} workload(s) running with only 1 replica:\n"
                        + truncated_list([f"  - {w.kind}/{w.name}" for w in workloads])
                    ),
                    "affected_resources": [f"{ns}/{w.name}" for w in workloads],
                    "recommended_action": "Consider increasing replicas to 2-3 for fault tolerance",
                    "yaml_example": (
                        "replicaCount: 3\n\n# AND add anti-affinity\naffinity:\n"
                        "  podAntiAffinity:\n    requiredDuringSchedulingIgnoredDuringExecution:\n"
                        "      - labelSelector:\n          matchLabels:\n            app: my-app\n"
                        "        topologyKey: kubernetes.io/hostname"
                    ),
                })

        # Overcommitted nodes
        overcommitted = [
            n for n in node_resources if n.cpu_req_pct > 100 or n.mem_req_pct > 100
        ]
        if overcommitted:
            recs.append({
                "id": "node-overcommitted",
                "category": "eks",
                "severity": "warning",
                "title": f"Overcommitted nodes detected ({len(overcommitted)} nodes)",
                "description": (
                    "The following nodes have resource requests exceeding allocatable capacity:\n"
                    + truncated_list([
                        f"  - {n.name} (CPU: {n.cpu_req_pct:.1f}%, Mem: {n.mem_req_pct:.1f}%)"
                        for n in overcommitted
                    ])
                ),
                "affected_resources": [n.name for n in overcommitted],
                "recommended_action": "Review pod resource requests or add more nodes",
                "yaml_example": None,
            })

    except Exception:
        logger.exception("Failed to get cluster recommendations")

    return recs


# Recommendation severity filter options
REC_SEVERITY_FILTERS: list[str] = ["all", "critical", "warning", "info"]

# Recommendation category filter options (rebuilt dynamically from data)
REC_CATEGORY_FILTERS: list[str] = ["all", "eks", "reliability", "resource"]


__all__ = [
    "REC_CATEGORY_FILTERS",
    "REC_SEVERITY_FILTERS",
    "OptimizerDataLoadFailed",
    "OptimizerDataLoaded",
    "build_helm_recommendations",
    "get_cluster_recommendations",
    "truncated_list",
]
