"""Recommendations view component - tree + details panel.

Handles recommendations-specific UI:
- KPI summary row
- Search
- Dropdown filter/sort controls
- Recommendations tree
- Details panel
- Loading overlay
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, cast

from rich.markup import escape
from textual import on
from textual.app import ComposeResult
from textual.events import Click, Resize
from textual.screen import ModalScreen
from textual.timer import Timer

from kubeagle.screens.detail.components.fix_details_modal import (
    FixDetailsModal,
)
from kubeagle.screens.detail.presenter import (
    REC_SEVERITY_FILTERS,
)
from kubeagle.widgets import (
    CustomButton,
    CustomContainer,
    CustomHorizontal,
    CustomInput,
    CustomKPI,
    CustomLoadingIndicator,
    CustomMarkdownViewer as TextualMarkdownViewer,
    CustomSelect as Select,
    CustomSelectionList,
    CustomStatic,
    CustomTree,
    CustomVertical,
)

logger = logging.getLogger(__name__)


def _prefixed_option(prefix: str, label: str) -> str:
    return f"{prefix}: {label}"


SORT_SELECT_OPTIONS: list[tuple[str, str]] = [
    (_prefixed_option("Sort", "Severity"), "severity"),
    (_prefixed_option("Sort", "Category"), "category"),
    (_prefixed_option("Sort", "Title"), "title"),
]
SORT_ORDER_OPTIONS: list[tuple[str, str]] = [
    ("Asc", "asc"),
    ("Desc", "desc"),
]
VIEW_SELECT_OPTIONS: list[tuple[str, str]] = [
    (_prefixed_option("View", "Optimizer"), "violations"),
    (_prefixed_option("View", "Recommendations"), "recommendations"),
]


class _RecommendationFilterSelectionModal(ModalScreen[set[str] | None]):
    """Modal for multi-selecting recommendation filter values."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    _DIALOG_MIN_WIDTH = 44
    _DIALOG_MAX_WIDTH = 76
    _DIALOG_MIN_HEIGHT = 26
    _DIALOG_MAX_HEIGHT = 30
    _VISIBLE_ROWS_MIN = 4
    _VISIBLE_ROWS_MAX = 14
    _COMPACT_ACTIONS_MAX_WIDTH = 52
    _OPTION_RENDER_PADDING = 18

    def __init__(
        self,
        title: str,
        options: tuple[tuple[str, str], ...],
        selected_values: set[str],
    ) -> None:
        super().__init__(classes="viol-filter-modal-screen selection-modal-screen")
        self._title = title
        self._all_options = options
        self._all_values = {value for _, value in options}
        self._selected_values = {
            value for value in selected_values if value in self._all_values
        }
        self._visible_option_values: set[str] = set()
        self._search_query = ""

    def compose(self) -> ComposeResult:
        with CustomContainer(
            classes="viol-filter-modal-shell selection-modal-shell"
        ):
            yield CustomStatic(
                self._title,
                classes="viol-filter-modal-title selection-modal-title",
                markup=False,
            )
            yield CustomStatic(
                "",
                id="viol-filter-modal-summary",
                classes="viol-filter-modal-summary selection-modal-summary",
                markup=False,
            )
            yield CustomInput(
                placeholder="Search values...",
                id="viol-filter-modal-search",
                classes="viol-filter-modal-search selection-modal-search",
            )
            with CustomContainer(
                classes="viol-filter-modal-list-wrap selection-modal-list-wrap"
            ):
                yield CustomSelectionList[str](
                    id="viol-filter-modal-list",
                    classes="viol-filter-modal-list selection-modal-list",
                )
                yield CustomStatic(
                    "No matching values",
                    id="viol-filter-modal-empty",
                    classes="viol-filter-modal-empty selection-modal-empty hidden",
                    markup=False,
                )
            with CustomHorizontal(
                classes="viol-filter-modal-actions selection-modal-actions"
            ):
                yield CustomButton(
                    "Select All",
                    id="viol-filter-modal-select-all",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Clear",
                    id="viol-filter-modal-clear",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Apply",
                    variant="primary",
                    id="viol-filter-modal-apply",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Cancel",
                    id="viol-filter-modal-cancel",
                    compact=True,
                    classes="selection-modal-action-btn",
                )

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        self._refresh_selection_options()
        self._sync_action_buttons()
        with contextlib.suppress(Exception):
            search_input = self.query_one("#viol-filter-modal-search", CustomInput)
            search_input.input.focus()

    def on_resize(self, _: Resize) -> None:
        self._apply_dynamic_layout()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_custom_input_changed(self, event: CustomInput.Changed) -> None:
        if event.input.id != "viol-filter-modal-search":
            return
        self._search_query = event.value.strip().lower()
        self._refresh_selection_options()

    def on_selection_list_selected_changed(
        self,
        event: object,
    ) -> None:
        event_obj = cast(Any, event)
        control = getattr(event_obj, "control", None)
        visible_selected_values = {
            str(value) for value in getattr(control, "selected", [])
        }
        self._selected_values.difference_update(self._visible_option_values)
        self._selected_values.update(visible_selected_values)
        self._update_selection_summary()
        self._sync_action_buttons()

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "viol-filter-modal-select-all":
            self._selected_values = set(self._all_values)
            self._refresh_selection_options()
            self._sync_action_buttons()
            return
        if button_id == "viol-filter-modal-clear":
            self._selected_values.clear()
            self._refresh_selection_options()
            self._sync_action_buttons()
            return
        if button_id == "viol-filter-modal-apply":
            selected_values = set(self._selected_values)
            if selected_values == self._all_values:
                selected_values = set()
            self.dismiss(selected_values)
            return
        if button_id == "viol-filter-modal-cancel":
            self.dismiss(None)

    def _refresh_selection_options(self) -> None:
        visible_options = self._visible_options()
        self._visible_option_values = {value for _, value in visible_options}
        with contextlib.suppress(Exception):
            selection_list = self.query_one(
                "#viol-filter-modal-list", CustomSelectionList
            )
            if selection_list.selection_list is not None:
                selection_list.selection_list.clear_options()
                selection_list.selection_list.add_options(
                    [
                        (label, value, value in self._selected_values)
                        for label, value in visible_options
                    ]
                )
        with contextlib.suppress(Exception):
            empty_state = self.query_one("#viol-filter-modal-empty", CustomStatic)
            if visible_options:
                empty_state.add_class("hidden")
            else:
                empty_state.remove_class("hidden")
        self._update_selection_summary()

    def _visible_options(self) -> tuple[tuple[str, str], ...]:
        if not self._search_query:
            return self._all_options
        return tuple(
            (label, value)
            for label, value in self._all_options
            if self._search_query in label.lower()
        )

    def _sync_action_buttons(self) -> None:
        selected_count = len(self._selected_values)
        total_count = len(self._all_values)
        with contextlib.suppress(Exception):
            self.query_one(
                "#viol-filter-modal-select-all", CustomButton
            ).disabled = total_count == 0 or selected_count >= total_count
        with contextlib.suppress(Exception):
            self.query_one(
                "#viol-filter-modal-clear", CustomButton
            ).disabled = selected_count == 0

    def _update_selection_summary(self) -> None:
        total = len(self._all_values)
        selected_count = len(self._selected_values)
        if selected_count == 0 or selected_count == total:
            summary = f"All values ({total})"
        else:
            summary = f"{selected_count} of {total} selected"
        with contextlib.suppress(Exception):
            self.query_one("#viol-filter-modal-summary", CustomStatic).update(summary)

    def _apply_dynamic_layout(self) -> None:
        button_ids = [
            "viol-filter-modal-select-all",
            "viol-filter-modal-clear",
            "viol-filter-modal-apply",
            "viol-filter-modal-cancel",
        ]
        for button_id in button_ids:
            with contextlib.suppress(Exception):
                button = self.query_one(f"#{button_id}", CustomButton)
                button.styles.width = "1fr"
                button.styles.min_width = "0"
                button.styles.max_width = "100%"

        total_values = len(self._all_values)
        summary_all = f"All values ({total_values})"
        summary_partial = f"{total_values} of {total_values} selected"
        title_width = len(self._title)
        longest_option = max((len(label) for label, _ in self._all_options), default=0)
        target_width = max(
            title_width + 8,
            len("Search values...") + 8,
            len(summary_all) + 8,
            len(summary_partial) + 8,
            longest_option + self._OPTION_RENDER_PADDING,
            self._DIALOG_MIN_WIDTH,
        )

        available_width = max(
            24,
            getattr(self.app.size, "width", self._DIALOG_MIN_WIDTH + 6) - 4,
        )
        max_width = min(self._DIALOG_MAX_WIDTH, available_width)
        min_width = min(self._DIALOG_MIN_WIDTH, max_width)
        dialog_width = max(min_width, min(target_width, max_width))
        dialog_width_value = str(dialog_width)
        compact_actions = dialog_width <= self._COMPACT_ACTIONS_MAX_WIDTH

        with contextlib.suppress(Exception):
            select_all_btn = self.query_one(
                "#viol-filter-modal-select-all",
                CustomButton,
            )
            select_all_btn.label = "All" if compact_actions else "Select All"
        with contextlib.suppress(Exception):
            search_input = self.query_one("#viol-filter-modal-search", CustomInput)
            search_input.styles.height = "3"
            search_input.styles.min_height = "3"
            search_input.styles.max_height = "3"
            search_input.styles.width = "1fr"
            search_input.styles.min_width = "0"
            search_input.styles.max_width = "100%"

        visible_rows = min(
            max(len(self._all_options), self._VISIBLE_ROWS_MIN),
            self._VISIBLE_ROWS_MAX,
        )
        # Title + summary + input + action row + shell spacing.
        target_height = visible_rows + 12
        available_height = max(
            10,
            getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT) - 2,
        )
        max_height = min(self._DIALOG_MAX_HEIGHT, available_height)
        dialog_min_height = min(self._DIALOG_MIN_HEIGHT, max_height)
        dialog_max_height = max(dialog_min_height, min(target_height, max_height))
        dialog_min_height_value = str(dialog_min_height)
        dialog_max_height_value = str(dialog_max_height)
        with contextlib.suppress(Exception):
            shell = self.query_one(".viol-filter-modal-shell", CustomContainer)
            shell.styles.width = dialog_width_value
            shell.styles.min_width = dialog_width_value
            shell.styles.max_width = dialog_width_value
            shell.styles.height = dialog_max_height_value
            shell.styles.min_height = dialog_min_height_value
            shell.styles.max_height = dialog_max_height_value


