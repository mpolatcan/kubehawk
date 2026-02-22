"""Report generator utility for TUI - matches CLI report format."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from kubeagle.constants.enums import QoSClass, Severity
from kubeagle.models.analysis.violation import ViolationResult
from kubeagle.models.charts.chart_info import ChartInfo
from kubeagle.models.core.node_info import NodeInfo
from kubeagle.models.core.workload_info import SingleReplicaWorkloadInfo
from kubeagle.models.events.event_summary import EventSummary
from kubeagle.models.pdb.pdb_info import PDBInfo
from kubeagle.models.reports.report_data import ReportData

if TYPE_CHECKING:
    from kubeagle.controllers import ChartsController, ClusterController

logger = logging.getLogger(__name__)


class TUIReportGenerator:
    """Generate unified analysis reports matching CLI format."""

    # Constants for formatting
    TABLE_HEADER_METRIC_VALUE = (
        "| Metric | Value |",
        "| --- | --- |",
    )

    def __init__(self, data: ReportData):
        self.data = data
        self.lines: list[str] = []
        self._build_lookup_indexes()

    def _build_lookup_indexes(self) -> None:
        """Pre-build lookup indexes to avoid O(n^2) filtering patterns.

        Called once at construction time to create:
        - _team_charts: team name -> list of charts
        - _chart_names_by_team: team name -> set of chart names
        - _violations_by_chart: chart name -> list of violations
        - _team_counts: Counter of charts per team
        - _qos_counts: Counter of QoS class values
        """
        # Team -> charts mapping
        self._team_charts: dict[str, list[ChartInfo]] = defaultdict(list)
        self._chart_names_by_team: dict[str, set[str]] = defaultdict(set)
        for c in self.data.charts:
            self._team_charts[c.team].append(c)
            self._chart_names_by_team[c.team].add(c.name)

        # Chart name -> violations mapping
        self._violations_by_chart: dict[str, list[ViolationResult]] = defaultdict(list)
        for v in self.data.violations:
            self._violations_by_chart[v.chart_name].append(v)

        # Pre-computed counters
        self._team_counts: Counter[str] = Counter(c.team for c in self.data.charts)
        self._qos_counts: Counter[str] = Counter(
            c.qos_class.value for c in self.data.charts
        )

        # Pre-computed violation severity counts
        self._error_violation_count: int = sum(
            1 for v in self.data.violations if v.severity == Severity.ERROR
        )
        self._warning_violation_count: int = sum(
            1 for v in self.data.violations if v.severity == Severity.WARNING
        )

        # Pre-computed chart subsets
        self._single_replica_charts: list[ChartInfo] = [
            c for c in self.data.charts if c.replicas is not None and c.replicas == 1
        ]
        self._charts_without_pdb: list[ChartInfo] = [
            c for c in self.data.charts if not c.pdb_enabled
        ]
        self._charts_best_effort: list[ChartInfo] = [
            c for c in self.data.charts if c.qos_class == QoSClass.BEST_EFFORT
        ]
        self._charts_with_pdb_count: int = sum(
            1 for c in self.data.charts if c.pdb_enabled
        )

    def _team_violation_count(self, team: str) -> int:
        """Get the number of violations for charts belonging to a team."""
        chart_names = self._chart_names_by_team.get(team, set())
        count = 0
        for name in chart_names:
            count += len(self._violations_by_chart.get(name, []))
        return count

    def generate_markdown_report(self, report_format: str = "full") -> str:
        """Generate a markdown report in CLI format.

        Args:
            report_format: One of 'full', 'brief', 'summary'
        """
        self.lines = []

        self._add_header()

        if report_format == "summary":
            self._add_executive_summary()
            self._add_summary_recommendations()
        elif report_format == "brief":
            self._add_executive_summary()
            self._add_eks_brief()
            self._add_helm_brief()
            self._add_recommendations()
        else:  # full
            self._add_executive_summary()
            self._add_eks_analysis()
            self._add_helm_analysis()
            self._add_recommendations()

        self._add_footer()

        return "\n".join(self.lines)

    def generate_json_report(self, report_format: str = "full") -> str:
        """Generate a JSON report with equivalent data."""
        import json

        report_data: dict[str, Any] = {
            "metadata": {
                "generated": self.data.timestamp,
                "cluster": self.data.cluster_name,
                "context": self.data.context,
                "format": report_format,
            },
        }

        if report_format in ("summary", "brief", "full"):
            report_data["summary"] = self._get_summary_dict()

        if report_format in ("brief", "full") and self.data.nodes:
            report_data["cluster"] = self._get_cluster_dict()

        if report_format in ("brief", "full") and self.data.charts:
            report_data["charts"] = self._get_charts_dict()

        if report_format == "full":
            report_data["violations"] = self._get_violations_dict()
            report_data["recommendations"] = self._get_recommendations_list()

        return json.dumps(report_data, indent=2, default=str)

    def _add(self, line: str = "") -> None:
        """Add a line to the report."""
        self.lines.append(line)

    def _add_lines(self, *lines: str) -> None:
        """Add multiple lines to the report."""
        self.lines.extend(lines)

    def _format_cpu(self, cpu_millis: float) -> str:
        """Format CPU in millicores to human readable."""
        if cpu_millis >= 1000:
            return f"{cpu_millis / 1000:.1f}c"
        return f"{cpu_millis:.0f}m"

    def _format_memory(self, memory_bytes: float) -> str:
        """Format memory in bytes to human readable."""
        if memory_bytes >= 1024**3:
            return f"{memory_bytes / (1024**3):.1f}Gi"
        if memory_bytes >= 1024**2:
            return f"{memory_bytes / (1024**2):.0f}Mi"
        if memory_bytes >= 1024:
            return f"{memory_bytes / 1024:.0f}Ki"
        return f"{memory_bytes:.0f}B"

    def _format_ratio(self, ratio: float | None, threshold: float = 2.0) -> str:
        """Format ratio with an ASCII warning indicator."""
        if ratio is None:
            return "N/A"
        if ratio > threshold:
            return f"{ratio:.1f} [WARN]"
        return f"{ratio:.1f}"

    def _status_emoji(self, condition: bool, warn: bool = False) -> str:
        """Return an ASCII status marker for a condition."""
        if condition:
            return "[OK]"
        return "[WARN]" if warn else "[ERR]"

    def _bool_emoji(self, value: bool) -> str:
        """Return an ASCII marker for a boolean value."""
        return "[OK]" if value else "[ERR]"

    def _pct(self, part: int, total: int) -> float:
        """Calculate percentage."""
        return (part / total * 100) if total else 0.0

    def _add_header(self) -> None:
        """Add report header."""
        self._add_lines(
            "# Unified EKS Cluster & Helm Chart Analysis Report",
            "",
            f"- **Cluster:** {self.data.cluster_name}",
            f"- **Generated:** {self.data.timestamp}",
            "- **Source:** EKS Cluster & Local Helm Repository Analysis",
            "",
        )

    def _add_executive_summary(self) -> None:
        """Add executive summary section matching CLI format."""
        self._add_lines(
            "## Executive Summary",
            "",
            "Combined metrics from EKS cluster and Helm chart analysis.",
            "",
        )

        # EKS Cluster Overview
        total_nodes = len(self.data.nodes)
        healthy_nodes = sum(1 for n in self.data.nodes if n.status.value == "Ready")
        cordoned_nodes = 0

        events = self.data.event_summary
        oom_count = events.oom_count if events else 0
        node_not_ready_count = events.node_not_ready_count if events else 0

        total_pdbs = len(self.data.pdbs)
        blocking_pdbs = sum(1 for p in self.data.pdbs if p.is_blocking)

        single_replica_workloads = len(self.data.single_replica_workloads)

        total_charts = len(self.data.charts)
        charts_with_pdb = self._charts_with_pdb_count
        pdb_coverage = self._pct(charts_with_pdb, total_charts)

        teams = set(self._team_counts)

        single_replica_chart_count = len(self._single_replica_charts)

        self._add_lines(
            "### EKS Cluster Overview",
            "",
            *self.TABLE_HEADER_METRIC_VALUE,
            f"| Total Nodes | {total_nodes} |",
            f"| Healthy Nodes | {self._status_emoji(healthy_nodes == total_nodes, warn=True)} {healthy_nodes} |",
            f"| Cordoned Nodes | {self._status_emoji(not cordoned_nodes, warn=True)} {cordoned_nodes} |",
            f"| OOM Events (1h) | {self._status_emoji(not oom_count, warn=True)} {oom_count} |",
            f"| NodeNotReady Events (1h) | {self._status_emoji(not node_not_ready_count, warn=True)} {node_not_ready_count} |",
            f"| Cluster PDBs | {total_pdbs} |",
            f"| PDBs Blocking Drains | {self._status_emoji(not blocking_pdbs)} {blocking_pdbs} |",
            f"| Single Replica Workloads | {self._status_emoji(not single_replica_workloads, warn=True)} {single_replica_workloads} |",
            f"| Charts with PDB Enabled | {charts_with_pdb} |",
            f"| PDB Coverage (Charts) | {self._format_coverage(pdb_coverage)} |",
            "",
            "### Helm Chart Overview",
            "",
            *self.TABLE_HEADER_METRIC_VALUE,
            f"| Total Charts | {total_charts} |",
            f"| Teams Identified | {len(teams)} |",
            f"| Single Replica Charts | {self._status_emoji(not single_replica_chart_count, warn=True)} {single_replica_chart_count} ({self._pct(single_replica_chart_count, total_charts):.1f}%) |",
            "",
            "---",
            "",
        )

    def _format_coverage(self, pct: float) -> str:
        """Format coverage percentage with ASCII status markers."""
        if pct >= 80:
            return f"{pct:.1f}% [OK]"
        if pct >= 50:
            return f"{pct:.1f}% [WARN]"
        return f"{pct:.1f}% [ERR]"

    def _add_eks_brief(self) -> None:
        """Add brief EKS analysis section."""
        self._add_lines("## 1. EKS Cluster Analysis", "")

        if not self.data.nodes:
            self._add("_No EKS cluster data available._")
            return

        # Node Resources
        self._add_lines(
            "### 1.1 Node Resources",
            "",
            "| Node | CPU Allocatable | Memory Allocatable | CPU Requests | Memory Requests |",
            "| --- | --- | --- | --- | --- |",
        )

        for node in sorted(self.data.nodes, key=lambda n: n.name):
            self._add(
                f"| {node.name} | {self._format_cpu(node.cpu_allocatable)} | {self._format_memory(node.memory_allocatable)} | {self._format_cpu(node.cpu_requests)} | {self._format_memory(node.memory_requests)} |"
            )
        self._add()

        # Event Summary
        events = self.data.event_summary
        self._add_lines(
            "### 1.2 Event Summary",
            "",
            "| Type | Count |",
            "| --- | --- |",
        )

        if events:
            event_types = [
                ("OOMKilling", events.oom_count),
                ("NodeNotReady", events.node_not_ready_count),
                ("FailedScheduling", events.failed_scheduling_count),
                ("BackOff", events.backoff_count),
                ("Unhealthy", events.unhealthy_count),
                ("FailedMount", events.failed_mount_count),
                ("Evicted", events.evicted_count),
            ]
            for event_type, count in event_types:
                self._add(f"| {event_type} | {count} |")
        else:
            self._add("| No events data | 0 |")
        self._add()

        # PDB Analysis
        self._add_lines(
            "### 1.3 Pod Disruption Budgets",
            "",
            "| Name | Namespace | Status | Issues |",
            "| --- | --- | --- | --- |",
        )

        for pdb in sorted(self.data.pdbs, key=lambda p: f"{p.namespace}/{p.name}"):
            status = self._status_emoji(not pdb.is_blocking)
            issues = pdb.blocking_reason or "None"
            self._add(f"| {pdb.name} | {pdb.namespace} | {status} | {issues} |")
        self._add()

        # Single Replica Workloads
        self._add_lines(
            "### 1.4 Single Replica Workloads",
            "",
            "| Name | Namespace | Kind | Helm Release | Chart |",
            "| --- | --- | --- | --- | --- |",
        )

        for wl in sorted(
            self.data.single_replica_workloads, key=lambda w: f"{w.namespace}/{w.name}"
        ):
            self._add(
                f"| {wl.name} | {wl.namespace} | {wl.kind} | {wl.helm_release or '-'} | {wl.chart_name or '-'} |"
            )
        self._add("---")

    def _add_eks_analysis(self) -> None:
        """Add full EKS analysis section matching CLI format.

        Spec parity note:
        This section currently renders the data available in TUI report models.
        CLI-only subsections requiring extra source data are intentionally omitted.
        """
        self._add_lines("## 1. EKS Cluster Analysis", "")

        if not self.data.nodes:
            self._add("_No EKS cluster data available._")
            return

        # Node Resources (detailed)
        self._add_lines(
            "### 1.1 Node Resources",
            "",
            "| Node | CPU Allocatable | Memory Allocatable | CPU Requests | Memory Requests |",
            "| --- | --- | --- | --- | --- |",
        )

        for node in sorted(self.data.nodes, key=lambda n: n.name):
            self._add(
                f"| {node.name} | {self._format_cpu(node.cpu_allocatable)} | {self._format_memory(node.memory_allocatable)} | {self._format_cpu(node.cpu_requests)} | {self._format_memory(node.memory_requests)} |"
            )
        self._add()

        # Event Summary
        events = self.data.event_summary
        self._add_lines(
            "### 1.2 Event Summary",
            "",
            "| Type | Count | Status |",
            "| --- | --- | --- |",
        )

        if events:
            event_types = [
                ("OOMKilling", events.oom_count),
                ("NodeNotReady", events.node_not_ready_count),
                ("FailedScheduling", events.failed_scheduling_count),
                ("BackOff", events.backoff_count),
                ("Unhealthy", events.unhealthy_count),
                ("FailedMount", events.failed_mount_count),
                ("Evicted", events.evicted_count),
            ]
            for event_type, count in event_types:
                self._add(
                    f"| {event_type} | {count} | {self._status_emoji(not count, warn=True)} |"
                )
            self._add()
        else:
            self._add("| No events data | 0 | [OK] |")
        self._add()

        # PDB Analysis
        self._add_lines(
            "### 1.3 Pod Disruption Budgets",
            "",
            "| Name | Namespace | Status | Issues |",
            "| --- | --- | --- | --- |",
        )

        for pdb in sorted(self.data.pdbs, key=lambda p: f"{p.namespace}/{p.name}"):
            status = self._status_emoji(not pdb.is_blocking)
            issues = pdb.blocking_reason or "None"
            self._add(f"| {pdb.name} | {pdb.namespace} | {status} | {issues} |")
        self._add()

        # Single Replica Workloads
        self._add_lines(
            "### 1.4 Single Replica Workloads",
            "",
            "| Name | Namespace | Kind | Helm Release | Chart |",
            "| --- | --- | --- | --- | --- |",
        )

        for wl in sorted(
            self.data.single_replica_workloads, key=lambda w: f"{w.namespace}/{w.name}"
        ):
            self._add(
                f"| {wl.name} | {wl.namespace} | {wl.kind} | {wl.helm_release or '-'} | {wl.chart_name or '-'} |"
            )
        self._add()

        # Node Group Analysis
        node_groups = Counter(n.node_group for n in self.data.nodes)
        self._add_lines(
            "### 1.5 Node Group Distribution",
            "",
            "| Node Group | Node Count |",
            "| --- | --- |",
        )
        for ng, count in sorted(node_groups.items(), key=lambda x: x[1], reverse=True):
            self._add(f"| {ng} | {count} |")
        self._add()

        self._add("---")

    def _add_helm_brief(self) -> None:
        """Add brief Helm analysis section."""
        self._add_lines("## 2. Helm Chart Analysis", "")

        if not self.data.charts:
            self._add("_No Helm chart data available._")
            return

        # By Team
        self._add_lines(
            "### 2.1 By Team",
            "",
            "| Team | Charts | Violations |",
            "| --- | --- | --- |",
        )
        for team in sorted(self._team_counts):
            team_violations = self._team_violation_count(team)
            self._add(f"| {team} | {self._team_counts[team]} | {team_violations} |")
        self._add()

        # QoS Class Distribution
        self._add_lines(
            "### 2.2 QoS Class Distribution",
            "",
            "| QoS Class | Charts | Percentage |",
            "| --- | --- | --- |",
        )
        total_charts = len(self.data.charts)
        for qos in QoSClass:
            count = self._qos_counts.get(qos.value, 0)
            pct = self._pct(count, total_charts)
            self._add(f"| {qos.value} | {count} | {pct:.1f}% |")
        self._add()

        # Single Replica Charts
        self._add_lines(
            "### 2.3 Single Replica Charts",
            "",
            "| Chart | Team | Replicas |",
            "| --- | --- | --- |",
        )
        for chart in sorted(self._single_replica_charts, key=lambda c: c.name):
            self._add(f"| {chart.name} | {chart.team} | {chart.replicas} |")
        self._add()

        # Resource Analysis
        self._add_lines(
            "### 2.4 Resource Analysis",
            "",
            "| Chart | CPU Request | CPU Limit | Memory Request | Memory Limit |",
            "| --- | --- | --- | --- | --- |",
        )
        sorted_charts = sorted(self.data.charts, key=lambda c: c.name)
        for chart in sorted_charts[:50]:
            self._add(
                f"| {chart.name} | {self._format_cpu(chart.cpu_request)} | {self._format_cpu(chart.cpu_limit)} | {self._format_memory(chart.memory_request)} | {self._format_memory(chart.memory_limit)} |"
            )
        if len(sorted_charts) > 50:
            self._add(f"\n*Showing 50 of {len(sorted_charts)} charts. Export full report for complete data.*")
        self._add("---")

    def _add_helm_analysis(self) -> None:
        """Add full Helm analysis section matching CLI format.

        Spec parity note:
        This section currently renders the data available in TUI report models.
        CLI-only subsections requiring extra source data are intentionally omitted.
        """
        self._add_lines("## 2. Helm Chart Analysis", "")

        if not self.data.charts:
            self._add("_No Helm chart data available._")
            return

        # By Team
        self._add_lines(
            "### 2.1 By Team",
            "",
            "| Team | Charts | Violations |",
            "| --- | --- | --- |",
        )
        for team in sorted(self._team_counts):
            team_violations = self._team_violation_count(team)
            self._add(f"| {team} | {self._team_counts[team]} | {team_violations} |")
        self._add()

        # QoS Class Distribution
        self._add_lines(
            "### 2.2 QoS Class Distribution",
            "",
            "| QoS Class | Charts | Percentage |",
            "| --- | --- | --- |",
        )
        total_charts = len(self.data.charts)
        for qos in QoSClass:
            count = self._qos_counts.get(qos.value, 0)
            pct = self._pct(count, total_charts)
            self._add(f"| {qos.value} | {count} | {pct:.1f}% |")
        self._add()

        # Single Replica Charts
        self._add_lines(
            "### 2.3 Single Replica Charts",
            "",
            "| Chart | Team | Replicas | QoS Class |",
            "| --- | --- | --- | --- |",
        )
        for chart in sorted(self._single_replica_charts, key=lambda c: c.name):
            self._add(
                f"| {chart.name} | {chart.team} | {chart.replicas} | {chart.qos_class.value} |"
            )
        self._add()

        # Resource Analysis
        self._add_lines(
            "### 2.4 Resource Analysis",
            "",
            "| Chart | CPU Request | CPU Limit | Memory Request | Memory Limit |",
            "| --- | --- | --- | --- | --- |",
        )
        sorted_charts = sorted(self.data.charts, key=lambda c: c.name)
        for chart in sorted_charts[:50]:
            self._add(
                f"| {chart.name} | {self._format_cpu(chart.cpu_request)} | {self._format_cpu(chart.cpu_limit)} | {self._format_memory(chart.memory_request)} | {self._format_memory(chart.memory_limit)} |"
            )
        if len(sorted_charts) > 50:
            self._add(f"\n*Showing 50 of {len(sorted_charts)} charts. Export full report for complete data.*")
        self._add()

        # Violations Summary
        self._add_lines(
            "### 2.5 Violations Summary",
            "",
            "| ID | Severity | Chart | Description | Recommendation |",
            "| --- | --- | --- | --- | --- |",
        )
        for v in sorted(
            self.data.violations, key=lambda x: (x.severity.value, x.chart_name)
        ):
            severity_marker = f"[{v.severity.value.upper()}]"
            self._add(
                f"| {v.id} | {severity_marker} | {v.chart_name} | {v.description} | Configure {v.recommended_value} |"
            )
        self._add()

        self._add("---")

    def _add_summary_recommendations(self) -> None:
        """Add summary recommendations section."""
        self._add_lines(
            "## 2. Recommendations",
            "",
            "### Summary",
            "",
            f"- Total Charts: {len(self.data.charts)}",
            f"- Charts with Violations: {len(self.data.violations)}",
            "",
        )

        if self.data.violations:
            self._add(f"- Errors: {self._error_violation_count}")
            self._add(f"- Warnings: {self._warning_violation_count}")
            self._add()

        self._add("### Priority Actions")
        for v in sorted(
            self.data.violations, key=lambda x: (x.severity.value, x.chart_name)
        )[:10]:
            self._add(f"- **{v.chart_name}**: {v.description}")

    def _add_recommendations(self) -> None:
        """Add recommendations section matching CLI format."""
        self._add_lines(
            "## 3. Recommendations",
            "",
        )

        # EKS Recommendations
        self._add_lines(
            "### 3.1 EKS Cluster Recommendations",
            "",
        )

        blocking_pdbs = [p for p in self.data.pdbs if p.is_blocking]
        if blocking_pdbs:
            self._add_lines(
                "**[CRITICAL] PDBs Blocking Node Drains**",
                "",
                f"- {len(blocking_pdbs)} PDB(s) in the cluster are configured to block all pod evictions",
                "  - This will prevent node drains, cluster upgrades, and autoscaler operations",
                "",
            )
            for pdb in blocking_pdbs[:5]:
                self._add(f"  - `{pdb.namespace}/{pdb.name}`: {pdb.blocking_reason}")
            if len(blocking_pdbs) > 5:
                self._add(f"  - ... and {len(blocking_pdbs) - 5} more")
            self._add()
        else:
            self._add_lines(
                "[OK] No critical EKS issues found.",
                "",
            )

        # Helm Recommendations
        self._add_lines(
            "### 3.2 Helm Chart Recommendations",
            "",
        )

        # Missing PDBs
        if self._charts_without_pdb:
            self._add_lines(
                f"**[WARN] Charts Without PDBs:** {len(self._charts_without_pdb)} charts",
                "",
            )

        # Missing Resources
        if self._charts_best_effort:
            self._add_lines(
                f"**[WARN] Missing Resource Definitions:** {len(self._charts_best_effort)} charts",
                "",
            )

        # Single Replica
        if self._single_replica_charts:
            self._add_lines(
                f"**[WARN] Single Replica Charts:** {len(self._single_replica_charts)} charts have no pod redundancy",
                "",
                "For production workloads, consider:",
                "",
                "1. **Increase replicas** to at least 2-3 for fault tolerance",
                "2. **Add PodDisruptionBudget** to protect during node drains",
                "3. **Configure anti-affinity** to spread replicas across nodes",
                "",
            )

        # Violation-based recommendations
        self._add_lines(
            "### 3.3 Violation Fixes",
            "",
            "| ID | Severity | Chart | Action |",
            "| --- | --- | --- | --- |",
        )
        for v in sorted(
            self.data.violations, key=lambda x: (x.severity.value, x.chart_name)
        ):
            severity_marker = "ERROR" if v.severity == Severity.ERROR else "WARN"
            self._add(
                f"| {v.id} | {severity_marker} | {v.chart_name} | {v.description} |"
            )
        self._add()

        self._add("---")

    def _add_footer(self) -> None:
        """Add report footer."""
        self._add_lines(
            f"**Report Generated:** {self.data.timestamp}",
            "**Analysis Tool:** KubEagle TUI v2.0",
        )

    def _get_summary_dict(self) -> dict[str, Any]:
        """Get summary data as dictionary."""
        return {
            "total_charts": len(self.data.charts),
            "total_nodes": len(self.data.nodes),
            "total_violations": len(self.data.violations),
            "error_violations": self._error_violation_count,
            "warning_violations": self._warning_violation_count,
            "charts_with_pdb": self._charts_with_pdb_count,
            "single_replica_charts": len(self._single_replica_charts),
            "single_replica_workloads": len(self.data.single_replica_workloads),
            "blocking_pdbs": sum(1 for p in self.data.pdbs if p.is_blocking),
        }

    def _get_cluster_dict(self) -> dict[str, Any]:
        """Get cluster data as dictionary."""
        return {
            "nodes": [
                {
                    "name": n.name,
                    "status": n.status.value,
                    "node_group": n.node_group,
                    "cpu_allocatable": n.cpu_allocatable,
                    "memory_allocatable": n.memory_allocatable,
                    "cpu_requests": n.cpu_requests,
                    "memory_requests": n.memory_requests,
                }
                for n in self.data.nodes
            ],
            "event_summary": {
                "oom_count": self.data.event_summary.oom_count
                if self.data.event_summary
                else 0,
                "node_not_ready_count": self.data.event_summary.node_not_ready_count
                if self.data.event_summary
                else 0,
            }
            if self.data.event_summary
            else {},
            "pdbs": [
                {
                    "name": p.name,
                    "namespace": p.namespace,
                    "is_blocking": p.is_blocking,
                    "blocking_reason": p.blocking_reason,
                }
                for p in self.data.pdbs
            ],
            "single_replica_workloads": [
                {
                    "name": w.name,
                    "namespace": w.namespace,
                    "kind": w.kind,
                    "helm_release": w.helm_release,
                    "chart_name": w.chart_name,
                }
                for w in self.data.single_replica_workloads
            ],
        }

    def _get_charts_dict(self) -> dict[str, Any]:
        """Get charts data as dictionary."""
        return {
            "total_charts": len(self.data.charts),
            "by_team": dict(self._team_counts),
            "by_qos": dict(self._qos_counts),
            "single_replica_count": len(self._single_replica_charts),
            "charts": [
                {
                    "name": c.name,
                    "team": c.team,
                    "qos_class": c.qos_class.value,
                    "replicas": c.replicas,
                    "cpu_request": c.cpu_request,
                    "cpu_limit": c.cpu_limit,
                    "memory_request": c.memory_request,
                    "memory_limit": c.memory_limit,
                    "has_liveness": c.has_liveness,
                    "has_readiness": c.has_readiness,
                    "has_startup": c.has_startup,
                    "has_anti_affinity": c.has_anti_affinity,
                    "has_topology_spread": c.has_topology_spread,
                    "pdb_enabled": c.pdb_enabled,
                }
                for c in self.data.charts
            ],
        }

    def _get_violations_dict(self) -> list[dict[str, Any]]:
        """Get violations as list of dictionaries."""
        return [
            {
                "id": v.id,
                "chart_name": v.chart_name,
                "rule_name": v.rule_name,
                "severity": v.severity.value,
                "description": v.description,
                "current_value": v.current_value,
                "recommended_value": v.recommended_value,
                "fix_available": v.fix_available,
            }
            for v in self.data.violations
        ]

    def _get_recommendations_list(self) -> list[str]:
        """Get recommendations as list of strings."""
        recommendations = []

        # Blocking PDBs
        blocking_pdbs = [p for p in self.data.pdbs if p.is_blocking]
        recommendations.extend(
                f"Fix blocking PDB: {pdb.namespace}/{pdb.name} - {pdb.blocking_reason}"
                for pdb in blocking_pdbs
            )

        # Missing PDBs
        recommendations.extend(f"Enable PDB for {chart.name}" for chart in self._charts_without_pdb[:5])

        # Single replica
        recommendations.extend(
            f"Consider increasing replicas for {chart.name}" for chart in self._single_replica_charts[:5]
        )

        # Violations
        recommendations.extend(
            f"[{v.severity.value.upper()}] {v.chart_name}: {v.description}"
            for v in sorted(self.data.violations, key=lambda x: (x.severity.value, x.chart_name))[:10]
        )

        return recommendations


async def collect_report_data(
    cluster_controller: ClusterController | None,
    charts_controller: ChartsController | None,
    optimizer_controller: Any,
    charts_path: str | None,
    context: str | None,
    on_partial: Callable[[ReportData], None] | None = None,
) -> ReportData:
    """Collect all data needed for report generation.

    Args:
        cluster_controller: Cluster controller for EKS data
        charts_controller: Charts controller for Helm data
        optimizer_controller: Optimizer controller for violations
        charts_path: Path to charts directory
        context: Kubernetes context

    Returns:
        ReportData container with all collected data
    """
    # Initialize data containers
    nodes: list[NodeInfo] = []
    event_summary: EventSummary | None = None
    pdbs: list[PDBInfo] = []
    single_replica_workloads: list[SingleReplicaWorkloadInfo] = []
    charts: list[ChartInfo] = []
    violations: list[ViolationResult] = []

    cluster_name = "Unknown"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def _build_report_data() -> ReportData:
        return ReportData(
            nodes=nodes,
            event_summary=event_summary,
            pdbs=pdbs,
            single_replica_workloads=single_replica_workloads,
            charts=charts,
            violations=violations,
            cluster_name=cluster_name,
            context=context,
            timestamp=timestamp,
        )

    def _emit_partial_update() -> None:
        if on_partial is None:
            return
        try:
            on_partial(_build_report_data())
        except Exception:
            logger.debug("Partial report update callback failed", exc_info=True)

    async def _collect_cluster_data() -> None:
        """Collect cluster data and emit one partial update when finished."""
        nonlocal cluster_name
        nonlocal event_summary
        nonlocal nodes
        nonlocal pdbs
        nonlocal single_replica_workloads

        if cluster_controller is None:
            return
        try:
            connected = await cluster_controller.check_cluster_connection()
            if not connected:
                return

            # Get cluster name from kubectl
            import subprocess

            cmd = ["kubectl"]
            if context:
                cmd.extend(["--context", context])
            cmd.extend(["cluster-info", "--request-timeout=10s"])
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
            )
            stdout_text = result.stdout
            if isinstance(stdout_text, bytes):
                stdout_text = stdout_text.decode(errors="ignore")

            if "Kubernetes control plane" in stdout_text:
                for line in stdout_text.split("\n"):
                    if "https://" in line:
                        cluster_name = line.split("//")[1].split(":")[0]
                        break

            try:
                (
                    nodes,
                    event_summary,
                    pdbs,
                    single_replica_workloads,
                ) = await asyncio.wait_for(
                    asyncio.gather(
                        cluster_controller.fetch_nodes(),
                        cluster_controller.get_event_summary(),
                        cluster_controller.fetch_pdbs(),
                        cluster_controller.fetch_single_replica_workloads(),
                    ),
                    timeout=60.0,
                )
            except asyncio.TimeoutError:
                logger.error("K8s API call timed out after 60 seconds")
            except Exception as e:
                logger.error("Error collecting cluster data: %s", e)

            _emit_partial_update()
        except Exception as e:
            logger.error("Error checking cluster connection: %s", e)

    async def _collect_charts_data() -> None:
        """Collect chart analysis data and emit one partial update when ready."""
        nonlocal charts
        if not charts_controller or not charts_path:
            return
        try:
            charts = await charts_controller.analyze_all_charts_async()
            _emit_partial_update()
        except Exception as e:
            logger.error("Error analyzing charts: %s", e)

    collection_tasks: list[asyncio.Task[None]] = []
    if cluster_controller is not None:
        collection_tasks.append(asyncio.create_task(_collect_cluster_data()))
    if charts_controller is not None and charts_path:
        collection_tasks.append(asyncio.create_task(_collect_charts_data()))
    if collection_tasks:
        await asyncio.gather(*collection_tasks)

    # Collect violations
    if optimizer_controller and charts:
        violations = await asyncio.to_thread(
            optimizer_controller.check_all_charts,
            charts,
        )

    return _build_report_data()
