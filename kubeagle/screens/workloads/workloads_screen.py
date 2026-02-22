"""Workloads screen - runtime workload resource requests/limits and ratios."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime
from typing import Any, TypedDict, cast

from textual import on
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import ContentSwitcher, ProgressBar

from kubeagle.keyboard import WORKLOADS_SCREEN_BINDINGS
from kubeagle.keyboard.navigation import ScreenNavigator
from kubeagle.models.core.workload_inventory_info import (
    WorkloadLiveUsageSampleInfo,
)
from kubeagle.screens.mixins.main_navigation_tabs_mixin import (
    MAIN_NAV_TAB_WORKLOADS,
    MainNavigationTabsMixin,
)
from kubeagle.screens.mixins.worker_mixin import WorkerMixin
from kubeagle.screens.workloads.config import (
    SORT_BY_NAME,
    TAB_WORKLOADS_ALL,
    TAB_WORKLOADS_NODE_ANALYSIS,
    WORKLOAD_VIEW_ALL,
    WORKLOAD_VIEW_FILTER_BY_TAB,
    WORKLOADS_HEADER_TOOLTIPS_BY_TAB,
    WORKLOADS_SORT_OPTIONS,
    WORKLOADS_TAB_IDS,
    WORKLOADS_TAB_LABELS,
    WORKLOADS_TABLE_COLUMNS_BY_TAB,
    WORKLOADS_TABLE_ID_BY_TAB,
)
from kubeagle.screens.workloads.presenter import (
    WorkloadsDataLoaded,
    WorkloadsDataLoadFailed,
    WorkloadsPresenter,
    WorkloadsSourceLoaded,
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
    CustomSelect as Select,
    CustomSelectionList,
    CustomStatic,
    CustomTabs,
    CustomVertical,
)

PlotextPlot: Any | None
try:
    from textual_plotext import PlotextPlot as _PlotextPlot
except Exception:  # pragma: no cover - runtime dependency fallback guard
    PlotextPlot = None
else:
    PlotextPlot = _PlotextPlot


class _WorkloadsFilterState(TypedDict):
    name_filter_values: set[str]
    kind_filter_values: set[str]
    helm_release_filter_values: set[str]
    namespace_filter_values: set[str]
    status_filter_values: set[str]
    pdb_filter_values: set[str]


class _WorkloadsFiltersModal(ModalScreen[_WorkloadsFilterState | None]):
    """Modal for namespace/status/PDB filters."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        name_options: tuple[tuple[str, str], ...],
        name_selected_values: set[str],
        kind_options: tuple[tuple[str, str], ...],
        kind_selected_values: set[str],
        helm_release_options: tuple[tuple[str, str], ...],
        helm_release_selected_values: set[str],
        namespace_options: tuple[tuple[str, str], ...],
        namespace_selected_values: set[str],
        status_options: tuple[tuple[str, str], ...],
        status_selected_values: set[str],
        pdb_options: tuple[tuple[str, str], ...],
        pdb_selected_values: set[str],
    ) -> None:
        super().__init__(classes="workloads-filters-modal-screen selection-modal-screen")

        self._name_options = name_options
        self._name_values = {value for _, value in name_options}
        selected_names = {value for value in name_selected_values if value in self._name_values}
        self._name_selected_values = selected_names if selected_names else set(self._name_values)

        self._kind_options = kind_options
        self._kind_values = {value for _, value in kind_options}
        selected_kinds = {value for value in kind_selected_values if value in self._kind_values}
        self._kind_selected_values = selected_kinds if selected_kinds else set(self._kind_values)

        self._helm_release_options = helm_release_options
        self._helm_release_values = {value for _, value in helm_release_options}
        selected_helm_releases = {
            value
            for value in helm_release_selected_values
            if value in self._helm_release_values
        }
        self._helm_release_selected_values = (
            selected_helm_releases if selected_helm_releases else set(self._helm_release_values)
        )

        self._namespace_options = namespace_options
        self._namespace_values = {value for _, value in namespace_options}
        selected_namespaces = {
            value for value in namespace_selected_values if value in self._namespace_values
        }
        self._namespace_selected_values = (
            selected_namespaces if selected_namespaces else set(self._namespace_values)
        )

        self._status_options = status_options
        self._status_values = {value for _, value in status_options}
        selected_statuses = {
            value for value in status_selected_values if value in self._status_values
        }
        self._status_selected_values = (
            selected_statuses if selected_statuses else set(self._status_values)
        )

        self._pdb_options = pdb_options
        self._pdb_values = {value for _, value in pdb_options}
        selected_pdb_values = {value for value in pdb_selected_values if value in self._pdb_values}
        self._pdb_selected_values = (
            selected_pdb_values if selected_pdb_values else set(self._pdb_values)
        )

    def compose(self) -> ComposeResult:
        with CustomContainer(
            classes="workloads-filters-modal-shell selection-modal-shell"
        ):
            yield CustomStatic(
                "Workload Filters",
                classes="workloads-filters-modal-title selection-modal-title",
                markup=False,
            )
            with CustomHorizontal(
                id="workloads-filters-modal-lists-row",
                classes="workloads-filters-modal-lists-row",
            ):
                with CustomVertical(classes="workloads-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Name",
                            id="workloads-filters-modal-name-title",
                            classes="workloads-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="workloads-filters-modal-name-list",
                            classes="workloads-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(
                        classes="workloads-filters-modal-list-actions",
                    ):
                        yield CustomButton(
                            "All",
                            id="workloads-filters-modal-name-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="workloads-filters-modal-name-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="workloads-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Kind",
                            id="workloads-filters-modal-kind-title",
                            classes="workloads-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="workloads-filters-modal-kind-list",
                            classes="workloads-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(
                        classes="workloads-filters-modal-list-actions",
                    ):
                        yield CustomButton(
                            "All",
                            id="workloads-filters-modal-kind-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="workloads-filters-modal-kind-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="workloads-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Helm",
                            id="workloads-filters-modal-helm-release-title",
                            classes="workloads-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="workloads-filters-modal-helm-release-list",
                            classes="workloads-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(
                        classes="workloads-filters-modal-list-actions",
                    ):
                        yield CustomButton(
                            "All",
                            id="workloads-filters-modal-helm-release-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="workloads-filters-modal-helm-release-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="workloads-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Namespace",
                            id="workloads-filters-modal-namespace-title",
                            classes="workloads-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="workloads-filters-modal-namespace-list",
                            classes="workloads-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(
                        classes="workloads-filters-modal-list-actions",
                    ):
                        yield CustomButton(
                            "All",
                            id="workloads-filters-modal-namespace-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="workloads-filters-modal-namespace-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="workloads-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "Status",
                            id="workloads-filters-modal-status-title",
                            classes="workloads-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="workloads-filters-modal-status-list",
                            classes="workloads-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(
                        classes="workloads-filters-modal-list-actions",
                    ):
                        yield CustomButton(
                            "All",
                            id="workloads-filters-modal-status-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="workloads-filters-modal-status-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                with CustomVertical(classes="workloads-filters-modal-list-column"):
                    with CustomVertical(classes="selection-modal-list-panel"):
                        yield CustomStatic(
                            "PDB",
                            id="workloads-filters-modal-pdb-title",
                            classes="workloads-filters-modal-list-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomSelectionList[str](
                            id="workloads-filters-modal-pdb-list",
                            classes="workloads-filters-modal-list selection-modal-list",
                        )
                    with CustomHorizontal(
                        classes="workloads-filters-modal-list-actions",
                    ):
                        yield CustomButton(
                            "All",
                            id="workloads-filters-modal-pdb-all",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                        yield CustomButton(
                            "Clear",
                            id="workloads-filters-modal-pdb-clear",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
            with CustomHorizontal(
                classes="workloads-filters-modal-actions selection-modal-actions"
            ):
                yield CustomButton(
                    "Apply",
                    id="workloads-filters-modal-apply",
                    compact=True,
                    variant="primary",
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Cancel",
                    id="workloads-filters-modal-cancel",
                    compact=True,
                    classes="selection-modal-action-btn",
                )

    def on_mount(self) -> None:
        self._refresh_name_selection_options()
        self._refresh_kind_selection_options()
        self._refresh_helm_release_selection_options()
        self._refresh_namespace_selection_options()
        self._refresh_status_selection_options()
        self._refresh_pdb_selection_options()
        self._sync_all_action_buttons()
        with suppress(Exception):
            self.query_one(
                "#workloads-filters-modal-name-list",
                CustomSelectionList,
            ).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_selection_list_selected_changed(self, event: object) -> None:
        event_obj = cast(Any, event)
        control = getattr(event_obj, "control", None)
        control_id = str(getattr(control, "id", ""))
        selected_values = {str(value) for value in getattr(control, "selected", [])}
        if control_id == "workloads-filters-modal-name-list-inner":
            self._name_selected_values = selected_values
            self._sync_filter_action_buttons(
                "name", self._name_selected_values, self._name_values
            )
            return
        if control_id == "workloads-filters-modal-kind-list-inner":
            self._kind_selected_values = selected_values
            self._sync_filter_action_buttons(
                "kind", self._kind_selected_values, self._kind_values
            )
            return
        if control_id == "workloads-filters-modal-helm-release-list-inner":
            self._helm_release_selected_values = selected_values
            self._sync_filter_action_buttons(
                "helm-release",
                self._helm_release_selected_values,
                self._helm_release_values,
            )
            return
        if control_id == "workloads-filters-modal-namespace-list-inner":
            self._namespace_selected_values = selected_values
            self._sync_filter_action_buttons(
                "namespace", self._namespace_selected_values, self._namespace_values
            )
            return
        if control_id == "workloads-filters-modal-status-list-inner":
            self._status_selected_values = selected_values
            self._sync_filter_action_buttons(
                "status", self._status_selected_values, self._status_values
            )
            return
        if control_id == "workloads-filters-modal-pdb-list-inner":
            self._pdb_selected_values = selected_values
            self._sync_filter_action_buttons("pdb", self._pdb_selected_values, self._pdb_values)

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "workloads-filters-modal-name-all":
            self._name_selected_values = set(self._name_values)
            self._refresh_name_selection_options()
            self._sync_filter_action_buttons("name", self._name_selected_values, self._name_values)
            return
        if button_id == "workloads-filters-modal-name-clear":
            self._name_selected_values.clear()
            self._refresh_name_selection_options()
            self._sync_filter_action_buttons("name", self._name_selected_values, self._name_values)
            return
        if button_id == "workloads-filters-modal-kind-all":
            self._kind_selected_values = set(self._kind_values)
            self._refresh_kind_selection_options()
            self._sync_filter_action_buttons("kind", self._kind_selected_values, self._kind_values)
            return
        if button_id == "workloads-filters-modal-kind-clear":
            self._kind_selected_values.clear()
            self._refresh_kind_selection_options()
            self._sync_filter_action_buttons("kind", self._kind_selected_values, self._kind_values)
            return
        if button_id == "workloads-filters-modal-helm-release-all":
            self._helm_release_selected_values = set(self._helm_release_values)
            self._refresh_helm_release_selection_options()
            self._sync_filter_action_buttons(
                "helm-release",
                self._helm_release_selected_values,
                self._helm_release_values,
            )
            return
        if button_id == "workloads-filters-modal-helm-release-clear":
            self._helm_release_selected_values.clear()
            self._refresh_helm_release_selection_options()
            self._sync_filter_action_buttons(
                "helm-release",
                self._helm_release_selected_values,
                self._helm_release_values,
            )
            return
        if button_id == "workloads-filters-modal-namespace-all":
            self._namespace_selected_values = set(self._namespace_values)
            self._refresh_namespace_selection_options()
            self._sync_filter_action_buttons(
                "namespace", self._namespace_selected_values, self._namespace_values
            )
            return
        if button_id == "workloads-filters-modal-namespace-clear":
            self._namespace_selected_values.clear()
            self._refresh_namespace_selection_options()
            self._sync_filter_action_buttons(
                "namespace", self._namespace_selected_values, self._namespace_values
            )
            return
        if button_id == "workloads-filters-modal-status-all":
            self._status_selected_values = set(self._status_values)
            self._refresh_status_selection_options()
            self._sync_filter_action_buttons(
                "status", self._status_selected_values, self._status_values
            )
            return
        if button_id == "workloads-filters-modal-status-clear":
            self._status_selected_values.clear()
            self._refresh_status_selection_options()
            self._sync_filter_action_buttons(
                "status", self._status_selected_values, self._status_values
            )
            return
        if button_id == "workloads-filters-modal-pdb-all":
            self._pdb_selected_values = set(self._pdb_values)
            self._refresh_pdb_selection_options()
            self._sync_filter_action_buttons("pdb", self._pdb_selected_values, self._pdb_values)
            return
        if button_id == "workloads-filters-modal-pdb-clear":
            self._pdb_selected_values.clear()
            self._refresh_pdb_selection_options()
            self._sync_filter_action_buttons("pdb", self._pdb_selected_values, self._pdb_values)
            return
        if button_id == "workloads-filters-modal-apply":
            self._apply()
            return
        if button_id == "workloads-filters-modal-cancel":
            self.dismiss(None)

    def _refresh_name_selection_options(self) -> None:
        self._refresh_selection_options(
            "workloads-filters-modal-name-list",
            self._name_options,
            self._name_selected_values,
        )

    def _refresh_kind_selection_options(self) -> None:
        self._refresh_selection_options(
            "workloads-filters-modal-kind-list",
            self._kind_options,
            self._kind_selected_values,
        )

    def _refresh_helm_release_selection_options(self) -> None:
        self._refresh_selection_options(
            "workloads-filters-modal-helm-release-list",
            self._helm_release_options,
            self._helm_release_selected_values,
        )

    def _refresh_namespace_selection_options(self) -> None:
        self._refresh_selection_options(
            "workloads-filters-modal-namespace-list",
            self._namespace_options,
            self._namespace_selected_values,
        )

    def _refresh_status_selection_options(self) -> None:
        self._refresh_selection_options(
            "workloads-filters-modal-status-list",
            self._status_options,
            self._status_selected_values,
        )

    def _refresh_pdb_selection_options(self) -> None:
        self._refresh_selection_options(
            "workloads-filters-modal-pdb-list",
            self._pdb_options,
            self._pdb_selected_values,
        )

    def _refresh_selection_options(
        self,
        list_id: str,
        options: tuple[tuple[str, str], ...],
        selected_values: set[str],
    ) -> None:
        with suppress(Exception):
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
        with suppress(Exception):
            self.query_one(
                f"#workloads-filters-modal-{slug}-all", CustomButton
            ).disabled = total_count == 0 or selected_count >= total_count
        with suppress(Exception):
            self.query_one(
                f"#workloads-filters-modal-{slug}-clear", CustomButton
            ).disabled = selected_count == 0

    def _sync_all_action_buttons(self) -> None:
        self._sync_filter_action_buttons(
            "name",
            self._name_selected_values,
            self._name_values,
        )
        self._sync_filter_action_buttons(
            "kind",
            self._kind_selected_values,
            self._kind_values,
        )
        self._sync_filter_action_buttons(
            "helm-release",
            self._helm_release_selected_values,
            self._helm_release_values,
        )
        self._sync_filter_action_buttons(
            "namespace",
            self._namespace_selected_values,
            self._namespace_values,
        )
        self._sync_filter_action_buttons(
            "status",
            self._status_selected_values,
            self._status_values,
        )
        self._sync_filter_action_buttons(
            "pdb",
            self._pdb_selected_values,
            self._pdb_values,
        )

    def _apply(self) -> None:
        name_values = set(self._name_selected_values)
        if name_values == self._name_values:
            name_values = set()

        kind_values = set(self._kind_selected_values)
        if kind_values == self._kind_values:
            kind_values = set()

        helm_release_values = set(self._helm_release_selected_values)
        if helm_release_values == self._helm_release_values:
            helm_release_values = set()

        namespace_values = set(self._namespace_selected_values)
        if namespace_values == self._namespace_values:
            namespace_values = set()

        status_values = set(self._status_selected_values)
        if status_values == self._status_values:
            status_values = set()

        pdb_values = set(self._pdb_selected_values)
        if pdb_values == self._pdb_values:
            pdb_values = set()

        state: _WorkloadsFilterState = {
            "name_filter_values": name_values,
            "kind_filter_values": kind_values,
            "helm_release_filter_values": helm_release_values,
            "namespace_filter_values": namespace_values,
            "status_filter_values": status_values,
            "pdb_filter_values": pdb_values,
        }
        self.dismiss(state)


class _WorkloadAssignedNodesDetailModal(ModalScreen[None]):
    """Modal showing per-node and per-pod runtime detail for one workload."""

    BINDINGS = [("escape", "cancel", "Close")]
    _DETAIL_TAB_TABLES = "workloads-node-details-tab-tables"
    _DETAIL_TAB_LIVE = "workloads-node-details-tab-live"
    _LIVE_POLL_INTERVAL_SECONDS = 5.0
    _LIVE_HISTORY_LIMIT = 720
    _LIVE_ANIMATION_FRAME_SECONDS = 0.04
    _LIVE_ANIMATION_STEPS = 16

    _NODE_COLUMNS: list[tuple[str, int]] = [
        ("Node", 24),
        ("Group", 20),
        ("Pods", 8),
        ("Node CPU Req %", 12),
        ("Node CPU Lim %", 12),
        ("Node Mem Req %", 12),
        ("Node Mem Lim %", 12),
        ("Node CPU Usage", 20),
        ("Node Mem Usage", 22),
        ("Workload CPU Usage on Node", 24),
        ("Workload Mem Usage on Node", 26),
    ]
    _POD_COLUMNS: list[tuple[str, int]] = [
        ("Namespace", 20),
        ("Pod", 34),
        ("Node", 24),
        ("Phase", 12),
        ("CPU Usage", 16),
        ("Mem Usage", 18),
        ("Node CPU Alloc", 16),
        ("Node Mem Alloc", 18),
        ("Restart Reason", 20),
        ("Exit Code", 10),
    ]

    def __init__(
        self,
        *,
        workload_name: str,
        workload_namespace: str,
        workload_kind: str,
        node_rows: list[tuple[str, ...]],
        pod_rows: list[tuple[str, ...]],
        live_sample_provider: Callable[[], Awaitable[WorkloadLiveUsageSampleInfo]],
    ) -> None:
        super().__init__(classes="workloads-node-details-modal-screen selection-modal-screen")
        self._workload_name = workload_name
        self._workload_namespace = workload_namespace
        self._workload_kind = workload_kind
        self._node_rows = node_rows
        self._pod_rows = pod_rows
        self._live_sample_provider = live_sample_provider
        self._live_polling_enabled = False
        self._live_poll_in_flight = False
        self._live_poll_timer: Any | None = None
        self._live_timestamps: deque[float] = deque(maxlen=self._LIVE_HISTORY_LIMIT)
        self._live_cpu_timestamps: deque[float] = deque(maxlen=self._LIVE_HISTORY_LIMIT)
        self._live_cpu_values: deque[float] = deque(maxlen=self._LIVE_HISTORY_LIMIT)
        self._live_memory_timestamps: deque[float] = deque(maxlen=self._LIVE_HISTORY_LIMIT)
        self._live_memory_values: deque[float] = deque(maxlen=self._LIVE_HISTORY_LIMIT)
        self._live_animation_timer: Any | None = None
        self._live_animation_queue: deque[WorkloadLiveUsageSampleInfo] = deque()
        self._live_animation_active: WorkloadLiveUsageSampleInfo | None = None
        self._live_animation_step = 0
        self._live_animation_cpu_from: float | None = None
        self._live_animation_cpu_to: float | None = None
        self._live_animation_cpu_time_from: float | None = None
        self._live_animation_cpu_time_to: float | None = None
        self._live_animation_memory_from: float | None = None
        self._live_animation_memory_to: float | None = None
        self._live_animation_memory_time_from: float | None = None
        self._live_animation_memory_time_to: float | None = None

    def compose(self) -> ComposeResult:
        with CustomContainer(
            classes="workloads-node-details-modal-shell selection-modal-shell"
        ):
            yield CustomStatic(
                "Resource Usage Details",
                classes="workloads-node-details-modal-title selection-modal-title",
                markup=False,
            )
            yield CustomStatic(
                (
                    f"{self._workload_namespace} / {self._workload_name}"
                    f" ({self._workload_kind})"
                ),
                classes="workloads-node-details-modal-subtitle",
                markup=False,
            )
            yield CustomTabs(
                id="workloads-node-details-tabs",
                tabs=[
                    {"id": self._DETAIL_TAB_TABLES, "label": "Tables"},
                    {"id": self._DETAIL_TAB_LIVE, "label": "Live Plot"},
                ],
                active=self._DETAIL_TAB_TABLES,
                on_change=self._on_detail_tab_changed,
            )
            with ContentSwitcher(
                id="workloads-node-details-content-switcher",
                initial=self._DETAIL_TAB_TABLES,
            ):
                with CustomVertical(
                    id=self._DETAIL_TAB_TABLES,
                    classes="workloads-node-details-modal-tab-pane",
                ):
                    with CustomVertical(classes="workloads-node-details-modal-panel"):
                        yield CustomStatic(
                            "Nodes",
                            classes="workloads-node-details-modal-panel-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomDataTable(
                            id="workloads-node-details-nodes-table",
                            zebra_stripes=True,
                        )
                    with CustomVertical(classes="workloads-node-details-modal-panel"):
                        yield CustomStatic(
                            "Workload Pods",
                            classes="workloads-node-details-modal-panel-title selection-modal-list-title",
                            markup=False,
                        )
                        yield CustomDataTable(
                            id="workloads-node-details-pods-table",
                            zebra_stripes=True,
                        )
                with CustomVertical(
                    id=self._DETAIL_TAB_LIVE,
                    classes="workloads-node-details-modal-tab-pane workloads-node-details-live-pane",
                ):
                    yield CustomStatic(
                        "Paused - open Live Plot tab to start polling.",
                        id="workloads-node-details-live-status",
                        classes="workloads-node-details-live-status",
                        markup=False,
                    )
                    with CustomVertical(classes="workloads-node-details-live-chart-panel"):
                        yield CustomStatic(
                            "Workload CPU Usage (mcores)",
                            classes="workloads-node-details-modal-panel-title selection-modal-list-title",
                            markup=False,
                        )
                        if PlotextPlot is not None:
                            yield PlotextPlot(id="workloads-node-details-cpu-plot")
                        else:
                            yield CustomStatic(
                                "Live plot dependency unavailable: textual-plotext",
                                id="workloads-node-details-cpu-plot-fallback",
                                markup=False,
                            )
                    with CustomVertical(classes="workloads-node-details-live-chart-panel"):
                        yield CustomStatic(
                            "Workload Memory Usage (bytes)",
                            classes="workloads-node-details-modal-panel-title selection-modal-list-title",
                            markup=False,
                        )
                        if PlotextPlot is not None:
                            yield PlotextPlot(id="workloads-node-details-memory-plot")
                        else:
                            yield CustomStatic(
                                "Live plot dependency unavailable: textual-plotext",
                                id="workloads-node-details-memory-plot-fallback",
                                markup=False,
                            )
            with CustomHorizontal(
                classes="workloads-node-details-modal-actions selection-modal-actions"
            ):
                yield CustomButton(
                    "Close",
                    id="workloads-node-details-close",
                    compact=True,
                    classes="selection-modal-action-btn",
                )

    def on_mount(self) -> None:
        self._populate_table(
            table_id="#workloads-node-details-nodes-table",
            columns=self._NODE_COLUMNS,
            rows=self._node_rows,
        )
        self._populate_table(
            table_id="#workloads-node-details-pods-table",
            columns=self._POD_COLUMNS,
            rows=self._pod_rows,
        )
        self._set_live_status("Paused - open Live Plot tab to start polling.")
        self._render_live_plots()
        with suppress(Exception):
            self.query_one("#workloads-node-details-close", CustomButton).focus()

    def _populate_table(
        self,
        *,
        table_id: str,
        columns: list[tuple[str, int]],
        rows: list[tuple[str, ...]],
    ) -> None:
        with suppress(Exception):
            table = self.query_one(table_id, CustomDataTable)
            with table.batch_update():
                table.clear(columns=True)
                for index, (name, _width) in enumerate(columns):
                    table.add_column(name, key=f"col-{index}")
                if rows:
                    table.add_rows(rows)

    def _on_detail_tab_changed(self, tab_id: str) -> None:
        with suppress(Exception):
            self.query_one(
                "#workloads-node-details-content-switcher",
                ContentSwitcher,
            ).current = tab_id
        if tab_id == self._DETAIL_TAB_LIVE:
            self._resume_live_polling()
            return
        self._pause_live_polling()

    def _set_live_status(self, text: str) -> None:
        with suppress(Exception):
            self.query_one(
                "#workloads-node-details-live-status",
                CustomStatic,
            ).update(text)

    def _resume_live_polling(self) -> None:
        if PlotextPlot is None:
            self._set_live_status("Live plot unavailable: install textual-plotext.")
            return
        self._live_polling_enabled = True
        self._set_live_status("Polling every 5s...")
        if self._live_poll_timer is None:
            self._live_poll_timer = self.set_interval(
                self._LIVE_POLL_INTERVAL_SECONDS,
                self._on_live_poll_timer_tick,
            )
        self._on_live_poll_timer_tick()

    def _pause_live_polling(self) -> None:
        self._live_polling_enabled = False
        self._stop_live_animation(clear_queue=True)
        if PlotextPlot is None:
            return
        self._set_live_status("Paused - switch to Live Plot tab to resume.")

    def _stop_live_polling(self) -> None:
        self._live_polling_enabled = False
        self._live_poll_in_flight = False
        self._stop_live_animation(clear_queue=True)
        if self._live_poll_timer is not None:
            with suppress(Exception):
                self._live_poll_timer.stop()
            self._live_poll_timer = None
        with suppress(Exception):
            self.workers.cancel_all()

    def _on_live_poll_timer_tick(self) -> None:
        if not self._live_polling_enabled or self._live_poll_in_flight:
            return
        self._live_poll_in_flight = True
        self.run_worker(
            self._poll_live_sample_worker,
            name="workloads-live-plot-poll",
            exclusive=True,
        )

    async def _poll_live_sample_worker(self) -> None:
        try:
            sample = await self._live_sample_provider()
        except Exception as exc:
            error_text = str(exc)
            self.call_later(lambda: self._on_live_sample_error(error_text))
        else:
            self.call_later(lambda: self._on_live_sample(sample))
        finally:
            self._live_poll_in_flight = False

    def _on_live_sample_error(self, error: str) -> None:
        if not self.is_mounted or not self._live_polling_enabled:
            return
        self._set_live_status(f"Error: {error}")

    def _on_live_sample(self, sample: WorkloadLiveUsageSampleInfo) -> None:
        if not self.is_mounted or not self._live_polling_enabled:
            return
        has_any_metric = (
            sample.workload_cpu_mcores is not None
            or sample.workload_memory_bytes is not None
        )
        if not has_any_metric:
            self._set_live_status(
                "No metrics yet "
                f"({sample.pods_with_metrics}/{sample.pod_count} pods with top data)."
            )
            return

        self._set_live_status(
            "Polling every 5s "
            f"({sample.pods_with_metrics}/{sample.pod_count} pods, "
            f"{sample.nodes_with_metrics}/{sample.node_count} nodes with metrics)."
        )
        self._enqueue_live_sample_for_animation(sample)

    def _enqueue_live_sample_for_animation(
        self,
        sample: WorkloadLiveUsageSampleInfo,
    ) -> None:
        self._live_animation_queue.append(sample)
        if self._live_animation_active is None:
            self._start_next_live_animation()

    def _start_next_live_animation(self) -> None:
        if not self._live_animation_queue:
            self._stop_live_animation(clear_queue=False)
            return

        sample = self._live_animation_queue.popleft()
        self._live_animation_active = sample
        self._live_animation_step = 0

        self._live_animation_cpu_to = sample.workload_cpu_mcores
        self._live_animation_cpu_from = (
            self._live_cpu_values[-1]
            if self._live_cpu_values
            else self._live_animation_cpu_to
        )
        self._live_animation_cpu_time_to = sample.timestamp_epoch
        self._live_animation_cpu_time_from = (
            self._live_cpu_timestamps[-1]
            if self._live_cpu_timestamps
            else self._live_animation_cpu_time_to
        )
        if self._live_animation_cpu_to is None:
            self._live_animation_cpu_from = None
            self._live_animation_cpu_time_from = None
            self._live_animation_cpu_time_to = None

        self._live_animation_memory_to = sample.workload_memory_bytes
        self._live_animation_memory_from = (
            self._live_memory_values[-1]
            if self._live_memory_values
            else self._live_animation_memory_to
        )
        self._live_animation_memory_time_to = sample.timestamp_epoch
        self._live_animation_memory_time_from = (
            self._live_memory_timestamps[-1]
            if self._live_memory_timestamps
            else self._live_animation_memory_time_to
        )
        if self._live_animation_memory_to is None:
            self._live_animation_memory_from = None
            self._live_animation_memory_time_from = None
            self._live_animation_memory_time_to = None

        if self._live_animation_timer is None:
            self._live_animation_timer = self.set_interval(
                self._LIVE_ANIMATION_FRAME_SECONDS,
                self._on_live_animation_tick,
            )
        self._render_active_animation_frame(progress=0.0)

    def _stop_live_animation(self, *, clear_queue: bool) -> None:
        if self._live_animation_timer is not None:
            with suppress(Exception):
                self._live_animation_timer.stop()
            self._live_animation_timer = None
        if clear_queue:
            self._live_animation_queue.clear()
        self._live_animation_active = None
        self._live_animation_step = 0
        self._live_animation_cpu_from = None
        self._live_animation_cpu_to = None
        self._live_animation_cpu_time_from = None
        self._live_animation_cpu_time_to = None
        self._live_animation_memory_from = None
        self._live_animation_memory_to = None
        self._live_animation_memory_time_from = None
        self._live_animation_memory_time_to = None

    def _interpolate(
        self,
        start_value: float,
        end_value: float,
        progress: float,
    ) -> float:
        return start_value + ((end_value - start_value) * progress)

    def _on_live_animation_tick(self) -> None:
        if not self._live_polling_enabled or self._live_animation_active is None:
            return
        self._live_animation_step += 1
        progress = min(
            1.0,
            self._live_animation_step / float(self._LIVE_ANIMATION_STEPS),
        )
        self._render_active_animation_frame(progress=progress)
        if progress < 1.0:
            return
        self._commit_active_animation_sample()
        self._live_animation_active = None
        if self._live_animation_queue:
            self._start_next_live_animation()
            return
        self._stop_live_animation(clear_queue=False)

    def _commit_active_animation_sample(self) -> None:
        sample = self._live_animation_active
        if sample is None:
            return
        self._live_timestamps.append(sample.timestamp_epoch)
        if sample.workload_cpu_mcores is not None:
            self._live_cpu_timestamps.append(sample.timestamp_epoch)
            self._live_cpu_values.append(sample.workload_cpu_mcores)
        if sample.workload_memory_bytes is not None:
            self._live_memory_timestamps.append(sample.timestamp_epoch)
            self._live_memory_values.append(sample.workload_memory_bytes)
        self._render_live_plots()

    def _render_active_animation_frame(self, *, progress: float) -> None:
        cpu_x_values = list(self._live_cpu_timestamps)
        cpu_y_values = list(self._live_cpu_values)
        if (
            self._live_animation_cpu_to is not None
            and self._live_animation_cpu_from is not None
            and self._live_animation_cpu_time_to is not None
            and self._live_animation_cpu_time_from is not None
        ):
            cpu_x_values.append(
                self._interpolate(
                    self._live_animation_cpu_time_from,
                    self._live_animation_cpu_time_to,
                    progress,
                )
            )
            cpu_y_values.append(
                self._interpolate(
                    self._live_animation_cpu_from,
                    self._live_animation_cpu_to,
                    progress,
                )
            )

        memory_x_values = list(self._live_memory_timestamps)
        memory_y_values = list(self._live_memory_values)
        if (
            self._live_animation_memory_to is not None
            and self._live_animation_memory_from is not None
            and self._live_animation_memory_time_to is not None
            and self._live_animation_memory_time_from is not None
        ):
            memory_x_values.append(
                self._interpolate(
                    self._live_animation_memory_time_from,
                    self._live_animation_memory_time_to,
                    progress,
                )
            )
            memory_y_values.append(
                self._interpolate(
                    self._live_animation_memory_from,
                    self._live_animation_memory_to,
                    progress,
                )
            )

        self._render_single_plot(
            plot_id="#workloads-node-details-cpu-plot",
            x_values=cpu_x_values,
            y_values=cpu_y_values,
            title="Workload CPU (mcores)",
            color="cyan",
            y_label="mcores",
        )
        self._render_single_plot(
            plot_id="#workloads-node-details-memory-plot",
            x_values=memory_x_values,
            y_values=memory_y_values,
            title="Workload Memory (bytes)",
            color="magenta",
            y_label="bytes",
        )

    def _render_live_plots(self) -> None:
        self._render_single_plot(
            plot_id="#workloads-node-details-cpu-plot",
            x_values=list(self._live_cpu_timestamps),
            y_values=list(self._live_cpu_values),
            title="Workload CPU (mcores)",
            color="cyan",
            y_label="mcores",
        )
        self._render_single_plot(
            plot_id="#workloads-node-details-memory-plot",
            x_values=list(self._live_memory_timestamps),
            y_values=list(self._live_memory_values),
            title="Workload Memory (bytes)",
            color="magenta",
            y_label="bytes",
        )

    def _render_single_plot(
        self,
        *,
        plot_id: str,
        x_values: list[float],
        y_values: list[float],
        title: str,
        color: str,
        y_label: str,
    ) -> None:
        if PlotextPlot is None:
            return
        with suppress(Exception):
            plot = self.query_one(plot_id, PlotextPlot)
            plt = plot.plt
            plt.clear_data()
            plt.title(title)
            plt.xlabel("time")
            plt.ylabel(y_label)
            if x_values and y_values:
                tick_count = min(6, len(x_values))
                if tick_count > 0:
                    tick_indexes = [round(i * (len(x_values) - 1) / (tick_count - 1)) for i in range(tick_count)] if tick_count > 1 else [0]
                    tick_indexes = sorted(set(tick_indexes))
                    tick_values = [x_values[index] for index in tick_indexes]
                    tick_labels = [
                        datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
                        for timestamp in tick_values
                    ]
                    plt.xticks(tick_values, tick_labels)
                # plotext defaults to a dense marker ("hd"), which renders
                # thick bars in terminal cells. Use a thinner line and overlay
                # explicit sample points so each poll is visible.
                plt.plot(x_values, y_values, color=color, marker="dot")
                plt.scatter(x_values, y_values, color=color, marker="◆")
            plot.refresh()

    def action_cancel(self) -> None:
        self._stop_live_polling()
        self.dismiss(None)

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        if event.button.id == "workloads-node-details-close":
            self._stop_live_polling()
            self.dismiss(None)

    def on_unmount(self) -> None:
        self._stop_live_polling()


class WorkloadsScreen(MainNavigationTabsMixin, WorkerMixin, ScreenNavigator, Screen):
    """Dedicated Workloads screen with charts-style tabbed resource views."""

    BINDINGS = WORKLOADS_SCREEN_BINDINGS
    CSS_PATH = "../../css/screens/workloads_screen.tcss"
    _DOUBLE_SELECT_THRESHOLD_SECONDS = 0.5
    _PARTIAL_REFRESH_DEBOUNCE_SECONDS = 0.12
    _PARTIAL_TABLE_REPAINT_MIN_INTERVAL_SECONDS = 0.6
    _PARTIAL_TABLE_REPAINT_MIN_NEW_ROWS = 40
    _PARTIAL_TABLE_ALWAYS_REPAINT_MAX_ROWS = 120
    _PARTIAL_TABLE_REPAINT_PROGRESS_DIVISOR = 24
    _SEARCH_DEBOUNCE_SECONDS = 0.18
    _RESUME_RELOAD_CHECK_SECONDS = 0.2

    def __init__(self, context: str | None = None) -> None:
        ScreenNavigator.__init__(self, None)
        Screen.__init__(self)
        # Initialize WorkerMixin attrs without invoking its __init__ in MRO.
        self._load_start_time: float | None = None
        self._active_worker_name: str | None = None

        self._cluster_context = context
        self._presenter = WorkloadsPresenter(self)
        self._active_tab_id = TAB_WORKLOADS_ALL
        self._search_query = ""
        self._sort_by = SORT_BY_NAME
        self._sort_desc = False
        self._name_filter_options: tuple[tuple[str, str], ...] = ()
        self._name_filter_values: set[str] = set()
        self._kind_filter_options: tuple[tuple[str, str], ...] = ()
        self._kind_filter_values: set[str] = set()
        self._helm_release_filter_options: tuple[tuple[str, str], ...] = ()
        self._helm_release_filter_values: set[str] = set()
        self._namespace_filter_options: tuple[tuple[str, str], ...] = ()
        self._namespace_filter_values: set[str] = set()
        self._status_filter_options: tuple[tuple[str, str], ...] = ()
        self._status_filter_values: set[str] = set()
        self._pdb_filter_options: tuple[tuple[str, str], ...] = (
            ("With PDB", "with_pdb"),
            ("Without PDB", "without_pdb"),
        )
        self._pdb_filter_values: set[str] = set()
        self._load_progress = 0
        self._partial_refresh_scheduled = False
        self._partial_refresh_timer: object | None = None
        self._last_partial_refresh_at_monotonic: float = 0.0
        self._last_partial_refresh_row_count = 0
        self._reload_on_resume = False
        self._render_on_resume = False
        self._initialized_table_ids: set[str] = set()
        self._table_column_names_by_id: dict[str, tuple[str, ...]] = {}
        self._row_workload_map_by_table: dict[str, dict[int, Any]] = {}
        self._table_content_sig_by_id: dict[str, tuple] = {}
        self._last_streamed_row_count = 0
        self._stream_overlay_released = False
        self._is_loading = False
        self._loading_overlay_failsafe_timer: object | None = None
        self._search_debounce_timer: object | None = None
        self._resume_reload_timer: object | None = None
        self._ignore_next_view_tab_id: str | None = None
        self._last_selected_table_id: str | None = None
        self._last_selected_row: int | None = None
        self._last_selected_row_time = 0.0

    @property
    def context(self) -> str | None:
        """Cluster context used by workload data fetches."""
        return self._cluster_context

    def compose(self) -> ComposeResult:
        yield CustomHeader()
        yield self.compose_main_navigation_tabs(active_tab_id=MAIN_NAV_TAB_WORKLOADS)
        yield CustomVertical(
            CustomHorizontal(
                CustomHorizontal(
                    CustomButton("Refresh", id="workloads-refresh-btn"),
                    id="workloads-top-controls-left",
                ),
                CustomHorizontal(
                    CustomStatic("", id="workloads-loading-spacer", markup=False),
                    CustomHorizontal(
                        ProgressBar(
                            total=100,
                            show_percentage=False,
                            show_eta=False,
                            id="workloads-progress-bar",
                        ),
                        CustomStatic("0% - Idle", id="workloads-loading-text", markup=False),
                        id="workloads-progress-container",
                    ),
                    id="workloads-loading-bar",
                ),
                id="workloads-top-controls-row",
            ),
            CustomHorizontal(
                CustomTabs(
                    id="workloads-view-tabs",
                    tabs=[
                        {"id": tab_id, "label": WORKLOADS_TAB_LABELS[tab_id]}
                        for tab_id in WORKLOADS_TAB_IDS
                    ],
                    active=TAB_WORKLOADS_ALL,
                ),
                id="workloads-view-tabs-row",
            ),
            CustomVertical(
                CustomHorizontal(
                    CustomContainer(
                        CustomStatic("Search", classes="optimizer-filter-group-title"),
                        CustomVertical(
                            CustomHorizontal(
                                CustomInput(
                                    placeholder="Search workloads...",
                                    id="workloads-search-input",
                                ),
                                CustomButton("Search", id="workloads-search-btn"),
                                CustomButton("Clear", id="workloads-clear-btn"),
                                id="workloads-search-row",
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
                                    "Filters",
                                    id="workloads-filter-btn",
                                    classes="filter-picker-btn",
                                ),
                                classes="filter-control",
                            ),
                            id="workloads-filter-selection-row",
                            classes="optimizer-filter-group-body",
                        ),
                        id="workloads-filter-group",
                        classes="optimizer-filter-group",
                    ),
                    CustomContainer(
                        CustomStatic("Sort", classes="optimizer-filter-group-title"),
                        CustomVertical(
                            CustomHorizontal(
                                Select(
                                    [(label, value) for label, value in WORKLOADS_SORT_OPTIONS],
                                    value=SORT_BY_NAME,
                                    allow_blank=False,
                                    id="workloads-sort-select",
                                    classes="filter-select",
                                ),
                                Select(
                                    (("Asc", "asc"), ("Desc", "desc")),
                                    value="asc",
                                    allow_blank=False,
                                    id="workloads-sort-order-select",
                                    classes="filter-select",
                                ),
                                id="workloads-sort-control-row",
                            ),
                            classes="optimizer-filter-group-body",
                        ),
                        classes="optimizer-filter-group",
                    ),
                    id="workloads-filter-row",
                ),
                id="workloads-filter-bar",
            ),
            CustomContainer(
                ContentSwitcher(
                    *(
                        CustomVertical(
                            CustomContainer(
                                CustomDataTable(
                                    id=WORKLOADS_TABLE_ID_BY_TAB[tab_id],
                                    zebra_stripes=True,
                                ),
                                id=f"{WORKLOADS_TABLE_ID_BY_TAB[tab_id]}-container",
                            ),
                            id=tab_id,
                            classes="workloads-tab-pane",
                        )
                        for tab_id in WORKLOADS_TAB_IDS
                    ),
                    id="workloads-content-switcher",
                    initial=TAB_WORKLOADS_ALL,
                ),
                CustomVertical(
                    CustomLoadingIndicator(id="loading-indicator"),
                    CustomStatic("Loading workloads...", id="loading-message", markup=False),
                    id="loading-overlay",
                ),
                id="workloads-table-overlay-container",
            ),
            CustomHorizontal(
                CustomKPI(
                    "Shown",
                    "0/0",
                    id="workloads-kpi-shown",
                    classes="kpi-inline",
                ),
                CustomKPI(
                    "Missing CPU Req",
                    "0",
                    id="workloads-kpi-missing-cpu",
                    classes="kpi-inline",
                ),
                CustomKPI(
                    "Missing Mem Req",
                    "0",
                    id="workloads-kpi-missing-mem",
                    classes="kpi-inline",
                ),
                CustomKPI(
                    "Extreme Ratios",
                    "0",
                    id="workloads-kpi-extreme",
                    classes="kpi-inline",
                ),
                id="workloads-summary-bar",
            ),
            id="workloads-main-shell",
        )
        yield CustomFooter()

    def on_mount(self) -> None:
        self.app.title = "KubEagle - Workloads"
        self._set_primary_navigation_tab(MAIN_NAV_TAB_WORKLOADS)
        self._enable_primary_navigation_tabs()
        self._update_filter_button_label()
        self._configure_tables()
        self.hide_loading_overlay()
        self._set_load_progress(0, "Idle")
        self._start_load_worker(message="Loading workloads...")

    def on_unmount(self) -> None:
        """Cancel all workers and timers when screen is removed from DOM."""
        self._release_background_work_for_navigation()
        with suppress(Exception):
            self.workers.cancel_all()

    def on_screen_resume(self) -> None:
        self.app.title = "KubEagle - Workloads"
        self._set_primary_navigation_tab(MAIN_NAV_TAB_WORKLOADS)
        if self._render_on_resume:
            self._render_on_resume = False
            if not self._presenter.is_loading and self._has_existing_workloads_data():
                # Worker finished while away — just refresh display
                self._refresh_active_tab()
            elif not self._presenter.is_loading:
                # Failed — reload
                self._start_load_worker(message="Loading workloads...")
            # else: still loading, message handler will deliver
        if self._reload_on_resume:
            self._schedule_resume_reload_check(immediate=True)

    def on_screen_suspend(self) -> None:
        self._release_background_work_for_navigation()

    def prepare_for_screen_switch(self) -> None:
        self._release_background_work_for_navigation()

    def _release_background_work_for_navigation(self) -> None:
        self._stop_partial_refresh_timer()
        self._stop_search_debounce_timer()
        self._stop_resume_reload_timer()
        if self._presenter.is_loading:
            # Keep workers alive in background, render on resume if finished.
            self._render_on_resume = True
        if self._is_loading:
            self._is_loading = False
            self._stream_overlay_released = True
            self._stop_loading_overlay_failsafe_timer()
            self.hide_loading_overlay()

    def _start_load_worker(
        self,
        *,
        force_refresh: bool = False,
        message: str = "Loading workloads...",
    ) -> None:
        self._reload_on_resume = False
        self._table_content_sig_by_id.clear()
        self._partial_refresh_scheduled = False
        self._stop_partial_refresh_timer()
        self._stop_resume_reload_timer()
        self._last_partial_refresh_at_monotonic = 0.0
        self._last_partial_refresh_row_count = 0
        self._is_loading = True
        self._last_streamed_row_count = 0
        self._stream_overlay_released = False
        self._set_load_progress(5, message)
        self.show_loading_overlay(message, allow_cached_passthrough=False)
        self._start_loading_overlay_failsafe_timer()
        self.call_later(lambda: self._show_loading_overlay_if_loading(message))
        self._presenter.load_data(force_refresh=force_refresh)

    def _show_loading_overlay_if_loading(self, message: str) -> None:
        if not self._is_loading or self._stream_overlay_released:
            return
        self.show_loading_overlay(message, allow_cached_passthrough=False)

    def _schedule_resume_reload_check(self, *, immediate: bool = False) -> None:
        self._stop_resume_reload_timer()
        delay = 0.0 if immediate else self._RESUME_RELOAD_CHECK_SECONDS
        self._resume_reload_timer = self.set_timer(
            delay,
            self._attempt_reload_on_resume,
        )

    def _attempt_reload_on_resume(self) -> None:
        self._resume_reload_timer = None
        if not self._reload_on_resume or not self.is_current:
            return
        if self._presenter.is_loading:
            self._schedule_resume_reload_check()
            return
        self._reload_on_resume = False
        self._start_load_worker(message="Loading workloads...")

    def _stop_resume_reload_timer(self) -> None:
        timer = self._resume_reload_timer
        self._resume_reload_timer = None
        if timer is None:
            return
        stop = getattr(timer, "stop", None)
        if callable(stop):
            with suppress(Exception):
                stop()

    def _has_existing_workloads_data(self) -> bool:
        if bool(self._presenter.get_all_workloads()):
            return True
        table_id = WORKLOADS_TABLE_ID_BY_TAB.get(self._active_tab_id)
        if not table_id:
            return False
        with suppress(NoMatches):
            table = self.query_one(f"#{table_id}", CustomDataTable)
            return table.row_count > 0
        return False

    def show_loading_overlay(
        self,
        message: str = "Loading...",
        *,
        is_error: bool = False,
        allow_cached_passthrough: bool = True,
    ) -> None:
        """Show table loading overlay, following charts-screen behavior."""
        with suppress(NoMatches):
            overlay = self.query_one("#loading-overlay", CustomVertical)
            if (
                allow_cached_passthrough
                and not is_error
                and self._has_existing_workloads_data()
            ):
                overlay.display = False
                overlay.remove_class("visible")
                return
            overlay.display = True
            overlay.add_class("visible")
            label = self.query_one("#loading-message", CustomStatic)
            label.update(message)
            if is_error:
                label.add_class("error")
            else:
                label.remove_class("error")

    def hide_loading_overlay(self) -> None:
        """Hide table loading overlay."""
        with suppress(NoMatches):
            overlay = self.query_one("#loading-overlay", CustomVertical)
            overlay.display = False
            overlay.remove_class("visible")

    def _start_loading_overlay_failsafe_timer(self) -> None:
        self._stop_loading_overlay_failsafe_timer()

        def _release_overlay_if_stalled() -> None:
            self._loading_overlay_failsafe_timer = None
            if (
                not self.is_current
                or not self._is_loading
                or self._stream_overlay_released
            ):
                return
            self._stream_overlay_released = True
            self.hide_loading_overlay()

        self._loading_overlay_failsafe_timer = self.set_timer(
            12.0,
            _release_overlay_if_stalled,
        )

    def _stop_loading_overlay_failsafe_timer(self) -> None:
        timer = self._loading_overlay_failsafe_timer
        self._loading_overlay_failsafe_timer = None
        if timer is None:
            return
        stop = getattr(timer, "stop", None)
        if callable(stop):
            with suppress(Exception):
                stop()

    def _configure_tables(self) -> None:
        for tab_id in WORKLOADS_TAB_IDS:
            self._init_table_for_tab(tab_id)

    def _init_table_for_tab(self, tab_id: str) -> None:
        """Set up table columns for a tab (lightweight, no data processing)."""
        table_id = WORKLOADS_TABLE_ID_BY_TAB[tab_id]
        columns = self._columns_for_tab(tab_id)
        column_names = tuple(name for name, _width in columns)
        with suppress(NoMatches):
            table = self.query_one(f"#{table_id}", CustomDataTable)
            needs_reconfigure = (
                table_id not in self._initialized_table_ids
                or self._table_column_names_by_id.get(table_id) != column_names
            )
            if needs_reconfigure:
                fixed_columns = 0
                if tab_id == TAB_WORKLOADS_NODE_ANALYSIS and "Mem R/L" in column_names:
                    fixed_columns = column_names.index("Mem R/L") + 1
                with table.batch_update():
                    if table.data_table is not None:
                        table.data_table.fixed_columns = fixed_columns
                    table.clear(columns=True)
                    table.set_header_tooltips(self._tooltips_for_tab(tab_id))
                    if tab_id == TAB_WORKLOADS_NODE_ANALYSIS:
                        table.set_default_tooltip(
                            "Double-click row to open assigned node and pod details"
                        )
                    for index, (name, _) in enumerate(columns):
                        table.add_column(name, key=f"col-{index}")
                    self._initialized_table_ids.add(table_id)
                    self._table_column_names_by_id[table_id] = column_names

    def _schedule_partial_refresh(self) -> None:
        """Debounce frequent partial events to avoid repeated heavy table refreshes."""
        if self._partial_refresh_scheduled:
            return
        self._partial_refresh_scheduled = True
        self._stop_partial_refresh_timer()
        self._partial_refresh_timer = self.set_timer(
            self._PARTIAL_REFRESH_DEBOUNCE_SECONDS,
            self._run_partial_refresh,
        )

    def _run_partial_refresh(self) -> None:
        self._partial_refresh_scheduled = False
        self._partial_refresh_timer = None
        if not self.is_current:
            return
        self._refresh_filter_options()
        self._refresh_active_tab()
        self._mark_partial_table_repaint(len(self._presenter.get_all_workloads()))

    def _stop_partial_refresh_timer(self) -> None:
        timer = self._partial_refresh_timer
        self._partial_refresh_timer = None
        if timer is None:
            return
        stop = getattr(timer, "stop", None)
        if callable(stop):
            with suppress(Exception):
                stop()

    def _mark_partial_table_repaint(self, row_count: int) -> None:
        self._last_partial_refresh_at_monotonic = time.monotonic()
        self._last_partial_refresh_row_count = max(0, int(row_count))

    def _should_schedule_partial_table_repaint(
        self,
        *,
        row_count: int,
        completed: int,
        total: int,
        has_new_rows: bool,
    ) -> bool:
        """Throttle expensive partial table rebuilds while workloads stream in."""
        if row_count <= 0:
            return True
        if row_count <= self._PARTIAL_TABLE_ALWAYS_REPAINT_MAX_ROWS:
            self._mark_partial_table_repaint(row_count)
            return True
        if self._last_partial_refresh_row_count <= 0:
            self._mark_partial_table_repaint(row_count)
            return True

        min_new_rows = max(
            self._PARTIAL_TABLE_REPAINT_MIN_NEW_ROWS,
            row_count // self._PARTIAL_TABLE_REPAINT_PROGRESS_DIVISOR,
        )
        has_growth = (row_count - self._last_partial_refresh_row_count) >= min_new_rows
        elapsed = time.monotonic() - self._last_partial_refresh_at_monotonic
        is_interval_due = elapsed >= self._PARTIAL_TABLE_REPAINT_MIN_INTERVAL_SECONDS
        is_near_completion = total > 0 and completed >= max(1, total - 1)

        should_repaint = has_growth or (has_new_rows and is_interval_due) or is_near_completion
        if should_repaint:
            self._mark_partial_table_repaint(row_count)
        return should_repaint

    def _set_loading_text(self, message: str, *, is_error: bool = False) -> None:
        self._set_load_progress(self._load_progress, message, is_error=is_error)

    def _set_load_progress(
        self,
        progress: int,
        message: str,
        *,
        is_error: bool = False,
    ) -> None:
        self._load_progress = max(0, min(progress, 100))
        with suppress(NoMatches):
            label = self.query_one("#workloads-loading-text", CustomStatic)
            label.update(f"{self._load_progress}% - {message}")
            if is_error:
                label.add_class("status-error")
            else:
                label.remove_class("status-error")
        with suppress(NoMatches):
            self.query_one("#workloads-progress-bar", ProgressBar).update(
                total=100,
                progress=self._load_progress,
            )

    def _update_loading_message(self, message: str) -> None:
        if not self.is_current:
            return
        self._set_loading_text(message)
        with suppress(NoMatches):
            self.query_one("#loading-message", CustomStatic).update(message)

    def _active_view_filter(self) -> str:
        return WORKLOAD_VIEW_FILTER_BY_TAB.get(self._active_tab_id, WORKLOAD_VIEW_ALL)

    def _columns_for_tab(self, tab_id: str) -> list[tuple[str, int]]:
        return WORKLOADS_TABLE_COLUMNS_BY_TAB[tab_id]

    def _tooltips_for_tab(self, tab_id: str) -> dict[str, str]:
        return WORKLOADS_HEADER_TOOLTIPS_BY_TAB[tab_id]

    def _current_filter_kwargs(self) -> _WorkloadsFilterState:
        return {
            "name_filter_values": self._name_filter_values,
            "kind_filter_values": self._kind_filter_values,
            "helm_release_filter_values": self._helm_release_filter_values,
            "namespace_filter_values": self._namespace_filter_values,
            "status_filter_values": self._status_filter_values,
            "pdb_filter_values": self._pdb_filter_values,
        }

    def _refresh_filter_options(self) -> None:
        self._refresh_filter_seq = getattr(self, "_refresh_filter_seq", 0) + 1
        seq = self._refresh_filter_seq
        workloads = self._presenter.get_all_workloads()
        # Capture current selected values and pdb options for the thread.
        prev_name_values = set(self._name_filter_values)
        prev_kind_values = set(self._kind_filter_values)
        prev_helm_release_values = set(self._helm_release_filter_values)
        prev_namespace_values = set(self._namespace_filter_values)
        prev_status_values = set(self._status_filter_values)
        prev_pdb_values = set(self._pdb_filter_values)
        pdb_filter_options = self._pdb_filter_options

        async def _do_refresh() -> None:
            if getattr(self, "_refresh_filter_seq", 0) != seq:
                return

            def _heavy() -> tuple[
                tuple[tuple[str, str], ...],
                tuple[tuple[str, str], ...],
                tuple[tuple[str, str], ...],
                tuple[tuple[str, str], ...],
                tuple[tuple[str, str], ...],
                set[str],
                set[str],
                set[str],
                set[str],
                set[str],
                set[str],
            ]:
                # Single-pass extraction of all filter facets to avoid iterating
                # the workload list 5+ times.
                name_set: set[str] = set()
                kind_set: set[str] = set()
                namespace_set: set[str] = set()
                status_set: set[str] = set()
                with_helm_count = 0
                for workload in workloads:
                    name = str(getattr(workload, "name", "")).strip()
                    if name:
                        name_set.add(name)
                    kind = str(getattr(workload, "kind", "")).strip()
                    if kind:
                        kind_set.add(kind)
                    namespace = str(getattr(workload, "namespace", "")).strip()
                    if namespace:
                        namespace_set.add(namespace)
                    status = str(getattr(workload, "status", "")).strip()
                    if status:
                        status_set.add(status)
                    helm_release = str(getattr(workload, "helm_release", "") or "").strip()
                    if helm_release:
                        with_helm_count += 1
                without_helm_count = len(workloads) - with_helm_count
                names = sorted(name_set)
                kinds = sorted(kind_set)
                namespaces = sorted(namespace_set)
                statuses = sorted(status_set)

                name_opts: tuple[tuple[str, str], ...] = tuple(
                    (value, value) for value in names
                )
                kind_opts: tuple[tuple[str, str], ...] = tuple(
                    (value, value) for value in kinds
                )
                helm_release_opts: tuple[tuple[str, str], ...] = tuple(
                    option
                    for option in (
                        (
                            f"With Helm ({with_helm_count})",
                            "with_helm",
                        )
                        if with_helm_count > 0
                        else None,
                        (
                            f"Without Helm ({without_helm_count})",
                            "without_helm",
                        )
                        if without_helm_count > 0
                        else None,
                    )
                    if option is not None
                )
                namespace_opts: tuple[tuple[str, str], ...] = tuple(
                    (value, value) for value in namespaces
                )
                status_opts: tuple[tuple[str, str], ...] = tuple(
                    (value, value) for value in statuses
                )

                name_vals = {value for _, value in name_opts}
                kind_vals = {value for _, value in kind_opts}
                helm_release_vals = {value for _, value in helm_release_opts}
                namespace_vals = {value for _, value in namespace_opts}
                status_vals = {value for _, value in status_opts}
                pdb_vals = {value for _, value in pdb_filter_options}

                new_name_filter = {
                    value for value in prev_name_values if value in name_vals
                }
                new_kind_filter = {
                    value for value in prev_kind_values if value in kind_vals
                }
                new_helm_release_filter = {
                    value
                    for value in prev_helm_release_values
                    if value in helm_release_vals
                }
                new_namespace_filter = {
                    value for value in prev_namespace_values if value in namespace_vals
                }
                new_status_filter = {
                    value for value in prev_status_values if value in status_vals
                }
                new_pdb_filter = {
                    value for value in prev_pdb_values if value in pdb_vals
                }

                return (
                    name_opts,
                    kind_opts,
                    helm_release_opts,
                    namespace_opts,
                    status_opts,
                    new_name_filter,
                    new_kind_filter,
                    new_helm_release_filter,
                    new_namespace_filter,
                    new_status_filter,
                    new_pdb_filter,
                )

            result = await asyncio.to_thread(_heavy)

            if getattr(self, "_refresh_filter_seq", 0) != seq:
                return

            (
                name_opts,
                kind_opts,
                helm_release_opts,
                namespace_opts,
                status_opts,
                new_name_filter,
                new_kind_filter,
                new_helm_release_filter,
                new_namespace_filter,
                new_status_filter,
                new_pdb_filter,
            ) = result

            # Apply results on the main thread.
            self._name_filter_options = name_opts
            self._kind_filter_options = kind_opts
            self._helm_release_filter_options = helm_release_opts
            self._namespace_filter_options = namespace_opts
            self._status_filter_options = status_opts
            self._name_filter_values = new_name_filter
            self._kind_filter_values = new_kind_filter
            self._helm_release_filter_values = new_helm_release_filter
            self._namespace_filter_values = new_namespace_filter
            self._status_filter_values = new_status_filter
            self._pdb_filter_values = new_pdb_filter
            self._update_filter_button_label()

        self.call_later(_do_refresh)

    def _active_filter_count(self) -> int:
        count = 0
        if self._name_filter_values:
            count += 1
        if self._kind_filter_values:
            count += 1
        if self._helm_release_filter_values:
            count += 1
        if self._namespace_filter_values:
            count += 1
        if self._status_filter_values:
            count += 1
        if self._pdb_filter_values:
            count += 1
        return count

    def _update_filter_button_label(self) -> None:
        active_count = self._active_filter_count()
        label = "Filters" if active_count <= 0 else f"Filters ({active_count})"
        with suppress(NoMatches):
            self.query_one("#workloads-filter-btn", CustomButton).label = label

    def _open_filters_modal(self) -> None:
        modal = _WorkloadsFiltersModal(
            name_options=self._name_filter_options,
            name_selected_values=self._name_filter_values,
            kind_options=self._kind_filter_options,
            kind_selected_values=self._kind_filter_values,
            helm_release_options=self._helm_release_filter_options,
            helm_release_selected_values=self._helm_release_filter_values,
            namespace_options=self._namespace_filter_options,
            namespace_selected_values=self._namespace_filter_values,
            status_options=self._status_filter_options,
            status_selected_values=self._status_filter_values,
            pdb_options=self._pdb_filter_options,
            pdb_selected_values=self._pdb_filter_values,
        )
        self.app.push_screen(modal, self._on_filters_modal_dismissed)

    def _on_filters_modal_dismissed(
        self,
        result: _WorkloadsFilterState | None,
    ) -> None:
        if result is None:
            return

        valid_name_values = {value for _, value in self._name_filter_options}
        selected_name_values = {
            value for value in result["name_filter_values"] if value in valid_name_values
        }
        if selected_name_values == valid_name_values:
            selected_name_values = set()
        self._name_filter_values = selected_name_values

        valid_kind_values = {value for _, value in self._kind_filter_options}
        selected_kind_values = {
            value for value in result["kind_filter_values"] if value in valid_kind_values
        }
        if selected_kind_values == valid_kind_values:
            selected_kind_values = set()
        self._kind_filter_values = selected_kind_values

        valid_helm_release_values = {value for _, value in self._helm_release_filter_options}
        selected_helm_release_values = {
            value
            for value in result["helm_release_filter_values"]
            if value in valid_helm_release_values
        }
        if selected_helm_release_values == valid_helm_release_values:
            selected_helm_release_values = set()
        self._helm_release_filter_values = selected_helm_release_values

        valid_namespace_values = {value for _, value in self._namespace_filter_options}
        selected_namespace_values = {
            value
            for value in result["namespace_filter_values"]
            if value in valid_namespace_values
        }
        if selected_namespace_values == valid_namespace_values:
            selected_namespace_values = set()
        self._namespace_filter_values = selected_namespace_values

        valid_status_values = {value for _, value in self._status_filter_options}
        selected_status_values = {
            value for value in result["status_filter_values"] if value in valid_status_values
        }
        if selected_status_values == valid_status_values:
            selected_status_values = set()
        self._status_filter_values = selected_status_values

        valid_pdb_values = {value for _, value in self._pdb_filter_options}
        selected_pdb_values = {
            value for value in result["pdb_filter_values"] if value in valid_pdb_values
        }
        if selected_pdb_values == valid_pdb_values:
            selected_pdb_values = set()
        self._pdb_filter_values = selected_pdb_values

        self._update_filter_button_label()
        self._refresh_active_tab()

    def _refresh_active_tab(self) -> None:
        self._refresh_active_tab_seq = getattr(self, "_refresh_active_tab_seq", 0) + 1
        seq = self._refresh_active_tab_seq

        # Snapshot all inputs on the main thread so the worker sees a
        # consistent view even if the user changes filters/search/sort
        # while the background computation is in progress.
        filter_kwargs = self._current_filter_kwargs()
        active_view_filter = self._active_view_filter()
        has_search = bool(self._search_query)
        search_query = self._search_query
        sort_by = self._sort_by
        sort_desc = self._sort_desc
        active_tab_id = self._active_tab_id
        presenter = self._presenter
        columns = self._columns_for_tab(active_tab_id)

        async def _do_refresh() -> None:
            if getattr(self, "_refresh_active_tab_seq", 0) != seq:
                return

            def _heavy() -> tuple[
                list[Any],
                int,
                dict[str, Any],
                list[Any],
                list[tuple[str, int]],
                tuple[Any, ...],
            ]:
                filtered = presenter.get_filtered_workloads(
                    workload_view_filter=active_view_filter,
                    search_query=search_query,
                    sort_by=sort_by,
                    descending=sort_desc,
                    **filter_kwargs,
                )
                if has_search:
                    scoped = presenter.get_scoped_workload_count(
                        workload_view_filter=active_view_filter,
                        **filter_kwargs,
                    )
                else:
                    scoped = len(filtered)
                summary = presenter.build_resource_summary_from_filtered(
                    filtered_workloads=filtered,
                    scoped_total=scoped,
                )
                rows = presenter.format_workload_rows(filtered, columns=columns)
                column_names = tuple(name for name, _width in columns)
                content_sig = (
                    len(filtered),
                    tuple(
                        (
                            str(getattr(w, "namespace", "") or ""),
                            str(getattr(w, "kind", "") or ""),
                            str(getattr(w, "name", "") or ""),
                        )
                        for w in filtered
                    ),
                    column_names,
                    sort_by,
                    sort_desc,
                )
                return filtered, scoped, summary, rows, columns, content_sig

            result = await asyncio.to_thread(_heavy)

            if getattr(self, "_refresh_active_tab_seq", 0) != seq:
                return

            filtered, scoped, summary, rows, cols, content_sig = result

            # Apply UI updates on main thread.
            self._apply_summary(summary)
            self._apply_table(active_tab_id, filtered, rows, cols, content_sig)

        self.call_later(_do_refresh)

    def _apply_summary(self, summary: dict[str, Any]) -> None:
        """Apply a pre-computed resource summary to the KPI widgets."""
        missing_cpu = summary.get("missing_cpu_request", "0")
        missing_mem = summary.get("missing_memory_request", "0")
        extreme = summary.get("extreme_ratios", "0")
        missing_cpu_count = int(missing_cpu)
        missing_mem_count = int(missing_mem)
        extreme_count = int(extreme)
        shown_total = summary.get("shown_total", "0/0")

        self._set_kpi("workloads-kpi-shown", shown_total, status="success")
        self._set_kpi(
            "workloads-kpi-missing-cpu",
            missing_cpu,
            status="error" if missing_cpu_count > 0 else "success",
        )
        self._set_kpi(
            "workloads-kpi-missing-mem",
            missing_mem,
            status="error" if missing_mem_count > 0 else "success",
        )
        self._set_kpi(
            "workloads-kpi-extreme",
            extreme,
            status="warning" if extreme_count > 0 else "success",
        )

    def _set_kpi(self, kpi_id: str, value: str, *, status: str) -> None:
        with suppress(NoMatches):
            kpi = self.query_one(f"#{kpi_id}", CustomKPI)
            kpi.set_value(value)
            kpi.set_status(status)

    @staticmethod
    def _workload_identity_key(workload: Any) -> tuple[str, str, str]:
        return (
            str(getattr(workload, "namespace", "") or ""),
            str(getattr(workload, "kind", "") or ""),
            str(getattr(workload, "name", "") or ""),
        )

    def _apply_table(
        self,
        tab_id: str,
        filtered_workloads: list[Any],
        rows: list[Any],
        columns: list[tuple[str, int]],
        content_sig: tuple[Any, ...],
    ) -> None:
        """Apply pre-computed rows/columns to the table widget (main thread)."""
        table_id = WORKLOADS_TABLE_ID_BY_TAB[tab_id]
        column_names = tuple(name for name, _width in columns)

        # Skip the expensive clear+rebuild if the table already shows the same rows.
        if (
            table_id in self._initialized_table_ids
            and content_sig == self._table_content_sig_by_id.get(table_id)
        ):
            return

        selected_identity: tuple[str, str, str] | None = None
        previous_row_workload_map = self._row_workload_map_by_table.get(table_id, {})
        row_workload_map = dict(enumerate(filtered_workloads))
        self._row_workload_map_by_table[table_id] = row_workload_map

        with suppress(NoMatches):
            table = self.query_one(f"#{table_id}", CustomDataTable)
            previous_selected_row = table.cursor_row
            if isinstance(previous_selected_row, int) and previous_selected_row >= 0:
                previous_selected_workload = previous_row_workload_map.get(previous_selected_row)
                if previous_selected_workload is not None:
                    selected_identity = self._workload_identity_key(previous_selected_workload)

            identity_to_index: dict[tuple[str, str, str], int] = {}
            for index, workload in row_workload_map.items():
                identity_key = self._workload_identity_key(workload)
                if identity_key not in identity_to_index:
                    identity_to_index[identity_key] = index

            needs_reconfigure = (
                table_id not in self._initialized_table_ids
                or self._table_column_names_by_id.get(table_id) != column_names
            )
            fixed_columns = 0
            if tab_id == TAB_WORKLOADS_NODE_ANALYSIS and "Mem R/L" in column_names:
                fixed_columns = column_names.index("Mem R/L") + 1
            with table.batch_update():
                if table.data_table is not None:
                    table.data_table.fixed_columns = fixed_columns
                if needs_reconfigure:
                    table.clear(columns=True)
                    table.set_header_tooltips(self._tooltips_for_tab(tab_id))
                    if tab_id == TAB_WORKLOADS_NODE_ANALYSIS:
                        table.set_default_tooltip(
                            "Double-click row to open assigned node and pod details"
                        )
                    for index, (name, _) in enumerate(columns):
                        table.add_column(name, key=f"col-{index}")
                    self._initialized_table_ids.add(table_id)
                    self._table_column_names_by_id[table_id] = column_names
                else:
                    table.clear(columns=False)
                if rows:
                    table.add_rows(rows)
            self._table_content_sig_by_id[table_id] = content_sig
            if selected_identity is not None:
                restored_index = identity_to_index.get(selected_identity)
                if restored_index is not None:
                    table.cursor_row = restored_index

    def _set_active_tab(self, tab_id: str) -> None:
        if tab_id not in WORKLOADS_TAB_IDS:
            return
        self._active_tab_id = tab_id
        with suppress(NoMatches):
            tabs = self.query_one("#workloads-view-tabs", CustomTabs)
            if tabs.active != tab_id:
                self._ignore_next_view_tab_id = tab_id
                tabs.active = tab_id
        with suppress(NoMatches):
            self.query_one("#workloads-content-switcher", ContentSwitcher).current = tab_id
        # Defer table rebuild so the tab switch renders immediately
        self.call_later(self._refresh_active_tab)

    @on(CustomTabs.TabActivated, "#workloads-view-tabs")
    def _on_view_tab_activated(self, event: CustomTabs.TabActivated) -> None:
        tab_id = str(event.tab.id) if event.tab.id else ""
        if tab_id and tab_id == self._ignore_next_view_tab_id:
            self._ignore_next_view_tab_id = None
            return
        if tab_id:
            self._set_active_tab(tab_id)

    @on(Select.Changed, "#workloads-sort-select")
    def _on_sort_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self._sort_by = str(event.value)
        self._refresh_active_tab()

    @on(Select.Changed, "#workloads-sort-order-select")
    def _on_sort_order_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self._sort_desc = str(event.value) == "desc"
        self._refresh_active_tab()

    def on_input_changed(self, event: CustomInput.Changed) -> None:
        if event.input.id != "workloads-search-input":
            return
        self._search_query = event.value.strip()
        self._schedule_search_refresh()

    def on_input_submitted(self, event: CustomInput.Submitted) -> None:
        if event.input.id != "workloads-search-input":
            return
        self._search_query = event.value.strip()
        self._apply_search_refresh(immediate=True)

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "workloads-refresh-btn":
            self.action_refresh()
            return
        if button_id == "workloads-search-btn":
            with suppress(NoMatches):
                value = self.query_one("#workloads-search-input", CustomInput).value
                self._search_query = value.strip()
            self._apply_search_refresh(immediate=True)
            return
        if button_id == "workloads-filter-btn":
            self._open_filters_modal()
            return
        if button_id == "workloads-clear-btn":
            self._search_query = ""
            with suppress(NoMatches):
                self.query_one("#workloads-search-input", CustomInput).value = ""
            self._apply_search_refresh(immediate=True)
            return

    def _schedule_search_refresh(self) -> None:
        self._stop_search_debounce_timer()
        self._search_debounce_timer = self.set_timer(
            self._SEARCH_DEBOUNCE_SECONDS,
            self._run_debounced_search_refresh,
        )

    def _run_debounced_search_refresh(self) -> None:
        self._search_debounce_timer = None
        if not self.is_current:
            return
        self._refresh_active_tab()

    def _apply_search_refresh(self, *, immediate: bool = False) -> None:
        self._stop_search_debounce_timer()
        if immediate:
            self._refresh_active_tab()
            return
        self._schedule_search_refresh()

    def _stop_search_debounce_timer(self) -> None:
        timer = self._search_debounce_timer
        self._search_debounce_timer = None
        if timer is None:
            return
        stop = getattr(timer, "stop", None)
        if callable(stop):
            with suppress(Exception):
                stop()

    def _open_node_details_modal(self, workload: Any) -> None:
        node_rows = self._presenter.get_assigned_node_detail_rows(workload)
        pod_rows = self._presenter.get_assigned_pod_detail_rows(workload)
        if not node_rows and not pod_rows:
            self.notify(
                "No assigned node or pod metrics available for this workload.",
                severity="warning",
            )
            return
        modal = _WorkloadAssignedNodesDetailModal(
            workload_name=str(getattr(workload, "name", "")),
            workload_namespace=str(getattr(workload, "namespace", "")),
            workload_kind=str(getattr(workload, "kind", "")),
            node_rows=node_rows,
            pod_rows=pod_rows,
            live_sample_provider=lambda: self._presenter.fetch_live_usage_sample(workload),
        )
        self.app.push_screen(modal)

    def on_data_table_row_selected(self, event: object) -> None:
        if self._active_tab_id != TAB_WORKLOADS_NODE_ANALYSIS:
            return

        node_table_id = WORKLOADS_TABLE_ID_BY_TAB[TAB_WORKLOADS_NODE_ANALYSIS]
        event_obj = cast(Any, event)
        event_table = getattr(event_obj, "data_table", None)
        event_table_id = str(getattr(event_table, "id", "") or "")
        if event_table_id and event_table_id != node_table_id:
            return

        row_index = getattr(event_obj, "cursor_row", None)
        if not isinstance(row_index, int):
            with suppress(NoMatches):
                row_index = self.query_one(
                    f"#{node_table_id}",
                    CustomDataTable,
                ).cursor_row
        if not isinstance(row_index, int) or row_index < 0:
            return

        workload = self._row_workload_map_by_table.get(node_table_id, {}).get(row_index)
        if workload is None:
            return

        now = time.monotonic()
        is_double_select = (
            self._last_selected_table_id == node_table_id
            and self._last_selected_row == row_index
            and (now - self._last_selected_row_time) <= self._DOUBLE_SELECT_THRESHOLD_SECONDS
        )
        self._last_selected_table_id = node_table_id
        self._last_selected_row = row_index
        self._last_selected_row_time = now

        if is_double_select:
            self._open_node_details_modal(workload)

    def on_workloads_source_loaded(self, event: WorkloadsSourceLoaded) -> None:
        if not self.is_current:
            return
        if event.total and event.completed:
            progress = 10 + int((event.completed / event.total) * 80)
            self._set_load_progress(
                max(self._load_progress, min(progress, 95)),
                f"Loading workloads ({event.completed}/{event.total})...",
            )
        if (
            not self._stream_overlay_released
            and int(event.completed or 0) > 0
        ):
            self.hide_loading_overlay()
            self._stream_overlay_released = True
            self._stop_loading_overlay_failsafe_timer()
        row_count = int(event.row_count or 0)
        has_new_rows = bool(event.has_new_rows and row_count > self._last_streamed_row_count)
        if has_new_rows:
            first_streamed_rows = self._last_streamed_row_count <= 0
            self._last_streamed_row_count = row_count
            if first_streamed_rows:
                self._refresh_filter_options()
                self._refresh_active_tab()
                self._mark_partial_table_repaint(row_count)
                return
        if self._should_schedule_partial_table_repaint(
            row_count=row_count,
            completed=int(event.completed or 0),
            total=int(event.total or 0),
            has_new_rows=has_new_rows,
        ):
            self._schedule_partial_refresh()

    def on_workloads_data_loaded(self, _: WorkloadsDataLoaded) -> None:
        self._is_loading = False
        self._partial_refresh_scheduled = False
        self._stop_partial_refresh_timer()
        self._stream_overlay_released = True
        self._stop_loading_overlay_failsafe_timer()
        self.hide_loading_overlay()
        total_rows = len(self._presenter.get_all_workloads())
        self._set_load_progress(100, f"Loaded {total_rows} workload(s)")
        self._refresh_filter_options()
        self._refresh_active_tab()
        self._mark_partial_table_repaint(total_rows)
        if self._presenter.partial_errors:
            failed_sources = ", ".join(sorted(self._presenter.partial_errors.keys()))
            self.notify(
                f"Some sources are unavailable: {failed_sources}",
                severity="warning",
            )

    def on_workloads_data_load_failed(self, event: WorkloadsDataLoadFailed) -> None:
        self._is_loading = False
        self._partial_refresh_scheduled = False
        self._stop_partial_refresh_timer()
        self._stop_loading_overlay_failsafe_timer()
        self.show_loading_overlay(event.error, is_error=True, allow_cached_passthrough=False)
        self._set_load_progress(
            max(self._load_progress, 10),
            "Failed to load workloads data - Press Retry",
            is_error=True,
        )
        self.notify(event.error, severity="error")

    def action_refresh(self) -> None:
        self._start_load_worker(
            force_refresh=True,
            message="Refreshing workloads...",
        )

    def action_focus_search(self) -> None:
        self.set_timer(
            0.05,
            lambda: self.query_one("#workloads-search-input", CustomInput).focus(),
        )

    def _switch_tab(self, tab_index: int) -> None:
        if tab_index < 1 or tab_index > len(WORKLOADS_TAB_IDS):
            return
        self._set_active_tab(WORKLOADS_TAB_IDS[tab_index - 1])

    def action_switch_tab_1(self) -> None:
        self._switch_tab(1)

    def action_switch_tab_2(self) -> None:
        self._switch_tab(2)

    def action_switch_tab_3(self) -> None:
        self._switch_tab(3)

    def action_switch_tab_4(self) -> None:
        self._switch_tab(4)

    def action_switch_tab_5(self) -> None:
        self._switch_tab(5)