class RecommendationsView(CustomVertical):
    """Recommendations tree + details panel."""
    _ULTRA_MIN_WIDTH = 205
    _WIDE_MIN_WIDTH = 175
    _MEDIUM_MIN_WIDTH = 100
    _RESIZE_DEBOUNCE_SECONDS = 0.08

    def __init__(self, embedded: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._embedded = embedded
        self.all_recommendations: list[dict[str, Any]] = []
        self._loaded_charts: list[Any] = []
        self.selected_recommendation: dict[str, Any] | None = None
        self._filter_options: dict[str, list[tuple[str, str]]] = {}
        self.sort_by: str = "severity"
        self.sort_order: str = "asc"
        self.category_filter: set[str] = set()
        self.severity_filter: set[str] = set()
        self._search_query: str = ""
        self._search_debounce_timer: Timer | None = None
        self._resize_debounce_timer: Timer | None = None
        self._is_loading: bool = True
        self._layout_mode: str | None = None
        self._external_search_query: str = ""
        self._external_category_filter: set[str] = set()
        self._external_severity_filter: set[str] = set()

    def compose(self) -> ComposeResult:
        # Main content area
        yield CustomContainer(
            CustomVertical(
                CustomHorizontal(
                    CustomContainer(
                        CustomStatic("Page", classes="optimizer-filter-group-title"),
                        CustomHorizontal(
                            CustomVertical(
                                Select(
                                    VIEW_SELECT_OPTIONS,
                                    value="recommendations",
                                    allow_blank=False,
                                    id="rec-view-select",
                                    classes="filter-select",
                                ),
                                id="rec-view-control",
                                classes="filter-control",
                            ),
                            classes="optimizer-filter-group-body",
                        ),
                        id="rec-view-group",
                        classes="optimizer-filter-group",
                    ),
                    CustomContainer(
                        CustomStatic("Search", classes="optimizer-filter-group-title"),
                        CustomHorizontal(
                            CustomVertical(
                                CustomHorizontal(
                                    CustomInput(
                                        placeholder="Search recommendations...",
                                        id="rec-search-input",
                                    ),
                                    CustomButton("Search", id="rec-search-btn"),
                                    CustomButton("Clear", id="rec-clear-search-btn"),
                                    id="rec-search-row",
                                ),
                                id="rec-search-control",
                                classes="filter-control",
                            ),
                            classes="optimizer-filter-group-body",
                        ),
                        id="rec-search-group",
                        classes="optimizer-filter-group",
                    ),
                    CustomContainer(
                        CustomStatic("Filter", classes="optimizer-filter-group-title"),
                        CustomHorizontal(
                            CustomHorizontal(
                                CustomVertical(
                                    CustomButton(
                                        "Severity",
                                        id="rec-severity-filter-btn",
                                        classes="filter-picker-btn cluster-tab-filter-trigger",
                                    ),
                                    id="rec-severity-control",
                                    classes="filter-control",
                                ),
                                CustomVertical(
                                    CustomButton(
                                        "Category",
                                        id="rec-category-filter-btn",
                                        classes="filter-picker-btn cluster-tab-filter-trigger",
                                    ),
                                    id="rec-category-control",
                                    classes="filter-control",
                                ),
                                id="rec-filter-selection-row",
                                classes="cluster-tab-filters-row",
                            ),
                            classes="optimizer-filter-group-body",
                        ),
                        id="rec-filter-group",
                        classes="optimizer-filter-group",
                    ),
                    CustomContainer(
                        CustomStatic("Sort", classes="optimizer-filter-group-title"),
                        CustomHorizontal(
                            CustomVertical(
                                CustomHorizontal(
                                    Select(
                                        SORT_SELECT_OPTIONS,
                                        value=self.sort_by,
                                        allow_blank=False,
                                        id="rec-sort-select",
                                        classes="filter-select cluster-tab-control-select cluster-tab-sort",
                                    ),
                                    Select(
                                        SORT_ORDER_OPTIONS,
                                        value=self.sort_order,
                                        allow_blank=False,
                                        id="rec-order-select",
                                        classes="filter-select cluster-tab-control-select cluster-tab-order",
                                    ),
                                    id="rec-sort-control-row",
                                    classes="cluster-tab-sort-controls",
                                ),
                                id="rec-sort-control",
                                classes="filter-control",
                            ),
                            classes="optimizer-filter-group-body",
                        ),
                        id="rec-sort-group",
                        classes="optimizer-filter-group",
                    ),
                    id="rec-filter-row",
                ),
                id="rec-filter-bar",
            ),
            # Split content row: recommendation list + preview details
            CustomHorizontal(
                CustomContainer(
                    CustomContainer(
                        CustomTree("Recommendations", id="rec-recommendations-tree"),
                        CustomStatic(
                            "[dim]Loading recommendations...[/dim]",
                            id="rec-empty-state",
                            classes="empty-state",
                        ),
                        CustomContainer(
                            CustomVertical(
                                CustomLoadingIndicator(id="rec-loading-indicator"),
                                CustomStatic("Loading recommendations...", id="rec-loading-message"),
                                id="rec-loading-row",
                            ),
                            id="rec-loading-overlay",
                        ),
                        id="rec-list-body",
                    ),
                    CustomHorizontal(
                        CustomKPI(
                            "Critical",
                            "0",
                            status="error",
                            id="rec-kpi-critical",
                            classes="kpi-inline",
                        ),
                        CustomKPI(
                            "Warning",
                            "0",
                            status="warning",
                            id="rec-kpi-warning",
                            classes="kpi-inline",
                        ),
                        CustomKPI(
                            "Info",
                            "0",
                            status="info",
                            id="rec-kpi-info",
                            classes="kpi-inline",
                        ),
                        CustomKPI(
                            "Total",
                            "0",
                            status="info",
                            id="rec-kpi-total",
                            classes="kpi-inline",
                        ),
                        id="rec-kpi-row",
                    ),
                    id="rec-container",
                    classes="rec-container",
                ),
                CustomVertical(
                    TextualMarkdownViewer(
                        "### Preview\n\nSelect a recommendation to view details.",
                        id="rec-details",
                        show_table_of_contents=False,
                    ),
                    id="rec-details-scroll",
                ),
                id="rec-split-row",
            ),
            id="rec-main-container",
        )

    def on_unmount(self) -> None:
        """Stop debounce timers to prevent leaked timers after widget removal."""
        if self._resize_debounce_timer is not None:
            with contextlib.suppress(Exception):
                self._resize_debounce_timer.stop()
            self._resize_debounce_timer = None
        if self._search_debounce_timer is not None:
            with contextlib.suppress(Exception):
                self._search_debounce_timer.stop()
            self._search_debounce_timer = None

    def on_mount(self) -> None:
        if self._embedded:
            self.add_class("embedded")
        # CustomContainer DEFAULT_CSS has height:auto which overrides external CSS.
        # Must set height inline (same SCOPED_CSS pattern as cluster/charts screens).
        for container_id in ("rec-main-container", "rec-split-row", "rec-container", "rec-details-scroll"):
            with contextlib.suppress(Exception):
                self.query_one(f"#{container_id}").styles.height = "1fr"
        # First-pass UX: details are now shown in a modal instead of inline panel.
        with contextlib.suppress(Exception):
            self.query_one("#rec-details-scroll", CustomVertical).display = False
        with contextlib.suppress(Exception):
            tree_wrapper = self.query_one("#rec-recommendations-tree", CustomTree)
            tree_wrapper.tooltip = "Double-click a recommendation to open details"
            tree_wrapper.styles.height = "1fr"
            tree_wrapper.styles.min_height = "0"
            # Keep scrolling on the inner Tree only to avoid double horizontal bars.
            tree_wrapper.styles.overflow_y = "hidden"
            tree_wrapper.styles.overflow_x = "hidden"
            tree_widget = tree_wrapper.tree
            tree_widget.tooltip = "Double-click a recommendation to open details"
            tree_widget.show_horizontal_scrollbar = True
            tree_widget.show_vertical_scrollbar = True
            tree_widget.styles.height = "1fr"
            tree_widget.styles.min_height = "0"
            tree_widget.styles.overflow_y = "auto"
            tree_widget.styles.overflow_x = "scroll"
            tree_styles = cast(Any, tree_widget.styles)
            tree_styles.text_wrap = "nowrap"
        if self._embedded:
            with contextlib.suppress(Exception):
                list_body = self.query_one("#rec-list-body", CustomContainer)
                list_body.styles.height = "1fr"
                list_body.styles.min_height = "0"
                list_body.styles.overflow_y = "hidden"
                list_body.styles.overflow_x = "hidden"

        self._apply_static_select_widths()
        self._apply_static_action_button_widths()
        self._sync_sort_controls()
        self._rebuild_filter_options()
        self.set_loading(True)
        self._schedule_resize_update()

    def set_external_filters(
        self,
        *,
        search_query: str,
        category_filter: set[str],
        severity_filter: set[str],
    ) -> None:
        """Apply shared parent filters when recommendations are embedded."""
        self._external_search_query = search_query
        self._external_category_filter = set(category_filter)
        self._external_severity_filter = set(severity_filter)
        self._apply_filters()

    def on_resize(self, _: Resize) -> None:
        self._schedule_resize_update()

    def _schedule_resize_update(self) -> None:
        """Debounce relayout work during rapid terminal resizing."""
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

    def update_data(self, recommendations: list[dict[str, Any]], charts: list[Any]) -> None:
        """Receive data from the parent screen after worker completes."""
        self._update_data_internal(recommendations, charts, partial=False)

    def update_partial_data(
        self,
        recommendations: list[dict[str, Any]],
        charts: list[Any],
    ) -> None:
        """Incrementally refresh recommendations while preserving user selection."""
        self._update_data_internal(recommendations, charts, partial=True)

    def _update_data_internal(
        self,
        recommendations: list[dict[str, Any]],
        charts: list[Any],
        *,
        partial: bool,
    ) -> None:
        selected_key = self._recommendation_identity(self.selected_recommendation)
        self.all_recommendations = recommendations
        self._loaded_charts = charts
        selected_recommendation = self._find_recommendation_by_identity(
            selected_key,
            recommendations,
        )
        self.selected_recommendation = selected_recommendation

        if selected_recommendation is None:
            with contextlib.suppress(Exception):
                self.query_one("#rec-details", TextualMarkdownViewer).remove_class(
                    "rec-selected",
                )
            with contextlib.suppress(Exception):
                self._queue_details_markdown_update(
                    "### Preview\n\nSelect a recommendation to view details."
                )
        elif not partial:
            with contextlib.suppress(Exception):
                self._show_details(selected_recommendation)
                self.query_one("#rec-details", TextualMarkdownViewer).add_class(
                    "rec-selected",
                )

        # Defer filter rebuild + tree population so tab switches stay responsive
        def _deferred_filters() -> None:
            self._rebuild_filter_options()
            self._update_kpi_counts()
            self.set_loading(False)
            self._apply_filters()

        self.call_later(_deferred_filters)

    @staticmethod
    def _recommendation_identity(rec: dict[str, Any] | None) -> tuple[str, str, str]:
        if rec is None:
            return ("", "", "")
        return (
            str(rec.get("id", "")).strip(),
            str(rec.get("title", "")).strip(),
            str(rec.get("category", "")).strip(),
        )

    def _find_recommendation_by_identity(
        self,
        identity: tuple[str, str, str],
        recommendations: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if identity == ("", "", ""):
            return None
        for rec in recommendations:
            if self._recommendation_identity(rec) == identity:
                return rec
        return None

    def set_loading(self, loading: bool, message: str = "Loading recommendations...") -> None:
        """Show or hide loading overlay for recommendations tree area."""
        self._is_loading = loading
        with contextlib.suppress(Exception):
            self.query_one("#rec-loading-message", CustomStatic).update(message)
        with contextlib.suppress(Exception):
            self.query_one("#rec-loading-overlay", CustomContainer).display = loading

        if loading:
            with contextlib.suppress(Exception):
                self.query_one("#rec-recommendations-tree", CustomTree).display = False
            with contextlib.suppress(Exception):
                self.query_one("#rec-empty-state", CustomStatic).display = False

    def show_error(self, message: str) -> None:
        """Show recommendations load error state."""
        self.set_loading(False)
        self.all_recommendations = []

        with contextlib.suppress(Exception):
            tree = self.query_one("#rec-recommendations-tree", CustomTree)
            tree.display = False
            tree.root.remove_children()

        with contextlib.suppress(Exception):
            empty_state = self.query_one("#rec-empty-state", CustomStatic)
            empty_state.update(
                "[b]Failed to load recommendations[/b]\n\n"
                f"{escape(message)}"
            )
            empty_state.display = True

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _apply_filters(self) -> None:
        if self._is_loading:
            return

        effective_severity_filter = (
            self._external_severity_filter
            if self._embedded and self._external_severity_filter
            else self.severity_filter
        )
        effective_category_filter = (
            self._external_category_filter
            if self._embedded and self._external_category_filter
            else self.category_filter
        )
        effective_query = (
            self._external_search_query
            if self._embedded and self._external_search_query
            else self._search_query
        ).lower()

        filtered = list(self.all_recommendations)
        if effective_severity_filter:
            filtered = [
                r for r in filtered
                if r.get("severity", "").lower() in effective_severity_filter
            ]
        if effective_category_filter:
            filtered = [
                r for r in filtered
                if r.get("category", "").lower() in effective_category_filter
            ]

        if effective_query:
            filtered = [
                r for r in filtered
                if effective_query in r.get("title", "").lower()
                or effective_query in r.get("description", "").lower()
                or effective_query in r.get("category", "").lower()
                or effective_query in r.get("severity", "").lower()
            ]

        self._populate_tree(
            filtered,
            has_active_filters=bool(
                effective_query
                or effective_severity_filter
                or effective_category_filter
            ),
        )

    def _rebuild_filter_options(self) -> None:
        self._filter_options["severity"] = [
            (sev.capitalize(), sev)
            for sev in REC_SEVERITY_FILTERS
            if sev != "all"
        ]
        categories = sorted({
            rec.get("category", "").lower()
            for rec in self.all_recommendations
            if rec.get("category", "")
        })
        self._filter_options["category"] = [
            (cat.capitalize(), cat)
            for cat in categories
        ]
        self._sync_filter_selection_with_options()
        self._update_filter_trigger_buttons()
        self._apply_static_select_widths()

    def _sync_filter_selection_with_options(self) -> None:
        for key, selected_values in (
            ("severity", self.severity_filter),
            ("category", self.category_filter),
        ):
            valid_values = {value for _, value in self._filter_options.get(key, [])}
            selected_values.intersection_update(valid_values)

    def _update_kpi_counts(self) -> None:
        counts = {"critical": 0, "warning": 0, "info": 0}
        for rec in self.all_recommendations:
            sev = rec.get("severity", "info")
            if sev in counts:
                counts[sev] += 1

        total = len(self.all_recommendations)
        try:
            self.query_one("#rec-kpi-critical", CustomKPI).set_value(str(counts["critical"]))
            self.query_one("#rec-kpi-warning", CustomKPI).set_value(str(counts["warning"]))
            self.query_one("#rec-kpi-info", CustomKPI).set_value(str(counts["info"]))
            self.query_one("#rec-kpi-total", CustomKPI).set_value(str(total))
        except Exception:
            pass

    def cycle_severity(self) -> None:
        current = next(iter(self.severity_filter), "all")
        if current not in REC_SEVERITY_FILTERS:
            current = "all"
        idx = REC_SEVERITY_FILTERS.index(current)
        next_severity = REC_SEVERITY_FILTERS[(idx + 1) % len(REC_SEVERITY_FILTERS)]
        self.severity_filter = set() if next_severity == "all" else {next_severity}
        self._update_filter_trigger_buttons()
        self._apply_filters()

    # ------------------------------------------------------------------
    # Sort
    # ------------------------------------------------------------------

    def _sync_sort_controls(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#rec-sort-select", Select).value = self.sort_by
        with contextlib.suppress(Exception):
            self.query_one("#rec-order-select", Select).value = self.sort_order

    def _update_filter_trigger_buttons(self) -> None:
        severity_label = self._format_filter_trigger_label("severity", "Severity")
        category_label = self._format_filter_trigger_label("category", "Category")
        with contextlib.suppress(Exception):
            self.query_one("#rec-severity-filter-btn", CustomButton).label = severity_label
        with contextlib.suppress(Exception):
            self.query_one("#rec-category-filter-btn", CustomButton).label = category_label
        self._apply_static_select_widths()

    def _format_filter_trigger_label(self, key: str, base_label: str) -> str:
        selected_values = self._get_filter_selected_values(key)
        total_values = len(self._filter_options.get(key, []))
        if not selected_values or (total_values > 0 and len(selected_values) >= total_values):
            return base_label
        if self._get_layout_mode() in {"ultra", "wide"}:
            return f"{base_label} ({len(selected_values)})"
        return f"{base_label}({len(selected_values)})"

    def _get_filter_selected_values(self, key: str) -> set[str]:
        if key == "severity":
            return self.severity_filter
        if key == "category":
            return self.category_filter
        return set()

    def _set_filter_selected_values(self, key: str, values: set[str]) -> None:
        if key == "severity":
            self.severity_filter = values
        elif key == "category":
            self.category_filter = values

    def _open_filter_modal(self, key: str, title: str) -> None:
        options = tuple(self._filter_options.get(key, []))
        selected_values = set(self._get_filter_selected_values(key))
        modal = _RecommendationFilterSelectionModal(title, options, selected_values)
        self.app.push_screen(
            modal,
            lambda result: self._on_filter_modal_dismissed(key, result),
        )

    def _on_filter_modal_dismissed(
        self,
        key: str,
        result: set[str] | None,
    ) -> None:
        if result is None:
            return
        options = self._filter_options.get(key, [])
        valid_values = {value for _, value in options}
        selected_values = {value for value in result if value in valid_values}
        if selected_values == valid_values:
            selected_values = set()
        self._set_filter_selected_values(key, selected_values)
        self._update_filter_trigger_buttons()
        self._apply_filters()

    def _set_fluid_select_width(self, select_id: str, *, control_id: str | None = None) -> None:
        with contextlib.suppress(Exception):
            select = self.query_one(f"#{select_id}", Select)
            select.styles.width = "1fr"
            select.styles.min_width = "0"
            select.styles.max_width = "100%"
        if control_id:
            with contextlib.suppress(Exception):
                control = self.query_one(f"#{control_id}", CustomVertical)
                control.styles.width = "1fr"
                control.styles.min_width = "4"
                control.styles.max_width = "100%"

    def _set_fluid_button_width(self, button_id: str, *, control_id: str | None = None) -> None:
        with contextlib.suppress(Exception):
            button = self.query_one(f"#{button_id}", CustomButton)
            button.styles.width = "1fr"
            # Keep >= 1 writable cell after internal horizontal padding.
            button.styles.min_width = "4"
            button.styles.max_width = "100%"
        if control_id:
            with contextlib.suppress(Exception):
                control = self.query_one(f"#{control_id}", CustomVertical)
                control.styles.width = "1fr"
                control.styles.min_width = "0"
                control.styles.max_width = "100%"

    def _get_layout_mode(self) -> str:
        width = self.size.width
        if width <= 0:
            # During first mount, child width can be 0 before first real layout pass.
            width = getattr(getattr(self, "app", None), "size", self.size).width
        if width >= self._ULTRA_MIN_WIDTH:
            return "ultra"
        if width >= self._WIDE_MIN_WIDTH:
            return "wide"
        if width >= self._MEDIUM_MIN_WIDTH:
            return "medium"
        return "narrow"

    def _update_responsive_layout(self) -> None:
        mode = self._get_layout_mode()
        if mode == self._layout_mode:
            return
        self._layout_mode = mode
        for class_name in ("ultra", "wide", "medium", "narrow"):
            self.remove_class(class_name)
        self.add_class(mode)
        with contextlib.suppress(Exception):
            filter_bar = self.query_one("#rec-filter-bar", CustomVertical)
            for class_name in ("ultra", "wide", "medium", "narrow"):
                filter_bar.remove_class(class_name)
            filter_bar.add_class(mode)
        with contextlib.suppress(Exception):
            main_container = self.query_one("#rec-main-container", CustomContainer)
            for class_name in ("ultra", "wide", "medium", "narrow"):
                main_container.remove_class(class_name)
            main_container.add_class(mode)
        self._update_scroll_layout()
        self._update_filter_trigger_buttons()
        self._apply_static_action_button_widths()

    def _update_scroll_layout(self) -> None:
        """Enable vertical scrolling for medium/narrow to reveal list/details below filters."""
        mode = self._get_layout_mode()
        if self._embedded:
            self.styles.overflow_y = "hidden"
            self.styles.overflow_x = "hidden"
            with contextlib.suppress(Exception):
                main_container = self.query_one("#rec-main-container", CustomContainer)
                main_container.styles.height = "1fr"
                main_container.styles.min_height = "0"
            with contextlib.suppress(Exception):
                split_row = self.query_one("#rec-split-row", CustomHorizontal)
                split_row.styles.height = "1fr"
                split_row.styles.min_height = "0"
            with contextlib.suppress(Exception):
                rec_container = self.query_one("#rec-container", CustomContainer)
                rec_container.styles.height = "1fr"
                rec_container.styles.min_height = "0"
            with contextlib.suppress(Exception):
                details_scroll = self.query_one("#rec-details-scroll", CustomVertical)
                details_scroll.styles.height = "1fr"
                details_scroll.styles.min_height = "0"
                details_scroll.styles.max_height = "100%"
            return

        self.styles.overflow_y = "auto"
        self.styles.overflow_x = "hidden"

        with contextlib.suppress(Exception):
            main_container = self.query_one("#rec-main-container", CustomContainer)
            if mode in {"ultra", "wide"}:
                main_container.styles.height = "1fr"
                main_container.styles.min_height = "0"
            elif mode == "medium":
                main_container.styles.height = "1fr"
                main_container.styles.min_height = "16"
            else:
                main_container.styles.height = "auto"
                main_container.styles.min_height = "24"

        with contextlib.suppress(Exception):
            split_row = self.query_one("#rec-split-row", CustomHorizontal)
            if mode in {"ultra", "wide"}:
                split_row.styles.height = "1fr"
                split_row.styles.min_height = "0"
            elif mode == "medium":
                split_row.styles.height = "1fr"
                split_row.styles.min_height = "16"
            else:
                split_row.styles.height = "auto"
                split_row.styles.min_height = "24"

        with contextlib.suppress(Exception):
            rec_container = self.query_one("#rec-container", CustomContainer)
            if mode in {"ultra", "wide", "medium"}:
                rec_container.styles.height = "1fr"
                rec_container.styles.min_height = "10"
            else:
                rec_container.styles.height = "14"
                rec_container.styles.min_height = "10"

        with contextlib.suppress(Exception):
            details_scroll = self.query_one("#rec-details-scroll", CustomVertical)
            if mode in {"ultra", "wide"}:
                details_scroll.styles.height = "1fr"
                details_scroll.styles.min_height = "0"
                details_scroll.styles.max_height = "none"
            elif mode == "medium":
                details_scroll.styles.height = "1fr"
                details_scroll.styles.min_height = "10"
                details_scroll.styles.max_height = "none"
            else:
                details_scroll.styles.height = "12"
                details_scroll.styles.min_height = "10"
                details_scroll.styles.max_height = "100%"

    def _apply_static_action_button_widths(self) -> None:
        with contextlib.suppress(Exception):
            search_input = self.query_one("#rec-search-input", CustomInput)
            search_input.styles.width = "1fr"
            search_input.styles.min_width = "0"
            search_input.styles.max_width = "100%"
        with contextlib.suppress(Exception):
            search_control = self.query_one("#rec-search-control", CustomVertical)
            search_control.styles.width = "1fr"
            search_control.styles.min_width = "0"
            search_control.styles.max_width = "100%"
        self._set_fluid_button_width("rec-search-btn")
        self._set_fluid_button_width("rec-clear-search-btn")

    def _apply_static_select_widths(self) -> None:
        self._set_fluid_select_width("rec-view-select", control_id="rec-view-control")
        self._set_fluid_select_width("rec-sort-select")
        self._set_fluid_select_width("rec-order-select")
        self._set_fluid_button_width("rec-severity-filter-btn", control_id="rec-severity-control")
        self._set_fluid_button_width("rec-category-filter-btn", control_id="rec-category-control")

    def _sort_recommendations(self, recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        reverse = self.sort_order == "desc"
        if self.sort_by == "severity":
            order = {"critical": 0, "warning": 1, "info": 2}
            return sorted(
                recs,
                key=lambda r: order.get(r.get("severity", "info"), 3),
                reverse=reverse,
            )
        if self.sort_by == "category":
            return sorted(recs, key=lambda r: r.get("category", "").lower(), reverse=reverse)
        if self.sort_by == "title":
            return sorted(recs, key=lambda r: r.get("title", "").lower(), reverse=reverse)
        return recs

    def focus_sort(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#rec-sort-select", Select).focus()

    @on(Select.Changed, "#rec-sort-select")
    def _on_sort_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self.sort_by = str(event.value)
        self._apply_filters()

    @on(Select.Changed, "#rec-order-select")
    def _on_sort_order_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self.sort_order = str(event.value)
        self._apply_filters()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def focus_search(self) -> None:
        if self._embedded:
            return
        self.query_one("#rec-search-input", CustomInput).focus()

    def on_input_changed(self, event: CustomInput.Changed) -> None:
        if event.input.id == "rec-search-input":
            if self._search_debounce_timer is not None:
                self._search_debounce_timer.stop()
            value = event.value
            self._search_debounce_timer = self.set_timer(
                0.3,
                lambda: self._apply_debounced_search(value),
            )

    def on_input_submitted(self, event: CustomInput.Submitted) -> None:
        if event.input.id != "rec-search-input":
            return
        if self._search_debounce_timer is not None:
            self._search_debounce_timer.stop()
            self._search_debounce_timer = None
        self._search_query = event.value
        self._apply_filters()

    def _apply_debounced_search(self, value: str) -> None:
        self._search_debounce_timer = None
        self._search_query = value
        self._apply_filters()

    # ------------------------------------------------------------------
    # Tree
    # ------------------------------------------------------------------

    def _populate_tree(
        self,
        recommendations: list[dict[str, Any]],
        *,
        has_active_filters: bool = False,
    ) -> None:
        container = self.query_one("#rec-container", CustomContainer)
        tree = container.query_one("#rec-recommendations-tree", CustomTree)
        empty_state = container.query_one("#rec-empty-state", CustomStatic)

        if not recommendations:
            tree.display = False
            if has_active_filters:
                message = (
                    "[b]No recommendations match the current filters[/b]\n\n"
                    "Try clearing search or severity/category filters."
                )
            else:
                message = (
                    "[b]No recommendations found[/b]\n\n"
                    "Your EKS cluster and Helm charts appear to be well-configured."
                )
            empty_state.update(message)
            empty_state.display = True
            with contextlib.suppress(Exception):
                tree.root.remove_children()
            return

        empty_state.display = False
        tree.display = True
        sorted_recs = self._sort_recommendations(recommendations)
        tree.root.remove_children()
        tree.root.expand()

        severity_groups: dict[str, list[dict[str, Any]]] = {}
        for rec in sorted_recs:
            sev = rec.get("severity", "info")
            severity_groups.setdefault(sev, []).append(rec)

        labels = {"critical": "CRITICAL", "warning": "WARNING", "info": "INFO"}
        prefixes = {"critical": "[CRIT]", "warning": "[WARN]", "info": "[INFO]"}
        severity_styles = {"critical": "bold red", "warning": "bold yellow", "info": "bold cyan"}
        item_styles = {"critical": "red", "warning": "yellow", "info": "cyan"}

        for sev in ["critical", "warning", "info"]:
            sev_recs = severity_groups.get(sev, [])
            if not sev_recs:
                continue

            sev_style = severity_styles.get(sev, "bold white")
            sev_node = tree.root.add(
                f"[{sev_style}]{prefixes.get(sev, '[INFO]')} {labels.get(sev, sev.upper())} ({len(sev_recs)})[/]"
            )
            for rec in sev_recs:
                cat = escape(str(rec.get("category", "unknown")))
                title = escape(str(rec.get("title", "Recommendation")))
                item_style = item_styles.get(sev, "white")
                node = sev_node.add_leaf(f"[{item_style}]({cat}) {title}[/]")
                node.data = rec

            if sev == "critical":
                sev_node.expand()

    # ------------------------------------------------------------------
    # Details
    # ------------------------------------------------------------------

    def on_custom_tree_node_selected(self, event: CustomTree.NodeSelected) -> None:
        node = event.node
        if hasattr(node, "data") and node.data:
            self.selected_recommendation = node.data
            with contextlib.suppress(Exception):
                self.query_one("#rec-details", TextualMarkdownViewer).remove_class("rec-selected")
            self._show_details(node.data)
            with contextlib.suppress(Exception):
                self.query_one("#rec-details", TextualMarkdownViewer).add_class("rec-selected")

    @on(Click, "#rec-recommendations-tree")
    def on_recommendations_tree_click(self, event: Click) -> None:
        """Open recommendation details on double-click."""
        if event.chain < 2:
            return
        if not self.selected_recommendation:
            return
        self._open_details_modal(self.selected_recommendation)
        event.stop()

    def _show_details(self, rec: dict[str, Any]) -> None:
        self._queue_details_markdown_update(self._build_recommendation_markdown(rec))

    def _open_details_modal(self, rec: dict[str, Any]) -> None:
        title = str(rec.get("title", "Recommendation")).strip() or "Recommendation"
        severity = str(rec.get("severity", "info")).strip().upper() or "INFO"
        category = str(rec.get("category", "unknown")).strip() or "unknown"
        subtitle = f"{severity} | {category}"
        markdown = self._build_recommendation_markdown(rec)
        modal = FixDetailsModal(
            title=title,
            subtitle=subtitle,
            markdown=markdown,
            actions=(
                ("close", "Close", None),
            ),
        )
        self.app.push_screen(modal)

    @staticmethod
    def _to_markdown_code(value: str) -> str:
        """Render a value as a safe markdown inline code span."""
        safe_value = value.replace("`", "'")
        return f"`{safe_value}`"

    @staticmethod
    def _normalize_markdown_text(value: Any, fallback: str) -> str:
        """Normalize recommendation text for markdown rendering."""
        text = str(value).strip() if value is not None else ""
        if not text:
            return fallback

        normalized_lines: list[str] = []
        for line in text.splitlines():
            if line.startswith("  - "):
                normalized_lines.append(line[2:])
            else:
                normalized_lines.append(line)
        return "\n".join(normalized_lines)

    def _format_affected_resources_markdown(self, resources: list[Any]) -> str:
        normalized_resources = [str(resource).strip() for resource in resources if str(resource).strip()]
        if not normalized_resources:
            return f"- {self._to_markdown_code('All')}"

        preview_limit = 15
        lines = [
            f"- {self._to_markdown_code(resource)}"
            for resource in normalized_resources[:preview_limit]
        ]
        remaining = len(normalized_resources) - preview_limit
        if remaining > 0:
            lines.append(f"- ... and {remaining} more")
        return "\n".join(lines)

    def _build_recommendation_markdown(self, rec: dict[str, Any]) -> str:
        """Build markdown content for recommendation details preview."""
        title = str(rec.get("title", "Recommendation")).strip() or "Recommendation"
        severity = str(rec.get("severity", "info")).strip().upper() or "INFO"
        category = str(rec.get("category", "unknown")).strip() or "unknown"
        description = self._normalize_markdown_text(rec.get("description"), "No description")
        recommended_action = self._normalize_markdown_text(
            rec.get("recommended_action"),
            "No action specified",
        )
        raw_affected_resources = rec.get("affected_resources", [])
        if isinstance(raw_affected_resources, (list, tuple, set)):
            affected_resources = list(raw_affected_resources)
        elif raw_affected_resources:
            affected_resources = [raw_affected_resources]
        else:
            affected_resources = []
        yaml_example = str(rec.get("yaml_example", "")).strip()

        lines = [
            f"### {title}",
            "",
            f"- **Severity:** {self._to_markdown_code(severity)}",
            f"- **Category:** {self._to_markdown_code(category)}",
            "",
            "### Description",
            description,
            "",
            "### Affected Resources",
            self._format_affected_resources_markdown(affected_resources),
            "",
            "### Recommended Action",
            recommended_action,
        ]

        if yaml_example:
            lines.extend(
                [
                    "",
                    "### Example Fix",
                    "```yaml",
                    yaml_example,
                    "```",
                ]
            )

        return "\n".join(lines)

    def _queue_details_markdown_update(self, content: str) -> None:
        """Schedule markdown preview refresh for recommendation details."""

        async def _do_update() -> None:
            with contextlib.suppress(Exception):
                viewer = self.query_one("#rec-details", TextualMarkdownViewer)
                await viewer.document.update(content)

        self.call_later(_do_update)

    def go_to_chart(self) -> None:
        rec = self.selected_recommendation
        if not rec:
            self.notify("Select a recommendation first", severity="warning")
            return

        affected = rec.get("affected_resources", [])
        if not affected:
            self.notify("No affected resources in this recommendation", severity="warning")
            return

        chart_name = affected[0]
        chart_index = next((i for i, c in enumerate(self._loaded_charts) if c.name == chart_name), -1)
        if chart_index < 0:
            self.notify(f"Chart '{chart_name}' not found in loaded data", severity="warning")
            return

        from kubeagle.screens.detail import ChartDetailScreen

        self.app.push_screen(
            ChartDetailScreen(
                self._loaded_charts[chart_index],
                chart_list=self._loaded_charts,
                chart_index=chart_index,
            )
        )

    # ------------------------------------------------------------------
    # Button events
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "rec-search-btn":
            with contextlib.suppress(Exception):
                self._search_query = self.query_one("#rec-search-input", CustomInput).value
            self._apply_filters()
        elif bid == "rec-clear-search-btn":
            with contextlib.suppress(Exception):
                self.query_one("#rec-search-input", CustomInput).value = ""
            self._search_query = ""
            self._apply_filters()
        elif bid == "rec-severity-filter-btn":
            self._open_filter_modal("severity", "Severity")
        elif bid == "rec-category-filter-btn":
            self._open_filter_modal("category", "Category")


__all__ = ["RecommendationsView"]
