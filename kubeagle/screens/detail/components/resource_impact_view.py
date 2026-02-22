"""Resource impact analysis view — before/after optimization comparison.

Shows metric cards grid and per-chart resource breakdown.
Supports filtering by Team and Chart.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypedDict

from textual.app import ComposeResult
from textual.screen import ModalScreen

from kubeagle.models.optimization.resource_impact import (
    ResourceImpactResult,
)
from kubeagle.screens.detail.config import (
    IMPACT_CHART_TABLE_COLUMNS,
)
from kubeagle.widgets import (
    CustomButton,
    CustomContainer,
    CustomDataTable,
    CustomHorizontal,
    CustomLoadingIndicator,
    CustomSelectionList,
    CustomStatic,
    CustomVertical,
)

if TYPE_CHECKING:
    from kubeagle.models.analysis.violation import ViolationResult
    from kubeagle.models.charts.chart_info import ChartInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_cpu(millicores: float) -> str:
    """Format CPU millicores for display with thousands separators."""
    value = abs(millicores)
    if value == 0:
        return "0m"
    if value >= 1000 and value % 1000 == 0:
        cores = int(value / 1000)
        return f"{cores:,}" if cores >= 1000 else str(cores)
    rounded = round(value)
    return f"{rounded:,}m" if rounded >= 1000 else f"{rounded}m"


def _format_memory(memory_bytes: float) -> str:
    """Format memory bytes for display (Mi or Gi) with separators."""
    value = abs(memory_bytes)
    if value == 0:
        return "0Mi"
    gib = value / (1024**3)
    if gib >= 1.0:
        if gib >= 100:
            return f"{gib:,.1f}Gi"
        if gib == int(gib):
            return f"{int(gib)}Gi"
        return f"{gib:.1f}Gi"
    mib = value / (1024**2)
    rounded = round(mib)
    return f"{rounded:,}Mi" if rounded >= 1000 else f"{rounded}Mi"


def _format_signed(value: float, fmt_fn: Callable[[float], str]) -> str:
    """Format a value with +/- sign prefix."""
    sign = "+" if value > 0 else ("-" if value < 0 else "")
    return f"{sign}{fmt_fn(value)}"


def _format_pct(pct: float) -> str:
    """Format percentage with sign."""
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}%"


def _impact_style(value: float, *, invert: bool = False) -> tuple[str, str]:
    """Return (arrow, impact_class) for a metric delta.

    Arrow always reflects direction (up/down).
    Impact class reflects whether the change is good or bad.
    Default: decrease = success, increase = warning.
    Invert: increase = neutral (e.g. more replicas is expected).
    """
    if value == 0:
        return "\u2015", "impact-neutral"

    arrow = "\u25b2" if value > 0 else "\u25bc"

    if invert:
        impact = "impact-neutral" if value > 0 else "impact-warning"
    else:
        impact = "impact-success" if value < 0 else "impact-warning"

    return arrow, impact


# ---------------------------------------------------------------------------
# Impact filter modal
# ---------------------------------------------------------------------------


class _ImpactFiltersState(TypedDict):
    team_filter: set[str]
    chart_filter: set[str]


class _ImpactFiltersModal(ModalScreen[_ImpactFiltersState | None]):
    """Modal for filtering impact analysis by Team and Chart."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        teams: list[str],
        charts: list[str],
        selected_teams: set[str],
        selected_charts: set[str],
    ) -> None:
        super().__init__(classes="impact-filters-modal-screen selection-modal-screen")
        self._all_teams = sorted(set(teams))
        self._all_charts = sorted(set(charts))
        self._selected_teams = set(selected_teams) if selected_teams else set(self._all_teams)
        self._selected_charts = set(selected_charts) if selected_charts else set(self._all_charts)

    def compose(self) -> ComposeResult:
        with CustomContainer(
            classes="impact-filters-modal-shell selection-modal-shell"
        ):
            yield CustomStatic(
                "Impact Filters",
                classes="impact-filters-modal-title selection-modal-title",
                markup=False,
            )
            with CustomHorizontal(classes="impact-filters-modal-lists-row"):
                with CustomVertical(classes="impact-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Team",
                            id="impact-filters-modal-team-title",
                            classes="impact-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="impact-filters-modal-team-list",
                            classes="impact-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(classes="impact-filters-modal-list-actions"):
                        yield CustomButton(
                            "All",
                            id="impact-filters-modal-team-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="impact-filters-modal-team-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="impact-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Chart",
                            id="impact-filters-modal-chart-title",
                            classes="impact-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="impact-filters-modal-chart-list",
                            classes="impact-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(classes="impact-filters-modal-list-actions"):
                        yield CustomButton(
                            "All",
                            id="impact-filters-modal-chart-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="impact-filters-modal-chart-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
            with CustomHorizontal(classes="impact-filters-modal-actions selection-modal-actions"):
                yield CustomButton(
                    "Apply",
                    id="impact-filters-modal-apply",
                    compact=True,
                    variant="primary",
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Cancel",
                    id="impact-filters-modal-cancel",
                    compact=True,
                    classes="selection-modal-action-btn",
                )

    def on_mount(self) -> None:
        self._refresh_team_list()
        self._refresh_chart_list()
        self._sync_buttons()
        with contextlib.suppress(Exception):
            self.query_one("#impact-filters-modal-team-list", CustomSelectionList).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_selection_list_selected_changed(self, event: object) -> None:
        control = getattr(event, "control", None)
        control_id = str(getattr(control, "id", ""))
        selected = {str(v) for v in getattr(control, "selected", [])}
        if control_id == "impact-filters-modal-team-list-inner":
            self._selected_teams = selected
        elif control_id == "impact-filters-modal-chart-list-inner":
            self._selected_charts = selected
        self._sync_buttons()

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "impact-filters-modal-team-all":
            self._selected_teams = set(self._all_teams)
            self._refresh_team_list()
        elif bid == "impact-filters-modal-team-clear":
            self._selected_teams.clear()
            self._refresh_team_list()
        elif bid == "impact-filters-modal-chart-all":
            self._selected_charts = set(self._all_charts)
            self._refresh_chart_list()
        elif bid == "impact-filters-modal-chart-clear":
            self._selected_charts.clear()
            self._refresh_chart_list()
        elif bid == "impact-filters-modal-apply":
            self._apply()
            return
        elif bid == "impact-filters-modal-cancel":
            self.dismiss(None)
            return
        self._sync_buttons()

    def _refresh_team_list(self) -> None:
        with contextlib.suppress(Exception):
            sl = self.query_one("#impact-filters-modal-team-list", CustomSelectionList)
            if sl.selection_list is not None:
                sl.selection_list.clear_options()
                sl.selection_list.add_options(
                    [(t, t, t in self._selected_teams) for t in self._all_teams]
                )

    def _refresh_chart_list(self) -> None:
        with contextlib.suppress(Exception):
            sl = self.query_one("#impact-filters-modal-chart-list", CustomSelectionList)
            if sl.selection_list is not None:
                sl.selection_list.clear_options()
                sl.selection_list.add_options(
                    [(c, c, c in self._selected_charts) for c in self._all_charts]
                )

    def _sync_buttons(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one(
                "#impact-filters-modal-team-all", CustomButton
            ).disabled = len(self._selected_teams) >= len(self._all_teams)
        with contextlib.suppress(Exception):
            self.query_one(
                "#impact-filters-modal-team-clear", CustomButton
            ).disabled = len(self._selected_teams) == 0
        with contextlib.suppress(Exception):
            self.query_one(
                "#impact-filters-modal-chart-all", CustomButton
            ).disabled = len(self._selected_charts) >= len(self._all_charts)
        with contextlib.suppress(Exception):
            self.query_one(
                "#impact-filters-modal-chart-clear", CustomButton
            ).disabled = len(self._selected_charts) == 0

    def _apply(self) -> None:
        team_filter = (
            set() if self._selected_teams == set(self._all_teams) else set(self._selected_teams)
        )
        chart_filter = (
            set() if self._selected_charts == set(self._all_charts) else set(self._selected_charts)
        )
        self.dismiss(_ImpactFiltersState(team_filter=team_filter, chart_filter=chart_filter))


# ---------------------------------------------------------------------------
# Sub-widgets
# ---------------------------------------------------------------------------


class ImpactMetricCard(CustomVertical):
    """Styled metric card showing resource delta with direction indicator."""

    def __init__(self, title: str, *, id: str | None = None) -> None:
        super().__init__(id=id, classes="impact-metric-card")
        self._title = title

    def compose(self) -> ComposeResult:
        yield CustomStatic(self._title, classes="imc-title")
        yield CustomStatic("--", classes="imc-delta")
        yield CustomStatic("", classes="imc-pct")
        yield CustomStatic("", classes="imc-range")

    def set_loading(self, loading: bool) -> None:
        """Toggle loading placeholder state."""
        if loading:
            self.add_class("imc-loading")
            with contextlib.suppress(Exception):
                self.query_one(".imc-delta", CustomStatic).update("[dim]Loading...[/dim]")
            with contextlib.suppress(Exception):
                self.query_one(".imc-pct", CustomStatic).update("")
            with contextlib.suppress(Exception):
                self.query_one(".imc-range", CustomStatic).update("")
        else:
            self.remove_class("imc-loading")

    def set_data(
        self,
        *,
        delta: str,
        pct: str,
        range_text: str,
        arrow: str,
        impact: str,
    ) -> None:
        """Update card with metric data.

        Args:
            delta: Formatted delta string (e.g. "+63,393m").
            pct: Percentage string (e.g. "+58.9%").
            range_text: Before/after range (e.g. "107,539m -> 170,932m").
            arrow: Direction arrow character.
            impact: CSS class — "impact-success", "impact-warning", or "impact-neutral".
        """
        self.remove_class("imc-loading")
        for cls in ("impact-success", "impact-warning", "impact-neutral"):
            self.remove_class(cls)
        self.add_class(impact)

        with contextlib.suppress(Exception):
            self.query_one(".imc-delta", CustomStatic).update(f"{arrow} {delta}")
        with contextlib.suppress(Exception):
            self.query_one(".imc-pct", CustomStatic).update(pct)
        with contextlib.suppress(Exception):
            self.query_one(".imc-range", CustomStatic).update(range_text)


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------


class ResourceImpactView(CustomVertical):
    """Resource impact analysis view with savings banner, metric cards, and tables."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._result: ResourceImpactResult | None = None
        # Source data for recomputation
        self._source_charts: list[ChartInfo] = []
        self._source_violations: list[ViolationResult] = []
        self._optimizer_controller: Any | None = None
        # Filter state (empty set = all selected)
        self._team_filter: set[str] = set()
        self._chart_filter: set[str] = set()

    def compose(self) -> ComposeResult:
        # Metric cards — row of 5
        yield CustomHorizontal(
            ImpactMetricCard("CPU Requests", id="impact-kpi-cpu-req"),
            ImpactMetricCard("CPU Limits", id="impact-kpi-cpu-lim"),
            ImpactMetricCard("Memory Requests", id="impact-kpi-mem-req"),
            ImpactMetricCard("Memory Limits", id="impact-kpi-mem-lim"),
            ImpactMetricCard("Replicas", id="impact-kpi-replicas"),
            id="impact-kpi-row",
        )

        # Per-chart resource changes table
        yield CustomVertical(
            CustomStatic(
                "[bold]Per-Chart Resource Changes[/bold]",
                id="impact-chart-header",
                classes="impact-section-title",
            ),
            CustomContainer(
                CustomDataTable(
                    id="impact-chart-table",
                    zebra_stripes=True,
                ),
                CustomContainer(
                    CustomVertical(
                        CustomLoadingIndicator(id="impact-chart-loading-indicator"),
                        CustomStatic("Loading chart changes...", id="impact-chart-loading-message"),
                        id="impact-chart-loading-row",
                    ),
                    id="impact-chart-loading-overlay",
                ),
                id="impact-chart-table-container",
            ),
            CustomStatic(
                "[dim]No charts with resource changes detected.[/dim]",
                id="impact-chart-empty",
            ),
            id="impact-chart-section",
            classes="impact-section",
        )

    def on_mount(self) -> None:
        """Initialize table columns and show loading state."""
        self._setup_chart_table()
        self.set_loading(True)

    def set_loading(self, loading: bool, message: str | None = None) -> None:
        """Set loading state on all sub-widgets: KPI cards and table."""
        # KPI cards
        for card in self.query(ImpactMetricCard):
            with contextlib.suppress(Exception):
                card.set_loading(loading)
        # Table overlay
        self._set_table_loading(loading, message)

    def _set_table_loading(self, loading: bool, message: str | None = None) -> None:
        """Show or hide loading overlay on the chart table."""
        with contextlib.suppress(Exception):
            self.query_one("#impact-chart-loading-overlay", CustomContainer).display = loading
        if message:
            with contextlib.suppress(Exception):
                self.query_one("#impact-chart-loading-message", CustomStatic).update(message)

    def _setup_chart_table(self) -> None:
        with contextlib.suppress(Exception):
            table = self.query_one("#impact-chart-table", CustomDataTable)
            table.clear(columns=True)
            for label, width in IMPACT_CHART_TABLE_COLUMNS:
                table.add_column(label, width=width)

    def set_source_data(
        self,
        result: ResourceImpactResult,
        *,
        charts: list[ChartInfo],
        violations: list[ViolationResult],
        optimizer_controller: Any | None = None,
    ) -> None:
        """Store source data for recomputation and display initial result."""
        self._source_charts = charts
        self._source_violations = violations
        self._optimizer_controller = optimizer_controller
        self._team_filter = set()
        self._chart_filter = set()
        self.set_data(result)

    def set_data(self, result: ResourceImpactResult) -> None:
        """Update all sub-widgets with computed impact data."""
        self._result = result
        self.set_loading(False)
        self._update_metrics(result)
        self._update_chart_table(result)

    # ------------------------------------------------------------------
    # Filters (triggered externally via top bar)
    # ------------------------------------------------------------------

    def open_filters_modal(self) -> None:
        """Open the impact filters modal. Called from the top bar filter button."""
        teams = sorted({getattr(c, "team", "") for c in self._source_charts if getattr(c, "team", "")})
        charts = sorted({getattr(c, "name", "") for c in self._source_charts if getattr(c, "name", "")})
        self.app.push_screen(
            _ImpactFiltersModal(
                teams=teams,
                charts=charts,
                selected_teams=self._team_filter if self._team_filter else set(teams),
                selected_charts=self._chart_filter if self._chart_filter else set(charts),
            ),
            callback=self._on_filters_dismissed,
        )

    def _on_filters_dismissed(self, state: _ImpactFiltersState | None) -> None:
        if state is None:
            return
        self._team_filter = state["team_filter"]
        self._chart_filter = state["chart_filter"]
        self._recompute_filtered_impact()

    def _recompute_filtered_impact(self) -> None:
        with contextlib.suppress(Exception):
            from kubeagle.optimizer.resource_impact_calculator import (
                ResourceImpactCalculator,
            )

            # Filter charts
            filtered_charts = list(self._source_charts)
            if self._team_filter:
                filtered_charts = [
                    c for c in filtered_charts
                    if getattr(c, "team", "") in self._team_filter
                ]
            if self._chart_filter:
                filtered_charts = [
                    c for c in filtered_charts
                    if getattr(c, "name", "") in self._chart_filter
                ]

            # Filter violations to only those matching filtered chart names
            filtered_chart_names = {getattr(c, "name", "") for c in filtered_charts}
            filtered_violations = [
                v for v in self._source_violations
                if getattr(v, "chart_name", "") in filtered_chart_names
            ]

            calculator = ResourceImpactCalculator()
            optimizer_controller = self._optimizer_controller
            self.set_loading(True, "Recomputing impact...")

            def _do_compute() -> None:
                result = calculator.compute_impact(
                    filtered_charts,
                    filtered_violations,
                    optimizer_controller=optimizer_controller,
                )
                self.app.call_from_thread(self.set_data, result)

            self.run_worker(_do_compute, thread=True, name="impact-recompute", exclusive=True)

    # ------------------------------------------------------------------
    # Metric cards
    # ------------------------------------------------------------------

    def _update_metrics(self, result: ResourceImpactResult) -> None:
        """Update all metric cards with before/after deltas."""
        delta = result.delta
        before = result.before
        after = result.after

        # CPU Requests
        arrow, impact = _impact_style(delta.cpu_request_diff)
        self._set_metric(
            "impact-kpi-cpu-req",
            delta=_format_signed(delta.cpu_request_diff, _format_cpu),
            pct=_format_pct(delta.cpu_request_pct),
            range_text=(
                f"{_format_cpu(before.cpu_request_total)} \u2192 "
                f"{_format_cpu(after.cpu_request_total)}"
            ),
            arrow=arrow,
            impact=impact,
        )
        # CPU Limits
        arrow, impact = _impact_style(delta.cpu_limit_diff)
        self._set_metric(
            "impact-kpi-cpu-lim",
            delta=_format_signed(delta.cpu_limit_diff, _format_cpu),
            pct=_format_pct(delta.cpu_limit_pct),
            range_text=(
                f"{_format_cpu(before.cpu_limit_total)} \u2192 "
                f"{_format_cpu(after.cpu_limit_total)}"
            ),
            arrow=arrow,
            impact=impact,
        )
        # Memory Requests
        arrow, impact = _impact_style(delta.memory_request_diff)
        self._set_metric(
            "impact-kpi-mem-req",
            delta=_format_signed(delta.memory_request_diff, _format_memory),
            pct=_format_pct(delta.memory_request_pct),
            range_text=(
                f"{_format_memory(before.memory_request_total)} \u2192 "
                f"{_format_memory(after.memory_request_total)}"
            ),
            arrow=arrow,
            impact=impact,
        )
        # Memory Limits
        arrow, impact = _impact_style(delta.memory_limit_diff)
        self._set_metric(
            "impact-kpi-mem-lim",
            delta=_format_signed(delta.memory_limit_diff, _format_memory),
            pct=_format_pct(delta.memory_limit_pct),
            range_text=(
                f"{_format_memory(before.memory_limit_total)} \u2192 "
                f"{_format_memory(after.memory_limit_total)}"
            ),
            arrow=arrow,
            impact=impact,
        )
        # Replicas — invert: more replicas is not a warning
        arrow, impact = _impact_style(delta.replicas_diff, invert=True)
        rep_sign = "+" if delta.replicas_diff > 0 else ""
        self._set_metric(
            "impact-kpi-replicas",
            delta=f"{rep_sign}{delta.replicas_diff:,}",
            pct=_format_pct(delta.replicas_pct),
            range_text=(
                f"{before.total_replicas:,} \u2192 {after.total_replicas:,}"
            ),
            arrow=arrow,
            impact=impact,
        )

    def _set_metric(
        self,
        card_id: str,
        *,
        delta: str,
        pct: str,
        range_text: str,
        arrow: str,
        impact: str,
    ) -> None:
        """Update an ImpactMetricCard by widget ID."""
        with contextlib.suppress(Exception):
            card = self.query_one(f"#{card_id}", ImpactMetricCard)
            card.set_data(
                delta=delta,
                pct=pct,
                range_text=range_text,
                arrow=arrow,
                impact=impact,
            )

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------

    def _update_chart_table(self, result: ResourceImpactResult) -> None:
        with contextlib.suppress(Exception):
            table = self.query_one("#impact-chart-table", CustomDataTable)
            table.clear()

            before_map = {s.name: s for s in result.before_charts}
            after_map = {s.name: s for s in result.after_charts}

            has_changes = False
            for name, after in after_map.items():
                before = before_map.get(name)
                if before is None:
                    continue
                if (
                    before.cpu_request_per_replica == after.cpu_request_per_replica
                    and before.cpu_limit_per_replica == after.cpu_limit_per_replica
                    and before.memory_request_per_replica
                    == after.memory_request_per_replica
                    and before.memory_limit_per_replica
                    == after.memory_limit_per_replica
                    and before.replicas == after.replicas
                ):
                    continue

                has_changes = True
                table.add_row(
                    name,
                    after.team,
                    f"{_format_cpu(before.cpu_request_per_replica)} \u2192 {_format_cpu(after.cpu_request_per_replica)}",
                    f"{_format_cpu(before.cpu_limit_per_replica)} \u2192 {_format_cpu(after.cpu_limit_per_replica)}",
                    f"{_format_memory(before.memory_request_per_replica)} \u2192 {_format_memory(after.memory_request_per_replica)}",
                    f"{_format_memory(before.memory_limit_per_replica)} \u2192 {_format_memory(after.memory_limit_per_replica)}",
                    f"{before.replicas} \u2192 {after.replicas}",
                )

            # Toggle table vs empty state
            with contextlib.suppress(Exception):
                self.query_one(
                    "#impact-chart-table", CustomDataTable
                ).display = has_changes
            with contextlib.suppress(Exception):
                self.query_one(
                    "#impact-chart-empty", CustomStatic
                ).display = not has_changes
