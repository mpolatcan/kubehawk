"""Charts Explorer screen - unified charts browser with tabbed view filters."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any, TypedDict, cast

from rich.markup import escape
from textual import on
from textual.app import ComposeResult
from textual.events import Resize
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import ContentSwitcher
from textual.worker import get_current_worker

from kubeagle.constants.screens.charts_explorer import (
    BUTTON_CLEAR,
    BUTTON_FILTER,
    BUTTON_MODE_CLUSTER,
    BUTTON_MODE_LOCAL,
    BUTTON_SEARCH,
    CHARTS_EXPLORER_TITLE,
    SEARCH_PLACEHOLDER,
)
from kubeagle.constants.timeouts import (
    CHART_ANALYSIS_TIMEOUT,
    CLUSTER_CHECK_TIMEOUT,
)
from kubeagle.keyboard import CHARTS_EXPLORER_SCREEN_BINDINGS
from kubeagle.models.analysis.violation import ViolationResult
from kubeagle.models.charts.chart_info import ChartInfo
from kubeagle.screens.base_screen import BaseScreen
from kubeagle.screens.charts_explorer.config import (
    EXPLORER_HEADER_TOOLTIPS,
    EXPLORER_TABLE_COLUMNS,
    SORT_OPTIONS,
    TAB_CHARTS,
    TAB_RECOMMENDATIONS,
    TAB_VIOLATIONS,
    VIEW_FILTER_BY_TAB_ID,
    VIEW_TAB_ID_BY_FILTER,
    VIEW_TAB_OPTIONS,
    SortBy,
    ViewFilter,
)
from kubeagle.screens.charts_explorer.presenter import (
    ChartsExplorerPresenter,
)
from kubeagle.screens.detail.components import (
    ViolationRefreshRequested,
    ViolationsView,
)
from kubeagle.screens.detail.config import (
    QOS_COLORS,
    RATIO_GOOD_MAX,
    RATIO_WARN_MAX,
)
from kubeagle.screens.detail.presenter import (
    OptimizerDataLoaded,
    OptimizerDataLoadFailed,
    build_helm_recommendations,
    get_cluster_recommendations,
)
from kubeagle.screens.mixins.main_navigation_tabs_mixin import (
    MAIN_NAV_TAB_CHARTS,
    MainNavigationTabsMixin,
)
from kubeagle.widgets import (
    CustomButton,
    CustomContainer,
    CustomDataTable,
    CustomFooter,
    CustomHeader,
    CustomHorizontal,
    CustomInput,
    CustomKPI,
    CustomLoadingIndicator,
    CustomMarkdownViewer as TextualMarkdownViewer,
    CustomProgressBar as ProgressBar,
    CustomSelect as Select,
    CustomSelectionList,
    CustomStatic,
    CustomTabs,
    CustomVertical,
)

logger = logging.getLogger(__name__)


class ChartsExplorerDataLoaded(Message):
    """Message: chart list loaded and ready for first render."""

    def __init__(
        self,
        charts: list[ChartInfo],
        active_charts: set[str] | None = None,
        mode_generation: int = 0,
    ) -> None:
        super().__init__()
        self.charts = charts
        self.active_charts = active_charts
        self.mode_generation = mode_generation


class ChartsExplorerPartialDataLoaded(Message):
    """Message: partial chart list loaded during progressive cluster analysis."""

    def __init__(
        self,
        charts: list[ChartInfo],
        completed: int,
        total: int,
        active_charts: set[str] | None = None,
        mode_generation: int = 0,
    ) -> None:
        super().__init__()
        self.charts = charts
        self.completed = completed
        self.total = total
        self.active_charts = active_charts
        self.mode_generation = mode_generation


class ChartsExplorerViolationsLoaded(Message):
    """Message: violation counts computed for loaded charts."""

    def __init__(self, violation_counts: dict[str, int]) -> None:
        super().__init__()
        self.violation_counts = violation_counts


class ChartsExplorerOptimizerPartialLoaded(Message):
    """Message: incremental optimizer violations during analysis."""

    def __init__(
        self,
        *,
        violations: list[ViolationResult],
        recommendations: list[dict[str, Any]] | None = None,
        completed_charts: int,
        total_charts: int,
        optimizer_generation: int,
    ) -> None:
        super().__init__()
        self.violations = violations
        self.recommendations = recommendations
        self.completed_charts = completed_charts
        self.total_charts = total_charts
        self.optimizer_generation = optimizer_generation


class ChartsExplorerDataLoadFailed(Message):
    """Message: chart loading failed."""

    def __init__(self, error: str, mode_generation: int = 0) -> None:
        super().__init__()
        self.error = error
        self.mode_generation = mode_generation


class _ChartsFilterState(TypedDict):
    team_filter_values: set[str]
    visible_column_names: set[str]
    qos_filter_values: set[str]
    values_file_type_filter_values: set[str]


class _ChartsFiltersModal(ModalScreen[_ChartsFilterState | None]):
    """Unified modal for storing charts selection-list filters."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    _DIALOG_MIN_WIDTH = 108
    _DIALOG_MAX_WIDTH = 148
    _DIALOG_MIN_HEIGHT = 28
    _DIALOG_MAX_HEIGHT = 42

    def __init__(
        self,
        *,
        team_options: tuple[tuple[str, str], ...],
        team_selected_values: set[str],
        column_options: tuple[tuple[str, str], ...],
        visible_column_names: set[str],
        locked_column_names: set[str] | None = None,
        qos_options: tuple[tuple[str, str], ...],
        qos_selected_values: set[str],
        values_file_type_options: tuple[tuple[str, str], ...],
        values_file_type_selected_values: set[str],
    ) -> None:
        super().__init__(classes="charts-filters-modal-screen selection-modal-screen")

        self._team_options = team_options
        self._team_values = {value for _, value in team_options}
        selected_team_values = {
            value for value in team_selected_values if value in self._team_values
        }
        self._team_selected_values = (
            selected_team_values if selected_team_values else set(self._team_values)
        )

        self._column_options = column_options
        self._column_values = {value for _, value in column_options}
        self._locked_column_values = {
            value for value in (locked_column_names or set())
            if value in self._column_values
        }
        selected_column_values = {
            value for value in visible_column_names if value in self._column_values
        }
        self._column_selected_values = (
            selected_column_values
            if selected_column_values
            else set(self._column_values)
        )
        self._column_selected_values.update(self._locked_column_values)

        self._qos_options = qos_options
        self._qos_values = {value for _, value in qos_options}
        selected_qos_values = {
            value for value in qos_selected_values if value in self._qos_values
        }
        self._qos_selected_values = (
            selected_qos_values if selected_qos_values else set(self._qos_values)
        )

        self._values_file_type_options = values_file_type_options
        self._values_file_type_values = {
            value for _, value in values_file_type_options
        }
        selected_values_file_type_values = {
            value
            for value in values_file_type_selected_values
            if value in self._values_file_type_values
        }
        self._values_file_type_selected_values = (
            selected_values_file_type_values
            if selected_values_file_type_values
            else set(self._values_file_type_values)
        )

    def compose(self) -> ComposeResult:
        with CustomContainer(
            classes="charts-filters-modal-shell selection-modal-shell"
        ):
            yield CustomStatic(
                "Charts Filters",
                classes="charts-filters-modal-title selection-modal-title",
                markup=False,
            )
            with CustomHorizontal(
                id="charts-filters-modal-lists-row",
                classes="charts-filters-modal-lists-row",
            ):
                with CustomVertical(classes="charts-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Teams",
                            id="charts-filters-modal-team-title",
                            classes="charts-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="charts-filters-modal-team-list",
                            classes="charts-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(
                        classes="charts-filters-modal-list-actions",
                    ):
                        yield CustomButton(
                            "All",
                            id="charts-filters-modal-team-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="charts-filters-modal-team-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="charts-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Columns",
                            id="charts-filters-modal-column-title",
                            classes="charts-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="charts-filters-modal-column-list",
                            classes="charts-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(
                        classes="charts-filters-modal-list-actions",
                    ):
                        yield CustomButton(
                            "All",
                            id="charts-filters-modal-column-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="charts-filters-modal-column-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="charts-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "QoS",
                            id="charts-filters-modal-qos-title",
                            classes="charts-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="charts-filters-modal-qos-list",
                            classes="charts-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(
                        classes="charts-filters-modal-list-actions",
                    ):
                        yield CustomButton(
                            "All",
                            id="charts-filters-modal-qos-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="charts-filters-modal-qos-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="charts-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Values File Type",
                            id="charts-filters-modal-values-file-type-title",
                            classes="charts-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="charts-filters-modal-values-file-type-list",
                            classes="charts-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(
                        classes="charts-filters-modal-list-actions",
                    ):
                        yield CustomButton(
                            "All",
                            id="charts-filters-modal-values-file-type-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="charts-filters-modal-values-file-type-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
            with CustomHorizontal(
                classes="charts-filters-modal-actions selection-modal-actions"
            ):
                yield CustomButton(
                    "Apply",
                    id="charts-filters-modal-apply",
                    compact=True,
                    variant="primary",
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Cancel",
                    id="charts-filters-modal-cancel",
                    compact=True,
                    classes="selection-modal-action-btn",
                )

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        self._refresh_team_selection_options()
        self._refresh_column_selection_options()
        self._refresh_qos_selection_options()
        self._refresh_values_file_type_selection_options()
        self._update_summary()
        self._sync_all_action_buttons()
        with contextlib.suppress(Exception):
            self.query_one("#charts-filters-modal-team-list", CustomSelectionList).focus()

    def on_resize(self, _: Resize) -> None:
        if hasattr(self, "_resize_timer") and self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer: Timer | None = self.set_timer(
            0.1, self._apply_dynamic_layout
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_selection_list_selected_changed(
        self,
        event: object,
    ) -> None:
        event_obj = cast(Any, event)
        control = getattr(event_obj, "control", None)
        control_id = str(getattr(control, "id", ""))
        selected_values = {str(value) for value in getattr(control, "selected", [])}
        if control_id == "charts-filters-modal-team-list-inner":
            self._team_selected_values = selected_values
            self._update_summary()
            self._sync_filter_action_buttons("team", self._team_selected_values, self._team_values)
            return
        if control_id == "charts-filters-modal-column-list-inner":
            self._column_selected_values = selected_values | self._locked_column_values
            self._update_summary()
            self._sync_filter_action_buttons("column", self._column_selected_values, self._column_values)
            return
        if control_id == "charts-filters-modal-qos-list-inner":
            self._qos_selected_values = selected_values
            self._update_summary()
            self._sync_filter_action_buttons("qos", self._qos_selected_values, self._qos_values)
            return
        if control_id == "charts-filters-modal-values-file-type-list-inner":
            self._values_file_type_selected_values = selected_values
            self._update_summary()
            self._sync_filter_action_buttons("values-file-type", self._values_file_type_selected_values, self._values_file_type_values)

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "charts-filters-modal-team-all":
            self._team_selected_values = set(self._team_values)
            self._refresh_team_selection_options()
            self._sync_filter_action_buttons("team", self._team_selected_values, self._team_values)
            return
        if button_id == "charts-filters-modal-team-clear":
            self._team_selected_values.clear()
            self._refresh_team_selection_options()
            self._sync_filter_action_buttons("team", self._team_selected_values, self._team_values)
            return
        if button_id == "charts-filters-modal-column-all":
            self._column_selected_values = set(self._column_values)
            self._refresh_column_selection_options()
            self._sync_filter_action_buttons("column", self._column_selected_values, self._column_values)
            return
        if button_id == "charts-filters-modal-column-clear":
            self._column_selected_values = set(self._locked_column_values)
            self._refresh_column_selection_options()
            self._sync_filter_action_buttons("column", self._column_selected_values, self._column_values)
            return
        if button_id == "charts-filters-modal-qos-all":
            self._qos_selected_values = set(self._qos_values)
            self._refresh_qos_selection_options()
            self._sync_filter_action_buttons("qos", self._qos_selected_values, self._qos_values)
            return
        if button_id == "charts-filters-modal-qos-clear":
            self._qos_selected_values.clear()
            self._refresh_qos_selection_options()
            self._sync_filter_action_buttons("qos", self._qos_selected_values, self._qos_values)
            return
        if button_id == "charts-filters-modal-values-file-type-all":
            self._values_file_type_selected_values = set(self._values_file_type_values)
            self._refresh_values_file_type_selection_options()
            self._sync_filter_action_buttons("values-file-type", self._values_file_type_selected_values, self._values_file_type_values)
            return
        if button_id == "charts-filters-modal-values-file-type-clear":
            self._values_file_type_selected_values.clear()
            self._refresh_values_file_type_selection_options()
            self._sync_filter_action_buttons("values-file-type", self._values_file_type_selected_values, self._values_file_type_values)
            return
        if button_id == "charts-filters-modal-apply":
            self._apply()
            return
        if button_id == "charts-filters-modal-cancel":
            self.dismiss(None)

    def _refresh_team_selection_options(self) -> None:
        self._refresh_selection_options(
            "charts-filters-modal-team-list",
            self._team_options,
            self._team_selected_values,
        )
        self._update_summary()

    def _refresh_column_selection_options(self) -> None:
        self._refresh_selection_options(
            "charts-filters-modal-column-list",
            self._column_options,
            self._column_selected_values,
        )
        self._update_summary()

    def _refresh_qos_selection_options(self) -> None:
        self._refresh_selection_options(
            "charts-filters-modal-qos-list",
            self._qos_options,
            self._qos_selected_values,
        )
        self._update_summary()

    def _refresh_values_file_type_selection_options(self) -> None:
        self._refresh_selection_options(
            "charts-filters-modal-values-file-type-list",
            self._values_file_type_options,
            self._values_file_type_selected_values,
        )
        self._update_summary()

    def _refresh_selection_options(
        self,
        list_id: str,
        options: tuple[tuple[str, str], ...],
        selected_values: set[str],
    ) -> None:
        with contextlib.suppress(Exception):
            selection_list = self.query_one(f"#{list_id}", CustomSelectionList)
            if selection_list.selection_list is not None:
                selection_list.selection_list.clear_options()
                selection_list.selection_list.add_options(
                    [
                        (label, value, value in selected_values)
                        for label, value in options
                    ]
                )

    def _sync_filter_action_buttons(
        self, slug: str, selected_values: set[str], all_values: set[str]
    ) -> None:
        selected_count = len(selected_values)
        total_count = len(all_values)
        with contextlib.suppress(Exception):
            self.query_one(
                f"#charts-filters-modal-{slug}-all", CustomButton
            ).disabled = total_count == 0 or selected_count >= total_count
        with contextlib.suppress(Exception):
            self.query_one(
                f"#charts-filters-modal-{slug}-clear", CustomButton
            ).disabled = selected_count == 0

    def _sync_all_action_buttons(self) -> None:
        self._sync_filter_action_buttons("team", self._team_selected_values, self._team_values)
        self._sync_filter_action_buttons("column", self._column_selected_values, self._column_values)
        self._sync_filter_action_buttons("qos", self._qos_selected_values, self._qos_values)
        self._sync_filter_action_buttons("values-file-type", self._values_file_type_selected_values, self._values_file_type_values)

    def _apply(self) -> None:
        self._column_selected_values.update(self._locked_column_values)
        if self._column_values and not self._column_selected_values:
            self.notify("Select at least one column", severity="warning")
            return

        selected_team_values = set(self._team_selected_values)
        if selected_team_values == self._team_values:
            selected_team_values = set()

        selected_qos_values = set(self._qos_selected_values)
        if selected_qos_values == self._qos_values:
            selected_qos_values = set()

        selected_values_file_type_values = set(self._values_file_type_selected_values)
        if selected_values_file_type_values == self._values_file_type_values:
            selected_values_file_type_values = set()

        state: _ChartsFilterState = {
            "team_filter_values": selected_team_values,
            "visible_column_names": set(self._column_selected_values),
            "qos_filter_values": selected_qos_values,
            "values_file_type_filter_values": selected_values_file_type_values,
        }
        self.dismiss(state)

    def _update_summary(self) -> None:
        self._update_list_titles(
            team_total=len(self._team_values),
            team_selected=len(self._team_selected_values),
            column_total=len(self._column_values),
            column_selected=len(self._column_selected_values),
            qos_total=len(self._qos_values),
            qos_selected=len(self._qos_selected_values),
            values_file_type_total=len(self._values_file_type_values),
            values_file_type_selected=len(self._values_file_type_selected_values),
        )

    def _update_list_titles(
        self,
        *,
        team_total: int,
        team_selected: int,
        column_total: int,
        column_selected: int,
        qos_total: int,
        qos_selected: int,
        values_file_type_total: int,
        values_file_type_selected: int,
    ) -> None:
        with contextlib.suppress(Exception):
            self.query_one(
                "#charts-filters-modal-team-title",
                CustomStatic,
            ).update(
                self._format_title_count(
                    label="Team",
                    total=team_total,
                    selected=team_selected,
                    all_label="Teams",
                )
            )
        with contextlib.suppress(Exception):
            self.query_one(
                "#charts-filters-modal-column-title",
                CustomStatic,
            ).update(
                self._format_title_count(
                    label="Columns",
                    total=column_total,
                    selected=column_selected,
                )
            )
        with contextlib.suppress(Exception):
            self.query_one(
                "#charts-filters-modal-qos-title",
                CustomStatic,
            ).update(
                self._format_title_count(
                    label="QoS",
                    total=qos_total,
                    selected=qos_selected,
                )
            )
        with contextlib.suppress(Exception):
            self.query_one(
                "#charts-filters-modal-values-file-type-title",
                CustomStatic,
            ).update(
                self._format_title_count(
                    label="Values File Type",
                    total=values_file_type_total,
                    selected=values_file_type_selected,
                )
            )

    @staticmethod
    def _format_title_count(
        *,
        label: str,
        total: int,
        selected: int,
        all_label: str | None = None,
    ) -> str:
        if total > 0 and selected == total:
            return f"{all_label or label} (All)"
        return f"{label} ({selected})"

    def _apply_dynamic_layout(self) -> None:
        available_width = max(
            48,
            getattr(self.app.size, "width", self._DIALOG_MIN_WIDTH + 8) - 4,
        )
        max_width = min(self._DIALOG_MAX_WIDTH, available_width)
        min_width = min(self._DIALOG_MIN_WIDTH, max_width)
        dialog_width = max(min_width, max_width)
        width_value = str(dialog_width)

        available_height = max(
            18,
            getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT) - 2,
        )
        max_height = min(self._DIALOG_MAX_HEIGHT, available_height)
        min_height = min(self._DIALOG_MIN_HEIGHT, max_height)
        dialog_height = max(min_height, max_height)
        height_value = str(dialog_height)

        with contextlib.suppress(Exception):
            shell = self.query_one(".charts-filters-modal-shell", CustomContainer)
            shell.styles.width = width_value
            shell.styles.min_width = width_value
            shell.styles.max_width = width_value
            shell.styles.height = height_value
            shell.styles.min_height = height_value
            shell.styles.max_height = height_value


class _ChartDetailsModal(ModalScreen[None]):
    """Modal that shows chart metadata and full values content side by side."""

    BINDINGS = [("escape", "cancel", "Close")]
    _DIALOG_MIN_WIDTH = 124
    _DIALOG_MAX_WIDTH = 196
    _DIALOG_MIN_HEIGHT = 28
    _DIALOG_MAX_HEIGHT = 50

    def __init__(
        self,
        *,
        chart: ChartInfo,
        values_markdown: str,
    ) -> None:
        super().__init__(classes="chart-details-modal-screen selection-modal-screen")
        self._chart = chart
        self._values_markdown = values_markdown

    @staticmethod
    def _format_resource(value: float, unit: str) -> str:
        if value <= 0:
            return "-"
        if value == int(value):
            return f"{int(value)}{unit}"
        return f"{value}{unit}"

    @staticmethod
    def _ratio_value(limit: float, request: float) -> float | None:
        if request <= 0:
            return None
        return limit / request

    @staticmethod
    def _status_markup(
        is_ok: bool,
        ok_text: str = "Configured",
        missing_text: str = "Missing",
    ) -> str:
        return (
            f"[#30d158]{ok_text}[/#30d158]"
            if is_ok
            else f"[bold #ff3b30]{missing_text}[/bold #ff3b30]"
        )

    @staticmethod
    def _ratio_markup(ratio: float | None) -> str:
        if ratio is None:
            return "[dim]N/A[/dim]"
        if ratio <= RATIO_GOOD_MAX:
            return f"[#30d158]{ratio:.1f}x[/#30d158]"
        if ratio <= RATIO_WARN_MAX:
            return f"[bold #ff9f0a]{ratio:.1f}x[/bold #ff9f0a]"
        return f"[bold #ff3b30]{ratio:.1f}x[/bold #ff3b30]"

    _format_memory = staticmethod(ChartsExplorerPresenter._format_memory)

    def compose(self) -> ComposeResult:
        chart = self._chart
        replicas = str(chart.replicas) if chart.replicas is not None else "Not set"
        if chart.replicas == 1:
            replicas_markup = "[bold #ff9f0a]1 (single)[/bold #ff9f0a]"
        elif chart.replicas is not None and chart.replicas > 1:
            replicas_markup = f"[#30d158]{replicas}[/#30d158]"
        else:
            replicas_markup = f"[bold #ff9f0a]{replicas}[/bold #ff9f0a]"

        priority = chart.priority_class if chart.priority_class else "Not set"
        qos = chart.qos_class.value if chart.qos_class else "Unknown"
        qos_color = QOS_COLORS.get(qos, "")
        qos_markup = (
            f"[{qos_color}]{escape(qos)}[/{qos_color}]"
            if qos_color
            else escape(qos)
        )
        chart_name_display = escape(chart.name)
        team_display = escape(chart.team) if chart.team else "Unknown"
        priority_display = escape(priority)
        values_file_type_display = escape(
            ChartsExplorerPresenter._classify_values_file_type(chart.values_file)
        )

        cpu_req = self._format_resource(chart.cpu_request, "m")
        cpu_lim = self._format_resource(chart.cpu_limit, "m")
        mem_req = self._format_memory(chart.memory_request)
        mem_lim = self._format_memory(chart.memory_limit)

        cpu_ratio_value = self._ratio_value(chart.cpu_limit, chart.cpu_request)
        cpu_ratio = self._ratio_markup(cpu_ratio_value)

        mem_ratio_value = self._ratio_value(chart.memory_limit, chart.memory_request)
        mem_ratio = self._ratio_markup(mem_ratio_value)

        pdb_enabled = (
            "[#30d158]Enabled[/#30d158]"
            if chart.pdb_enabled
            else "[bold #ff9f0a]Disabled[/bold #ff9f0a]"
        )
        pdb_template = (
            "[#30d158]Template[/#30d158]"
            if chart.pdb_enabled and chart.pdb_template_exists
            else (
                "[bold #ff9f0a]No template[/bold #ff9f0a]"
                if chart.pdb_enabled
                else "[dim]-[/dim]"
            )
        )
        pdb_min = (
                str(chart.pdb_min_available)
                if chart.pdb_enabled and chart.pdb_min_available is not None
                else (
                    "[bold #ff9f0a]Not set[/bold #ff9f0a]"
                    if chart.pdb_enabled
                    else "[dim]-[/dim]"
                )
            )
        pdb_max = (
                str(chart.pdb_max_unavailable)
                if chart.pdb_enabled and chart.pdb_max_unavailable is not None
                else (
                    "[bold #ff9f0a]Not set[/bold #ff9f0a]"
                    if chart.pdb_enabled
                    else "[dim]-[/dim]"
                )
            )

        with CustomContainer(classes="chart-details-modal-shell selection-modal-shell"):
            yield CustomStatic(
                "Chart Detail",
                classes="chart-details-modal-title selection-modal-title",
                markup=False,
            )
            with CustomHorizontal(
                id="chart-details-modal-panels",
                classes="chart-details-modal-panels",
            ):
                with (
                    CustomVertical(classes="chart-details-modal-panel"),
                    CustomVertical(
                        id="chart-details-modal-meta",
                        classes="chart-details-modal-meta-layout",
                    ),
                ):
                    yield CustomStatic(
                        "Metadata",
                        classes="chart-details-modal-panel-title selection-modal-list-title",
                        markup=False,
                    )
                    with CustomVertical(
                        id="chart-details-modal-meta-content",
                        classes="chart-details-modal-meta-content",
                    ):
                        with CustomVertical(
                            classes="chart-meta-section-card chart-meta-overview-card",
                        ):
                            yield CustomStatic("Overview", classes="chart-meta-section-title")
                            with CustomVertical(classes="chart-meta-overview-grid"):
                                with CustomHorizontal(classes="chart-meta-chip-row"):
                                    yield CustomStatic(
                                        f"[bold]Chart Name[/bold]\n{chart_name_display}",
                                        classes="chart-meta-chip",
                                    )
                                    yield CustomStatic(
                                        f"[bold]Owning Team[/bold]\n{team_display}",
                                        classes="chart-meta-chip",
                                    )
                                with CustomHorizontal(classes="chart-meta-chip-row"):
                                    yield CustomStatic(
                                        f"[bold]Quality of Service[/bold]\n{qos_markup}",
                                        classes="chart-meta-chip",
                                    )
                                    yield CustomStatic(
                                        f"[bold]Priority Class[/bold]\n{priority_display}",
                                        classes="chart-meta-chip",
                                    )
                                with CustomHorizontal(classes="chart-meta-chip-row"):
                                    yield CustomStatic(
                                        f"[bold]Replica Count[/bold]\n{replicas_markup}",
                                        classes="chart-meta-chip",
                                    )
                                    yield CustomStatic(
                                        f"[bold]Values File Type[/bold]\n{values_file_type_display}",
                                        classes="chart-meta-chip",
                                    )

                        with CustomVertical(classes="chart-meta-section-card"):
                            yield CustomStatic("Resources", classes="chart-meta-section-title")
                            with CustomHorizontal(classes="chart-meta-metric-row"):
                                yield CustomStatic(
                                    f"[bold]CPU Request[/bold]\n{cpu_req}",
                                    classes="chart-meta-metric-card",
                                )
                                yield CustomStatic(
                                    f"[bold]CPU Limit[/bold]\n{cpu_lim}",
                                    classes="chart-meta-metric-card",
                                )
                                yield CustomStatic(
                                    f"[bold]CPU Ratio (L/R)[/bold]\n{cpu_ratio}",
                                    classes="chart-meta-metric-card",
                                )
                            with CustomHorizontal(classes="chart-meta-metric-row"):
                                yield CustomStatic(
                                    f"[bold]Memory Request[/bold]\n{mem_req}",
                                    classes="chart-meta-metric-card",
                                )
                                yield CustomStatic(
                                    f"[bold]Memory Limit[/bold]\n{mem_lim}",
                                    classes="chart-meta-metric-card",
                                )
                                yield CustomStatic(
                                    f"[bold]Memory Ratio (L/R)[/bold]\n{mem_ratio}",
                                    classes="chart-meta-metric-card",
                                )

                        with CustomVertical(classes="chart-meta-section-card"):
                            yield CustomStatic(
                                "Health and Availability",
                                classes="chart-meta-section-title",
                            )
                            with CustomVertical(classes="chart-meta-status-grid"):
                                with CustomHorizontal(classes="chart-meta-status-row-grid"):
                                    yield CustomStatic(
                                        f"[bold]Liveness Probe[/bold]\n{self._status_markup(chart.has_liveness)}",
                                        classes="chart-meta-status-card",
                                    )
                                    yield CustomStatic(
                                        f"[bold]Readiness Probe[/bold]\n{self._status_markup(chart.has_readiness)}",
                                        classes="chart-meta-status-card",
                                    )
                                    yield CustomStatic(
                                        f"[bold]Startup Probe[/bold]\n{self._status_markup(chart.has_startup)}",
                                        classes="chart-meta-status-card",
                                    )
                                with CustomHorizontal(classes="chart-meta-status-row-grid"):
                                    yield CustomStatic(
                                        f"[bold]Pod Anti-Affinity[/bold]\n{self._status_markup(chart.has_anti_affinity, 'Enabled')}",
                                        classes="chart-meta-status-card",
                                    )
                                    yield CustomStatic(
                                        f"[bold]Topology Spread Constraints[/bold]\n{self._status_markup(chart.has_topology_spread, 'Enabled')}",
                                        classes="chart-meta-status-card",
                                    )
                                    yield CustomStatic(
                                        f"[bold]Pod Disruption Budget[/bold]\n{pdb_enabled}",
                                        classes="chart-meta-status-card",
                                    )
                                with CustomHorizontal(classes="chart-meta-status-row-grid"):
                                    yield CustomStatic(
                                        f"[bold]PDB Template[/bold]\n{pdb_template}",
                                        classes="chart-meta-status-card",
                                    )
                                    yield CustomStatic(
                                        f"[bold]PDB Min Available[/bold]\n{pdb_min}",
                                        classes="chart-meta-status-card",
                                    )
                                    yield CustomStatic(
                                        f"[bold]PDB Max Unavailable[/bold]\n{pdb_max}",
                                        classes="chart-meta-status-card",
                                    )
                with (
                    CustomVertical(classes="chart-details-modal-panel"),
                    CustomVertical(
                        id="chart-details-modal-values",
                        classes="chart-details-modal-values-layout",
                    ),
                ):
                    yield CustomStatic(
                        "Values File",
                        classes="chart-details-modal-panel-title selection-modal-list-title",
                        markup=False,
                    )
                    yield TextualMarkdownViewer(
                        self._values_markdown,
                        id="chart-details-modal-values-content",
                        show_table_of_contents=False,
                    )
            with CustomHorizontal(
                classes="chart-details-modal-actions"
            ):
                yield CustomButton(
                    "Close",
                    id="chart-details-modal-close",
                )

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        with contextlib.suppress(Exception):
            self.query_one("#chart-details-modal-close", CustomButton).focus()

    def on_resize(self, _: Resize) -> None:
        if hasattr(self, "_resize_timer") and self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer: Timer | None = self.set_timer(
            0.1, self._apply_dynamic_layout
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        if event.button.id == "chart-details-modal-close":
            self.dismiss(None)

    def _apply_dynamic_layout(self) -> None:
        available_width = max(
            88,
            getattr(self.app.size, "width", self._DIALOG_MIN_WIDTH + 8) - 4,
        )
        max_width = min(self._DIALOG_MAX_WIDTH, available_width)
        min_width = min(self._DIALOG_MIN_WIDTH, max_width)
        dialog_width = max(min_width, max_width)
        width_value = str(dialog_width)

        available_height = max(
            20,
            getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT) - 2,
        )
        max_height = min(self._DIALOG_MAX_HEIGHT, available_height)
        min_height = min(self._DIALOG_MIN_HEIGHT, max_height)
        dialog_height = max(min_height, max_height)
        height_value = str(dialog_height)

        with contextlib.suppress(Exception):
            shell = self.query_one(".chart-details-modal-shell", CustomContainer)
            shell.styles.width = width_value
            shell.styles.min_width = width_value
            shell.styles.max_width = width_value
            shell.styles.height = height_value
            shell.styles.min_height = height_value
            shell.styles.max_height = height_value


class ChartsExplorerScreen(MainNavigationTabsMixin, BaseScreen):
    """Unified charts browser with view tabs, sort controls, and team filters."""

    BINDINGS = CHARTS_EXPLORER_SCREEN_BINDINGS
    CSS_PATH = [
        "../../css/screens/charts_explorer.tcss",
        "../../css/screens/optimizer_screen.tcss",
    ]
    _ULTRA_MIN_WIDTH = 205
    _WIDE_MIN_WIDTH = 175
    _MEDIUM_MIN_WIDTH = 100
    _RESIZE_DEBOUNCE_SECONDS = 0.08
    _CLUSTER_PARTIAL_UPDATE_STEP = 5
    _CLUSTER_PARTIAL_UPDATE_MIN_INTERVAL_SECONDS = 0.35
    _OPTIMIZER_PARTIAL_UPDATE_STEP = 2
    _OPTIMIZER_PARTIAL_UPDATE_MIN_INTERVAL_SECONDS = 0.15
    _OPTIMIZER_PARTIAL_UI_MIN_INTERVAL_SECONDS = 0.40
    _NAMESPACE_COLUMN_NAME = "Namespace"
    _LOCKED_COLUMN_NAMES = frozenset({"Chart", "Team", "Values File Type"})
    _PROGRESS_TEXT_MAX_ULTRA = 96
    _PROGRESS_TEXT_MAX_WIDE = 80
    _PROGRESS_TEXT_MAX_MEDIUM = 64
    _PROGRESS_TEXT_MAX_NARROW = 48
    _PROGRESS_ANIMATION_INTERVAL_SECONDS = 0.10
    _PROGRESS_ANIMATION_STEP_RATIO = 0.25
    _TABLE_CHUNK_INSERT_THRESHOLD = 240
    _TABLE_CHUNK_INSERT_SIZE = 120
    _PARTIAL_TABLE_REPAINT_MIN_INTERVAL_SECONDS = 0.80
    _PARTIAL_TABLE_REPAINT_MIN_NEW_ROWS = 30
    _PARTIAL_TABLE_ALWAYS_REPAINT_MAX_ROWS = 120
    _PARTIAL_TABLE_REPAINT_PROGRESS_DIVISOR = 24
    _PARTIAL_CHARTS_REFRESH_DEBOUNCE_SECONDS = 0.30
    _LOAD_PROGRESS_RE = re.compile(r"\((\d+)/(\d+)\)")

    # Reactive state
    use_cluster_mode: bool = reactive(False)  # type: ignore[assignment]
    show_active_only: bool = reactive(False)  # type: ignore[assignment]
    current_view: ViewFilter = reactive(ViewFilter.ALL)  # type: ignore[assignment]
    current_sort: SortBy = reactive(SortBy.CHART)  # type: ignore[assignment]
    sort_desc: bool = reactive(False)  # type: ignore[assignment]
    current_team: str | None = reactive(None)  # type: ignore[assignment]

    def __init__(
        self,
        initial_view: ViewFilter | None = None,
        initial_sort: SortBy | None = None,
        initial_tab: str = TAB_CHARTS,
        team_filter: str | None = None,
        include_cluster: bool = True,
        testing: bool = False,
    ) -> None:
        super().__init__()
        self._initial_view = initial_view
        self._initial_sort = initial_sort
        self._initial_tab = initial_tab
        self._active_tab = initial_tab
        self._testing = testing
        self.charts: list[ChartInfo] = []
        self.filtered_charts: list[ChartInfo] = []
        self._presenter = ChartsExplorerPresenter()
        self._row_chart_map: dict[int, ChartInfo] = {}
        self._active_charts: set[str] | None = None
        self._team_filter_options: tuple[tuple[str, str], ...] = ()
        self._team_filter_values: set[str] = set()
        self._qos_filter_options: tuple[tuple[str, str], ...] = ()
        self._qos_filter_values: set[str] = set()
        self._values_file_type_filter_options: tuple[tuple[str, str], ...] = ()
        self._values_file_type_filter_values: set[str] = set()
        self._column_filter_options: tuple[tuple[str, str], ...] = tuple(
            (column_name, column_name) for column_name, _ in EXPLORER_TABLE_COLUMNS
        )
        self._visible_column_names: set[str] = {
            column_name for column_name, _ in EXPLORER_TABLE_COLUMNS
        }
        self._search_debounce_timer: Timer | None = None
        self._resize_debounce_timer: Timer | None = None
        self._loading = False
        self._pending_refresh = False
        self._pending_force_refresh = False
        self._pending_force_overlay = False
        self._load_force_refresh = False
        self._force_overlay_until_load_complete = False
        self._mode_generation = 0
        self._optimizer_generation = 0
        self._reload_on_resume = False
        self._reload_optimizer_on_resume = False
        self._reload_violation_counts_on_resume = False
        self._render_data_on_resume = False
        self._render_violations_on_resume = False
        self._render_optimizer_on_resume = False
        self._selected_chart: ChartInfo | None = None
        self._layout_mode: str | None = None
        self._optimizer_loading = False
        self._optimizer_loaded = False
        self._violation_counts_loading = False
        self._optimizer_team_filter = team_filter
        self._optimizer_include_cluster = include_cluster
        self._ignore_next_view_tab_id: str | None = None
        self._table_populate_sequence = 0
        self._last_table_columns_signature: tuple[int, ...] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._populate_on_tab_switch_pending = False
        self._populate_on_tab_switch_force = False
        self._partial_charts_refresh_scheduled = False
        self._partial_charts_refresh_timer: Timer | None = None
        self._last_filter_signature: tuple[Any, ...] | None = None
        self._table_content_signature: tuple[Any, ...] | None = None
        self._charts_controller: Any | None = None
        self._charts_controller_cache_key: tuple[str, str, str, str] | None = None
        self._violations_signature: str | None = None
        self._cached_violation_counts: dict[str, int] | None = None
        self._cached_violations: list[ViolationResult] | None = None
        self._cached_helm_recommendations: list[dict[str, Any]] | None = None
        self._cached_helm_recommendations_signature: str | None = None
        self._streaming_optimizer_violations: list[ViolationResult] = []
        self._streaming_optimizer_charts: list[ChartInfo] = []
        self._last_optimizer_partial_ui_update_monotonic: float = 0.0
        self._violations_view_initialized = False
        self._chart_search_index: dict[int, str] = {}
        self._chart_values_file_type_index: dict[int, str] = {}
        self._charts_load_progress = 0
        self._charts_progress_display = 0
        self._charts_progress_target = 0
        self._charts_progress_animation_timer: Timer | None = None
        self._charts_loading_message = "Idle"
        self._charts_progress_is_error = False
        self._cached_progress_bar: ProgressBar | None = None
        self._cached_loading_text: CustomStatic | None = None
        self._charts_load_generation = 0
        self._charts_payload_ready_for_optimizer = False
        self._violations_cache_generation = -1
        self._batch_updating = False
        self._cached_search_input: CustomInput | None = None
        self._last_partial_table_repaint_monotonic: float = 0.0
        self._last_partial_table_repaint_chart_count: int = 0

    @classmethod
    def _partial_update_step(cls, total: int) -> int:
        """Return partial-update step size with small-batch fast-path."""
        if total <= cls._CLUSTER_PARTIAL_UPDATE_STEP:
            return 1
        return cls._CLUSTER_PARTIAL_UPDATE_STEP

    @classmethod
    def _optimizer_partial_update_step(cls, total: int) -> int:
        """Return partial-update step size for optimizer violations streaming."""
        if total <= cls._OPTIMIZER_PARTIAL_UPDATE_STEP:
            return 1
        return cls._OPTIMIZER_PARTIAL_UPDATE_STEP

    @classmethod
    def _table_chunk_size(cls, row_count: int) -> int:
        """Return table insertion chunk size for large payloads."""
        if row_count < cls._TABLE_CHUNK_INSERT_THRESHOLD:
            return row_count
        return cls._TABLE_CHUNK_INSERT_SIZE

    def _mark_partial_table_repaint(self, chart_count: int) -> None:
        """Record most recent partial table repaint point."""
        self._last_partial_table_repaint_monotonic = time.monotonic()
        self._last_partial_table_repaint_chart_count = chart_count

    def _should_schedule_partial_table_repaint(
        self,
        *,
        chart_count: int,
        completed: int,
        total: int,
    ) -> bool:
        """Throttle partial table repaints to keep table interactions responsive."""
        if chart_count <= 0:
            return False
        if chart_count <= self._PARTIAL_TABLE_ALWAYS_REPAINT_MAX_ROWS:
            self._mark_partial_table_repaint(chart_count)
            return True
        if self._last_partial_table_repaint_chart_count <= 0:
            self._mark_partial_table_repaint(chart_count)
            return True

        min_new_rows = self._PARTIAL_TABLE_REPAINT_MIN_NEW_ROWS
        if total > 0:
            min_new_rows = max(
                min_new_rows,
                total // self._PARTIAL_TABLE_REPAINT_PROGRESS_DIVISOR,
            )
        has_growth = (
            chart_count - self._last_partial_table_repaint_chart_count
        ) >= min_new_rows
        elapsed = time.monotonic() - self._last_partial_table_repaint_monotonic
        is_interval_due = elapsed >= self._PARTIAL_TABLE_REPAINT_MIN_INTERVAL_SECONDS
        is_near_completion = total > 0 and completed >= (total - max(2, min_new_rows // 2))

        should_repaint = has_growth or is_interval_due or is_near_completion
        if should_repaint:
            self._mark_partial_table_repaint(chart_count)
        return should_repaint

    def _cancel_workers_by_name(self, *worker_names: str) -> None:
        """Cancel only selected named workers without interrupting unrelated work."""
        if not worker_names:
            return
        target_names = set(worker_names)
        with contextlib.suppress(Exception):
            for worker in tuple(self.workers):
                if getattr(worker, "name", "") in target_names:
                    worker.cancel()

    def _get_or_create_charts_controller(
        self,
        charts_path: Path,
        *,
        context: str | None,
        codeowners_path: Path | None,
        active_charts_path: Path | None,
    ) -> Any:
        """Reuse ChartsController across refreshes when inputs stay the same."""
        cache_key = (
            str(charts_path.resolve()),
            context or "",
            str(codeowners_path.resolve()) if codeowners_path is not None else "",
            str(active_charts_path.resolve()) if active_charts_path is not None else "",
        )
        if self._charts_controller is not None and cache_key == self._charts_controller_cache_key:
            return self._charts_controller

        from kubeagle.controllers import ChartsController

        self._charts_controller = ChartsController(
            charts_path,
            context=context,
            codeowners_path=codeowners_path,
            active_charts_path=active_charts_path,
        )
        self._charts_controller_cache_key = cache_key
        return self._charts_controller

    def _resolve_charts_path(self) -> tuple[Path | None, str]:
        """Resolve charts repository path from settings/CLI/state with fallbacks."""
        app = self.app
        candidate_values: list[str] = [
            str(getattr(app.settings, "charts_path", "") or "").strip()
        ]

        cli_charts_path = getattr(app, "charts_path", None)
        if cli_charts_path is not None:
            candidate_values.append(str(cli_charts_path).strip())

        app_state = getattr(app, "state", None)
        if app_state is not None:
            candidate_values.append(str(getattr(app_state, "charts_path", "") or "").strip())

        seen_raw: set[str] = set()
        invalid_candidates: list[Path] = []
        for raw_value in candidate_values:
            if not raw_value or raw_value in seen_raw:
                continue
            seen_raw.add(raw_value)
            candidate_path = Path(raw_value).expanduser().resolve()
            if candidate_path.is_dir():
                normalized = str(candidate_path)
                app.settings.charts_path = normalized
                if app_state is not None:
                    app_state.charts_path = normalized
                return candidate_path, ""
            invalid_candidates.append(candidate_path)

        if invalid_candidates:
            return None, f"Charts path is invalid: {invalid_candidates[0]}"
        return None, "No charts path configured."

    @staticmethod
    def _charts_payload_signature(charts: list[ChartInfo]) -> str:
        """Build stable digest for charts payload to reuse expensive analysis.

        Uses a sort-key tuple per chart fed directly into the hasher to avoid
        creating large intermediate f-strings.  The sort itself uses a
        lightweight key to produce a deterministic order.
        """
        hasher = hashlib.sha1(usedforsecurity=False)
        values_mtime_cache: dict[str, int] = {}

        # Build per-chart keys and sort — use a minimal sort key to avoid
        # repeated getattr/str calls during sort comparisons.
        def _sort_key(c: ChartInfo) -> tuple[str, str, str]:
            return (c.name, c.values_file, c.namespace or "")

        for chart in sorted(charts, key=_sort_key):
            values_file = chart.values_file or ""
            values_mtime = values_mtime_cache.get(values_file)
            if values_mtime is None:
                values_mtime = -1
                if values_file and not values_file.startswith("cluster:"):
                    with contextlib.suppress(OSError):
                        values_mtime = (
                            Path(values_file).expanduser().resolve().stat().st_mtime_ns
                        )
                values_mtime_cache[values_file] = values_mtime

            qos_value = getattr(chart.qos_class, "value", "")
            # Feed a single encoded line per chart into the incremental hasher
            hasher.update(
                f"{chart.name}|{chart.namespace or ''}|{chart.team}|{values_file}|"
                f"{chart.replicas}|{chart.pdb_enabled}|"
                f"{chart.pdb_min_available}|{chart.pdb_max_unavailable}|"
                f"{chart.has_liveness}|{chart.has_readiness}|{chart.has_startup}|"
                f"{chart.has_anti_affinity}|{chart.has_topology_spread}|"
                f"{chart.cpu_request:.6f}|{chart.cpu_limit:.6f}|"
                f"{chart.memory_request:.6f}|{chart.memory_limit:.6f}|"
                f"{qos_value}|{values_mtime}\n"
                .encode()
            )
        return hasher.hexdigest()

    def _optimizer_settings_signature(self) -> tuple[str, int]:
        """Return optimizer settings that affect violation analysis output."""
        app_settings = getattr(self.app, "settings", None)
        analysis_source = str(
            getattr(app_settings, "optimizer_analysis_source", "auto")
        ).strip() or "auto"
        render_timeout_seconds = max(
            1,
            int(getattr(app_settings, "helm_template_timeout_seconds", 30)),
        )
        return analysis_source, render_timeout_seconds

    async def _violations_payload_signature_async(self, charts: list[ChartInfo]) -> str:
        """Build violations signature without blocking the UI event loop."""
        analysis_source, render_timeout_seconds = self._optimizer_settings_signature()
        charts_signature = await asyncio.to_thread(self._charts_payload_signature, charts)
        return f"{charts_signature}|{analysis_source}|{render_timeout_seconds}"

    @staticmethod
    def _build_violation_counts(violations: list[ViolationResult]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for violation in violations:
            chart_name = violation.chart_name
            counts[chart_name] = counts.get(chart_name, 0) + 1
        return counts

    @staticmethod
    def _clone_violations_payload(
        violations: list[ViolationResult],
    ) -> list[ViolationResult]:
        # ViolationResult objects are never mutated after creation, so a
        # shallow list copy is sufficient and avoids the Pydantic deep-copy
        # overhead (model_copy(deep=True) is ~100x slower per object).
        return list(violations)

    def _cache_violations_payload(
        self,
        *,
        violations_signature: str,
        violations: list[ViolationResult],
    ) -> None:
        """Persist violations so charts/violations views can reuse one analysis pass."""
        self._violations_signature = violations_signature
        self._violations_cache_generation = self._charts_load_generation
        self._cached_violations = self._clone_violations_payload(violations)
        self._cached_violation_counts = self._build_violation_counts(violations)
        if self._cached_helm_recommendations_signature != violations_signature:
            self._cached_helm_recommendations = None
            self._cached_helm_recommendations_signature = None

    @property
    def screen_title(self) -> str:
        return CHARTS_EXPLORER_TITLE

    def compose(self) -> ComposeResult:
        yield CustomHeader()
        yield self.compose_main_navigation_tabs(active_tab_id=MAIN_NAV_TAB_CHARTS)
        # Inner tab content switcher + controls + main content
        yield CustomVertical(
            CustomHorizontal(
                CustomHorizontal(
                    CustomButton("", id="charts-mode-btn"),
                    CustomButton("Refresh", id="charts-refresh-btn"),
                    id="charts-top-controls-left",
                ),
                CustomHorizontal(
                    CustomStatic("", id="charts-loading-spacer", markup=False),
                    CustomHorizontal(
                        ProgressBar(
                            total=100,
                            show_percentage=False,
                            show_eta=False,
                            id="charts-progress-bar",
                        ),
                        CustomStatic("0% - Idle", id="charts-loading-text", markup=False),
                        id="charts-progress-container",
                    ),
                    id="charts-loading-bar",
                ),
                id="charts-top-controls-row",
            ),
            CustomHorizontal(
                CustomTabs(
                    id="charts-view-tabs",
                    tabs=[
                        {"id": tab_id, "label": label}
                        for label, _, tab_id in VIEW_TAB_OPTIONS
                    ],
                    active=VIEW_TAB_ID_BY_FILTER[ViewFilter.ALL],
                ),
                id="charts-view-tabs-row",
            ),
            ContentSwitcher(
                CustomVertical(
                    CustomVertical(
                        CustomHorizontal(
                            CustomContainer(
                                CustomStatic("Search", classes="optimizer-filter-group-title"),
                                CustomVertical(
                                    CustomHorizontal(
                                        CustomInput(
                                            placeholder=SEARCH_PLACEHOLDER,
                                            id="charts-search-input",
                                        ),
                                        CustomButton(BUTTON_SEARCH, id="charts-search-btn"),
                                        CustomButton(BUTTON_CLEAR, id="charts-clear-btn"),
                                        id="charts-search-row",
                                    ),
                                    classes="optimizer-filter-group-body",
                                ),
                                classes="optimizer-filter-group",
                            ),
                            CustomContainer(
                                CustomStatic("Filter", classes="optimizer-filter-group-title"),
                                CustomHorizontal(
                                    CustomVertical(
                                        CustomButton(
                                            BUTTON_FILTER,
                                            id="charts-filter-btn",
                                            classes="filter-picker-btn",
                                        ),
                                        classes="filter-control",
                                    ),
                                    id="charts-filter-selection-row",
                                    classes="optimizer-filter-group-body",
                                ),
                                id="charts-filter-group",
                                classes="optimizer-filter-group",
                            ),
                            CustomContainer(
                                CustomStatic("Sort", classes="optimizer-filter-group-title"),
                                CustomVertical(
                                    CustomHorizontal(
                                        Select(
                                            [(label, val) for label, val in SORT_OPTIONS],
                                            value=SortBy.CHART,
                                            allow_blank=False,
                                            id="charts-sort-select",
                                            classes="filter-select",
                                        ),
                                        Select(
                                            (("Asc", "asc"), ("Desc", "desc")),
                                            value="asc",
                                            allow_blank=False,
                                            id="charts-sort-order-select",
                                            classes="filter-select",
                                        ),
                                        id="charts-sort-control-row",
                                    ),
                                    classes="optimizer-filter-group-body",
                                ),
                                classes="optimizer-filter-group",
                            ),
                            id="charts-filter-row",
                        ),
                        id="charts-filter-bar",
                    ),
                    CustomHorizontal(
                        CustomVertical(
                            CustomStatic("Charts Table (0)", id="explorer-table-title"),
                            CustomContainer(
                                CustomDataTable(id="explorer-table"),
                                CustomVertical(
                                    CustomLoadingIndicator(id="loading-indicator"),
                                    CustomStatic("Loading charts...", id="loading-message"),
                                    CustomButton("Retry", id="charts-retry-btn"),
                                    id="loading-overlay",
                                ),
                                id="explorer-table-container",
                            ),
                            CustomHorizontal(
                                CustomKPI("Charts", "0/0", id="kpi-total", classes="kpi-inline"),
                                CustomKPI(
                                    "Extreme Ratios",
                                    "0",
                                    status="warning",
                                    id="kpi-extreme",
                                    classes="kpi-inline",
                                ),
                                CustomKPI(
                                    "Single Replica",
                                    "0",
                                    id="kpi-single",
                                    classes="kpi-inline",
                                ),
                                CustomKPI(
                                    "Missing PDB",
                                    "0",
                                    id="kpi-no-pdb",
                                    classes="kpi-inline",
                                ),
                                id="charts-summary-bar",
                            ),
                            id="explorer-table-panel",
                        ),
                        id="charts-main-content",
                    ),
                    id=TAB_CHARTS,
                ),
                CustomVertical(
                    ViolationsView(
                        team_filter=self._optimizer_team_filter,
                        id="violations-view",
                    ),
                    id=TAB_VIOLATIONS,
                ),
                id="charts-inner-switcher",
                initial=TAB_CHARTS,
            ),
            id="charts-main-shell",
        )

        yield CustomFooter()

    def on_mount(self) -> None:
        """Called when screen is mounted."""
        super().on_mount()
        self.app.title = "KubEagle - Charts Explorer"
        self._set_primary_navigation_tab(MAIN_NAV_TAB_CHARTS)
        self._enable_primary_navigation_tabs()
        self._set_charts_progress(0, "Idle")

        # Sync with settings
        app = self.app
        self.use_cluster_mode = app.settings.use_cluster_mode
        self._sync_mode_column_state()

        # Pre-populate table columns for structured loading state
        try:
            table = self.query_one("#explorer-table", CustomDataTable)
            table.clear(columns=True)
            for col_name in self._iter_visible_column_names():
                table.add_column(col_name)
            self._configure_explorer_table_header_tooltips(table)
        except Exception:
            pass

        # Hide retry button and loading overlay initially
        with contextlib.suppress(Exception):
            self.query_one("#charts-retry-btn", CustomButton).display = False
        self.hide_loading_overlay()
        if self._optimizer_team_filter:
            self._team_filter_values = {self._optimizer_team_filter}
            self.current_team = self._optimizer_team_filter

        # Apply initial view if provided (e.g. from V/N global shortcuts)
        if self._initial_view is not None:
            self.current_view = self._initial_view
        self._sync_view_tabs()

        # Apply initial sort if provided
        if self._initial_sort is not None:
            self.current_sort = self._initial_sort
            with contextlib.suppress(Exception):
                self.query_one("#charts-sort-select", Select).value = self._initial_sort

        self._update_sort_direction_button()
        self._update_mode_button()

        self._set_active_tab(self._initial_tab)

        # Focus visible controls
        self._update_responsive_layout()
        if self._active_tab == TAB_CHARTS:
            self._focus_table()

    def on_resize(self, _: Resize) -> None:
        """Apply responsive class switches whenever terminal size changes."""
        self._schedule_resize_update()

    def on_unmount(self) -> None:
        """Cancel all workers and timers when screen is removed from DOM."""
        self._release_background_work_for_navigation()
        with contextlib.suppress(Exception):
            self.workers.cancel_all()

    def on_screen_suspend(self) -> None:
        """Pause timers and defer in-flight loading when this screen is hidden."""
        self._release_background_work_for_navigation()

    def prepare_for_screen_switch(self) -> None:
        """Release background work before another screen becomes active."""
        self._release_background_work_for_navigation()

    def _release_background_work_for_navigation(self) -> None:
        """Stop hidden-screen timers/workers to keep navigation responsive."""
        if self._resize_debounce_timer is not None:
            self._resize_debounce_timer.stop()
            self._resize_debounce_timer = None
        if self._search_debounce_timer is not None:
            self._search_debounce_timer.stop()
            self._search_debounce_timer = None
        if self._charts_progress_animation_timer is not None:
            self._charts_progress_animation_timer.stop()
            self._charts_progress_animation_timer = None
        self._partial_charts_refresh_scheduled = False
        self._stop_partial_charts_refresh_timer()
        if self._loading:
            # Keep primary charts load alive to avoid expensive restart thrash.
            self._reload_on_resume = False
            self._render_data_on_resume = True
        if self._optimizer_loading:
            # Keep optimizer worker alive in background.
            # On resume, if it finished, just render cached results.
            self._render_optimizer_on_resume = True
        if self._violation_counts_loading:
            # Keep violation-count analysis running in background and re-render
            # once this screen becomes active again.
            self._reload_violation_counts_on_resume = False
            self._render_violations_on_resume = True

    def on_screen_resume(self) -> None:
        """Resume deferred data loading after returning to this screen."""
        self.app.title = "KubEagle - Charts Explorer"
        self._set_primary_navigation_tab(MAIN_NAV_TAB_CHARTS)
        if (
            self._reload_on_resume
            and not self._testing
            and not self._loading
        ):
            self._reload_on_resume = False
            self._start_load_worker()
        if self._render_optimizer_on_resume:
            self._render_optimizer_on_resume = False
            if self._optimizer_loaded:
                # Finished while away — deliver cached data to ViolationsView
                self._deliver_cached_optimizer_data()
            elif not self._optimizer_loading:
                # Failed while away — restart
                self._ensure_optimizer_data_loaded()
            # else: still loading, message handler will deliver when done
        if (
            self._reload_optimizer_on_resume
            and not self._optimizer_loading
            and not self._optimizer_loaded
            and not self._loading
            and bool(self.charts)
            and self._active_tab == TAB_VIOLATIONS
        ):
            self._reload_optimizer_on_resume = False
            self._start_optimizer_worker()
        if (
            self._reload_violation_counts_on_resume
            and not self._violation_counts_loading
            and bool(self.charts)
        ):
            self._reload_violation_counts_on_resume = False
            if (
                self._cached_violation_counts is None
                or self._violations_cache_generation != self._charts_load_generation
            ):
                self._start_violation_counts_worker(list(self.charts))
        if self._render_data_on_resume:
            self._render_data_on_resume = False
            self.hide_loading_overlay()
            if not self.charts:
                self._show_empty_table("No charts found in the configured path")
            else:
                if self._active_tab == TAB_CHARTS:
                    self._schedule_charts_tab_repopulate(force=False)
                    self._ensure_violation_counts_available()
                if self._active_tab == TAB_VIOLATIONS:
                    self._reload_optimizer_on_resume = False
                    self._ensure_optimizer_data_loaded()
        if self._render_violations_on_resume:
            self._render_violations_on_resume = False
            if self._active_tab == TAB_CHARTS:
                self._schedule_charts_tab_repopulate(force=False)
                self._ensure_violation_counts_available()

    def _schedule_resize_update(self) -> None:
        """Debounce responsive relayout work during rapid terminal resizing."""
        if self._resize_debounce_timer is not None:
            self._resize_debounce_timer.stop()
            self._resize_debounce_timer = None
        self._resize_debounce_timer = self.set_timer(
            self._RESIZE_DEBOUNCE_SECONDS,
            self._run_debounced_resize_update,
        )

    def _run_debounced_resize_update(self) -> None:
        self._resize_debounce_timer = None
        self._update_responsive_layout()

    def _get_layout_mode(self) -> str:
        """Return current responsive layout mode based on terminal width."""
        width = self.size.width
        if width >= self._ULTRA_MIN_WIDTH:
            return "ultra"
        if width >= self._WIDE_MIN_WIDTH:
            return "wide"
        if width >= self._MEDIUM_MIN_WIDTH:
            return "medium"
        return "narrow"

    _RESPONSIVE_CONTAINER_IDS = (
        "#charts-filter-bar",
        "#charts-top-controls-row",
        "#charts-loading-bar",
        "#charts-main-content",
    )

    def _update_responsive_layout(self) -> None:
        """Apply breakpoint classes to key containers for responsive CSS rules.

        Uses set_classes to swap the mode class in a single DOM mutation per
        widget instead of N remove_class + 1 add_class calls.
        """
        mode = self._get_layout_mode()
        if mode == self._layout_mode:
            return
        old_mode = self._layout_mode
        self._layout_mode = mode

        # Swap class on screen itself
        if old_mode:
            self.remove_class(old_mode)
        self.add_class(mode)

        # Swap class on each responsive container in a single pass
        for selector in self._RESPONSIVE_CONTAINER_IDS:
            with contextlib.suppress(Exception):
                widget = self.query_one(selector)
                if old_mode:
                    widget.remove_class(old_mode)
                widget.add_class(mode)

    # =========================================================================
    # Tabs + Optimizer Views
    # =========================================================================

    def _activate_view_tab(self, tab_id: str) -> None:
        """Set top view-tabs active id while suppressing synthetic tab events."""
        with contextlib.suppress(Exception):
            view_tabs = self.query_one("#charts-view-tabs", CustomTabs)
            if view_tabs.active != tab_id:
                self._ignore_next_view_tab_id = tab_id
                view_tabs.active = tab_id

    def _set_active_tab(self, tab_id: str) -> None:
        if tab_id == TAB_RECOMMENDATIONS:
            tab_id = TAB_VIOLATIONS
        valid_tabs = {TAB_CHARTS, TAB_VIOLATIONS}
        target_tab = tab_id if tab_id in valid_tabs else TAB_CHARTS
        self._active_tab = target_tab
        with contextlib.suppress(Exception):
            self.query_one("#charts-inner-switcher", ContentSwitcher).current = target_tab

        if target_tab == TAB_VIOLATIONS:
            violations_tab_id = VIEW_TAB_ID_BY_FILTER.get(ViewFilter.WITH_VIOLATIONS)
            if violations_tab_id:
                self._activate_view_tab(violations_tab_id)

        if target_tab == TAB_CHARTS:
            # Suppress reactive watchers during tab switch to avoid redundant
            # _apply_filters_and_populate() calls from watch_current_view etc.
            self._batch_updating = True
            try:
                if self.current_view == ViewFilter.WITH_VIOLATIONS:
                    self.current_view = ViewFilter.ALL
                else:
                    self._sync_view_tabs()
            finally:
                self._batch_updating = False
            if self.charts:
                self._schedule_charts_tab_repopulate(force=False)
                self._ensure_violation_counts_available()
            self._focus_table()
            return

        self._ensure_violations_view_initialized()
        self._ensure_optimizer_data_loaded()

    def _schedule_charts_tab_repopulate(self, *, force: bool = False) -> None:
        """Defer charts-table repaint so tab switch renders immediately."""
        if force:
            self._populate_on_tab_switch_force = True
        if self._populate_on_tab_switch_pending:
            return
        self._populate_on_tab_switch_pending = True

        def _do_repopulate() -> None:
            force_repaint = self._populate_on_tab_switch_force
            self._populate_on_tab_switch_pending = False
            self._populate_on_tab_switch_force = False
            if self._active_tab != TAB_CHARTS or not self.charts or not self.is_current:
                if self.charts and self._active_tab == TAB_CHARTS and not self.is_current:
                    self._render_data_on_resume = True
                return
            self._apply_filters_and_populate(force=force_repaint)

        self.call_later(_do_repopulate)

    def _schedule_partial_charts_refresh(self) -> None:
        """Debounce heavy charts-table repaints while stream updates are active."""
        if self._partial_charts_refresh_scheduled:
            return
        self._partial_charts_refresh_scheduled = True
        self._stop_partial_charts_refresh_timer()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # Unit tests may call handlers outside an active Textual loop.
            self._partial_charts_refresh_timer = None
            self._run_partial_charts_refresh()
            return
        try:
            self._partial_charts_refresh_timer = self.set_timer(
                self._PARTIAL_CHARTS_REFRESH_DEBOUNCE_SECONDS,
                self._run_partial_charts_refresh,
            )
        except RuntimeError:
            self._partial_charts_refresh_timer = None
            self._run_partial_charts_refresh()

    def _run_partial_charts_refresh(self) -> None:
        self._partial_charts_refresh_scheduled = False
        self._partial_charts_refresh_timer = None
        if not self.is_current:
            self._render_data_on_resume = True
            return
        if self._active_tab != TAB_CHARTS:
            return
        self._schedule_charts_tab_repopulate(force=False)

    def _stop_partial_charts_refresh_timer(self) -> None:
        timer = self._partial_charts_refresh_timer
        self._partial_charts_refresh_timer = None
        if timer is None:
            return
        with contextlib.suppress(Exception):
            timer.stop()

    def _ensure_violations_view_initialized(self) -> None:
        """Initialize the violations view lazily on first use."""
        if self._violations_view_initialized:
            return
        with contextlib.suppress(Exception):
            self.query_one("#violations-view", ViolationsView).initialize()
            self._violations_view_initialized = True

    def _ensure_optimizer_data_loaded(self) -> None:
        self._apply_optimizer_team_filter()
        if self._loading or not self._charts_payload_ready_for_optimizer:
            self._reload_optimizer_on_resume = True
            return
        if self._testing or self._optimizer_loading or self._optimizer_loaded:
            return
        self._start_optimizer_worker()

    def _apply_optimizer_team_filter(self) -> None:
        with contextlib.suppress(Exception):
            vv = self.query_one("#violations-view", ViolationsView)
            target_team_filter = (
                {self._optimizer_team_filter}
                if self._optimizer_team_filter
                else set()
            )
            if vv.team_filter != target_team_filter:
                vv.team_filter = target_team_filter
                if self._optimizer_loaded and not vv._table_loading:
                    vv.populate_violations_table()

    def _deliver_cached_optimizer_data(self) -> None:
        """Push already-cached optimizer results into ViolationsView after resume."""
        violations = self._cached_violations or self._streaming_optimizer_violations
        charts = self._streaming_optimizer_charts or list(self.charts)
        if not violations:
            return
        try:
            vv = self.query_one("#violations-view", ViolationsView)
            vv.set_table_loading(False)
            vv.set_recommendations_loading(False)
            vv.update_data(violations, charts)
            if self._cached_helm_recommendations is not None:
                vv.update_recommendations_data(self._cached_helm_recommendations, charts)
        except Exception:
            pass
        self._apply_optimizer_team_filter()

    def _reset_optimizer_caches(self) -> None:
        """Clear cached optimizer payloads for a guaranteed full re-analysis."""
        self._optimizer_loaded = False
        self._violations_signature = None
        self._cached_violations = None
        self._cached_violation_counts = None
        self._cached_helm_recommendations = None
        self._cached_helm_recommendations_signature = None
        self._streaming_optimizer_violations = []
        self._streaming_optimizer_charts = []
        self._last_optimizer_partial_ui_update_monotonic = 0.0

    def _start_optimizer_worker(self, *, force_refresh: bool = False) -> None:
        if self._optimizer_loading:
            if not force_refresh:
                return
            self._optimizer_generation += 1
            self._cancel_workers_by_name("charts-explorer-optimizer")
            self._optimizer_loading = False
        if force_refresh:
            self._reset_optimizer_caches()
        self._optimizer_generation += 1
        optimizer_generation = self._optimizer_generation
        # Violations tab does a superset of the counts worker, so avoid duplicate scans.
        self._cancel_workers_by_name("charts-explorer-violations")
        self._violation_counts_loading = False
        self._streaming_optimizer_violations = []
        self._streaming_optimizer_charts = []
        self._last_optimizer_partial_ui_update_monotonic = 0.0
        self._ensure_violations_view_initialized()
        self._optimizer_loading = True
        self._optimizer_loaded = False
        try:
            vv = self.query_one("#violations-view", ViolationsView)
            vv._hide_error_banner()
            has_cached_violations = bool(
                self._cached_violations or self._streaming_optimizer_violations
            )
            has_cached_recommendations = bool(self._cached_helm_recommendations)
            vv.set_table_loading(not has_cached_violations)
            vv.set_recommendations_loading(
                not has_cached_recommendations,
                "Loading recommendations...",
            )
        except Exception:
            pass
        async def _worker() -> None:
            await self._load_optimizer_data_worker(optimizer_generation)

        self.run_worker(_worker, name="charts-explorer-optimizer", exclusive=True)

    def _finish_optimizer_worker_generation(self, optimizer_generation: int) -> None:
        """Only the active optimizer generation may clear loading state."""
        if optimizer_generation != self._optimizer_generation:
            return
        self._optimizer_loading = False

    async def _load_optimizer_data_worker(self, optimizer_generation: int) -> None:
        import time

        start = time.time()
        worker = get_current_worker()
        cluster_recs_task: asyncio.Task[list[dict[str, Any]]] | None = None

        try:
            app = self.app
            charts_path, charts_path_error = self._resolve_charts_path()
            if charts_path is None and charts_path_error.startswith("No charts path"):
                self.post_message(
                    OptimizerDataLoadFailed(
                        "No charts path configured.\n\n"
                        "To analyze violations:\n"
                        "  1. Go to Settings screen\n"
                        "  2. Configure the Charts Path setting\n"
                        "  3. Return here and press 'r' to refresh",
                        optimizer_generation=optimizer_generation,
                    )
                )
                return
            if charts_path is None:
                self.post_message(
                    OptimizerDataLoadFailed(
                        f"{charts_path_error}\n\n"
                        "Go to Settings and update Charts Path, then press 'r' to refresh.",
                        optimizer_generation=optimizer_generation,
                    )
                )
                return

            charts = list(self.charts)
            if not charts:
                if self._charts_payload_ready_for_optimizer:
                    if optimizer_generation != self._optimizer_generation:
                        return
                    self.post_message(
                        OptimizerDataLoaded(
                            violations=[],
                            recommendations=[],
                            charts=[],
                            total_charts=0,
                            duration_ms=0.0,
                            optimizer_generation=optimizer_generation,
                        )
                    )
                    return
                self.call_later(
                    self._update_optimizer_loading_message,
                    "Analyzing charts...",
                )
                from kubeagle.controllers import ChartsController

                codeowners_path: Path | None = None
                if app.settings.codeowners_path:
                    candidate = Path(app.settings.codeowners_path).expanduser().resolve()
                    if candidate.is_file():
                        codeowners_path = candidate
                elif (charts_path / "CODEOWNERS").exists():
                    codeowners_path = charts_path / "CODEOWNERS"
                charts_controller = ChartsController(
                    charts_path,
                    codeowners_path=codeowners_path,
                )

                try:
                    charts = await asyncio.wait_for(
                        charts_controller.analyze_all_charts_async(),
                        timeout=CHART_ANALYSIS_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    self.post_message(
                        OptimizerDataLoadFailed(
                            f"Chart analysis timed out after {int(CHART_ANALYSIS_TIMEOUT)}s",
                            optimizer_generation=optimizer_generation,
                        )
                    )
                    return

            if worker.is_cancelled or optimizer_generation != self._optimizer_generation:
                return

            if not charts:
                if optimizer_generation != self._optimizer_generation:
                    return
                self.post_message(
                    OptimizerDataLoaded(
                        violations=[],
                        recommendations=[],
                        charts=[],
                        total_charts=0,
                        duration_ms=0.0,
                        optimizer_generation=optimizer_generation,
                    )
                )
                return

            if self._optimizer_include_cluster:
                context = getattr(app, "context", None)
                cluster_recs_task = asyncio.create_task(
                    get_cluster_recommendations(context),
                )

            total = len(charts)
            violations_signature = await self._violations_payload_signature_async(charts)
            cached_violations = (
                self._clone_violations_payload(self._cached_violations)
                if (
                    self._cached_violations is not None
                    and violations_signature == self._violations_signature
                )
                else None
            )

            all_violations: list[ViolationResult]
            if cached_violations is not None:
                all_violations = cached_violations
                self.call_later(
                    self._update_optimizer_loading_message,
                    (
                        "Using cached violations "
                        f"({len(all_violations)} findings across {total} charts)..."
                    ),
                )
            else:
                self.call_later(
                    self._update_optimizer_loading_message,
                    f"Checking violations across {total} chart(s)...",
                )
                from kubeagle.models.optimization import (
                    UnifiedOptimizerController,
                )

                analysis_source, render_timeout_seconds = self._optimizer_settings_signature()
                optimizer = UnifiedOptimizerController(
                    analysis_source=analysis_source,
                    render_timeout_seconds=render_timeout_seconds,
                )
                self._streaming_optimizer_charts = list(charts)
                self._streaming_optimizer_violations = []
                progress_queue: asyncio.Queue[tuple[list[ViolationResult], int, int]] = (
                    asyncio.Queue()
                )
                event_loop = asyncio.get_running_loop()
                partial_step = self._optimizer_partial_update_step(total)
                last_partial_emit_monotonic = 0.0
                pending_partial_violations: list[ViolationResult] = []
                cumulative_partial_violations: list[ViolationResult] = []
                latest_completed = 0

                def _on_chart_done(
                    _chart: ChartInfo,
                    chart_violations: list[ViolationResult],
                    completed: int,
                    total_charts: int,
                ) -> None:
                    event_loop.call_soon_threadsafe(
                        progress_queue.put_nowait,
                        (list(chart_violations), completed, total_charts),
                    )

                analysis_task = asyncio.create_task(
                    asyncio.to_thread(
                        optimizer.check_all_charts_with_progress,
                        charts,
                        on_chart_done=_on_chart_done,
                    ),
                )
                while True:
                    if worker.is_cancelled or optimizer_generation != self._optimizer_generation:
                        analysis_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await analysis_task
                        return
                    if analysis_task.done() and progress_queue.empty():
                        break
                    try:
                        chunk, completed, total_charts = await asyncio.wait_for(
                            progress_queue.get(),
                            timeout=0.1,
                        )
                    except asyncio.TimeoutError:
                        continue

                    latest_completed = max(latest_completed, completed)
                    if chunk:
                        pending_partial_violations.extend(chunk)
                        cumulative_partial_violations.extend(chunk)

                    now_monotonic = time.monotonic()
                    should_emit_partial = (
                        completed >= total_charts
                        or completed % partial_step == 0
                        or (
                            now_monotonic - last_partial_emit_monotonic
                            >= self._OPTIMIZER_PARTIAL_UPDATE_MIN_INTERVAL_SECONDS
                        )
                    )
                    if not should_emit_partial:
                        continue

                    # Only rebuild recommendations at milestone points (every
                    # 25% of total or on final emit) to avoid the O(n) cost of
                    # build_helm_recommendations on every partial update.
                    is_milestone = (
                        completed >= total_charts
                        or (total_charts > 0 and completed % max(1, total_charts // 4) == 0)
                    )
                    partial_recommendations = (
                        build_helm_recommendations(
                            cumulative_partial_violations,
                            charts,
                        )
                        if is_milestone
                        else None
                    )
                    self.post_message(
                        ChartsExplorerOptimizerPartialLoaded(
                            violations=pending_partial_violations,
                            recommendations=partial_recommendations,
                            completed_charts=completed,
                            total_charts=total_charts,
                            optimizer_generation=optimizer_generation,
                        )
                    )
                    pending_partial_violations = []
                    last_partial_emit_monotonic = now_monotonic

                all_violations = await analysis_task
                if pending_partial_violations or latest_completed < total:
                    partial_recommendations = build_helm_recommendations(
                        cumulative_partial_violations,
                        charts,
                    )
                    self.post_message(
                        ChartsExplorerOptimizerPartialLoaded(
                            violations=pending_partial_violations,
                            recommendations=partial_recommendations,
                            completed_charts=total,
                            total_charts=total,
                            optimizer_generation=optimizer_generation,
                        )
                    )
                if worker.is_cancelled or optimizer_generation != self._optimizer_generation:
                    return
                self._cache_violations_payload(
                    violations_signature=violations_signature,
                    violations=all_violations,
                )

            cached_helm_recommendations = (
                list(self._cached_helm_recommendations)
                if (
                    self._cached_helm_recommendations is not None
                    and self._cached_helm_recommendations_signature
                    == violations_signature
                )
                else None
            )

            if cached_helm_recommendations is not None:
                helm_recs = cached_helm_recommendations
            else:
                self.call_later(
                    self._update_optimizer_loading_message,
                    "Building recommendations...",
                )
                helm_recs = await asyncio.to_thread(
                    build_helm_recommendations,
                    all_violations,
                    charts,
                )
                if worker.is_cancelled or optimizer_generation != self._optimizer_generation:
                    return
                self._cached_helm_recommendations = list(helm_recs)
                self._cached_helm_recommendations_signature = violations_signature
            duration_ms = (time.time() - start) * 1000
            if worker.is_cancelled or optimizer_generation != self._optimizer_generation:
                return
            self.post_message(
                OptimizerDataLoaded(
                    violations=all_violations,
                    recommendations=helm_recs,
                    charts=charts,
                    total_charts=total,
                    duration_ms=duration_ms,
                    optimizer_generation=optimizer_generation,
                )
            )

            cluster_recs: list[dict[str, Any]] = []
            if cluster_recs_task is not None:
                self.call_later(
                    self._update_optimizer_loading_message,
                    "Collecting cluster recommendations...",
                )
                try:
                    cluster_recs = await asyncio.wait_for(
                        cluster_recs_task,
                        timeout=CLUSTER_CHECK_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.debug(
                        "Cluster recommendations timed out after %.1fs",
                        CLUSTER_CHECK_TIMEOUT,
                    )
                    cluster_recs_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await cluster_recs_task
                except Exception:
                    logger.debug(
                        "Cluster recommendations failed, continuing without them",
                        exc_info=True,
                    )

            if cluster_recs:
                if worker.is_cancelled or optimizer_generation != self._optimizer_generation:
                    return
                self.post_message(
                    OptimizerDataLoaded(
                        violations=all_violations,
                        recommendations=cluster_recs + helm_recs,
                        charts=charts,
                        total_charts=total,
                        duration_ms=(time.time() - start) * 1000,
                        optimizer_generation=optimizer_generation,
                    )
                )

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.exception("Failed to load optimizer data")
            self.post_message(
                OptimizerDataLoadFailed(
                    str(e),
                    optimizer_generation=optimizer_generation,
                )
            )
        finally:
            self._finish_optimizer_worker_generation(optimizer_generation)
            if cluster_recs_task is not None and not cluster_recs_task.done():
                cluster_recs_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cluster_recs_task

    def _update_optimizer_loading_message(self, message: str) -> None:
        if not self.is_current:
            return
        with contextlib.suppress(Exception):
            self.query_one("#violations-view", ViolationsView).update_loading_message(
                message,
            )

    def on_charts_explorer_optimizer_partial_loaded(
        self,
        event: ChartsExplorerOptimizerPartialLoaded,
    ) -> None:
        """Stream partial violations while optimizer analysis is still running."""
        if event.optimizer_generation != self._optimizer_generation:
            return
        if self._optimizer_loaded:
            return

        previous_violation_count = len(self._streaming_optimizer_violations)
        if event.violations:
            self._streaming_optimizer_violations.extend(event.violations)
        progress_message = (
            "Checking violations... "
            f"({event.completed_charts}/{event.total_charts} charts, "
            f"{len(self._streaming_optimizer_violations)} findings)"
        )
        self._update_optimizer_loading_message(progress_message)
        if not self.is_current:
            return
        if self._active_tab != TAB_VIOLATIONS:
            return

        is_first_payload = (
            previous_violation_count == 0
            and len(self._streaming_optimizer_violations) > 0
        )
        is_final_payload = event.completed_charts >= event.total_charts
        now_monotonic = time.monotonic()
        should_update_ui = (
            is_first_payload
            or is_final_payload
            or (
                now_monotonic - self._last_optimizer_partial_ui_update_monotonic
                >= self._OPTIMIZER_PARTIAL_UI_MIN_INTERVAL_SECONDS
            )
        )
        if not should_update_ui:
            return
        self._last_optimizer_partial_ui_update_monotonic = now_monotonic

        with contextlib.suppress(Exception):
            vv = self.query_one("#violations-view", ViolationsView)
            # Streamed rows/recommendations should become visible immediately.
            vv.set_table_loading(False)
            if event.recommendations is not None:
                vv.set_recommendations_loading(False)
                vv.update_recommendations_data(
                    event.recommendations,
                    self._streaming_optimizer_charts or list(self.charts),
                    partial=True,
                )
            vv.update_partial_data(
                self._streaming_optimizer_violations,
                self._streaming_optimizer_charts or list(self.charts),
                progress_message=progress_message,
            )

    def on_optimizer_data_loaded(self, event: OptimizerDataLoaded) -> None:
        if (
            event.optimizer_generation is not None
            and event.optimizer_generation != self._optimizer_generation
        ):
            return
        self._optimizer_loaded = True
        self._streaming_optimizer_violations = list(event.violations)
        self._streaming_optimizer_charts = list(event.charts)
        try:
            vv = self.query_one("#violations-view", ViolationsView)
            vv.set_table_loading(False)
            vv.set_recommendations_loading(False)
            vv.update_data(
                event.violations,
                event.charts,
            )
            vv.update_recommendations_data(
                event.recommendations,
                event.charts,
            )
        except Exception:
            logger.debug("Failed to update optimizer views", exc_info=True)
        self._apply_optimizer_team_filter()

    def on_optimizer_data_load_failed(self, event: OptimizerDataLoadFailed) -> None:
        if (
            event.optimizer_generation is not None
            and event.optimizer_generation != self._optimizer_generation
        ):
            return
        self._optimizer_loaded = False
        self._streaming_optimizer_violations = []
        self._streaming_optimizer_charts = []
        with contextlib.suppress(Exception):
            vv = self.query_one("#violations-view", ViolationsView)
            vv.show_error(event.error)
            vv.show_recommendations_error(event.error)

    def on_violation_refresh_requested(self, _: ViolationRefreshRequested) -> None:
        self.show_loading_overlay("Refreshing...")
        self._start_load_worker(force_refresh=True, interrupt_if_loading=True)

    async def load_data(self) -> None:
        """Load charts data."""
        if self._testing:
            return

        self._start_load_worker(force_refresh=False)

    def _start_load_worker(
        self,
        *,
        force_refresh: bool = False,
        interrupt_if_loading: bool = False,
        force_overlay: bool = False,
    ) -> None:
        """Start charts loading worker with progressive updates."""
        if self._loading:
            self._pending_refresh = True
            if force_refresh:
                self._pending_force_refresh = True
            if force_overlay:
                self._pending_force_overlay = True
            if interrupt_if_loading:
                self._partial_charts_refresh_scheduled = False
                self._stop_partial_charts_refresh_timer()
                self._optimizer_generation += 1
                self._cancel_workers_by_name(
                    "charts-explorer-data",
                    "charts-explorer-optimizer",
                    "charts-explorer-violations",
                )
                self._optimizer_loading = False
                self._optimizer_loaded = False
                self._violation_counts_loading = False
                self._streaming_optimizer_violations = []
                self._streaming_optimizer_charts = []
                self._last_optimizer_partial_ui_update_monotonic = 0.0
            return
        self._optimizer_generation += 1
        self._cancel_workers_by_name("charts-explorer-optimizer", "charts-explorer-violations")
        self._optimizer_loading = False
        self._optimizer_loaded = False
        self._charts_payload_ready_for_optimizer = False
        self._streaming_optimizer_violations = []
        self._streaming_optimizer_charts = []
        self._last_optimizer_partial_ui_update_monotonic = 0.0
        self._load_force_refresh = force_refresh or self._pending_force_refresh
        self._pending_force_refresh = False
        self._force_overlay_until_load_complete = (
            force_overlay or self._pending_force_overlay
        )
        self._pending_force_overlay = False
        self._loading = True
        self._partial_charts_refresh_scheduled = False
        self._stop_partial_charts_refresh_timer()
        self._last_partial_table_repaint_monotonic = 0.0
        self._last_partial_table_repaint_chart_count = 0
        self._presenter.set_violations({})
        self._reload_violation_counts_on_resume = False
        self._violation_counts_loading = False
        self.show_loading_overlay(
            "Loading charts...",
            allow_cached_passthrough=not self._force_overlay_until_load_complete,
        )
        self._set_charts_progress(5, "Loading charts...")
        self.run_worker(
            self._load_charts_data_worker,
            name="charts-explorer-data",
            exclusive=True,
        )

    async def _load_charts_data_worker(self) -> None:
        """Load charts asynchronously and post partial/final data messages."""
        worker = get_current_worker()
        force_refresh = self._load_force_refresh
        mode_generation = self._mode_generation
        use_cluster_mode = self.use_cluster_mode
        try:
            app = self.app
            charts_path, charts_path_error = self._resolve_charts_path()
            if charts_path is None and charts_path_error.startswith("No charts path"):
                self.post_message(
                    ChartsExplorerDataLoadFailed(
                        "No charts path configured.\n\n"
                        "Go to Settings to configure, then press 'r' to refresh.",
                        mode_generation=mode_generation,
                    )
                )
                return
            if charts_path is None:
                self.post_message(
                    ChartsExplorerDataLoadFailed(
                        f"{escape(charts_path_error)}\n\n"
                        "Go to Settings to update Charts Path, then press 'r' to refresh.",
                        mode_generation=mode_generation,
                    )
                )
                return

            self.call_later(self._update_loading_message, "Initializing controller...")
            self.call_later(self._set_charts_progress, 12, "Initializing controller...")

            context = app.context if hasattr(app, "context") else None
            codeowners_path: Path | None = None
            if app.settings.codeowners_path:
                candidate = Path(app.settings.codeowners_path).expanduser().resolve()
                if candidate.is_file():
                    codeowners_path = candidate
            elif (charts_path / "CODEOWNERS").exists():
                codeowners_path = charts_path / "CODEOWNERS"

            active_charts_path: Path | None = None
            if app.settings.active_charts_path:
                candidate = Path(app.settings.active_charts_path).expanduser().resolve()
                if candidate.is_file():
                    active_charts_path = candidate

            charts_controller = self._get_or_create_charts_controller(
                charts_path,
                context=context,
                codeowners_path=codeowners_path,
                active_charts_path=active_charts_path,
            )

            if worker.is_cancelled:
                return

            # Load charts
            if use_cluster_mode:
                self.call_later(
                    self._set_charts_progress,
                    20,
                    "Fetching Helm releases from cluster...",
                )
                self.call_later(
                    self._update_loading_message,
                    "Fetching Helm releases from cluster...",
                )

                def _on_release_discovery_progress(
                    partial_releases: list[dict[str, str]],
                    completed: int,
                    total: int,
                ) -> None:
                    if (
                        worker.is_cancelled
                        or not self.is_attached
                        or not self.is_current
                        or mode_generation != self._mode_generation
                    ):
                        return
                    release_count = len(partial_releases)
                    progress = 20
                    if total > 0:
                        progress = 20 + int((completed / total) * 20)
                    loading_message = (
                        "Fetching Helm releases from cluster... "
                        f"({completed}/{total} namespaces, {release_count} releases)"
                    )
                    self.call_later(
                        self._set_charts_progress,
                        max(self._charts_load_progress, min(progress, 40)),
                        loading_message,
                    )
                    self.call_later(
                        self._update_loading_message,
                        loading_message,
                    )

                def _on_analysis_progress(completed: int, total: int) -> None:
                    if (
                        worker.is_cancelled
                        or not self.is_attached
                        or not self.is_current
                        or mode_generation != self._mode_generation
                    ):
                        return
                    progress = 40
                    if total > 0:
                        progress = 40 + int((completed / total) * 50)
                    loading_message = (
                        f"Analyzing live Helm values... ({completed}/{total})"
                    )
                    self.call_later(
                        self._set_charts_progress,
                        max(self._charts_load_progress, min(progress, 90)),
                        loading_message,
                    )
                    self.call_later(
                        self._update_loading_message,
                        loading_message,
                    )

                last_partial_publish_monotonic = 0.0

                def _on_analysis_partial(
                    partial_charts: list[ChartInfo],
                    completed: int,
                    total: int,
                ) -> None:
                    nonlocal last_partial_publish_monotonic
                    if (
                        worker.is_cancelled
                        or not self.is_attached
                        or mode_generation != self._mode_generation
                    ):
                        return
                    if completed >= total:
                        return
                    if completed % self._partial_update_step(total) != 0:
                        return
                    now = time.monotonic()
                    if (
                        now - last_partial_publish_monotonic
                        < self._CLUSTER_PARTIAL_UPDATE_MIN_INTERVAL_SECONDS
                    ):
                        return
                    last_partial_publish_monotonic = now
                    snapshot = list(partial_charts)

                    def _publish_partial() -> None:
                        if (
                            worker.is_cancelled
                            or not self.is_attached
                            or mode_generation != self._mode_generation
                        ):
                            return
                        self.post_message(
                            ChartsExplorerPartialDataLoaded(
                                snapshot,
                                completed,
                                total,
                                mode_generation=mode_generation,
                            )
                        )

                    self.call_later(_publish_partial)

                charts = await charts_controller.analyze_all_charts_cluster_async(
                    None,
                    force_refresh,
                    on_release_discovery_progress=_on_release_discovery_progress,
                    on_analysis_progress=_on_analysis_progress,
                    on_analysis_partial=_on_analysis_partial,
                )
            else:
                self.call_later(self._set_charts_progress, 40, "Analyzing Helm charts...")
                self.call_later(self._update_loading_message, "Analyzing Helm charts...")
                last_partial_publish_monotonic = 0.0
                active_charts_snapshot: set[str] | None = (
                    set(charts_controller.active_charts)
                    if charts_controller.active_charts
                    else None
                )

                def _on_repo_analysis_progress(completed: int, total: int) -> None:
                    if (
                        worker.is_cancelled
                        or not self.is_attached
                        or not self.is_current
                        or mode_generation != self._mode_generation
                    ):
                        return
                    progress = 40
                    if total > 0:
                        progress = 40 + int((completed / total) * 50)
                    loading_message = f"Analyzing Helm charts... ({completed}/{total})"
                    self.call_later(
                        self._set_charts_progress,
                        max(self._charts_load_progress, min(progress, 90)),
                        loading_message,
                    )
                    self.call_later(
                        self._update_loading_message,
                        loading_message,
                    )

                def _on_repo_analysis_partial(
                    partial_charts: list[ChartInfo],
                    completed: int,
                    total: int,
                ) -> None:
                    nonlocal last_partial_publish_monotonic
                    if (
                        worker.is_cancelled
                        or not self.is_attached
                        or mode_generation != self._mode_generation
                    ):
                        return
                    if completed >= total:
                        return
                    if completed % self._partial_update_step(total) != 0:
                        return
                    now = time.monotonic()
                    if (
                        now - last_partial_publish_monotonic
                        < self._CLUSTER_PARTIAL_UPDATE_MIN_INTERVAL_SECONDS
                    ):
                        return
                    last_partial_publish_monotonic = now
                    snapshot = list(partial_charts)

                    def _publish_partial() -> None:
                        if (
                            worker.is_cancelled
                            or not self.is_attached
                            or mode_generation != self._mode_generation
                        ):
                            return
                        self.post_message(
                            ChartsExplorerPartialDataLoaded(
                                snapshot,
                                completed,
                                total,
                                active_charts=active_charts_snapshot,
                                mode_generation=mode_generation,
                            )
                        )

                    self.call_later(_publish_partial)

                charts = await charts_controller.analyze_all_charts_async(
                    active_releases=None,
                    force_refresh=force_refresh,
                    on_analysis_progress=_on_repo_analysis_progress,
                    on_analysis_partial=_on_repo_analysis_partial,
                )

            if worker.is_cancelled or not self.is_attached:
                return

            active_set: set[str] | None = (
                set(charts_controller.active_charts)
                if charts_controller.active_charts
                else None
            )
            if mode_generation != self._mode_generation:
                return
            self.post_message(
                ChartsExplorerDataLoaded(
                    charts,
                    active_set,
                    mode_generation=mode_generation,
                )
            )
            self.call_later(
                self._set_charts_progress,
                100,
                f"Loaded {len(charts)} chart(s)",
            )
            if not charts or worker.is_cancelled:
                return

            violations_signature = await self._violations_payload_signature_async(charts)
            requires_violation_counts = self._violations_required_for_charts_table()
            if (
                requires_violation_counts
                and self._cached_violation_counts is not None
                and violations_signature == self._violations_signature
            ):
                self.post_message(
                    ChartsExplorerViolationsLoaded(dict(self._cached_violation_counts))
                )
                return

            # Compute violation counts only when violations-aware view/sort is requested.
            if not requires_violation_counts:
                return

            if self.is_current:
                self.call_later(
                    self._start_violation_counts_worker,
                    list(charts),
                    violations_signature,
                )
            else:
                self._reload_violation_counts_on_resume = True

        except Exception as e:
            logger.exception("Failed to load charts")
            if self.is_attached:
                self.call_later(
                    lambda err=str(e): self._set_charts_progress(
                        max(self._charts_load_progress, 10),
                        f"Load failed: {err}",
                        is_error=True,
                    )
                )
            if self.is_attached:
                self.post_message(
                    ChartsExplorerDataLoadFailed(
                        f"Failed to load charts: {escape(str(e))}",
                        mode_generation=mode_generation,
                    )
                )
        finally:
            self._loading = False
            self._load_force_refresh = False
            if self._pending_refresh and self.is_attached:
                pending_force_refresh = self._pending_force_refresh
                self._pending_refresh = False
                self._pending_force_refresh = False
                self.call_later(
                    lambda: self._start_load_worker(
                        force_refresh=pending_force_refresh,
                    )
                )
            # Charts load finished — if optimizer was deferred because _loading
            # was True, kick it off now.
            elif (
                self._reload_optimizer_on_resume
                and not self._optimizer_loading
                and not self._optimizer_loaded
                and self._active_tab == TAB_VIOLATIONS
                and bool(self.charts)
                and self.is_attached
            ):
                self._reload_optimizer_on_resume = False
                self.call_later(self._start_optimizer_worker)

    def _start_violation_counts_worker(
        self,
        charts: list[ChartInfo],
        precomputed_signature: str | None = None,
    ) -> None:
        """Launch dedicated violation-count calculation after charts render.

        Args:
            charts: Snapshot of charts to analyze.
            precomputed_signature: Optional signature computed by a worker thread.
                When None, the signature is computed inside the worker to avoid
                blocking the UI thread with file-stat I/O.
        """
        if self._violation_counts_loading or not charts:
            return
        if not self.is_current:
            self._reload_violation_counts_on_resume = True
            return
        self._violation_counts_loading = True

        async def _worker() -> None:
            worker = get_current_worker()
            try:
                if worker.is_cancelled:
                    return
                # Compute signature in worker when not pre-computed (avoids
                # file-stat I/O on the UI thread).
                violations_signature = precomputed_signature
                if violations_signature is None:
                    violations_signature = await self._violations_payload_signature_async(
                        charts,
                    )
                if worker.is_cancelled:
                    return
                if self.is_current:
                    self.call_later(self._update_loading_message, "Checking violations...")
                violations: list[ViolationResult]
                if (
                    self._cached_violations is not None
                    and self._violations_signature == violations_signature
                ):
                    violations = self._clone_violations_payload(self._cached_violations)
                else:
                    from kubeagle.models.optimization.optimizer_controller import (
                        UnifiedOptimizerController,
                    )

                    analysis_source, render_timeout_seconds = (
                        self._optimizer_settings_signature()
                    )
                    optimizer = UnifiedOptimizerController(
                        analysis_source=analysis_source,
                        render_timeout_seconds=render_timeout_seconds,
                    )
                    violations = await asyncio.to_thread(optimizer.check_all_charts, charts)
                if worker.is_cancelled or not self.is_attached:
                    return

                violation_counts = self._build_violation_counts(violations)
                self._cache_violations_payload(
                    violations_signature=violations_signature,
                    violations=violations,
                )
                self.post_message(ChartsExplorerViolationsLoaded(violation_counts))
            except Exception:
                logger.exception("Failed to compute chart violation counts")
            finally:
                self._violation_counts_loading = False

        self.run_worker(
            _worker,
            name="charts-explorer-violations",
            exclusive=False,
        )

    def _violations_required_for_charts_table(self) -> bool:
        """Return whether current charts-table state needs violation counts."""
        return (
            self.current_view == ViewFilter.WITH_VIOLATIONS
            or self.current_sort == SortBy.VIOLATIONS
        )

    def _ensure_violation_counts_available(self) -> None:
        """Load violation counts lazily only when charts-table features need them."""
        if (
            self._active_tab != TAB_CHARTS
            or not self.charts
            or self._loading
            or self._violation_counts_loading
            or not self._violations_required_for_charts_table()
        ):
            return

        if (
            self._cached_violation_counts is not None
            and self._violations_cache_generation == self._charts_load_generation
        ):
            previous_revision = self._presenter.violation_revision
            self._presenter.set_violations(dict(self._cached_violation_counts))
            if (
                self.is_current
                and self._presenter.violation_revision != previous_revision
            ):
                self._schedule_charts_tab_repopulate(force=False)
            return

        self._start_violation_counts_worker(list(self.charts))

    def _sync_loaded_charts_state(
        self,
        charts: list[ChartInfo],
        active_charts: set[str] | None,
        *,
        partial_update: bool = False,
    ) -> None:
        """Sync screen state from a fresh charts payload."""
        self.charts = charts
        self._charts_load_generation += 1
        self._active_charts = active_charts
        if partial_update:
            self._extend_chart_runtime_indexes(self.charts)
            return
        self._rebuild_chart_runtime_indexes()

        teams = sorted({c.team for c in self.charts})
        self._team_filter_options = tuple((team, team) for team in teams)
        valid_team_values = {value for _, value in self._team_filter_options}
        self._team_filter_values = {
            value for value in self._team_filter_values if value in valid_team_values
        }
        if self._team_filter_values == valid_team_values:
            self._team_filter_values = set()

        qos_values = sorted({c.qos_class.value for c in self.charts})
        self._qos_filter_options = tuple((qos, qos) for qos in qos_values)
        valid_qos_values = {value for _, value in self._qos_filter_options}
        self._qos_filter_values = {
            value for value in self._qos_filter_values if value in valid_qos_values
        }
        if self._qos_filter_values == valid_qos_values:
            self._qos_filter_values = set()

        values_file_type_values = sorted(
            {self._chart_values_file_type(c) for c in self.charts}
        )
        self._values_file_type_filter_options = tuple(
            (value_type, value_type) for value_type in values_file_type_values
        )
        valid_values_file_type_values = {
            value for _, value in self._values_file_type_filter_options
        }
        self._values_file_type_filter_values = {
            value
            for value in self._values_file_type_filter_values
            if value in valid_values_file_type_values
        }
        if self._values_file_type_filter_values == valid_values_file_type_values:
            self._values_file_type_filter_values = set()

        self._sync_current_team_from_filter()

    def on_charts_explorer_partial_data_loaded(
        self,
        event: ChartsExplorerPartialDataLoaded,
    ) -> None:
        """Incrementally render cluster charts while analysis is still running."""
        if event.mode_generation != self._mode_generation:
            return
        if not self._loading:
            return
        self._sync_loaded_charts_state(
            event.charts,
            event.active_charts,
            partial_update=True,
        )
        if not self.is_current:
            self._render_data_on_resume = True
            return
        percent = 40
        if event.total > 0:
            percent = 40 + int((event.completed / event.total) * 50)
        self._set_charts_progress(
            max(self._charts_load_progress, min(percent, 90)),
            f"Analyzing live Helm values... ({event.completed}/{event.total})",
        )
        if event.charts and self._force_overlay_until_load_complete:
            # Mode-switch loads may force an initial overlay; once first real
            # partial payload arrives, unblock table interaction.
            self._force_overlay_until_load_complete = False
        if event.charts:
            self.hide_loading_overlay()
        if self._active_tab == TAB_CHARTS and self._should_schedule_partial_table_repaint(
            chart_count=len(event.charts),
            completed=event.completed,
            total=event.total,
        ):
            self._schedule_partial_charts_refresh()

    def on_charts_explorer_data_loaded(self, event: ChartsExplorerDataLoaded) -> None:
        """Apply chart list immediately without waiting for violations analysis."""
        if event.mode_generation != self._mode_generation:
            return
        self._charts_payload_ready_for_optimizer = True
        self._reload_on_resume = False
        self._reload_violation_counts_on_resume = False
        self._render_data_on_resume = False
        self._partial_charts_refresh_scheduled = False
        self._stop_partial_charts_refresh_timer()
        self._presenter.set_violations({})
        self._sync_loaded_charts_state(event.charts, event.active_charts)
        if not self.is_current:
            self._render_data_on_resume = True
            return

        if self.charts:
            self._set_charts_progress(100, f"Loaded {len(self.charts)} chart(s)")
            self._mark_partial_table_repaint(len(self.charts))
        else:
            self._set_charts_progress(100, "No charts found")
        self._force_overlay_until_load_complete = False
        self.hide_loading_overlay()
        if not self.charts:
            self._show_empty_table("No charts found in the configured path")
            return

        if self._active_tab == TAB_CHARTS:
            self._schedule_charts_tab_repopulate(force=True)
            self._ensure_violation_counts_available()
        status_suffix = (
            " (violations updating...)"
            if self._violations_required_for_charts_table()
            else ""
        )
        self.app.notify(
            f"Loaded {len(self.charts)} charts{status_suffix}",
            timeout=4,
        )
        if self._active_tab == TAB_VIOLATIONS:
            self._reload_optimizer_on_resume = False
            self._ensure_optimizer_data_loaded()

    def on_charts_explorer_violations_loaded(self, event: ChartsExplorerViolationsLoaded) -> None:
        """Apply violation counts after background analysis completes."""
        self._reload_violation_counts_on_resume = False
        self._render_violations_on_resume = False
        self._presenter.set_violations(event.violation_counts)
        if not self.is_current:
            self._render_violations_on_resume = True
            return
        if self._active_tab != TAB_CHARTS:
            self._last_filter_signature = None
            self._table_content_signature = None
            return
        self._schedule_charts_tab_repopulate(force=True)
        self.app.notify("Violation analysis completed", timeout=3)

    def on_charts_explorer_data_load_failed(self, event: ChartsExplorerDataLoadFailed) -> None:
        """Show worker loading failures in the screen overlay."""
        if event.mode_generation != self._mode_generation:
            return
        self._charts_payload_ready_for_optimizer = True
        self._reload_on_resume = False
        self._reload_violation_counts_on_resume = False
        self._partial_charts_refresh_scheduled = False
        self._stop_partial_charts_refresh_timer()
        self._set_charts_progress(
            max(self._charts_load_progress, 10),
            event.error,
            is_error=True,
        )
        self._force_overlay_until_load_complete = False
        self.show_error_state(event.error)
        self._show_retry_button()

    # =========================================================================
    # Central Update Method
    # =========================================================================

    def _apply_filters_and_populate(self, *, force: bool = False) -> None:
        """Apply all filters and repopulate the table."""
        if not self.charts:
            self._clear_selected_chart()
            return
        if self._active_tab != TAB_CHARTS:
            return

        # Get search query from cached ref or DOM fallback
        search_query = ""
        search_ref = getattr(self, "_cached_search_input", None)
        if search_ref is not None:
            search_query = search_ref.value
        else:
            with contextlib.suppress(Exception):
                search_ref = self.query_one("#charts-search-input", CustomInput)
                self._cached_search_input = search_ref
                search_query = search_ref.value
        normalized_query = search_query.strip().lower()

        active_charts = self._active_charts
        active_charts_len = len(active_charts) if active_charts is not None else 0
        render_signature = (
            id(self.charts),
            len(self.charts),
            self.current_view,
            self.current_sort,
            self.sort_desc,
            self.show_active_only,
            id(active_charts),
            active_charts_len,
            frozenset(self._team_filter_values),
            frozenset(self._qos_filter_values),
            frozenset(self._values_file_type_filter_values),
            tuple(self._iter_visible_column_names()),
            normalized_query,
            self._presenter.violation_revision,
        )
        if not force and render_signature == self._last_filter_signature:
            return
        self._last_filter_signature = render_signature

        # Apply all filters in a single pass after presenter pre-filter
        self.filtered_charts = self._presenter.apply_filters(
            self.charts,
            self.current_view,
            self._team_filter_values,
            "",
            self.show_active_only,
            self._active_charts,
        )
        # Combine search + QoS + values-file-type into one pass
        has_search = bool(normalized_query)
        has_qos = bool(self._qos_filter_values)
        has_vft = bool(self._values_file_type_filter_values)
        if has_search or has_qos or has_vft:
            qos_values = self._qos_filter_values
            vft_values = self._values_file_type_filter_values
            combined = []
            for chart in self.filtered_charts:
                if has_search and normalized_query not in self._chart_search_haystack(chart):
                    continue
                if has_qos and chart.qos_class.value not in qos_values:
                    continue
                if has_vft and self._chart_values_file_type(chart) not in vft_values:
                    continue
                combined.append(chart)
            self.filtered_charts = combined

        if self._violations_required_for_charts_table():
            self._ensure_violation_counts_available()

        sorted_filtered_charts = self._presenter.sort_charts(
            self.filtered_charts,
            sort_by=self.current_sort,
            descending=self.sort_desc,
        )

        # Populate table — defer row formatting to async _do_populate
        self._populate_table(sorted_charts=sorted_filtered_charts)

        # Update summary
        self._update_summary()
        self._update_sort_direction_button()

        if not self.filtered_charts:
            self._clear_selected_chart()

    def _populate_table(
        self,
        *,
        sorted_charts: list[ChartInfo] | None = None,
    ) -> None:
        """Populate the explorer table with rows (formatting deferred to async)."""
        try:
            table = self.query_one("#explorer-table", CustomDataTable)
        except Exception:
            return

        visible_indices = self._visible_column_indices()
        columns_changed = visible_indices != self._last_table_columns_signature

        charts_for_rows = sorted_charts or []
        filtered_count = len(self.filtered_charts)

        # Build a content signature from the chart identities, order, and columns.
        # If the table already shows exactly this content, skip the expensive
        # clear-and-rebuild cycle entirely — the DOM rows are still intact.
        # Note: violation_revision is intentionally excluded here — it affects
        # which charts pass the filter/sort (handled by render_signature in
        # _apply_filters_and_populate), but format_chart_row() output does
        # not include violation data.  Including it here caused unnecessary
        # table clear-and-rebuild cycles that produced visible flicker when
        # switching back from the violations tab.
        content_sig: tuple[Any, ...] = (
            tuple(id(c) for c in charts_for_rows),
            visible_indices,
        )
        if not columns_changed and content_sig == self._table_content_signature:
            # Table already has the right rows — just update title/selection.
            with contextlib.suppress(Exception):
                self.query_one("#explorer-table-title", CustomStatic).update(
                    f"Charts Table ({filtered_count})",
                )
            return

        self._table_populate_sequence += 1
        sequence = self._table_populate_sequence

        # Capture presenter ref for the async closure
        presenter = self._presenter

        # Threshold above which row formatting is offloaded to a worker thread
        # to avoid blocking the Textual event loop.
        _ROW_FORMAT_THREAD_THRESHOLD = 80

        async def _do_populate() -> None:
            if not self._screen_is_current() or self._active_tab != TAB_CHARTS:
                self._render_data_on_resume = True
                return
            if sequence != self._table_populate_sequence:
                return

            # Format rows — offload to thread for large payloads to keep UI
            # responsive during the pure-Python string formatting work.
            def _format_all() -> list[tuple[str, ...]]:
                return [
                    tuple(row[i] for i in visible_indices)
                    for row in (presenter.format_chart_row(c) for c in charts_for_rows)
                ]

            if len(charts_for_rows) > _ROW_FORMAT_THREAD_THRESHOLD:
                visible_rows = await asyncio.to_thread(_format_all)
            else:
                visible_rows = _format_all()

            if sequence != self._table_populate_sequence:
                return

            inner = table.data_table

            # Phase 1 — clear + column setup in a single batch so the user
            # never sees an intermediate state with wrong columns.
            with table.batch_update():
                if inner is not None:
                    inner.fixed_columns = self._locked_fixed_column_count(
                        visible_indices,
                    )
                if columns_changed:
                    table.clear(columns=True)
                    self._configure_explorer_table_header_tooltips(table)
                    for col_index in visible_indices:
                        col_name, _ = EXPLORER_TABLE_COLUMNS[col_index]
                        table.add_column(col_name)
                    self._last_table_columns_signature = visible_indices
                else:
                    table.clear(columns=False)

            if sorted_charts is not None and len(sorted_charts) == len(visible_rows):
                self._row_chart_map = dict(enumerate(sorted_charts))
            else:
                self._row_chart_map = {}

            # Phase 2 — insert rows in per-chunk batches.  Each chunk gets
            # its own batch_update so _on_idle → _update_dimensions only
            # measures that chunk's new rows, keeping the UI responsive.
            row_count = len(visible_rows)
            chunk_size = self._table_chunk_size(row_count)

            if row_count and chunk_size < row_count:
                for start in range(0, row_count, chunk_size):
                    if (
                        not self._screen_is_current()
                        or self._active_tab != TAB_CHARTS
                        or sequence != self._table_populate_sequence
                    ):
                        return
                    end = min(start + chunk_size, row_count)
                    with table.batch_update():
                        table.add_rows(visible_rows[start:end])
                    if end < row_count:
                        # Yield so _on_idle measures only this chunk's rows
                        await asyncio.sleep(0)
            elif row_count:
                with table.batch_update():
                    table.add_rows(visible_rows)

            if sequence != self._table_populate_sequence:
                return

            # Record what the table now contains so future tab-switch
            # round-trips can skip the rebuild when nothing changed.
            self._table_content_signature = content_sig

            with contextlib.suppress(Exception):
                self.query_one("#explorer-table-title", CustomStatic).update(
                    f"Charts Table ({filtered_count})",
                )

            if self._row_chart_map:
                selected_row = self._find_selected_chart_row(self._row_chart_map)
                target_row = (
                    selected_row
                    if selected_row is not None
                    else min(self._row_chart_map.keys())
                )
                table.cursor_row = target_row
                self._set_selected_chart(self._row_chart_map[target_row])
            else:
                self._clear_selected_chart()

        self.call_later(_do_populate)

    def _configure_explorer_table_header_tooltips(
        self,
        table: CustomDataTable,
    ) -> None:
        """Apply per-column header tooltips for charts table."""
        table.set_header_tooltips(EXPLORER_HEADER_TOOLTIPS)
        table.set_default_tooltip("Double-click a row to open chart details")

    def _iter_visible_column_names(self) -> tuple[str, ...]:
        """Return currently visible table columns preserving the canonical order."""
        visible = tuple(
            column_name
            for column_name, _ in EXPLORER_TABLE_COLUMNS
            if (
                column_name in self._visible_column_names
                and self._is_column_available_for_mode(column_name)
            )
        )
        if visible:
            return visible
        fallback = tuple(
            column_name
            for column_name, _ in EXPLORER_TABLE_COLUMNS
            if self._is_column_available_for_mode(column_name)
        )
        if fallback:
            return (fallback[0],)
        return (EXPLORER_TABLE_COLUMNS[0][0],)

    def _visible_column_indices(self) -> tuple[int, ...]:
        """Return visible column indexes in table order."""
        visible_names = set(self._iter_visible_column_names())
        return tuple(
            index
            for index, (column_name, _) in enumerate(EXPLORER_TABLE_COLUMNS)
            if column_name in visible_names
        )

    def _locked_fixed_column_count(self, visible_indices: tuple[int, ...]) -> int:
        """Return contiguous fixed-column count required for locked columns."""
        visible_names = [
            EXPLORER_TABLE_COLUMNS[index][0]
            for index in visible_indices
        ]
        locked_positions = [
            position
            for position, column_name in enumerate(visible_names)
            if column_name in self._LOCKED_COLUMN_NAMES
        ]
        if not locked_positions:
            return 0
        return max(locked_positions) + 1

    # =========================================================================
    # Loading State
    # =========================================================================

    def _progress_text_limit(self) -> int:
        """Return max chars for top progress text based on current layout mode."""
        mode = self._layout_mode or self._get_layout_mode()
        if mode == "ultra":
            return self._PROGRESS_TEXT_MAX_ULTRA
        if mode == "wide":
            return self._PROGRESS_TEXT_MAX_WIDE
        if mode == "medium":
            return self._PROGRESS_TEXT_MAX_MEDIUM
        return self._PROGRESS_TEXT_MAX_NARROW

    @staticmethod
    def _truncate_plain_text(text: str, max_chars: int) -> str:
        """Return single-line truncated text with ellipsis when needed."""
        compact = " ".join(text.split())
        if max_chars <= 0 or len(compact) <= max_chars:
            return compact
        if max_chars == 1:
            return compact[:1]
        return f"{compact[: max_chars - 1].rstrip()}…"

    def _infer_progress_percent(self, message: str) -> int | None:
        """Infer progress from messages containing '(completed/total)'."""
        match = self._LOAD_PROGRESS_RE.search(message)
        if match is None:
            return None
        completed = int(match.group(1))
        total = int(match.group(2))
        if total <= 0:
            return None
        estimated = int((completed / total) * 90)
        return max(self._charts_load_progress, min(estimated, 99))

    def _set_charts_progress(
        self,
        percent: int,
        state_text: str,
        *,
        is_error: bool = False,
    ) -> None:
        """Update top-row charts progress bar and status text."""
        safe_percent = max(0, min(percent, 100))
        self._charts_progress_target = safe_percent
        if safe_percent < self._charts_progress_display:
            self._charts_progress_display = safe_percent
        state_plain = " ".join(state_text.split())
        if not state_plain:
            state_plain = "Idle"
        self._charts_load_progress = safe_percent
        self._charts_loading_message = state_plain
        self._charts_progress_is_error = is_error

        if self._charts_progress_display == self._charts_progress_target:
            self._stop_charts_progress_animation()
        else:
            self._ensure_charts_progress_animation_running()
        self._render_charts_progress()

    def _ensure_charts_progress_animation_running(self) -> None:
        """Start smooth progress interpolation timer when needed."""
        if self._charts_progress_animation_timer is not None:
            return
        self._charts_progress_animation_timer = self.set_interval(
            self._PROGRESS_ANIMATION_INTERVAL_SECONDS,
            self._tick_charts_progress_animation,
        )

    def _stop_charts_progress_animation(self) -> None:
        """Stop smooth progress interpolation timer."""
        if self._charts_progress_animation_timer is None:
            return
        with contextlib.suppress(Exception):
            self._charts_progress_animation_timer.stop()
        self._charts_progress_animation_timer = None

    def _tick_charts_progress_animation(self) -> None:
        """Advance the visible top progress percent towards its target."""
        target = self._charts_progress_target
        current = self._charts_progress_display
        delta = target - current
        if delta == 0:
            self._stop_charts_progress_animation()
            return
        step = max(1, int(abs(delta) * self._PROGRESS_ANIMATION_STEP_RATIO))
        if step <= 0:
            step = 1
        if delta > 0:
            current = min(target, current + step)
        else:
            current = max(target, current - step)
        self._charts_progress_display = current
        self._render_charts_progress()
        if current == target:
            self._stop_charts_progress_animation()

    def _render_charts_progress(self) -> None:
        """Render top-row charts progress bar and status text."""
        display_percent = max(0, min(self._charts_progress_display, 100))
        state_plain = self._charts_loading_message
        is_error = self._charts_progress_is_error

        # Use cached widget refs to avoid per-frame DOM queries
        if self._cached_progress_bar is None:
            with contextlib.suppress(Exception):
                self._cached_progress_bar = self.query_one("#charts-progress-bar", ProgressBar)
        if self._cached_progress_bar is not None:
            with contextlib.suppress(Exception):
                self._cached_progress_bar.update(total=100, progress=display_percent)

        if self._cached_loading_text is None:
            with contextlib.suppress(Exception):
                self._cached_loading_text = self.query_one("#charts-loading-text", CustomStatic)
        loading_text_widget = self._cached_loading_text

        prefix = f"{display_percent}% - "
        max_chars = self._progress_text_limit()
        if loading_text_widget is not None and loading_text_widget.size.width > len(prefix):
            max_chars = min(max_chars, loading_text_widget.size.width - len(prefix))
        compact_state = self._truncate_plain_text(state_plain, max_chars)
        displayed = f"{prefix}{compact_state}"
        full_text = f"{display_percent}% - {state_plain}"
        if loading_text_widget is not None:
            loading_text_widget.update(displayed)
            loading_text_widget.tooltip = full_text if displayed != full_text else None
            if is_error:
                loading_text_widget.add_class("status-error")
            else:
                loading_text_widget.remove_class("status-error")

    def show_loading_overlay(
        self,
        message: str = "Loading...",
        is_error: bool = False,
        *,
        allow_cached_passthrough: bool = True,
    ) -> None:
        """Show loading overlay."""
        try:
            overlay = self.query_one("#loading-overlay", CustomVertical)
            if (
                allow_cached_passthrough
                and not is_error
                and message in {"Loading charts...", "Refreshing..."}
                and self._has_existing_charts_data()
            ):
                overlay.display = False
                overlay.remove_class("visible")
                return
            overlay.display = True
            overlay.add_class("visible")
            msg_widget = self.query_one("#loading-message", CustomStatic)
            msg_widget.update(escape(message))
            if is_error:
                msg_widget.add_class("error")
                msg_widget.remove_class("loading")
            else:
                msg_widget.remove_class("error")
                msg_widget.add_class("loading")
        except Exception:
            pass

    def hide_loading_overlay(self) -> None:
        """Hide loading overlay."""
        try:
            overlay = self.query_one("#loading-overlay", CustomVertical)
            overlay.display = False
            overlay.remove_class("visible")
        except Exception:
            pass

    def _has_existing_charts_data(self) -> bool:
        """Return True when charts table already has interactive data to keep visible."""
        if bool(self.charts):
            return True
        with contextlib.suppress(Exception):
            table = self.query_one("#explorer-table", CustomDataTable)
            return table.row_count > 0
        return False

    def _show_retry_button(self) -> None:
        """Show the retry button."""
        with contextlib.suppress(Exception):
            self.query_one("#charts-retry-btn", CustomButton).display = True

    def _update_loading_message(self, message: str) -> None:
        """Update loading message text."""
        if not self.is_current:
            return
        with contextlib.suppress(Exception):
            self.query_one("#loading-message", CustomStatic).update(message)
        inferred_progress = self._infer_progress_percent(message)
        if inferred_progress is not None:
            self._set_charts_progress(inferred_progress, message)

    def _show_empty_table(self, message: str) -> None:
        """Show empty state in the table."""
        try:
            table = self.query_one("#explorer-table", CustomDataTable)
            self._last_table_columns_signature = None
            self._table_content_signature = None

            async def _do_empty() -> None:
                if not self._screen_is_current() or self._active_tab != TAB_CHARTS:
                    self._render_data_on_resume = True
                    return
                async with table.batch():
                    table.clear(columns=True)
                    table.add_column("Message")
                    table.add_row(f"[dim]{escape(message)}[/dim]")

            self.call_later(_do_empty)
        except Exception:
            pass

    # =========================================================================
    # UI Helpers
    # =========================================================================

    def _focus_table(self) -> None:
        """Focus the explorer DataTable."""
        with contextlib.suppress(Exception):
            self.query_one("#explorer-table", CustomDataTable).focus()

    def _screen_is_current(self) -> bool:
        """Return current-screen state without requiring an active app context."""
        with contextlib.suppress(Exception):
            return bool(self.is_current)
        return False

    def _rebuild_chart_runtime_indexes(self) -> None:
        """Build per-chart search/type indexes used by repeated filter passes."""
        self._chart_search_index = {}
        self._chart_values_file_type_index = {}
        self._extend_chart_runtime_indexes(self.charts)

    def _extend_chart_runtime_indexes(self, charts: list[ChartInfo]) -> None:
        """Add missing chart search/type entries without rebuilding existing ones."""
        search_index: dict[int, str] = {}
        values_type_index: dict[int, str] = {}
        for chart in charts:
            chart_id = id(chart)
            if (
                chart_id in self._chart_search_index
                and chart_id in self._chart_values_file_type_index
            ):
                continue
            values_type = ChartsExplorerPresenter._classify_values_file_type(chart.values_file)
            values_type_index[chart_id] = values_type
            search_index[chart_id] = "|".join(
                (
                    str(chart.name).lower(),
                    str(chart.namespace or "").lower(),
                    str(chart.team).lower(),
                    str(chart.values_file).lower(),
                    str(chart.qos_class.value).lower(),
                    values_type.lower(),
                )
            )
        self._chart_search_index.update(search_index)
        self._chart_values_file_type_index.update(values_type_index)

    def _chart_values_file_type(self, chart: ChartInfo) -> str:
        """Return cached values-file classification for a chart."""
        chart_id = id(chart)
        cached = self._chart_values_file_type_index.get(chart_id)
        if cached is not None:
            return cached
        value = ChartsExplorerPresenter._classify_values_file_type(chart.values_file)
        self._chart_values_file_type_index[chart_id] = value
        return value

    def _chart_search_haystack(self, chart: ChartInfo) -> str:
        """Return cached lowercase search haystack for a chart row."""
        chart_id = id(chart)
        cached = self._chart_search_index.get(chart_id)
        if cached is not None:
            return cached
        values_type = self._chart_values_file_type(chart)
        haystack = "|".join(
            (
                str(chart.name).lower(),
                str(chart.namespace or "").lower(),
                str(chart.team).lower(),
                str(chart.values_file).lower(),
                str(chart.qos_class.value).lower(),
                values_type.lower(),
            )
        )
        self._chart_search_index[chart_id] = haystack
        return haystack

    def _sync_view_tabs(self) -> None:
        """Keep the view tab widget in sync with current_view."""
        target_tab_id = VIEW_TAB_ID_BY_FILTER.get(self.current_view)
        if target_tab_id is None:
            return
        self._activate_view_tab(target_tab_id)

    def _update_sort_direction_button(self) -> None:
        """Keep sort direction select value in sync with screen state."""
        with contextlib.suppress(Exception):
            sort_order_select = self.query_one("#charts-sort-order-select", Select)
            target_value = "desc" if self.sort_desc else "asc"
            if sort_order_select.value != target_value:
                sort_order_select.value = target_value

    def _update_mode_button(self) -> None:
        """Update mode toggle button label and styling."""
        with contextlib.suppress(Exception):
            mode_btn = self.query_one("#charts-mode-btn", CustomButton)
            mode_btn.label = (
                BUTTON_MODE_CLUSTER if self.use_cluster_mode else BUTTON_MODE_LOCAL
            )
            mode_btn.tooltip = (
                "Live cluster mode (Helm releases)"
                if self.use_cluster_mode
                else "Local repository mode (values files)"
            )
            # Keep mode button visuals consistent with refresh button.
            mode_btn.remove_class("--warning")

    def _is_column_available_for_mode(self, column_name: str) -> bool:
        """Return whether a table column should be available in current mode."""
        if column_name == self._NAMESPACE_COLUMN_NAME:
            return self.use_cluster_mode
        return True

    def _sync_mode_column_state(self) -> None:
        """Keep column options/visibility aligned with current mode."""
        previous_visible = set(self._visible_column_names)
        self._column_filter_options = tuple(
            (column_name, column_name)
            for column_name, _ in EXPLORER_TABLE_COLUMNS
            if self._is_column_available_for_mode(column_name)
        )
        available_column_names = {name for name, _ in self._column_filter_options}
        self._visible_column_names = {
            name for name in self._visible_column_names if name in available_column_names
        }
        self._visible_column_names.update(
            self._LOCKED_COLUMN_NAMES & available_column_names,
        )
        if (
            self.use_cluster_mode
            and self._NAMESPACE_COLUMN_NAME in available_column_names
        ):
            # Ensure Namespace is shown when cluster mode is enabled.
            self._visible_column_names.add(self._NAMESPACE_COLUMN_NAME)
        if not self._visible_column_names:
            self._visible_column_names = set(available_column_names)
        if previous_visible != self._visible_column_names:
            self._last_filter_signature = None
            self._last_table_columns_signature = None
            self._table_content_signature = None

    def _sync_current_team_from_filter(self) -> None:
        """Keep legacy single-team state in sync with SelectionList filter values."""
        if len(self._team_filter_values) == 1:
            self.current_team = next(iter(self._team_filter_values))
            return
        self.current_team = None

    def _open_filters_modal(self) -> None:
        """Open a unified modal that stores all charts filter settings."""
        modal = _ChartsFiltersModal(
            team_options=self._team_filter_options,
            team_selected_values=self._team_filter_values,
            column_options=self._column_filter_options,
            visible_column_names=self._visible_column_names,
            locked_column_names=set(self._LOCKED_COLUMN_NAMES),
            qos_options=self._qos_filter_options,
            qos_selected_values=self._qos_filter_values,
            values_file_type_options=self._values_file_type_filter_options,
            values_file_type_selected_values=self._values_file_type_filter_values,
        )
        self.app.push_screen(modal, self._on_filters_modal_dismissed)

    def _on_filters_modal_dismissed(
        self,
        result: _ChartsFilterState | None,
    ) -> None:
        if result is None:
            return

        self._set_active_tab(TAB_CHARTS)

        valid_team_values = {value for _, value in self._team_filter_options}
        selected_team_values = {
            value for value in result["team_filter_values"] if value in valid_team_values
        }
        if selected_team_values == valid_team_values:
            selected_team_values = set()
        self._team_filter_values = selected_team_values
        self._sync_current_team_from_filter()

        valid_column_values = {value for _, value in self._column_filter_options}
        visible_column_values = {
            value for value in result["visible_column_names"]
            if value in valid_column_values
        }
        visible_column_values.update(self._LOCKED_COLUMN_NAMES & valid_column_values)
        if visible_column_values:
            self._visible_column_names = visible_column_values

        valid_qos_values = {value for _, value in self._qos_filter_options}
        selected_qos_values = {
            value for value in result["qos_filter_values"] if value in valid_qos_values
        }
        if selected_qos_values == valid_qos_values:
            selected_qos_values = set()
        self._qos_filter_values = selected_qos_values

        valid_values_file_type_values = {
            value for _, value in self._values_file_type_filter_options
        }
        selected_values_file_type_values = {
            value
            for value in result["values_file_type_filter_values"]
            if value in valid_values_file_type_values
        }
        if selected_values_file_type_values == valid_values_file_type_values:
            selected_values_file_type_values = set()
        self._values_file_type_filter_values = selected_values_file_type_values

        self._sync_view_tabs()
        self._apply_filters_and_populate()
        self._focus_table()

    def _update_summary(self) -> None:
        """Update KPI summary row for charts table tabs."""
        try:
            metrics = self._presenter.build_summary_metrics(self.charts, self.filtered_charts)
            shown = int(metrics["shown"])
            total = int(metrics["total"])
            extreme = int(metrics["filtered_extreme"])
            single = int(metrics["filtered_single_replica"])
            no_pdb = int(metrics["filtered_no_pdb"])

            self.query_one("#kpi-total", CustomKPI).set_value(
                self._presenter.format_fraction_with_percentage(shown, total)
            )
            self.query_one("#kpi-extreme", CustomKPI).set_value(
                self._presenter.format_count_with_percentage(extreme, shown)
            )
            self.query_one("#kpi-single", CustomKPI).set_value(
                self._presenter.format_count_with_percentage(single, shown)
            )
            self.query_one("#kpi-no-pdb", CustomKPI).set_value(
                self._presenter.format_count_with_percentage(no_pdb, shown)
            )
        except Exception:
            pass

    # =========================================================================
    # Reactive Watchers
    # =========================================================================

    def watch_show_active_only(self) -> None:
        """React to active filter change."""
        if not self._batch_updating:
            self._apply_filters_and_populate()

    def watch_use_cluster_mode(self) -> None:
        """React to mode changes by syncing mode button text."""
        self._sync_mode_column_state()
        self._update_mode_button()
        if self._active_tab == TAB_CHARTS and self.charts:
            self._schedule_charts_tab_repopulate(force=True)

    def watch_current_view(self) -> None:
        """React to view filter change."""
        if not self._batch_updating:
            self._sync_view_tabs()
            self._ensure_violation_counts_available()
            self._apply_filters_and_populate()

    def watch_current_sort(self) -> None:
        """React to sort field change."""
        if not self._batch_updating:
            self._ensure_violation_counts_available()
            self._apply_filters_and_populate()

    def watch_sort_desc(self) -> None:
        """React to sort direction change."""
        if not self._batch_updating:
            self._apply_filters_and_populate()
            self._update_sort_direction_button()

    def watch_current_team(self) -> None:
        """Legacy reactive hook; team filtering is driven by SelectionList state."""

    # =========================================================================
    # Select Change Handlers
    # =========================================================================

    @on(CustomTabs.TabActivated, "#charts-view-tabs")
    def _on_view_tab_activated(self, event: CustomTabs.TabActivated) -> None:
        """Handle view tab changes."""
        tab_id = str(event.tab.id) if event.tab.id else ""
        if tab_id and tab_id == self._ignore_next_view_tab_id:
            self._ignore_next_view_tab_id = None
            return
        target_view = VIEW_FILTER_BY_TAB_ID.get(tab_id)
        if target_view is None:
            return
        if target_view == ViewFilter.WITH_VIOLATIONS:
            self._set_active_tab(TAB_VIOLATIONS)
            return
        if self._active_tab != TAB_CHARTS:
            self._set_active_tab(TAB_CHARTS)
        if target_view != self.current_view:
            self.current_view = target_view

    @on(Select.Changed, "#charts-sort-select")
    def _on_sort_changed(self, event: Select.Changed) -> None:
        """Handle sort dropdown change."""
        if event.value is not Select.BLANK:
            self.current_sort = event.value  # type: ignore[assignment]

    @on(Select.Changed, "#charts-sort-order-select")
    def _on_sort_order_changed(self, event: Select.Changed) -> None:
        """Handle sort direction dropdown change."""
        if event.value is Select.BLANK:
            return
        self.sort_desc = str(event.value) == "desc"

    # =========================================================================
    # Input Handlers
    # =========================================================================

    def on_input_changed(self, event: CustomInput.Changed) -> None:
        """Handle search input changes with debounce."""
        if event.input.id == "charts-search-input":
            if self._search_debounce_timer is not None:
                self._search_debounce_timer.stop()
            self._search_debounce_timer = self.set_timer(
                0.3, self._apply_filters_and_populate,
            )

    def on_input_submitted(self, event: CustomInput.Submitted) -> None:
        """Handle search input submission."""
        if event.input.id == "charts-search-input":
            self._apply_filters_and_populate()
            self._focus_table()

    # =========================================================================
    # Button Handlers
    # =========================================================================

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "charts-search-btn":
            self._apply_filters_and_populate()
            self._focus_table()
        elif event.button.id == "charts-mode-btn":
            self.action_toggle_mode()
        elif event.button.id == "charts-filter-btn":
            self._open_filters_modal()
        elif event.button.id == "charts-clear-btn":
            self._clear_all_filters()
        elif event.button.id in {"charts-refresh-btn", "charts-retry-btn"}:
            self.action_refresh()

    def _clear_all_filters(self) -> None:
        """Clear all filters and reset view/sort controls.

        Uses _batch_updating to suppress reactive watchers during the reset,
        then applies a single filter+populate pass at the end.
        """
        self._batch_updating = True
        try:
            with contextlib.suppress(Exception):
                self.query_one("#charts-search-input", CustomInput).value = ""
            self.show_active_only = False
            self.current_view = ViewFilter.ALL
            self.current_sort = SortBy.CHART
            self.sort_desc = False
            self._team_filter_values = set()
            self._qos_filter_values = set()
            self._values_file_type_filter_values = set()
            self._visible_column_names = {
                column_name
                for column_name, _ in EXPLORER_TABLE_COLUMNS
                if self._is_column_available_for_mode(column_name)
            }
            self._visible_column_names.update(
                self._LOCKED_COLUMN_NAMES,
            )
            self.current_team = None
            with contextlib.suppress(Exception):
                self.query_one("#charts-sort-select", Select).value = SortBy.CHART
        finally:
            self._batch_updating = False
        self._sync_view_tabs()
        self._update_sort_direction_button()
        self._apply_filters_and_populate()
        self._focus_table()

    # =========================================================================
    # Row Selection
    # =========================================================================

    def on_data_table_row_highlighted(self, event: object) -> None:
        """Track selected chart as highlighted table row changes."""
        event_obj = cast(Any, event)
        cursor_row = getattr(event_obj, "cursor_row", None)
        if not isinstance(cursor_row, int):
            return
        chart = self._row_chart_map.get(cursor_row)
        if chart is not None:
            self._set_selected_chart(chart)

    def on_data_table_row_selected(self, _: object) -> None:
        """Handle row activation (Enter / click on highlighted row) and open chart preview."""
        if self._active_tab != TAB_CHARTS:
            return
        try:
            table = self.query_one("#explorer-table", CustomDataTable)
            cursor_row = table.cursor_row
        except Exception:
            return

        if cursor_row is None or cursor_row < 0:
            return

        chart = self._row_chart_map.get(cursor_row)
        if chart is None:
            # Group header row - skip
            return

        self._set_selected_chart(chart)
        task = asyncio.create_task(self._open_chart_preview_dialog(chart))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # =========================================================================
    # Actions
    # =========================================================================

    def action_select_chart(self) -> None:
        """Open chart preview dialog for selected row."""
        if self._active_tab != TAB_CHARTS:
            return
        try:
            table = self.query_one("#explorer-table", CustomDataTable)
            cursor_row = table.cursor_row
        except Exception:
            return

        if cursor_row is None or cursor_row < 0:
            return

        chart = self._row_chart_map.get(cursor_row)
        if chart is None:
            # Group header row - skip
            return

        self._set_selected_chart(chart)
        task = asyncio.create_task(self._open_chart_preview_dialog(chart))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def action_toggle_mode(self) -> None:
        """Toggle between cluster and local mode."""
        self.use_cluster_mode = not self.use_cluster_mode
        self._mode_generation += 1
        self._update_mode_button()
        app = self.app
        app.settings.use_cluster_mode = self.use_cluster_mode
        self.show_loading_overlay("Refreshing...", allow_cached_passthrough=False)
        self._start_load_worker(
            force_refresh=True,
            interrupt_if_loading=True,
            force_overlay=True,
        )

    def action_toggle_active_filter(self) -> None:
        """Toggle active charts filter."""
        if self._active_tab == TAB_VIOLATIONS:
            self.action_apply_all()
            return
        self._set_active_tab(TAB_CHARTS)
        self.show_active_only = not self.show_active_only

    def action_refresh(self) -> None:
        """Refresh current tab's data."""
        if self._active_tab == TAB_CHARTS:
            self.show_loading_overlay("Refreshing...")
            self._start_load_worker(force_refresh=True)
            return
        self.show_loading_overlay("Refreshing...")
        self._start_load_worker(force_refresh=True, interrupt_if_loading=True)

    def action_focus_search(self) -> None:
        """Focus the search input."""
        if self._active_tab == TAB_VIOLATIONS:
            self.query_one("#violations-view", ViolationsView).focus_search()
            return
        with contextlib.suppress(Exception):
            self.query_one("#charts-search-input", CustomInput).focus()

    def action_show_charts_tab(self) -> None:
        if self._active_tab != TAB_CHARTS:
            self._set_active_tab(TAB_CHARTS)

    def action_show_violations_tab(self) -> None:
        if self._active_tab != TAB_VIOLATIONS:
            self._set_active_tab(TAB_VIOLATIONS)

    def action_show_recommendations_tab(self) -> None:
        if self._active_tab != TAB_VIOLATIONS:
            self._set_active_tab(TAB_VIOLATIONS)

    def action_view_recommendations(self) -> None:
        """Compatibility action used by recommendations navigation."""
        self.action_show_recommendations_tab()

    def action_view_all(self) -> None:
        """Set view to All Charts."""
        self._set_active_tab(TAB_CHARTS)
        self.current_view = ViewFilter.ALL

    def action_view_extreme(self) -> None:
        """Set view to Extreme Ratios."""
        self._set_active_tab(TAB_CHARTS)
        self.current_view = ViewFilter.EXTREME_RATIOS

    def action_view_single_replica(self) -> None:
        """Set view to Single Replica."""
        self._set_active_tab(TAB_CHARTS)
        self.current_view = ViewFilter.SINGLE_REPLICA

    def action_view_no_pdb(self) -> None:
        """Set view to Missing PDB."""
        self._set_active_tab(TAB_CHARTS)
        self.current_view = ViewFilter.NO_PDB

    def action_view_violations(self) -> None:
        """Show violations view in the inner content switcher."""
        self._set_active_tab(TAB_VIOLATIONS)

    def action_toggle_sort_direction(self) -> None:
        """Toggle charts sort direction or focus optimizer sort controls."""
        if self._active_tab == TAB_VIOLATIONS:
            self.action_focus_sort()
            return
        self._set_active_tab(TAB_CHARTS)
        self.sort_desc = not self.sort_desc

    def action_cycle_team(self) -> None:
        """Cycle through team options."""
        self._set_active_tab(TAB_CHARTS)
        teams = [value for _, value in self._team_filter_options]
        if not teams:
            return

        selected_team = (
            next(iter(self._team_filter_values))
            if len(self._team_filter_values) == 1
            else None
        )
        try:
            current_idx = teams.index(selected_team) if selected_team is not None else -1
        except ValueError:
            current_idx = -1

        next_idx = (current_idx + 1) % (len(teams) + 1)
        if next_idx == len(teams):
            self._team_filter_values = set()
        else:
            self._team_filter_values = {teams[next_idx]}
        self._sync_current_team_from_filter()
        self._apply_filters_and_populate()

    def _get_single_selected_team(self) -> str | None:
        if len(self._team_filter_values) == 1:
            return next(iter(self._team_filter_values))
        if not self._team_filter_values:
            self.notify(
                "Select a team first (Filter > Team or press 't' to cycle)",
                severity="warning",
            )
            return None
        self.notify(
            "Select exactly one team for this action",
            severity="warning",
        )
        return None

    def action_view_team_violations(self) -> None:
        """Switch to violations filtered to the selected team."""
        team = self._get_single_selected_team()
        if team is None:
            return
        self._optimizer_team_filter = team
        self.action_show_violations_tab()
        self._apply_optimizer_team_filter()
        self._ensure_optimizer_data_loaded()

    def action_apply_all(self) -> None:
        self.query_one("#violations-view", ViolationsView).apply_all()

    async def action_fix_violation(self) -> None:
        await self.query_one("#violations-view", ViolationsView).fix_violation()

    def action_preview_fix(self) -> None:
        self.query_one("#violations-view", ViolationsView).preview_fix()

    def action_copy_yaml(self) -> None:
        self.query_one("#violations-view", ViolationsView).copy_yaml()

    def action_focus_sort(self) -> None:
        self.query_one("#violations-view", ViolationsView).focus_sort()

    def action_cycle_severity(self) -> None:
        self.query_one("#violations-view", ViolationsView).cycle_recommendation_severity()

    def action_go_to_chart(self) -> None:
        self.query_one("#violations-view", ViolationsView).go_to_recommendation_chart()

    def action_pop_screen(self) -> None:
        if self._active_tab == TAB_VIOLATIONS:
            vv = self.query_one("#violations-view", ViolationsView)
            if vv.handle_escape():
                return
        self.app.pop_screen()

    def action_export_team_report(self) -> None:
        """Export a markdown report for the selected team."""
        team = self._get_single_selected_team()
        if team is None:
            return

        team_charts = sorted(
            [c for c in self.charts if c.team == team],
            key=lambda c: c.name,
        )

        if not team_charts:
            self.notify(f"No charts found for team: {team}", severity="warning")
            return

        lines = [
            f"# Team Report: {team}",
            "",
            f"**Total Charts:** {len(team_charts)}",
            "",
            "## Charts",
            "",
        ]
        lines.extend(f"- {chart.name}" for chart in team_charts)

        report = "\n".join(lines)

        app = self.app
        app.state.export_data = report
        self.notify(f"Team report generated for {team}", severity="information")

    def action_show_help(self) -> None:
        """Show help dialog."""
        self.app.notify(
            "Charts Explorer\n\n"
            "Tabs:\n"
            "  C - Charts tab\n"
            "  5 - Optimizer tab\n"
            "  R - Optimizer tab (recommendations section)\n\n"
            "Chart Views (1-4):\n"
            "  1 - All Charts\n"
            "  2 - Extreme Ratios\n"
            "  3 - Single Replica\n"
            "  4 - Missing PDB\n\n"
            "Optimizer View:\n"
            "  5 - Optimizer\n\n"
            "Controls:\n"
            "  s - Toggle Sort Direction\n"
            "  t - Cycle Team filter\n"
            "  m - Toggle cluster/local mode\n"
            "  a - Filter to active charts\n"
            "  Filter button - Team/Columns/QoS/Values File Type lists\n"
            "  v - Team violations\n"
            "  f - Fix selected chart\n"
            "  p - Preview selected fix\n"
            "  y - Copy YAML fix\n"
            "  g - Go to chart (from recommendation)\n"
            "  x - Export team report\n"
            "  / - Search charts\n"
            "  enter - Open chart preview dialog\n"
            "  double-click row - Open chart preview dialog\n"
            "  r - Refresh data\n"
            "  ? - Show this help\n"
            "  escape - Go back",
            title="Charts Explorer Help",
            timeout=20,
        )

    # =========================================================================
    # Chart Preview Dialog
    # =========================================================================

    def _clear_selected_chart(self) -> None:
        """Clear chart selection when table has no selectable rows."""
        self._selected_chart = None

    def _set_selected_chart(self, chart: ChartInfo) -> None:
        """Set selected chart."""
        self._selected_chart = chart

    @staticmethod
    def _chart_selection_key(chart: ChartInfo) -> tuple[str, str, str, str]:
        """Return stable key used to preserve selection across table re-renders."""
        return (chart.name, chart.namespace or "", chart.values_file, chart.team)

    def _find_selected_chart_row(
        self,
        row_chart_map: dict[int, ChartInfo],
    ) -> int | None:
        """Find selected chart row in current table payload when still visible."""
        if not row_chart_map:
            return None
        selected_chart = self._selected_chart
        if selected_chart is None:
            return None
        selected_key = self._chart_selection_key(selected_chart)
        for row_index, chart in row_chart_map.items():
            if self._chart_selection_key(chart) == selected_key:
                return row_index
        return None

    @staticmethod
    def _build_values_content_markdown(content: str) -> str:
        """Render raw values content as a fenced YAML block."""
        normalized = content.replace("\r\n", "\n")
        if not normalized.strip():
            normalized = "# Empty values file\n"
        safe_content = normalized.replace("```", "` ` `")
        return f"```yaml\n{safe_content}\n```"

    def _load_values_file_content(self, chart: ChartInfo) -> str:
        """Load full values file content for chart detail dialog."""
        values_path = str(chart.values_file or "").strip()
        if not values_path:
            return "Values content is not available for this chart."

        if values_path.startswith("cluster:"):
            deployed_values = chart.deployed_values_content or ""
            if deployed_values.strip():
                return deployed_values
            return (
                "Unable to fetch deployed values for this cluster-backed chart.\n"
                "Ensure Helm/Kubernetes access is available and refresh."
            )

        path = Path(values_path).expanduser()
        if not path.is_file():
            return "Values file was not found."

        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "Failed to read values file."

    async def _open_chart_preview_dialog(self, chart: ChartInfo) -> None:
        """Open chart details preview dialog for selected chart.

        File I/O is offloaded to a thread to prevent blocking the UI.
        """
        values_content = await asyncio.to_thread(self._load_values_file_content, chart)
        modal = _ChartDetailsModal(
            chart=chart,
            values_markdown=self._build_values_content_markdown(values_content),
        )

        def _on_modal_dismiss(_: str | None) -> None:
            self._focus_table()

        self.app.push_screen(modal, _on_modal_dismiss)


__all__ = ["ChartsExplorerScreen"]
