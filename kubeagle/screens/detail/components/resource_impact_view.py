"""Resource impact analysis view — before/after optimization comparison.

Shows savings banner with Digits, metric cards grid, node estimation table,
and per-chart breakdown.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable

from textual.app import ComposeResult

from kubeagle.models.optimization.resource_impact import (
    ResourceImpactResult,
)
from kubeagle.screens.detail.config import (
    IMPACT_CHART_TABLE_COLUMNS,
    IMPACT_CLUSTER_NODE_TABLE_COLUMNS,
    IMPACT_NODE_TABLE_COLUMNS,
)
from kubeagle.widgets import (
    CustomDataTable,
    CustomDigits,
    CustomHorizontal,
    CustomStatic,
    CustomVertical,
)

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


def _format_cost(usd: float) -> str:
    """Format a USD cost value for display (absolute, no sign)."""
    if usd == 0:
        return "--"
    value = abs(usd)
    if value >= 1000:
        return f"${value:,.0f}"
    if value >= 10:
        return f"${value:.0f}"
    return f"${value:.2f}"


def _format_cost_delta(savings: float) -> str:
    """Format savings as cost change: +$X = cost increased, -$X = cost saved."""
    if savings == 0:
        return "--"
    # Negate: positive savings means cost went DOWN
    delta = -savings
    sign = "+" if delta > 0 else "-"
    value = abs(delta)
    if value >= 1000:
        return f"{sign}${value:,.0f}"
    if value >= 10:
        return f"{sign}${value:.0f}"
    return f"{sign}${value:.2f}"


def _format_spot_price(usd: float) -> str:
    """Format a per-hour spot price."""
    if usd == 0:
        return "--"
    return f"${usd:.3f}"


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
# Sub-widgets
# ---------------------------------------------------------------------------


class ImpactSavingsBanner(CustomHorizontal):
    """Prominent banner showing estimated monthly cost impact with Digits."""

    def compose(self) -> ComposeResult:
        yield CustomVertical(
            CustomStatic(
                "Estimated Monthly Spot Cost Impact",
                classes="isb-label",
            ),
            CustomStatic(
                "projected change based on optimization fixes",
                classes="isb-sublabel",
            ),
            classes="isb-text",
        )
        yield CustomDigits("--", align="right", id="impact-savings-digits")

    def set_data(self, savings: float) -> None:
        """Update banner. Positive savings = cost decrease (good)."""
        cost_delta = -savings
        for cls in ("banner-savings", "banner-increase", "banner-neutral"):
            self.remove_class(cls)

        if cost_delta == 0:
            text = "$0"
            self.add_class("banner-neutral")
        elif cost_delta > 0:
            text = f"+${abs(cost_delta):,.0f}"
            self.add_class("banner-increase")
        else:
            text = f"-${abs(cost_delta):,.0f}"
            self.add_class("banner-savings")

        with contextlib.suppress(Exception):
            digits = self.query_one("#impact-savings-digits", CustomDigits)
            if digits.is_mounted:
                digits.update_with_animation(text)
            else:
                digits.update(text)


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

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._result: ResourceImpactResult | None = None

    def compose(self) -> ComposeResult:
        # Savings banner with animated Digits
        yield ImpactSavingsBanner(id="impact-savings-banner")

        # Metric cards — 2 rows of 3
        yield CustomHorizontal(
            ImpactMetricCard("CPU Requests", id="impact-kpi-cpu-req"),
            ImpactMetricCard("CPU Limits", id="impact-kpi-cpu-lim"),
            ImpactMetricCard("Memory Requests", id="impact-kpi-mem-req"),
            id="impact-kpi-row-1",
        )
        yield CustomHorizontal(
            ImpactMetricCard("Memory Limits", id="impact-kpi-mem-lim"),
            ImpactMetricCard("Replicas", id="impact-kpi-replicas"),
            ImpactMetricCard("Spot Cost /mo", id="impact-kpi-spot-cost"),
            id="impact-kpi-row-2",
        )

        # Cluster node estimation section (real cluster data)
        yield CustomVertical(
            CustomStatic(
                "[bold]Cluster Node Estimation (Spot)[/bold]",
                id="impact-cluster-node-header",
                classes="impact-section-title",
            ),
            CustomDataTable(id="impact-cluster-node-table"),
            id="impact-cluster-node-section",
            classes="impact-section",
        )
        # Fallback instance type estimation section
        yield CustomVertical(
            CustomStatic(
                "[bold]Instance Type Estimation (Spot)[/bold]",
                id="impact-node-header",
                classes="impact-section-title",
            ),
            CustomDataTable(id="impact-node-table"),
            id="impact-node-section",
            classes="impact-section",
        )
        # Per-chart resource changes section
        yield CustomVertical(
            CustomStatic(
                "[bold]Per-Chart Resource Changes[/bold]",
                id="impact-chart-header",
                classes="impact-section-title",
            ),
            CustomDataTable(id="impact-chart-table"),
            CustomStatic(
                "[dim]No charts with resource changes detected.[/dim]",
                id="impact-chart-empty",
            ),
            id="impact-chart-section",
            classes="impact-section",
        )

    def on_mount(self) -> None:
        """Initialize table columns."""
        self._setup_cluster_node_table()
        self._setup_node_table()
        self._setup_chart_table()

    def _setup_cluster_node_table(self) -> None:
        with contextlib.suppress(Exception):
            table = self.query_one("#impact-cluster-node-table", CustomDataTable)
            table.clear(columns=True)
            for label, width in IMPACT_CLUSTER_NODE_TABLE_COLUMNS:
                table.add_column(label, width=width)

    def _setup_node_table(self) -> None:
        with contextlib.suppress(Exception):
            table = self.query_one("#impact-node-table", CustomDataTable)
            table.clear(columns=True)
            for label, width in IMPACT_NODE_TABLE_COLUMNS:
                table.add_column(label, width=width)

    def _setup_chart_table(self) -> None:
        with contextlib.suppress(Exception):
            table = self.query_one("#impact-chart-table", CustomDataTable)
            table.clear(columns=True)
            for label, width in IMPACT_CHART_TABLE_COLUMNS:
                table.add_column(label, width=width)

    def set_data(self, result: ResourceImpactResult) -> None:
        """Update all sub-widgets with computed impact data."""
        self._result = result
        self._update_banner(result)
        self._update_metrics(result)
        self._update_cluster_node_table(result)
        self._update_node_table(result)
        self._update_chart_table(result)

        # Show cluster node table when available, hide fallback; or vice versa
        has_cluster = bool(result.cluster_node_groups)
        with contextlib.suppress(Exception):
            self.query_one(
                "#impact-cluster-node-section", CustomVertical
            ).display = has_cluster
        with contextlib.suppress(Exception):
            self.query_one("#impact-node-section", CustomVertical).display = (
                not has_cluster
            )

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------

    def _update_banner(self, result: ResourceImpactResult) -> None:
        """Update the savings banner with total cost impact."""
        with contextlib.suppress(Exception):
            banner = self.query_one("#impact-savings-banner", ImpactSavingsBanner)
            banner.set_data(result.total_spot_savings_monthly)

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
        # Spot Cost /mo
        savings = result.total_spot_savings_monthly
        cost_delta = -savings
        cost_arrow = (
            "\u25b2" if cost_delta > 0 else "\u25bc" if cost_delta < 0 else "\u2015"
        )
        cost_impact = (
            "impact-success"
            if cost_delta < 0
            else "impact-warning"
            if cost_delta > 0
            else "impact-neutral"
        )
        self._set_metric(
            "impact-kpi-spot-cost",
            delta=_format_cost_delta(savings),
            pct="monthly",
            range_text="spot pricing estimate",
            arrow=cost_arrow,
            impact=cost_impact,
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

    def _update_cluster_node_table(self, result: ResourceImpactResult) -> None:
        """Update the cluster node estimation table with real cluster data."""
        with contextlib.suppress(Exception):
            table = self.query_one("#impact-cluster-node-table", CustomDataTable)
            table.clear()
            for group in result.cluster_node_groups:
                reduction_str = (
                    f"{group.reduction}"
                    if group.reduction <= 0
                    else f"-{group.reduction}"
                )
                pct_str = f"{group.reduction_pct:.1f}%"
                table.add_row(
                    group.instance_type,
                    str(group.node_count),
                    _format_cpu(group.cpu_allocatable_per_node),
                    _format_memory(group.memory_allocatable_per_node),
                    _format_spot_price(group.spot_price_usd),
                    str(group.nodes_needed_after),
                    reduction_str,
                    pct_str,
                    _format_cost(group.cost_current_monthly),
                    _format_cost(group.cost_after_monthly),
                    _format_cost_delta(group.cost_savings_monthly),
                )

    def _update_node_table(self, result: ResourceImpactResult) -> None:
        with contextlib.suppress(Exception):
            table = self.query_one("#impact-node-table", CustomDataTable)
            table.clear()
            for est in result.node_estimations:
                reduction_str = (
                    f"{est.reduction}" if est.reduction <= 0 else f"-{est.reduction}"
                )
                pct_str = f"{est.reduction_pct:.1f}%"
                table.add_row(
                    est.instance_type,
                    str(est.vcpus),
                    f"{est.memory_gib:.0f} GiB",
                    _format_spot_price(est.spot_price_usd),
                    str(est.nodes_before),
                    str(est.nodes_after),
                    reduction_str,
                    pct_str,
                    _format_cost(est.cost_before_monthly),
                    _format_cost(est.cost_after_monthly),
                    _format_cost_delta(est.cost_savings_monthly),
                )

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
