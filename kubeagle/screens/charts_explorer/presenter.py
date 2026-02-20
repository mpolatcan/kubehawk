"""Charts Explorer presenter - filtering, formatting, grouping logic."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from kubeagle.screens.charts_explorer.config import (
    EXTREME_RATIO_THRESHOLD,
    SortBy,
    ViewFilter,
)

if TYPE_CHECKING:
    from kubeagle.models.charts.chart_info import ChartInfo


class ChartsExplorerPresenter:
    """Presenter for Charts Explorer screen.

    Handles filtering, formatting, and grouping logic for the unified charts table.
    """

    def __init__(self) -> None:
        self._violations: dict[str, int] = {}
        self._violation_revision = 0

    def set_violations(self, violations: dict[str, int]) -> None:
        """Store violation counts per chart name.

        Args:
            violations: Mapping of chart_name -> violation_count.
        """
        if violations == self._violations:
            return
        self._violations = violations
        self._violation_revision += 1

    @property
    def violation_revision(self) -> int:
        """Monotonic counter incremented whenever violations are updated."""
        return self._violation_revision

    # =========================================================================
    # Filtering
    # =========================================================================

    def apply_filters(
        self,
        charts: list[ChartInfo],
        view: ViewFilter,
        team_filter: set[str] | str | None,
        search_query: str,
        active_only: bool,
        active_charts: set[str] | None,
    ) -> list[ChartInfo]:
        """Apply all filters and return matching charts.

        Args:
            charts: Full list of charts.
            view: Current view filter preset.
            team_filter: Selected team names, single team, or None (all teams).
            search_query: Free-text search string.
            active_only: Whether to filter to active charts only.
            active_charts: Set of active chart names (from cluster).

        Returns:
            Filtered list of charts.
        """
        result = list(charts)

        # View filter
        if view == ViewFilter.EXTREME_RATIOS:
            result = [c for c in result if self._is_extreme_ratio(c)]
        elif view == ViewFilter.SINGLE_REPLICA:
            result = [c for c in result if c.replicas is not None and c.replicas == 1]
        elif view == ViewFilter.NO_PDB:
            result = [c for c in result if not c.pdb_enabled]
        elif view == ViewFilter.WITH_VIOLATIONS:
            result = [c for c in result if c.name in self._violations]

        # Team filter
        team_values: set[str]
        if isinstance(team_filter, str):
            team_values = {team_filter}
        elif team_filter is None:
            team_values = set()
        else:
            team_values = set(team_filter)

        if team_values:
            result = [c for c in result if c.team in team_values]

        # Active filter
        if active_only and active_charts is not None:
            result = [c for c in result if c.name in active_charts]

        # Search filter
        if search_query:
            q = search_query.lower()
            result = [
                c for c in result
                if q in c.name.lower()
                or q in c.team.lower()
                or q in c.values_file.lower()
                or q in c.qos_class.value.lower()
            ]

        return result

    # =========================================================================
    # Row Building
    # =========================================================================

    def sort_charts(
        self,
        charts: list[ChartInfo],
        *,
        sort_by: SortBy,
        descending: bool,
    ) -> list[ChartInfo]:
        """Sort charts by a selected field while keeping missing values at the end."""
        if not charts:
            return []

        def _ratio(request: float, limit: float) -> float | None:
            if request <= 0 or limit <= 0:
                return None
            return limit / request

        def _value(chart: ChartInfo) -> str | float | int | None:
            if sort_by == SortBy.CHART:
                return chart.name.lower()
            if sort_by == SortBy.TEAM:
                return chart.team.lower()
            if sort_by == SortBy.QOS:
                return chart.qos_class.value.lower()
            if sort_by == SortBy.CPU_REQUEST:
                return chart.cpu_request if chart.cpu_request > 0 else None
            if sort_by == SortBy.CPU_LIMIT:
                return chart.cpu_limit if chart.cpu_limit > 0 else None
            if sort_by == SortBy.CPU_RATIO:
                return _ratio(chart.cpu_request, chart.cpu_limit)
            if sort_by == SortBy.MEMORY_REQUEST:
                return chart.memory_request if chart.memory_request > 0 else None
            if sort_by == SortBy.MEMORY_LIMIT:
                return chart.memory_limit if chart.memory_limit > 0 else None
            if sort_by == SortBy.MEMORY_RATIO:
                return _ratio(chart.memory_request, chart.memory_limit)
            if sort_by == SortBy.REPLICAS:
                return chart.replicas
            if sort_by == SortBy.VALUES_FILE:
                return chart.values_file.lower()
            if sort_by == SortBy.VIOLATIONS:
                return self._violations.get(chart.name, 0)
            return chart.name.lower()

        present: list[tuple[ChartInfo, str | float | int]] = []
        missing: list[ChartInfo] = []

        for chart in charts:
            value = _value(chart)
            if value is None:
                missing.append(chart)
            else:
                present.append((chart, value))

        present.sort(key=lambda item: item[1], reverse=descending)
        return [chart for chart, _ in present] + missing

    def format_chart_row(self, chart: ChartInfo) -> tuple[str, ...]:
        """Format a single chart into a row tuple.

        Columns: Chart, Namespace, Team, Values File Type, QoS, CPU R/L,
                 Mem R/L, Replicas, Probes, Affinity, PDB, Chart Path
        """
        probes_str = self._build_probes_str(chart)
        values_file_type = self._classify_values_file_type(chart.values_file)
        namespace = chart.namespace or "-"

        affinity = "Anti" if chart.has_anti_affinity else "No"
        if chart.has_topology_spread:
            affinity += "+Topology"

        pdb = "Yes" if chart.pdb_enabled else "No"
        replicas = str(chart.replicas) if chart.replicas is not None else "N/A"

        cpu_req = f"{chart.cpu_request:.0f}m" if chart.cpu_request else "-"
        cpu_lim = f"{chart.cpu_limit:.0f}m" if chart.cpu_limit else "-"
        cpu_ratio_str = self._format_ratio(chart.cpu_request, chart.cpu_limit)
        cpu_req_lim = self._format_req_lim_with_ratio(cpu_req, cpu_lim, cpu_ratio_str)

        mem_req = self._format_memory(chart.memory_request) if chart.memory_request else "-"
        mem_lim = self._format_memory(chart.memory_limit) if chart.memory_limit else "-"
        mem_ratio_str = self._format_ratio(chart.memory_request, chart.memory_limit)
        mem_req_lim = self._format_req_lim_with_ratio(mem_req, mem_lim, mem_ratio_str)

        chart_name = self._format_chart_name(chart)

        return (
            chart_name,
            namespace,
            chart.team,
            values_file_type,
            chart.qos_class.value,
            cpu_req_lim,
            mem_req_lim,
            replicas,
            probes_str,
            affinity,
            pdb,
            chart.values_file,
        )

    # =========================================================================
    # Summary
    # =========================================================================

    def build_summary_metrics(
        self,
        all_charts: list[ChartInfo],
        filtered_charts: list[ChartInfo],
    ) -> dict[str, str | int | float]:
        """Build numeric summary metrics for KPI-style summary rows.

        Uses a single pass over filtered_charts for all per-chart accumulators.
        """
        total = len(all_charts)
        shown = len(filtered_charts)
        total_violations = sum(self._violations.values())

        filtered_violations = 0
        filtered_extreme = 0
        filtered_single_replica = 0
        filtered_no_pdb = 0
        total_cpu_req = 0.0
        total_cpu_lim = 0.0
        total_mem_req = 0.0
        total_mem_lim = 0.0

        violations = self._violations
        is_extreme = self._is_extreme_ratio
        for chart in filtered_charts:
            if chart.name in violations:
                filtered_violations += 1
            if is_extreme(chart):
                filtered_extreme += 1
            if chart.replicas is not None and chart.replicas == 1:
                filtered_single_replica += 1
            if not chart.pdb_enabled:
                filtered_no_pdb += 1
            total_cpu_req += chart.cpu_request
            total_cpu_lim += chart.cpu_limit
            total_mem_req += chart.memory_request
            total_mem_lim += chart.memory_limit

        return {
            "total": total,
            "shown": shown,
            "violations": total_violations,
            "filtered_violations": filtered_violations,
            "filtered_extreme": filtered_extreme,
            "filtered_single_replica": filtered_single_replica,
            "filtered_no_pdb": filtered_no_pdb,
            "cpu_req": total_cpu_req,
            "cpu_lim": total_cpu_lim,
            "mem_req": total_mem_req,
            "mem_lim": total_mem_lim,
            "mem_req_fmt": self._format_memory(total_mem_req) if total_mem_req > 0 else "-",
            "mem_lim_fmt": self._format_memory(total_mem_lim) if total_mem_lim > 0 else "-",
        }

    @staticmethod
    def format_count_with_percentage(count: int, total: int) -> str:
        """Format count with percentage in parenthesis."""
        safe_count = max(count, 0)
        if total <= 0:
            return f"{safe_count} (0%)"
        percentage = (safe_count / total) * 100
        return f"{safe_count} ({percentage:.0f}%)"

    @staticmethod
    def format_fraction_with_percentage(part: int, total: int) -> str:
        """Format fraction with percentage in parenthesis."""
        safe_part = max(part, 0)
        safe_total = max(total, 0)
        if safe_total <= 0:
            return f"{safe_part}/{safe_total} (0%)"
        percentage = (safe_part / safe_total) * 100
        return f"{safe_part}/{safe_total} ({percentage:.0f}%)"

    # =========================================================================
    # Helpers (ported from ChartsTableBuilder)
    # =========================================================================

    @staticmethod
    def _build_probes_str(chart: ChartInfo) -> str:
        """Build probes status string from chart info."""
        probes: list[str] = []
        if chart.has_liveness:
            probes.append("L")
        if chart.has_readiness:
            probes.append("R")
        if chart.has_startup:
            probes.append("S")
        return ", ".join(probes) if probes else "None"

    @staticmethod
    def _classify_values_file_type(values_file: str) -> str:
        """Classify values file path into user-facing type labels."""
        file_name = Path(values_file).name.lower()
        if "automation" in file_name:
            return "Automation"
        if file_name == "values.yaml":
            return "Main"
        if "default" in file_name:
            return "Default"
        return "Other"

    @staticmethod
    def _format_memory(bytes_val: float) -> str:
        """Format memory value from bytes to human readable string."""
        if bytes_val >= 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024 * 1024):.1f}Gi"
        if bytes_val >= 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f}Mi"
        if bytes_val >= 1024:
            return f"{bytes_val / 1024:.1f}Ki"
        return f"{bytes_val:.0f}B"

    @staticmethod
    def _format_compact_pair(left: str, right: str) -> str:
        """Render a compact left/right value pair for table cells."""
        if left == "-" and right == "-":
            return "-"
        return f"{left} / {right}"

    @staticmethod
    def _format_ratio(request: float | None, limit: float | None) -> str:
        """Format a limit/request ratio with warning markup for extreme values."""
        if not request or not limit or request <= 0:
            return "-"
        ratio = limit / request
        if ratio >= 4.0:
            return f"[bold #ff3b30]{ratio:.1f}×[/bold #ff3b30]"
        if ratio >= 2.0:
            return f"[bold #ff9f0a]{ratio:.1f}×[/bold #ff9f0a]"
        return f"{ratio:.1f}×"

    @staticmethod
    def _format_chart_name(chart: ChartInfo) -> str:
        """Render chart name with Helm marker prefix."""
        return f"⎈ {chart.name}"

    @classmethod
    def _format_req_lim_with_ratio(
        cls,
        request_text: str,
        limit_text: str,
        ratio_text: str,
    ) -> str:
        """Render request/limit text with inline ratio for compact columns."""
        base_text = cls._format_compact_pair(request_text, limit_text)
        if ratio_text == "-" or base_text == "-":
            return base_text
        return f"{base_text} [dim]·[/dim] {ratio_text}"

    @staticmethod
    def _is_extreme_ratio(chart: ChartInfo) -> bool:
        """Check if chart has extreme CPU or memory ratio."""
        if chart.cpu_request and chart.cpu_limit and chart.cpu_request > 0 and chart.cpu_limit / chart.cpu_request >= EXTREME_RATIO_THRESHOLD:
            return True
        return bool(
            chart.memory_request and chart.memory_limit and chart.memory_request > 0
            and chart.memory_limit / chart.memory_request >= EXTREME_RATIO_THRESHOLD
        )
