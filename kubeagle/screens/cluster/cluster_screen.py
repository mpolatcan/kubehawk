"""Cluster screen for EKS cluster overview with enhanced event, PDB, and single replica analysis."""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from typing import Any, cast

from rich.style import Style
from rich.text import Span as _RichSpan, Text
from textual import on
from textual.app import ComposeResult
from textual.color import Gradient
from textual.css.query import NoMatches, WrongType
from textual.events import Resize
from textual.reactive import reactive
from textual.renderables.bar import Bar as RichBarRenderable
from textual.screen import ModalScreen, Screen
from textual.timer import Timer
from textual.widgets import ContentSwitcher

from kubeagle.constants.screens.cluster import (
    CLUSTER_EVENT_WINDOW_DEFAULT,
    CLUSTER_EVENT_WINDOW_OPTIONS,
)
from kubeagle.keyboard import CLUSTER_SCREEN_BINDINGS
from kubeagle.keyboard.navigation import ScreenNavigator
from kubeagle.screens.cluster.config import (
    CLUSTER_TABLE_HEADER_TOOLTIPS,
    EVENTS_DETAIL_TABLE_COLUMNS,
    NODE_TABLE_COLUMNS,
    TAB_IDS as CLUSTER_TAB_IDS,
    TAB_LABELS_COMPACT,
    TAB_LABELS_FULL,
    TAB_NODES,
    TAB_TITLES,
)
from kubeagle.screens.cluster.presenter import (
    ClusterDataLoaded,
    ClusterDataLoadFailed,
    ClusterPresenter,
    ClusterSourceLoaded,
)
from kubeagle.screens.mixins.main_navigation_tabs_mixin import (
    MAIN_NAV_TAB_CLUSTER,
    MainNavigationTabsMixin,
)
from kubeagle.screens.mixins.worker_mixin import WorkerMixin
from kubeagle.widgets import (
    CustomButton,
    CustomContainer,
    CustomDataTable,
    CustomDigits,
    CustomFooter,
    CustomHeader,
    CustomHorizontal,
    CustomInput,
    CustomLoadingIndicator,
    CustomProgressBar as ProgressBar,
    CustomSelect as Select,
    CustomSelectionList,
    CustomStatic,
    CustomTabs,
    CustomVertical,
)

logger = logging.getLogger(__name__)
_EVENT_WINDOW_SELECT_ID = "cluster-event-window-select"
_POD_STATS_UNITS_SELECT_ID = "pod-stats-units-select"
_NODE_DISTRIBUTION_UNITS_SELECT_ID = "node-distribution-units-select"

def _apply_gradient_left_to_right(text: Text, gradient: Gradient, width: int) -> None:
    """Apply gradient left-to-right across the progress bar width.

    Performance: builds all gradient spans in a batch and assigns them
    directly to the Text._spans list, avoiding per-character stylize()
    overhead.
    """
    if not width:
        return
    max_width = width - 1
    if max_width <= 0:
        text.stylize(Style.from_color(gradient.get_color(0).rich_color))
        return

    text_length = len(text)
    if text_length <= 0:
        return

    # Pre-compute all gradient colors in one pass then batch-assign spans.
    # This avoids O(n) individual stylize() calls that each scan/merge
    # the internal spans list.
    inv_max = 1.0 / max_width
    spans = [
        _RichSpan(offset, offset + 1, Style.from_color(gradient.get_rich_color(offset * inv_max)))
        for offset in range(text_length)
    ]
    text._spans.extend(spans)


class _ForwardGradientBarRenderable(RichBarRenderable):
    """Bar renderable with forward gradient direction (left -> right)."""

    def __rich_console__(self, console: Any, options: Any) -> Any:
        highlight_style = console.get_style(self.highlight_style)
        background_style = console.get_style(self.background_style)

        width = self.width or options.max_width
        start, end = self.highlight_range

        start = max(start, 0)
        end = min(end, width)

        output_bar = Text("", end="")

        if start == end == 0 or end < 0 or start > end:
            output_bar.append(Text(self.BAR * width, style=background_style, end=""))
            yield output_bar
            return

        start = round(start * 2) / 2
        end = round(end * 2) / 2
        half_start = start - int(start) > 0
        half_end = end - int(end) > 0

        output_bar.append(
            Text(self.BAR * (int(start - 0.5)), style=background_style, end="")
        )
        if not half_start and start > 0:
            output_bar.append(Text(self.HALF_BAR_RIGHT, style=background_style, end=""))

        highlight_bar = Text("", end="")
        bar_width = int(end) - int(start)
        if half_start:
            highlight_bar.append(
                Text(
                    self.HALF_BAR_LEFT + self.BAR * (bar_width - 1),
                    style=highlight_style,
                    end="",
                )
            )
        else:
            highlight_bar.append(
                Text(self.BAR * bar_width, style=highlight_style, end="")
            )
        if half_end:
            highlight_bar.append(
                Text(self.HALF_BAR_RIGHT, style=highlight_style, end="")
            )

        if self.gradient is not None:
            _apply_gradient_left_to_right(highlight_bar, self.gradient, width)
        output_bar.append(highlight_bar)

        if not half_end and end - width != 0:
            output_bar.append(Text(self.HALF_BAR_LEFT, style=background_style, end=""))
        output_bar.append(
            Text(self.BAR * (int(width) - int(end) - 1), style=background_style, end="")
        )

        for range_name, (range_start, range_end) in self.clickable_ranges.items():
            output_bar.apply_meta(
                {"@click": f"range_clicked('{range_name}')"}, range_start, range_end
            )

        yield output_bar


class _ForwardGradientProgressBar(ProgressBar):
    """ProgressBar that uses left-to-right gradient mapping."""

    BAR_RENDERABLE = _ForwardGradientBarRenderable


class _ColumnFilterSelectionModal(ModalScreen[set[str] | None]):
    """Modal for multi-selecting values of a single column filter."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    _DIALOG_MIN_WIDTH = 44
    _DIALOG_MIN_HEIGHT = 14
    _DIALOG_MAX_HEIGHT = 30
    _VISIBLE_ROWS_MIN = 4
    _VISIBLE_ROWS_MAX = 14
    _COMPACT_ACTIONS_MAX_WIDTH = 52

    def __init__(
        self,
        column_name: str,
        options: tuple[tuple[str, str], ...],
        selected_values: set[str],
    ) -> None:
        super().__init__(classes="cluster-filter-modal-screen selection-modal-screen")
        self._column_name = column_name
        self._all_options = tuple(
            (label, value) for label, value in options if value != "all"
        )
        self._all_values = {value for _, value in self._all_options}
        self._selected_values = {value for value in selected_values if value in self._all_values}
        self._search_query = ""
        self._visible_option_values: set[str] = set()
        self._search_debounce_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with CustomContainer(
            classes="cluster-filter-modal-shell selection-modal-shell"
        ):
            yield CustomStatic(
                f"{self._column_name} Filter",
                classes="cluster-filter-modal-title selection-modal-title",
                markup=False,
            )
            yield CustomStatic(
                "",
                id="cluster-filter-modal-summary",
                classes="cluster-filter-modal-summary selection-modal-summary",
                markup=False,
            )
            yield CustomInput(
                placeholder="Search values...",
                id="cluster-filter-modal-search",
                classes="cluster-filter-modal-search selection-modal-search",
            )
            with CustomContainer(
                classes="cluster-filter-modal-list-wrap selection-modal-list-wrap"
            ):
                yield CustomSelectionList[str](
                    id="cluster-filter-modal-list",
                    classes="cluster-filter-modal-list selection-modal-list",
                )
                yield CustomStatic(
                    "No matching values",
                    id="cluster-filter-modal-empty",
                    classes="cluster-filter-modal-empty selection-modal-empty hidden",
                    markup=False,
                )
            with CustomHorizontal(
                classes="cluster-filter-modal-actions selection-modal-actions"
            ):
                yield CustomButton(
                    "Select All",
                    id="cluster-filter-modal-select-all",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Clear",
                    id="cluster-filter-modal-clear",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Apply",
                    variant="primary",
                    id="cluster-filter-modal-apply",
                    compact=True,
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Cancel",
                    id="cluster-filter-modal-cancel",
                    compact=True,
                    classes="selection-modal-action-btn",
                )

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        self._refresh_selection_options()
        self._sync_action_buttons()
        with suppress(NoMatches):
            search_input = self.query_one("#cluster-filter-modal-search", CustomInput)
            search_input.input.focus()

    def on_resize(self, _: Resize) -> None:
        if hasattr(self, "_resize_timer") and self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer: Timer | None = self.set_timer(
            0.1, self._apply_dynamic_layout
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_custom_input_changed(self, event: CustomInput.Changed) -> None:
        if event.input.id != "cluster-filter-modal-search":
            return
        self._search_query = event.value.strip().lower()
        if self._search_debounce_timer is not None:
            self._search_debounce_timer.stop()
        self._search_debounce_timer = self.set_timer(
            0.15, self._debounced_refresh_options
        )

    def _debounced_refresh_options(self) -> None:
        self._search_debounce_timer = None
        self._refresh_selection_options()

    def on_selection_list_selected_changed(
        self, event: object
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
        if button_id == "cluster-filter-modal-select-all":
            self._selected_values = set(self._all_values)
            self._refresh_selection_options()
            self._sync_action_buttons()
            return
        if button_id == "cluster-filter-modal-clear":
            self._selected_values.clear()
            self._refresh_selection_options()
            self._sync_action_buttons()
            return
        if button_id == "cluster-filter-modal-apply":
            selected_values = set(self._selected_values)
            if selected_values == self._all_values:
                selected_values = set()
            self.dismiss(selected_values)
            return
        if button_id == "cluster-filter-modal-cancel":
            self.dismiss(None)

    def _refresh_selection_options(self) -> None:
        filtered_options = self._visible_options()
        self._visible_option_values = {value for _, value in filtered_options}
        with suppress(NoMatches):
            selection_list = self.query_one(
                "#cluster-filter-modal-list",
                CustomSelectionList,
            )
            if selection_list.selection_list is not None:
                selection_list.selection_list.clear_options()
                selection_list.selection_list.add_options(
                    [
                        (label, value, value in self._selected_values)
                        for label, value in filtered_options
                    ]
                )
        with suppress(NoMatches):
            empty_state = self.query_one("#cluster-filter-modal-empty", CustomStatic)
            if filtered_options:
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
        with suppress(NoMatches):
            self.query_one(
                "#cluster-filter-modal-select-all", CustomButton
            ).disabled = total_count == 0 or selected_count >= total_count
        with suppress(NoMatches):
            self.query_one(
                "#cluster-filter-modal-clear", CustomButton
            ).disabled = selected_count == 0

    def _update_selection_summary(self) -> None:
        total = len(self._all_values)
        selected_count = len(self._selected_values)
        if selected_count == 0 or selected_count == total:
            summary = f"All values ({total})"
        else:
            summary = f"{selected_count} of {total} selected"
        with suppress(NoMatches):
            self.query_one("#cluster-filter-modal-summary", CustomStatic).update(summary)

    def _apply_dynamic_layout(self) -> None:
        button_ids = [
            "cluster-filter-modal-select-all",
            "cluster-filter-modal-clear",
            "cluster-filter-modal-apply",
            "cluster-filter-modal-cancel",
        ]
        for button_id in button_ids:
            with suppress(Exception):
                button = self.query_one(f"#{button_id}", CustomButton)
                button.styles.width = "1fr"
                button.styles.min_width = "0"
                button.styles.max_width = "100%"

        title_width = len(f"{self._column_name} Filter")
        summary_width = len(f"All values ({len(self._all_values)})")
        option_prefix_width = len(f"{self._column_name}: ")
        longest_value_width = max(
            (self._option_value_text_width(label) for label, _ in self._all_options),
            default=0,
        )
        # Account for option prefix + checkbox row chrome + container padding.
        longest_option = option_prefix_width + longest_value_width + 6
        target_width = max(
            title_width + 8,
            summary_width + 8,
            longest_option + 4,
            self._DIALOG_MIN_WIDTH,
        )

        available_width = getattr(self.app.size, "width", self._DIALOG_MIN_WIDTH + 6)
        max_width = max(self._DIALOG_MIN_WIDTH, available_width - 6)
        dialog_width = max(self._DIALOG_MIN_WIDTH, min(target_width, max_width))
        dialog_width_value = str(dialog_width)
        compact_actions = dialog_width <= self._COMPACT_ACTIONS_MAX_WIDTH

        with suppress(NoMatches):
            select_all_btn = self.query_one(
                "#cluster-filter-modal-select-all",
                CustomButton,
            )
            select_all_btn.label = "All" if compact_actions else "Select All"

        visible_rows = min(
            max(len(self._all_options), self._VISIBLE_ROWS_MIN),
            self._VISIBLE_ROWS_MAX,
        )
        # Title + summary + search + action row + shell padding.
        target_height = visible_rows + 9
        available_height = getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT)
        max_height = min(
            self._DIALOG_MAX_HEIGHT,
            max(self._DIALOG_MIN_HEIGHT, available_height - 2),
        )
        dialog_max_height = max(self._DIALOG_MIN_HEIGHT, min(target_height, max_height))
        dialog_min_height_value = str(self._DIALOG_MIN_HEIGHT)
        dialog_max_height_value = str(dialog_max_height)
        with suppress(NoMatches):
            shell = self.query_one(".cluster-filter-modal-shell", CustomContainer)
            shell.styles.width = dialog_width_value
            shell.styles.min_width = dialog_width_value
            shell.styles.max_width = dialog_width_value
            shell.styles.height = "auto"
            shell.styles.min_height = dialog_min_height_value
            shell.styles.max_height = dialog_max_height_value

    def _option_value_text_width(self, label: str) -> int:
        """Return width of value part from `<column>: <value>` option labels."""
        _, sep, value_text = label.partition(": ")
        if sep:
            return len(value_text)
        return len(label)


class _ClusterFiltersModal(ModalScreen[dict[str, set[str]] | None]):
    """Unified cluster filters modal with per-column selection lists."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    _DIALOG_MIN_WIDTH = 112
    _DIALOG_MAX_WIDTH = 172
    _DIALOG_MIN_HEIGHT = 26
    _DIALOG_MAX_HEIGHT = 48
    _LIST_CONTROL_RE = re.compile(r"^cluster-filters-modal-(?P<slug>[a-z0-9_]+)-list-inner$")
    _LIST_ACTION_RE = re.compile(
        r"^cluster-filters-modal-(?P<slug>[a-z0-9_]+)-(?P<action>all|clear)$"
    )
    _PREFERRED_COLUMN_ORDER: tuple[str, ...] = ("type", "reason", "object")

    def __init__(
        self,
        *,
        options_by_column: dict[str, tuple[str, tuple[tuple[str, str], ...]]],
        selected_values: dict[str, set[str]],
    ) -> None:
        super().__init__(classes="cluster-filters-modal-screen selection-modal-screen")
        self._columns: list[tuple[str, str]] = []
        self._column_options: dict[str, tuple[tuple[str, str], ...]] = {}
        self._column_values: dict[str, set[str]] = {}
        self._selected_by_column: dict[str, set[str]] = {}

        ordered_slugs = [
            slug for slug in self._PREFERRED_COLUMN_ORDER if slug in options_by_column
        ]
        ordered_slugs.extend(
            sorted(slug for slug in options_by_column if slug not in self._PREFERRED_COLUMN_ORDER)
        )

        for column_slug in ordered_slugs:
            column_label, options = options_by_column[column_slug]
            selectable_options = tuple(
                (label, value) for label, value in options if value != "all"
            )
            values = {value for _, value in selectable_options}
            selected = {value for value in selected_values.get(column_slug, set()) if value in values}

            self._columns.append((column_slug, column_label))
            self._column_options[column_slug] = selectable_options
            self._column_values[column_slug] = values
            self._selected_by_column[column_slug] = selected if selected else set(values)

    def compose(self) -> ComposeResult:
        with CustomContainer(classes="cluster-filters-modal-shell selection-modal-shell"):
            yield CustomStatic(
                "Cluster Filters",
                classes="cluster-filters-modal-title selection-modal-title",
                markup=False,
            )
            yield CustomStatic(
                "",
                id="cluster-filters-modal-summary",
                classes="cluster-filters-modal-summary selection-modal-summary",
                markup=False,
            )
            with CustomHorizontal(
                id="cluster-filters-modal-lists-row",
                classes="cluster-filters-modal-lists-row",
            ):
                if not self._columns:
                    yield CustomStatic(
                        "No filter columns available",
                        id="cluster-filters-modal-empty",
                        classes="cluster-filters-modal-empty selection-modal-empty",
                        markup=False,
                    )
                for column_slug, column_label in self._columns:
                    with CustomVertical(classes="cluster-filters-modal-list-column"):
                        with CustomVertical(classes="selection-modal-list-panel"):
                            yield CustomStatic(
                                column_label,
                                id=f"cluster-filters-modal-{column_slug}-title",
                                classes="cluster-filters-modal-list-title selection-modal-list-title",
                                markup=False,
                            )
                            yield CustomSelectionList[str](
                                id=f"cluster-filters-modal-{column_slug}-list",
                                classes="cluster-filters-modal-list selection-modal-list",
                            )
                        with CustomHorizontal(classes="cluster-filters-modal-list-actions"):
                            yield CustomButton(
                                "All",
                                id=f"cluster-filters-modal-{column_slug}-all",
                                compact=True,
                                classes="selection-modal-action-btn",
                            )
                            yield CustomButton(
                                "Clear",
                                id=f"cluster-filters-modal-{column_slug}-clear",
                                compact=True,
                                classes="selection-modal-action-btn",
                            )
            with CustomHorizontal(classes="cluster-filters-modal-actions selection-modal-actions"):
                yield CustomButton(
                    "Apply",
                    id="cluster-filters-modal-apply",
                    compact=True,
                    variant="primary",
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Cancel",
                    id="cluster-filters-modal-cancel",
                    compact=True,
                    classes="selection-modal-action-btn",
                )

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        for column_slug, _ in self._columns:
            self._refresh_column_options(column_slug)
            self._update_column_title(column_slug)
            self._sync_column_action_buttons(column_slug)
        self._update_summary()
        if self._columns:
            with suppress(NoMatches):
                self.query_one(
                    f"#cluster-filters-modal-{self._columns[0][0]}-list",
                    CustomSelectionList,
                ).focus()

    def on_resize(self, _: Resize) -> None:
        if hasattr(self, "_resize_timer") and self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer: Timer | None = self.set_timer(
            0.1, self._apply_dynamic_layout
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_selection_list_selected_changed(self, event: object) -> None:
        control_id = str(getattr(getattr(event, "control", None), "id", "") or "")
        match = self._LIST_CONTROL_RE.match(control_id)
        if not match:
            return

        column_slug = match.group("slug")
        with suppress(NoMatches):
            selection_list = self.query_one(
                f"#cluster-filters-modal-{column_slug}-list",
                CustomSelectionList,
            )
            self._selected_by_column[column_slug] = set(selection_list.selected)

        self._update_column_title(column_slug)
        self._sync_column_action_buttons(column_slug)
        self._update_summary()

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "cluster-filters-modal-apply":
            self.dismiss(self._build_result_map())
            return
        if button_id == "cluster-filters-modal-cancel":
            self.dismiss(None)
            return

        match = self._LIST_ACTION_RE.match(button_id)
        if not match:
            return

        column_slug = match.group("slug")
        action = match.group("action")
        all_values = self._column_values.get(column_slug, set())
        if action == "all":
            self._selected_by_column[column_slug] = set(all_values)
        else:
            self._selected_by_column[column_slug] = set()

        self._refresh_column_options(column_slug)
        self._update_column_title(column_slug)
        self._sync_column_action_buttons(column_slug)
        self._update_summary()

    def _update_summary(self) -> None:
        total_values = sum(len(values) for values in self._column_values.values())
        selected_values = sum(
            len(self._selected_by_column.get(column_slug, set()))
            for column_slug, _ in self._columns
        )
        active_columns = sum(
            1
            for column_slug, _ in self._columns
            if self._selected_by_column.get(column_slug, set())
            and self._selected_by_column.get(column_slug, set())
            != self._column_values.get(column_slug, set())
        )
        if active_columns == 0:
            summary = f"No active filters • {total_values} available values"
        else:
            summary = f"{active_columns} columns • {selected_values} selected values"
        with suppress(NoMatches):
            self.query_one("#cluster-filters-modal-summary", CustomStatic).update(summary)

    def _build_result_map(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for column_slug, _ in self._columns:
            selected_values = set(self._selected_by_column.get(column_slug, set()))
            all_values = self._column_values.get(column_slug, set())
            if not selected_values or selected_values == all_values:
                continue
            result[column_slug] = selected_values
        return result

    def _apply_dynamic_layout(self) -> None:
        option_labels = [
            label
            for options in self._column_options.values()
            for label, _ in options
        ]
        preferred_width = max(
            self._DIALOG_MIN_WIDTH,
            min(
                self._DIALOG_MAX_WIDTH,
                max((len(label) for label in option_labels), default=0) + 44,
            ),
        )
        available_width = getattr(self.app.size, "width", preferred_width)
        dialog_width = max(
            self._DIALOG_MIN_WIDTH,
            min(preferred_width, available_width - 4),
        )
        available_height = getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT)
        dialog_height = min(
            self._DIALOG_MAX_HEIGHT,
            max(self._DIALOG_MIN_HEIGHT, available_height - 1),
        )
        with suppress(NoMatches):
            shell = self.query_one(".cluster-filters-modal-shell", CustomContainer)
            width_value = str(dialog_width)
            shell.styles.width = width_value
            shell.styles.min_width = width_value
            shell.styles.max_width = width_value
            height_value = str(dialog_height)
            shell.styles.height = height_value
            shell.styles.min_height = height_value
            shell.styles.max_height = height_value
        with suppress(NoMatches):
            lists_row = self.query_one(
                "#cluster-filters-modal-lists-row",
                CustomHorizontal,
            )
            filter_count = max(1, len(self._columns))
            if filter_count <= 4:
                # 1xN for up to four filters: 1x1 ... 1x4
                grid_columns = filter_count
                grid_rows = 1
            elif filter_count <= 8:
                # Two rows preserve enough vertical list space for dense tabs
                # (for example Workloads has 8 filter columns).
                grid_columns = 4
                grid_rows = math.ceil(filter_count / grid_columns)
            else:
                # Larger sets stay on three columns to avoid overly narrow lists.
                grid_columns = 3
                grid_rows = max(2, math.ceil(filter_count / grid_columns))
            lists_row.styles.grid_size_columns = grid_columns
            lists_row.styles.grid_size_rows = grid_rows
            lists_row.styles.grid_columns = " ".join(["1fr"] * grid_columns)
            lists_row.styles.grid_rows = " ".join(["1fr"] * grid_rows)

    def _refresh_column_options(self, column_slug: str) -> None:
        options = self._column_options.get(column_slug, ())
        selected_values = self._selected_by_column.get(column_slug, set())
        with suppress(NoMatches):
            selection_list = self.query_one(
                f"#cluster-filters-modal-{column_slug}-list",
                CustomSelectionList,
            )
            if selection_list.selection_list is not None:
                selection_list.selection_list.clear_options()
                selection_list.selection_list.add_options(
                    [
                        (label, value, value in selected_values)
                        for label, value in options
                    ]
                )

    def _update_column_title(self, column_slug: str) -> None:
        label = next(
            (column_label for slug, column_label in self._columns if slug == column_slug),
            column_slug.title(),
        )
        total = len(self._column_values.get(column_slug, set()))
        selected = len(self._selected_by_column.get(column_slug, set()))
        with suppress(NoMatches):
            self.query_one(
                f"#cluster-filters-modal-{column_slug}-title",
                CustomStatic,
            ).update(
                self._format_title_count(label=label, total=total, selected=selected)
            )

    def _sync_column_action_buttons(self, column_slug: str) -> None:
        selected_values = self._selected_by_column.get(column_slug, set())
        all_values = self._column_values.get(column_slug, set())
        selected_count = len(selected_values)
        total_count = len(all_values)

        with suppress(NoMatches):
            all_button = self.query_one(
                f"#cluster-filters-modal-{column_slug}-all",
                CustomButton,
            )
            all_button.disabled = total_count == 0 or selected_count >= total_count

        with suppress(NoMatches):
            clear_button = self.query_one(
                f"#cluster-filters-modal-{column_slug}-clear",
                CustomButton,
            )
            clear_button.disabled = selected_count == 0

    @staticmethod
    def _format_title_count(*, label: str, total: int, selected: int) -> str:
        if total > 0 and selected == total:
            return f"{label} (All)"
        return f"{label} ({selected})"


class ClusterScreen(MainNavigationTabsMixin, WorkerMixin, ScreenNavigator, Screen):
    """EKS cluster analysis with nodes, events, PDBs, single replica, and health analysis."""

    BINDINGS = CLUSTER_SCREEN_BINDINGS

    search_query: str = reactive("")  # type: ignore[assignment]

    TAB_IDS = CLUSTER_TAB_IDS
    _TAB_LABELS_FULL: dict[str, str] = TAB_LABELS_FULL
    _TAB_LABELS_COMPACT: dict[str, str] = TAB_LABELS_COMPACT
    _COMPACT_TAB_LABEL_MIN_WIDTH = 100
    _COL_KEY_SANITIZE_RE = re.compile(r"[^a-z0-9]+")
    _LOAD_PROGRESS_RE = re.compile(r"Loading data \((\d+)/(\d+)\)\.\.\.")
    _NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
    _DIGIT_DECORATION_RE = re.compile(r"[⚠🚨✅✨•]|\ufe0f")
    _MARKUP_TAG_RE = re.compile(r"\[[^\]]+\]")
    _HAS_ALPHA_RE = re.compile(r"[a-zA-Z]")
    _AWS_AZ_COLUMN_RE = re.compile(r"^[a-z]{2}(?:-[a-z0-9]+)+-\d+[a-z]$")
    _AWS_AZ_GROUPED_COLUMN_RE = re.compile(
        r"^(?P<region>[a-z]{2}(?:-[a-z0-9]+)+-\d+)\s+\((?P<zones>[a-z](?:/[a-z])*)\)$"
    )
    _NUMERIC_LIKE_RE = re.compile(
        (
            r"^\s*[-+]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\d*\.\d+)"
            r"(?:\s*(?:%|m|ms|s|sec|secs|"
            r"(?:[kmgtpe]i?b)|(?:[kmgtpe]i)|"
            r"cpu|cores?|pods?|nodes?|req|requests?|limits?|"
            r"gib|mib|kib|tb|gb|mb|kb|b))?\s*$"
        ),
        re.IGNORECASE,
    )
    _RATIO_LIKE_RE = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")
    _FILTER_VALUE_RE = re.compile(r"^col::(?P<col>[a-z0-9_]+)::val::(?P<val>.+)$")
    _LOAD_WORKING_MAX = 95
    _CONNECTION_STALL_WARN_SECONDS = 20.0
    _CONNECTION_STALL_FAIL_SECONDS = 45.0
    _CONNECTION_STALL_CHECK_INTERVAL_SECONDS = 1.0
    _LOAD_INTERRUPTED_GRACE_SECONDS = 1.5
    _RESIZE_DEBOUNCE_SECONDS = 0.08
    _PROGRESS_ANIMATION_INTERVAL_SECONDS = 0.03
    _PROGRESS_ANIMATION_STEP_RATIO = 0.25
    _SOURCE_REFRESH_DEBOUNCE_SECONDS = 0.25
    _STATUS_BAR_DEBOUNCE_SECONDS = 0.2
    _TAB_CONTROLS_XWIDE_MIN_WIDTH = 220
    _TAB_CONTROLS_WIDE_MIN_WIDTH = 170
    _TAB_CONTROLS_MEDIUM_MIN_WIDTH = 130
    _TAB_CONTROLS_NARROW_MIN_WIDTH = 100
    _EVENTS_FILTER_COLUMNS: tuple[str, ...] = ("type", "reason", "object")
    _TAB_HEIGHT_SHORT_MIN_ROWS = 41
    _TAB_HEIGHT_TIGHT_MIN_ROWS = 30
    _FILTER_SELECT_BASE_MAX_WIDTH = 52
    _FILTER_SELECT_MIN_RESPONSIVE_WIDTH = 10
    _FILTER_ROW_FIXED_OVERHEAD = 44
    _MAX_FILTER_VALUES_PER_COLUMN = 240
    _TABLE_SIGNATURE_MASK = (1 << 64) - 1
    _TABLE_SIGNATURE_MIXER = 1099511628211
    _DIGIT_COMPACT_THRESHOLD = 1_000
    _SUMMARY_DIGIT_UPDATE_INDICATOR_SECONDS = 0.8
    _PROGRESS_TEXT_MAX_XWIDE = 120
    _PROGRESS_TEXT_MAX_WIDE = 96
    _PROGRESS_TEXT_MAX_MEDIUM = 80
    _PROGRESS_TEXT_MAX_NARROW = 64
    _PROGRESS_TEXT_MAX_COMPACT = 48
    _OVERVIEW_ERROR_MAX_CHARS = 74
    _FILTER_OPTION_SYNC_LOADING_INTERVAL_SECONDS = 0.75
    _REFRESH_BUTTON_LABELS: dict[str, str] = {
        "xwide": "Refresh",
        "wide": "Refresh",
        "medium": "Refresh",
        "narrow": "R",
        "compact": "R",
    }
    _EVENT_WINDOW_PREFIX_BY_MODE: dict[str, str] = {
        "xwide": "Event Window:",
        "wide": "Event Window:",
        "medium": "Event Window:",
        "narrow": "",
        "compact": "",
    }
    _CLUSTER_PROGRESS_GRADIENT = Gradient(
        (0.0, "rgb(255,0,0)"),
        (0.5, "rgb(255,255,0)"),
        (1.0, "rgb(0,255,0)"),
        quality=120,
    )
    _TAB_LOADING_BASE_MESSAGES: dict[str, str] = {
        "tab-nodes": "Loading nodes...",
        "tab-pods": "Loading workloads...",
        "tab-events": "Loading events...",
    }
    _TAB_TABLE_IDS: dict[str, tuple[str, ...]] = {
        "tab-nodes": (
            "nodes-table",
            "node-groups-table",
        ),
        "tab-pods": (),
        "tab-events": (
            "events-detail-table",
        ),
    }
    _TABLE_DATA_KEYS: dict[str, tuple[str, ...]] = {
        "events-detail-table": ("critical_events",),
        "nodes-table": ("nodes",),
        "node-groups-table": ("node_groups", "node_groups_az_matrix", "nodes"),
    }
    _TABLE_LOCKED_COLUMNS: dict[str, tuple[str, ...]] = {
        "nodes-table": ("Name", "Node Group"),
        "node-groups-table": ("Node Group", "Nodes"),
    }
    _TAB_CONTROL_PROFILES: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
        "tab-events": {
            "filters": (
                ("Cond1: All", "all"),
                ("Cond1: Warnings+", "warning"),
                ("Cond1: Errors", "error"),
            ),
            "secondary_filters": (
                ("Cond2: All", "all"),
                ("Cond2: Warning Type", "warning"),
                ("Cond2: Error Type", "error"),
            ),
            "sorts": (
                ("Sort: None", "none"),
                ("Sort: Type", "idx:0"),
                ("Sort: Reason", "idx:1"),
                ("Sort: Count", "idx:3"),
                ("Sort: Message", "idx:4"),
            ),
        },
        "tab-nodes": {
            "filters": (
                ("Cond1: All", "all"),
                ("Cond1: High Usage", "high_usage"),
                ("Cond1: Warnings+", "warning"),
                ("Cond1: Errors", "error"),
            ),
            "secondary_filters": (
                ("Cond2: All", "all"),
                ("Cond2: CPU", "cpu"),
                ("Cond2: Memory", "memory"),
                ("Cond2: Pod Usage", "pods"),
            ),
            "sorts": (
                ("Sort: None", "none"),
                ("Sort: Name", "idx:0"),
                ("Sort: Node Group", "idx:1"),
                ("Sort: Pod Usage", "idx:2"),
                ("Sort: CPU Req/Alloc", "idx:3"),
                ("Sort: Mem Req/Alloc", "idx:4"),
                ("Sort: CPU Lim/Alloc", "idx:5"),
                ("Sort: Mem Lim/Alloc", "idx:6"),
            ),
        },
        "tab-pods": {
            "filters": (
                ("Cond1: All", "all"),
                ("Cond1: High Usage", "high_usage"),
                ("Cond1: Warnings+", "warning"),
            ),
            "secondary_filters": (
                ("Cond2: All", "all"),
                ("Cond2: CPU", "cpu"),
                ("Cond2: Memory", "memory"),
                ("Cond2: Pod Count", "pods"),
            ),
            "sorts": (
                ("Sort: None", "none"),
                ("Sort: Col 1", "idx:0"),
                ("Sort: Col 2", "idx:1"),
                ("Sort: Col 3", "idx:2"),
            ),
        },
        "tab-pdbs": {
            "filters": (
                ("Cond1: All", "all"),
                ("Cond1: Blocking", "blocking"),
                ("Cond1: Warnings+", "warning"),
                ("Cond1: Errors", "error"),
            ),
            "secondary_filters": (
                ("Cond2: All", "all"),
                ("Cond2: Blocking", "blocking"),
                ("Cond2: Non-zero", "non_zero"),
            ),
            "sorts": (
                ("Sort: None", "none"),
                ("Sort: Namespace", "idx:0"),
                ("Sort: Name/Metric", "idx:1"),
                ("Sort: Status", "idx:8"),
            ),
        },
        "tab-single-replica": {
            "filters": (
                ("Cond1: All", "all"),
                ("Cond1: Not Ready", "not_ready"),
                ("Cond1: Errors", "error"),
            ),
            "secondary_filters": (
                ("Cond2: All", "all"),
                ("Cond2: Not Ready", "not_ready"),
                ("Cond2: Non-zero", "non_zero"),
            ),
            "sorts": (
                ("Sort: None", "none"),
                ("Sort: Namespace", "idx:0"),
                ("Sort: Name", "idx:1"),
                ("Sort: Replicas", "idx:3"),
                ("Sort: Status", "idx:6"),
            ),
        },
        "tab-health": {
            "filters": (
                ("Cond1: All", "all"),
                ("Cond1: Not Ready", "not_ready"),
                ("Cond1: Warnings+", "warning"),
                ("Cond1: Errors", "error"),
            ),
            "secondary_filters": (
                ("Cond2: All", "all"),
                ("Cond2: Not Ready", "not_ready"),
                ("Cond2: Warning", "warning"),
            ),
            "sorts": (
                ("Sort: None", "none"),
                ("Sort: Condition/Taint", "idx:0"),
                ("Sort: True/Effect", "idx:1"),
                ("Sort: False/Occurrences", "idx:2"),
            ),
        },
        "tab-node-dist": {
            "filters": (
                ("Cond1: All", "all"),
                ("Cond1: Non-zero", "non_zero"),
            ),
            "secondary_filters": (
                ("Cond2: All", "all"),
                ("Cond2: Non-zero", "non_zero"),
            ),
            "sorts": (
                ("Sort: None", "none"),
                ("Sort: Label", "idx:0"),
                ("Sort: Count", "idx:1"),
            ),
        },
        "tab-groups": {
            "filters": (
                ("Cond1: All", "all"),
                ("Cond1: High Usage", "high_usage"),
                ("Cond1: Warnings+", "warning"),
            ),
            "secondary_filters": (
                ("Cond2: All", "all"),
                ("Cond2: High Usage", "high_usage"),
                ("Cond2: Pod Count", "pods"),
            ),
            "sorts": (
                ("Sort: None", "none"),
                ("Sort: Group/Node", "idx:0"),
                ("Sort: Nodes/Pods", "idx:1"),
                ("Sort: Usage", "idx:4"),
            ),
        },
        "tab-stats": {
            "filters": (
                ("Cond1: All", "all"),
                ("Cond1: Non-zero", "non_zero"),
                ("Cond1: Warnings+", "warning"),
            ),
            "secondary_filters": (
                ("Cond2: All", "all"),
                ("Cond2: Non-zero", "non_zero"),
            ),
            "sorts": (
                ("Sort: None", "none"),
                ("Sort: Category", "idx:0"),
                ("Sort: Metric", "idx:1"),
                ("Sort: Value", "idx:2"),
            ),
        },
    }
    _SORT_ORDER_OPTIONS: tuple[tuple[str, str], ...] = (
        ("Asc", "asc"),
        ("Desc", "desc"),
    )
    _POD_STATS_UNIT_MODE_MILLI = "m_mi"
    _POD_STATS_UNIT_MODE_CORE_GB = "core_gb"
    _POD_STATS_UNIT_OPTIONS: tuple[tuple[str, str], ...] = (
        ("Units: m/Mi", _POD_STATS_UNIT_MODE_MILLI),
        ("Units: core/GB", _POD_STATS_UNIT_MODE_CORE_GB),
    )
    _NODE_DISTRIBUTION_UNIT_MODE_MILLI_GI = "m_gi"
    _NODE_DISTRIBUTION_UNIT_MODE_CORE_GB = "core_gb"
    _NODE_DISTRIBUTION_UNIT_OPTIONS: tuple[tuple[str, str], ...] = (
        ("Units: m/Gi", _NODE_DISTRIBUTION_UNIT_MODE_MILLI_GI),
        ("Units: core/GB", _NODE_DISTRIBUTION_UNIT_MODE_CORE_GB),
    )
    CSS_PATH = "../../css/screens/cluster_screen.tcss"

    def __init__(self, context: str | None = None) -> None:
        ScreenNavigator.__init__(self, None)
        Screen.__init__(self)
        # Initialize WorkerMixin attributes (not calling WorkerMixin.__init__
        # to avoid double-init through MRO super() chain)
        self._load_start_time: float | None = None
        self._active_worker_name: str | None = None
        self._cluster_context: str | None = context
        self._presenter = ClusterPresenter(self)
        self._error_message: str | None = None
        self._last_updated: datetime | None = None
        self._loading_message: str = ""
        self._is_refreshing: bool = False
        self._tab_loading_states: dict[str, dict] = {}
        self._tab_last_updated: dict[str, str] = {}
        self._populated_tabs: set[str] = set()
        self._data_loaded: bool = False
        self._search_timer: object | None = None
        self._syncing_search_inputs: bool = False
        self._cached_search_inputs: dict[str, Any] = {}
        self._resize_debounce_timer: Timer | None = None
        self._source_refresh_timer: Timer | None = None
        self._status_refresh_timer: Timer | None = None
        self._connection_stall_timer: Timer | None = None
        self._connection_phase_started_at: float | None = None
        self._pending_source_tabs: set[str] = set()
        self._pending_source_keys: set[str] = set()
        self._progress_seen_source_keys: set[str] = set()
        self._last_source_refresh_at = 0.0
        self._refresh_on_resume = False
        self._status_on_resume = False
        self._reload_data_on_resume = False
        self._active_tab_id: str = TAB_NODES
        self._ignore_next_cluster_tab_id: str | None = None
        self._tab_labels_compact: bool | None = None
        self._tab_controls_layout_mode: str | None = None
        self._tab_height_layout_mode: str | None = None
        self._cluster_load_progress: int = 0
        self._cluster_progress_display: int = 0
        self._cluster_progress_target: int = 0
        self._cluster_progress_animation_timer: Timer | None = None
        self._tab_column_filter_values: dict[str, dict[str, set[str]]] = {}
        self._tab_column_filter_options: dict[
            str,
            dict[str, tuple[str, tuple[tuple[str, str], ...]]],
        ] = {}
        self._tab_sort_values: dict[str, str] = {}
        self._tab_sort_order_values: dict[str, str] = {}
        self._tab_filter_source_signatures: dict[str, int] = {}
        self._tab_filter_last_sync_at: dict[str, float] = {}
        self._tab_filter_truncated_columns: dict[str, int] = {}
        self._last_filter_truncated_column_count: int = 0
        self._progress_is_error: bool = False
        for tab_id in self.TAB_IDS:
            profile = self._get_tab_control_profile(tab_id)
            self._tab_column_filter_values[tab_id] = {}
            self._tab_column_filter_options[tab_id] = {}
            self._tab_sort_values[tab_id] = profile["sorts"][0][1]
            self._tab_sort_order_values[tab_id] = self._SORT_ORDER_OPTIONS[0][1]
            self._tab_filter_truncated_columns[tab_id] = 0
        self._table_sort: str = self._tab_sort_values.get(TAB_NODES, "none")
        self._table_sort_order: str = self._tab_sort_order_values.get(TAB_NODES, "asc")
        self._table_column_signatures: dict[str, tuple[str, ...]] = {}
        self._table_row_signatures: dict[str, int] = {}
        self._event_window_hours_value = CLUSTER_EVENT_WINDOW_DEFAULT
        self._status_widget_cache: dict[str, CustomStatic] = {}
        self._digits_widget_cache: dict[str, CustomDigits] = {}
        self._summary_digit_indicator_timers: dict[str, Timer] = {}
        self._summary_digit_default_emphasis: dict[str, str] = {}
        self._last_status_snapshot: tuple[str, int, str] | None = None
        self._pod_stats_unit_mode = self._POD_STATS_UNIT_MODE_MILLI
        self._node_distribution_unit_mode = self._NODE_DISTRIBUTION_UNIT_MODE_MILLI_GI
        self._presenter.set_event_window_hours(self._event_window_hours())

    @property
    def context(self) -> str | None:
        """Get the cluster context (for test compatibility)."""
        return self._cluster_context

    def _table_overlay_id(self, table_id: str) -> str:
        """Return stable overlay id for a table widget id."""
        return f"{table_id}-loading"

    def _compose_table_surface(self, table_id: str, loading_message: str) -> CustomContainer:
        """Compose a table inside a fixed surface with a local loading overlay."""
        return CustomContainer(
            CustomDataTable(id=table_id, zebra_stripes=True),
            CustomContainer(
                CustomLoadingIndicator(classes="table-loading-indicator"),
                CustomStatic(
                    loading_message,
                    classes="table-loading-label",
                    markup=False,
                ),
                id=self._table_overlay_id(table_id),
                classes="table-loading-overlay",
            ),
            id=f"{table_id}-surface",
            classes="cluster-table-surface",
        )

    def _compose_table_panel(
        self,
        title: str,
        table_id: str,
        loading_message: str,
        *,
        panel_id: str | None = None,
    ) -> CustomContainer:
        """Compose a titled table panel with consistent visual sizing."""
        return CustomContainer(
            CustomStatic(f"[b]{title}[/b]", classes="section-title"),
            self._compose_table_surface(table_id, loading_message),
            id=panel_id,
            classes="cluster-data-panel",
        )

    def _compose_summary_digit_item(
        self,
        label: str,
        digit_id: str,
        *,
        emphasis: str = "success",
        use_digits: bool = True,
        classes: str = "",
    ) -> CustomContainer:
        """Compose one labeled digits metric cell used in summary panels."""
        cell_classes = "summary-digit-item"
        if classes:
            cell_classes = f"{cell_classes} {classes}"
        self._summary_digit_default_emphasis[digit_id] = emphasis
        indicator_class = f"summary-digit-indicator status-{emphasis}"
        value_widget: CustomDigits | CustomStatic
        if use_digits:
            value_widget = CustomDigits(
                "0",
                align="center",
                emphasis=emphasis,
                id=digit_id,
                classes="summary-digit-value",
            )
        else:
            value_widget = CustomStatic(
                "0",
                id=digit_id,
                classes="summary-digit-value summary-digit-text-value",
                markup=False,
            )
        return CustomContainer(
            CustomHorizontal(
                CustomStatic(
                    " ",
                    id=f"{digit_id}-indicator",
                    classes=indicator_class,
                    markup=False,
                ),
                CustomStatic(label, classes="summary-digit-label", markup=False),
                CustomStatic("", classes="summary-digit-indicator-spacer", markup=False),
                classes="summary-digit-header",
            ),
            value_widget,
            classes=cell_classes,
        )

    def _compose_summary_digit_pair_item(
        self,
        label: str,
        req_digit_id: str,
        lim_digit_id: str,
        *,
        emphasis: str = "success",
        classes: str = "",
    ) -> CustomContainer:
        """Compose one labeled metric cell with separate request/limit digits."""
        cell_classes = "summary-digit-item summary-digit-item-pair"
        if classes:
            cell_classes = f"{cell_classes} {classes}"
        self._summary_digit_default_emphasis[req_digit_id] = emphasis
        self._summary_digit_default_emphasis[lim_digit_id] = emphasis
        indicator_class = f"summary-digit-indicator status-{emphasis}"
        return CustomContainer(
            CustomHorizontal(
                CustomStatic(
                    " ",
                    id=f"{req_digit_id}-indicator",
                    classes=indicator_class,
                    markup=False,
                ),
                CustomStatic(label, classes="summary-digit-label", markup=False),
                CustomStatic("", classes="summary-digit-indicator-spacer", markup=False),
                classes="summary-digit-header",
            ),
            CustomHorizontal(
                CustomContainer(
                    CustomStatic("Request", classes="summary-digit-pair-label", markup=False),
                    CustomDigits(
                        "0",
                        align="center",
                        emphasis=emphasis,
                        id=req_digit_id,
                        classes="summary-digit-value summary-digit-pair-value",
                    ),
                    classes="summary-digit-pair-block",
                ),
                CustomContainer(
                    CustomStatic("Limit", classes="summary-digit-pair-label", markup=False),
                    CustomDigits(
                        "0",
                        align="center",
                        emphasis=emphasis,
                        id=lim_digit_id,
                        classes="summary-digit-value summary-digit-pair-value",
                    ),
                    classes="summary-digit-pair-block",
                ),
                classes="summary-digit-pair-values",
            ),
            classes=cell_classes,
        )

    def _compose_tab_loading_overlay(self, tab_id: str) -> CustomContainer:
        """Compose full-pane loading overlay for one tab."""
        loading_id = self._TAB_LOADING_IDS.get(tab_id, f"{tab_id}-loading")
        base_label = self._TAB_LOADING_BASE_MESSAGES.get(tab_id, "Loading...")
        return CustomContainer(
            CustomContainer(
                CustomLoadingIndicator(classes="tab-loading-indicator"),
                CustomStatic(
                    base_label,
                    id=f"{loading_id}-label",
                    classes="tab-loading-label",
                    markup=False,
                ),
                CustomStatic(
                    "Waiting for cluster data sources...",
                    id=f"{loading_id}-status",
                    classes="tab-loading-status",
                    markup=False,
                ),
                classes="tab-loading-stack",
            ),
            id=loading_id,
            classes="tab-loading-overlay",
        )

    def _set_pod_stats_units_mode(self, unit_mode: str) -> None:
        """Set pod stats units mode and refresh pod stats digits."""
        if unit_mode not in {
            self._POD_STATS_UNIT_MODE_MILLI,
            self._POD_STATS_UNIT_MODE_CORE_GB,
        }:
            return
        if self._pod_stats_unit_mode == unit_mode:
            return
        self._pod_stats_unit_mode = unit_mode
        self._update_overview_pod_stats_widgets(self._presenter)

    def _set_node_distribution_units_mode(self, unit_mode: str) -> None:
        """Set node distribution units mode and refresh totals digits."""
        if unit_mode not in {
            self._NODE_DISTRIBUTION_UNIT_MODE_MILLI_GI,
            self._NODE_DISTRIBUTION_UNIT_MODE_CORE_GB,
        }:
            return
        if self._node_distribution_unit_mode == unit_mode:
            return
        self._node_distribution_unit_mode = unit_mode
        self._update_nodes_summary_widgets(self._presenter)

    def _set_table_overlay_visible(self, table_id: str, visible: bool) -> None:
        """Toggle one table overlay visibility."""
        overlay_id = self._table_overlay_id(table_id)
        with suppress(NoMatches):
            overlay = self.query_one(f"#{overlay_id}", CustomContainer)
            if visible:
                overlay.remove_class("hidden")
            else:
                overlay.add_class("hidden")

    def _set_tab_table_overlays_visible(self, tab_id: str, visible: bool) -> None:
        """Toggle all table overlays that belong to a tab."""
        for table_id in self._TAB_TABLE_IDS.get(tab_id, ()):
            self._set_table_overlay_visible(table_id, visible)

    def _set_all_table_overlays_visible(self, visible: bool) -> None:
        """Toggle all per-table overlays across cluster tabs."""
        for tab_id in self.TAB_IDS:
            self._set_tab_table_overlays_visible(tab_id, visible)

    def _set_tab_loading_overlay_visible(self, tab_id: str, visible: bool) -> None:
        """Toggle one tab-level loading overlay visibility."""
        loading_id = self._TAB_LOADING_IDS.get(tab_id)
        if not loading_id:
            return
        with suppress(NoMatches):
            overlay = self.query_one(f"#{loading_id}", CustomContainer)
            if visible:
                overlay.remove_class("hidden")
            else:
                overlay.add_class("hidden")

    def _set_tab_loading_text(
        self,
        tab_id: str,
        *,
        label_text: str | None = None,
        status_text: str | None = None,
    ) -> None:
        """Update loading overlay label/status text for a tab."""
        loading_id = self._TAB_LOADING_IDS.get(tab_id)
        if not loading_id:
            return
        if label_text is not None:
            with suppress(NoMatches):
                self.query_one(f"#{loading_id}-label", CustomStatic).update(label_text)
        if status_text is not None:
            with suppress(NoMatches):
                self.query_one(f"#{loading_id}-status", CustomStatic).update(status_text)

    def _get_cached_static(self, widget_id: str) -> CustomStatic | None:
        """Return cached static widget by id, querying only when needed."""
        cached = self._status_widget_cache.get(widget_id)
        if cached is not None:
            return cached
        with suppress(NoMatches):
            widget = self.query_one(f"#{widget_id}", CustomStatic)
            self._status_widget_cache[widget_id] = widget
            return widget
        return None

    def _get_cached_digits(self, widget_id: str) -> CustomDigits | None:
        """Return cached digits widget by id, querying only when needed."""
        cached = self._digits_widget_cache.get(widget_id)
        if cached is not None:
            return cached
        with suppress(NoMatches, WrongType):
            widget = self.query_one(f"#{widget_id}", CustomDigits)
            self._digits_widget_cache[widget_id] = widget
            return widget
        return None

    def _get_cached_metric_static(self, widget_id: str) -> CustomStatic | None:
        """Return cached static metric widget by id when digits are not used."""
        with suppress(NoMatches, WrongType):
            widget = self.query_one(f"#{widget_id}", CustomStatic)
            return widget
        return None

    def _hide_summary_digit_indicator(
        self,
        widget_id: str,
        *,
        final_indicator: str = " ",
    ) -> None:
        """Resolve one summary digit update indicator to its final symbol."""
        self._summary_digit_indicator_timers.pop(widget_id, None)
        with suppress(NoMatches):
            self.query_one(f"#{widget_id}-indicator", CustomStatic).update(final_indicator)

    def _schedule_summary_digit_indicator_hide(
        self,
        widget_id: str,
        *,
        final_indicator: str = " ",
    ) -> None:
        """Debounce final indicator resolution for a summary digit update."""
        existing_timer = self._summary_digit_indicator_timers.pop(widget_id, None)
        if existing_timer is not None:
            with suppress(Exception):
                existing_timer.stop()
        self._summary_digit_indicator_timers[widget_id] = self.set_timer(
            self._SUMMARY_DIGIT_UPDATE_INDICATOR_SECONDS,
            lambda wid=widget_id, symbol=final_indicator: self._hide_summary_digit_indicator(
                wid,
                final_indicator=symbol,
            ),
        )

    def _clear_summary_digit_indicators(self) -> None:
        """Stop indicator timers and hide all active summary digit indicators."""
        for widget_id, timer in tuple(self._summary_digit_indicator_timers.items()):
            with suppress(Exception):
                timer.stop()
            with suppress(NoMatches):
                self.query_one(f"#{widget_id}-indicator", CustomStatic).update(" ")
        self._summary_digit_indicator_timers.clear()

    def _reset_summary_widgets_for_refresh(self) -> None:
        """Reset summary widgets to their compose-time baseline before reload."""
        status_classes = ("success", "warning", "error", "muted", "accent")
        panel_status_classes = tuple(f"status-{name}" for name in status_classes)
        self._clear_summary_digit_indicators()

        with suppress(Exception):
            for widget in self.query(".summary-digit-value"):
                if not isinstance(widget, CustomDigits):
                    continue
                widget.update("0")
                widget.tooltip = None

                widget_id = str(widget.id or "")
                default_status = self._summary_digit_default_emphasis.get(
                    widget_id,
                    "success",
                )
                for class_name in status_classes:
                    widget.remove_class(class_name)
                widget.add_class(default_status)

                if not widget_id:
                    continue
                with suppress(NoMatches):
                    indicator = self.query_one(f"#{widget_id}-indicator", CustomStatic)
                    for class_name in panel_status_classes:
                        indicator.remove_class(class_name)
                    indicator.add_class(f"status-{default_status}")
                    indicator.update(" ")

        # Force next status-bar update after refresh, even when values match.
        self._last_updated = None
        self._last_status_snapshot = None
        for widget_id, initial_value in (
            ("cluster-name", "Unknown"),
            ("node-count", "0"),
            ("last-updated", "Never"),
        ):
            widget = self._get_cached_static(widget_id)
            if widget is not None:
                widget.update(initial_value)

    def _get_tab_control_profile(
        self, tab_id: str
    ) -> dict[str, tuple[tuple[str, str], ...]]:
        """Return filter/sort control profile for a tab."""
        return self._TAB_CONTROL_PROFILES.get(
            tab_id,
            self._TAB_CONTROL_PROFILES[TAB_NODES],
        )

    def _control_id(self, tab_id: str, suffix: str) -> str:
        """Build stable control widget id for a tab + control suffix."""
        return f"ctl-{tab_id}-{suffix}"

    def _inline_loading_bar_id(self, tab_id: str) -> str:
        """Widget id for per-tab inline loading bar in Sort group."""
        return self._control_id(tab_id, "loading-bar")

    def _inline_progress_bar_id(self, tab_id: str) -> str:
        """Widget id for per-tab inline progress bar in Sort group."""
        return self._control_id(tab_id, "progress-bar")

    def _inline_loading_text_id(self, tab_id: str) -> str:
        """Widget id for per-tab inline loading text in Sort group."""
        return self._control_id(tab_id, "loading-text")

    @staticmethod
    def _event_window_label_for(hours_value: str, *, compact: bool = False) -> str:
        """Resolve label for an event lookback option value."""
        for label, value in CLUSTER_EVENT_WINDOW_OPTIONS:
            if value == hours_value:
                resolved = label
                break
        else:
            resolved = CLUSTER_EVENT_WINDOW_OPTIONS[0][0]
        if compact:
            return resolved.removeprefix("Last ").strip()
        return resolved

    def _event_window_select_options(self, mode: str | None = None) -> list[tuple[str, str]]:
        """Build event lookback options for top bar selector."""
        resolved_mode = mode or self._get_tab_controls_layout_mode()
        prefix = self._EVENT_WINDOW_PREFIX_BY_MODE.get(resolved_mode, "Events:")
        compact_labels = True
        return [
            (
                f"{prefix} {self._event_window_label_for(value, compact=compact_labels)}".strip(),
                value,
            )
            for _, value in CLUSTER_EVENT_WINDOW_OPTIONS
        ]

    def _event_window_hours(self) -> float:
        """Parse selected event lookback hours value."""
        try:
            return float(self._event_window_hours_value)
        except (TypeError, ValueError):
            return self._presenter.event_window_hours

    def _filter_container_id(self, tab_id: str) -> str:
        """Widget id for a tab's dynamic filter-row container."""
        return self._control_id(tab_id, "filters")

    def _column_filter_control_id(self, tab_id: str, column_slug: str) -> str:
        """Widget id for a dynamic column-filter select in a tab."""
        return f"ctl-{tab_id}-filter-col-{column_slug}"

    def _parse_column_filter_control_id(
        self, control_id: str | None
    ) -> tuple[str, str] | None:
        """Parse tab id + column slug from dynamic column-filter control id."""
        if not control_id:
            return None
        marker = "-filter-col-"
        if not control_id.startswith("ctl-") or marker not in control_id:
            return None
        left, column_slug = control_id.rsplit(marker, 1)
        tab_id = left.removeprefix("ctl-")
        if not column_slug or tab_id not in self.TAB_IDS:
            return None
        return tab_id, column_slug

    def _tab_id_from_control_id(self, control_id: str | None, suffix: str) -> str | None:
        """Parse tab id from control id."""
        if not control_id:
            return None
        prefix = "ctl-"
        suffix_token = f"-{suffix}"
        if not control_id.startswith(prefix) or not control_id.endswith(suffix_token):
            return None
        return control_id[len(prefix):-len(suffix_token)]

    def _compose_tab_controls(self, tab_id: str) -> CustomContainer:
        """Compose per-tab filter/sort controls inside tab content area."""
        profile = self._get_tab_control_profile(tab_id)
        return CustomContainer(
            CustomHorizontal(
                CustomContainer(
                    CustomStatic(
                        "Search",
                        classes="optimizer-filter-group-title",
                        markup=False,
                    ),
                    CustomVertical(
                        CustomHorizontal(
                            CustomInput(
                                placeholder="Search...",
                                value=self.search_query,
                                id=self._control_id(tab_id, "search-input"),
                                classes="cluster-tab-search-input",
                            ),
                            CustomButton(
                                "Search",
                                id=self._control_id(tab_id, "search-btn"),
                                classes="cluster-tab-search-btn",
                            ),
                            CustomButton(
                                "Clear",
                                id=self._control_id(tab_id, "clear-btn"),
                                classes="cluster-tab-clear-btn",
                            ),
                            classes="cluster-tab-search-row",
                        ),
                        classes="optimizer-filter-group-body",
                    ),
                    classes="optimizer-filter-group cluster-tab-control-group cluster-tab-control-group-search",
                ),
                CustomContainer(
                    CustomStatic(
                        "Filter",
                        classes="optimizer-filter-group-title",
                        markup=False,
                    ),
                    CustomHorizontal(
                        CustomButton(
                            "Filters",
                            id=self._control_id(tab_id, "filters-btn"),
                            classes="filter-picker-btn cluster-tab-filters-btn",
                        ),
                        classes="optimizer-filter-group-body filter-control",
                    ),
                    classes="optimizer-filter-group cluster-tab-control-group cluster-tab-control-group-filters",
                ),
                CustomContainer(
                    CustomStatic(
                        "Sort",
                        classes="optimizer-filter-group-title",
                        markup=False,
                    ),
                    CustomHorizontal(
                        CustomHorizontal(
                            Select[str](
                                profile["sorts"],
                                value=self._tab_sort_values.get(
                                    tab_id, profile["sorts"][0][1]
                                ),
                                allow_blank=False,
                                id=self._control_id(tab_id, "sort"),
                                classes="cluster-tab-control-select cluster-tab-sort filter-select",
                            ),
                            Select[str](
                                self._SORT_ORDER_OPTIONS,
                                value=self._tab_sort_order_values.get(
                                    tab_id, self._SORT_ORDER_OPTIONS[0][1]
                                ),
                                allow_blank=False,
                                id=self._control_id(tab_id, "order"),
                                classes="cluster-tab-control-select cluster-tab-order filter-select",
                            ),
                            classes="cluster-tab-sort-controls",
                        ),
                        classes="optimizer-filter-group-body",
                    ),
                    classes="optimizer-filter-group cluster-tab-control-group cluster-tab-control-group-sort",
                ),
                classes="cluster-tab-controls-row cluster-filter-row",
            ),
            classes="cluster-tab-controls cluster-filter-bar",
        )

    def compose(self) -> ComposeResult:
        yield CustomHeader()
        yield self.compose_main_navigation_tabs(active_tab_id=MAIN_NAV_TAB_CLUSTER)

        with CustomHorizontal(id="cluster-search-bar"):
            with CustomHorizontal(id="cluster-top-controls-left"):
                yield Select[str](
                    self._event_window_select_options(),
                    value=self._event_window_hours_value,
                    allow_blank=False,
                    id=_EVENT_WINDOW_SELECT_ID,
                    classes="cluster-event-window-select",
                )
                yield CustomButton("Refresh", id="refresh-btn")
            with CustomHorizontal(id="cluster-loading-bar"):
                yield CustomStatic("", id="cluster-loading-spacer", markup=False)
                yield CustomHorizontal(
                    _ForwardGradientProgressBar(
                        total=100,
                        show_percentage=False,
                        show_eta=False,
                        gradient=self._CLUSTER_PROGRESS_GRADIENT,
                        id="cluster-progress-bar",
                    ),
                    CustomStatic("0% - Initializing...", id="loading-text", markup=False),
                    id="cluster-progress-container",
                )

        with CustomHorizontal(id="cluster-view-tabs-row"):
            yield CustomTabs(
                id="cluster-view-tabs",
                tabs=[
                    {"id": "tab-nodes", "label": TAB_LABELS_FULL["tab-nodes"]},
                    {"id": "tab-pods", "label": TAB_LABELS_FULL["tab-pods"]},
                    {"id": "tab-events", "label": TAB_LABELS_FULL["tab-events"]},
                ],
                active=TAB_NODES,
            )

        with ContentSwitcher(id="cluster-inner-switcher", initial=TAB_NODES):
            with CustomContainer(id="tab-events", classes="cluster-tab-pane"):
                yield self._compose_tab_controls("tab-events")
                with CustomContainer(id="events-main-grid", classes="summary-grid summary-grid-1"):
                    with CustomContainer(
                        id="events-panel-summary",
                        classes="summary-panel summary-events-metrics-panel",
                    ):
                        yield CustomStatic(
                            "[b]Event Summary[/b]",
                            classes="section-title summary-section-title",
                        )
                        yield CustomContainer(
                            self._compose_summary_digit_item(
                                "OOM Killing",
                                "events-digits-oomkilling",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Node Not Ready",
                                "events-digits-nodenotready",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Failed Scheduling",
                                "events-digits-failedscheduling",
                                emphasis="error",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "BackOff",
                                "events-digits-backoff",
                                emphasis="error",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Unhealthy",
                                "events-digits-unhealthy",
                                emphasis="error",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Failed Mount",
                                "events-digits-failedmount",
                                emphasis="error",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Evicted",
                                "events-digits-evicted",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            id="events-summary-digits-grid",
                            classes="summary-digits-grid summary-digits-grid-4",
                        )
                    yield self._compose_table_panel(
                        "Events Detail",
                        "events-detail-table",
                        "Loading event details...",
                        panel_id="events-detail-table-panel",
                    )

            with CustomContainer(id="tab-nodes", classes="cluster-tab-pane"):
                yield self._compose_tab_controls("tab-nodes")
                with CustomContainer(id="nodes-main-grid"):
                    with CustomContainer(
                        id="nodes-panel-health-summary",
                        classes="summary-panel summary-metrics-panel",
                    ):
                        yield CustomStatic(
                            "[b]Node Health Summary[/b]",
                            classes="section-title summary-section-title",
                        )
                        yield CustomContainer(
                            self._compose_summary_digit_item(
                                "Ready",
                                "nodes-digits-ready",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Not Ready",
                                "nodes-digits-not-ready",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Condition Alerts",
                                "nodes-digits-cond-alerts",
                                emphasis="error",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Unknown Conditions",
                                "nodes-digits-cond-unknown",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Tainted Nodes",
                                "nodes-digits-tainted",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "High Pod Nodes",
                                "nodes-digits-high-pod",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            id="nodes-health-digits-grid",
                            classes="summary-digits-grid summary-digits-grid-3 summary-digits-grid-tight",
                        )
                    with CustomContainer(
                        id="nodes-panel-distribution-summary",
                        classes="summary-panel summary-metrics-panel",
                    ):
                        yield CustomStatic(
                            "[b]Node Distribution Summary[/b]",
                            classes="section-title summary-section-title",
                        )
                        yield CustomHorizontal(
                            Select[str](
                                self._NODE_DISTRIBUTION_UNIT_OPTIONS,
                                value=self._node_distribution_unit_mode,
                                allow_blank=False,
                                id=_NODE_DISTRIBUTION_UNITS_SELECT_ID,
                                classes="pod-stats-units-select",
                            ),
                            classes="pod-stats-units-row",
                        )
                        yield CustomContainer(
                            self._compose_summary_digit_item(
                                "Availability Zones",
                                "nodes-digits-az-count",
                                emphasis="accent",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Instance Types",
                                "nodes-digits-instance-types",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Kubelet Versions",
                                "nodes-digits-kubelet-vers",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Node Groups",
                                "nodes-digits-group-count",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Total CPU",
                                "nodes-digits-total-cpu",
                                emphasis="accent",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Total Mem",
                                "nodes-digits-total-mem",
                                emphasis="accent",
                                classes="summary-digit-item-compact",
                            ),
                            id="nodes-distribution-digits-grid",
                            classes="summary-digits-grid summary-digits-grid-3 summary-digits-grid-tight",
                        )
                    with CustomContainer(
                        id="nodes-panel-cpu-alloc",
                        classes="summary-panel summary-metrics-panel",
                    ):
                        yield CustomStatic(
                            "[b]Node CPU Allocation Analysis[/b]",
                            classes="section-title summary-section-title",
                        )
                        yield CustomContainer(
                            self._compose_summary_digit_item(
                                "CPU Request Avg",
                                "overview-alloc-cpu-req-avg",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "CPU Request Max",
                                "overview-alloc-cpu-req-max",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "CPU Request P95",
                                "overview-alloc-cpu-req-p95",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "CPU Limit Avg",
                                "overview-alloc-cpu-lim-avg",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "CPU Limit Max",
                                "overview-alloc-cpu-lim-max",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "CPU Limit P95",
                                "overview-alloc-cpu-lim-p95",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            id="overview-cpu-alloc-grid",
                            classes="summary-digits-grid summary-digits-grid-3 summary-digits-grid-tight",
                        )
                    with CustomContainer(
                        id="nodes-panel-mem-alloc",
                        classes="summary-panel summary-metrics-panel",
                    ):
                        yield CustomStatic(
                            "[b]Node Memory Allocation Analysis[/b]",
                            classes="section-title summary-section-title",
                        )
                        yield CustomContainer(
                            self._compose_summary_digit_item(
                                "Memory Request Avg",
                                "overview-alloc-mem-req-avg",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Memory Request Max",
                                "overview-alloc-mem-req-max",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Memory Request P95",
                                "overview-alloc-mem-req-p95",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Memory Limit Avg",
                                "overview-alloc-mem-lim-avg",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Memory Limit Max",
                                "overview-alloc-mem-lim-max",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Memory Limit P95",
                                "overview-alloc-mem-lim-p95",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            id="overview-mem-alloc-grid",
                            classes="summary-digits-grid summary-digits-grid-3 summary-digits-grid-tight",
                        )
                    yield self._compose_table_panel(
                        "Node Inventory",
                        "nodes-table",
                        "Loading node inventory...",
                        panel_id="nodes-table-panel",
                    )
                    yield self._compose_table_panel(
                        "Node Groups",
                        "node-groups-table",
                        "Loading node groups...",
                        panel_id="node-groups-table-panel",
                    )

            # Tab 3: Workloads — request/limit stats + workload footprint
            with CustomContainer(id="tab-pods", classes="cluster-tab-pane"):
                yield self._compose_tab_controls("tab-pods")
                with CustomContainer(
                    id="workloads-main-grid",
                ):
                    with CustomContainer(
                        id="workloads-panel-pod-request-stats",
                        classes="summary-panel summary-metrics-panel",
                    ):
                        yield CustomStatic(
                            "[b]Pod Request/Limit Statistics[/b]",
                            classes="section-title summary-section-title",
                        )
                        yield CustomHorizontal(
                            Select[str](
                                self._POD_STATS_UNIT_OPTIONS,
                                value=self._pod_stats_unit_mode,
                                allow_blank=False,
                                id=_POD_STATS_UNITS_SELECT_ID,
                                classes="pod-stats-units-select",
                            ),
                            classes="pod-stats-units-row",
                        )
                        yield CustomContainer(
                            self._compose_summary_digit_pair_item(
                                "CPU Request/Limit Min",
                                "overview-pod-cpu-req-min",
                                "overview-pod-cpu-lim-min",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_pair_item(
                                "CPU Request/Limit Avg",
                                "overview-pod-cpu-req-avg",
                                "overview-pod-cpu-lim-avg",
                                emphasis="accent",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_pair_item(
                                "CPU Request/Limit Max",
                                "overview-pod-cpu-req-max",
                                "overview-pod-cpu-lim-max",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_pair_item(
                                "CPU Request/Limit P95",
                                "overview-pod-cpu-req-p95",
                                "overview-pod-cpu-lim-p95",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_pair_item(
                                "Memory Request/Limit Min",
                                "overview-pod-mem-req-min",
                                "overview-pod-mem-lim-min",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_pair_item(
                                "Memory Request/Limit Avg",
                                "overview-pod-mem-req-avg",
                                "overview-pod-mem-lim-avg",
                                emphasis="accent",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_pair_item(
                                "Memory Request/Limit Max",
                                "overview-pod-mem-req-max",
                                "overview-pod-mem-lim-max",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_pair_item(
                                "Memory Request/Limit P95",
                                "overview-pod-mem-req-p95",
                                "overview-pod-mem-lim-p95",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            id="overview-pod-stats-grid",
                            classes="summary-digits-grid summary-digits-grid-4 summary-digits-grid-tight",
                        )
                    with CustomContainer(
                        id="workloads-panel-footprint",
                        classes="summary-panel summary-metrics-panel",
                    ):
                        yield CustomStatic(
                            "[b]Workload Footprint[/b]",
                            classes="section-title summary-section-title",
                        )
                        yield CustomContainer(
                            self._compose_summary_digit_item(
                                "Teams",
                                "workloads-footprint-team-total",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Workloads",
                                "workloads-footprint-workloads-total",
                                emphasis="success",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Single Replica Charts",
                                "workloads-footprint-single-charts",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "Single Replica Ratio",
                                "workloads-footprint-single-ratio",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "No PDB Template",
                                "workloads-footprint-charts-no-template",
                                emphasis="warning",
                                classes="summary-digit-item-compact",
                            ),
                            self._compose_summary_digit_item(
                                "No PDB",
                                "workloads-footprint-charts-no-pdb",
                                emphasis="error",
                                classes="summary-digit-item-compact",
                            ),
                            id="workloads-footprint-grid",
                            classes="summary-digits-grid",
                        )

        yield CustomHorizontal(
            CustomStatic("Cluster: ", classes="status-label"),
            CustomStatic("Unknown", id="cluster-name", classes="status-value"),
            CustomStatic("Nodes: ", classes="status-label"),
            CustomStatic("0", id="node-count", classes="status-value"),
            CustomStatic("Last Updated: ", classes="status-label"),
            CustomStatic("Never", id="last-updated", classes="status-value"),
            id="cluster-status-bar",
        )

        yield CustomFooter()

    def on_mount(self) -> None:
        self.app.title = "KubEagle - Cluster"
        self._set_primary_navigation_tab(MAIN_NAV_TAB_CLUSTER)
        self._enable_primary_navigation_tabs()
        # Apply responsive classes after the first render and again one frame
        # later to absorb terminal-size settling on cold start.
        self.call_after_refresh(self._update_tab_labels)
        self.set_timer(0.05, self._update_tab_labels)
        self._set_active_tab(TAB_NODES)
        # Keep initial focus off the search input so numeric shortcuts switch
        # tabs immediately on screen entry.
        def _focus_shortcuts_anchor() -> None:
            with suppress(NoMatches):
                self.query_one("#refresh-btn", CustomButton).focus()

        self.set_timer(0.15, _focus_shortcuts_anchor)
        self._set_cluster_progress(0, "Initializing...")
        if bool(getattr(self.app, "skip_eks", False)):
            self._data_loaded = True
            self._set_inline_loading_bars_visible(True)
            self._hide_all_loading_indicators()
            self._set_all_table_overlays_visible(False)
            self._set_cluster_progress(100, "Cluster analysis disabled (--skip-eks)")
            self._refresh_tab(self._get_active_tab_id())
            self._update_status_bar()
            return
        self._start_connection_stall_watchdog()
        self._presenter.load_data()

    def on_resize(self, _: Resize) -> None:
        """Keep tab labels compact on narrow terminals to prevent wrapping."""
        self._schedule_resize_update()

    def on_unmount(self) -> None:
        """Cancel all workers and timers when screen is removed from DOM."""
        self._stop_connection_stall_watchdog()
        self._cancel_debounce_timers()
        with suppress(Exception):
            self.workers.cancel_all()

    def on_screen_suspend(self) -> None:
        """Pause debounce timers while this screen is inactive."""
        self._stop_connection_stall_watchdog()
        self._release_background_work_for_navigation()

    def prepare_for_screen_switch(self) -> None:
        """Release cluster background work before another screen is activated."""
        self._release_background_work_for_navigation()

    def _release_background_work_for_navigation(self) -> None:
        """Release background work so destination screens can become responsive faster."""
        self._cancel_debounce_timers()
        if self._presenter.is_loading:
            if not self._data_loaded:
                # Keep workers alive — they'll deliver results via message.
                # On resume, if data arrived while away, just render it.
                self._reload_data_on_resume = False
                self._refresh_on_resume = True
                self._status_on_resume = True
                return
            # Once data has started streaming, keep load alive to avoid
            # expensive cancel/restart thrash when users bounce between screens.
            self._reload_data_on_resume = False
            self._refresh_on_resume = True
            self._status_on_resume = True

    def on_screen_resume(self) -> None:
        """Apply deferred refreshes once this screen becomes active again."""
        self.app.title = "KubEagle - Cluster"
        self._set_primary_navigation_tab(MAIN_NAV_TAB_CLUSTER)
        # Re-apply responsive classes after stack navigation; hidden-screen
        # sizing can leave stale compact/tight classes on tab panes.
        self._tab_labels_compact = None
        self._tab_controls_layout_mode = None
        self._tab_height_layout_mode = None
        self.call_after_refresh(self._update_tab_labels)
        # Add one more deferred relayout tick for terminal sessions where
        # resumed screen size settles one frame later than the resume event.
        self.set_timer(0.05, self._update_tab_labels)
        if self._reload_data_on_resume and not self._presenter.is_loading:
            self._reload_data_on_resume = False
            self._data_loaded = False
            self._reset_incremental_load_tracking()
            self._start_connection_stall_watchdog()
            self._presenter.load_data()
            return
        if not self._data_loaded and not self._presenter.is_loading:
            self._reset_incremental_load_tracking()
            self._start_connection_stall_watchdog()
            self._presenter.load_data()
            return
        if self._presenter.is_loading:
            self._start_connection_stall_watchdog()
        if self._refresh_on_resume and self._data_loaded and not self._presenter.is_loading:
            self._refresh_on_resume = False
            self._populated_tabs.discard(self._get_active_tab_id())
            self._refresh_active_tab()
        if self._status_on_resume:
            self._status_on_resume = False
            self._update_status_bar()

    def _cancel_debounce_timers(self) -> None:
        """Stop transient timers that are only useful while this screen is active."""
        for timer_name in (
            "_resize_debounce_timer",
            "_source_refresh_timer",
            "_status_refresh_timer",
            "_search_timer",
            "_cluster_progress_animation_timer",
        ):
            timer = getattr(self, timer_name, None)
            if timer is None:
                continue
            with suppress(Exception):
                timer.stop()
            setattr(self, timer_name, None)
        self._clear_summary_digit_indicators()
        self._stop_connection_stall_watchdog()

    def _reset_incremental_load_tracking(self) -> None:
        """Clear transient state for in-flight incremental source updates."""
        self._pending_source_tabs.clear()
        self._pending_source_keys.clear()
        self._progress_seen_source_keys.clear()
        self._last_source_refresh_at = 0.0
        self._tab_filter_last_sync_at.clear()

    def _schedule_resize_update(self) -> None:
        """Debounce resize-driven tab relayout work."""
        if self._resize_debounce_timer is not None:
            self._resize_debounce_timer.stop()
            self._resize_debounce_timer = None
        self._resize_debounce_timer = self.set_timer(
            self._RESIZE_DEBOUNCE_SECONDS,
            self._run_debounced_resize_update,
        )

    def _run_debounced_resize_update(self) -> None:
        self._resize_debounce_timer = None
        self._update_tab_labels()

    def _update_tab_labels(self) -> None:
        compact_mode = (
            self._current_viewport_width() < self._COMPACT_TAB_LABEL_MIN_WIDTH
            or self._get_tab_controls_layout_mode() == "compact"
        )
        if self._tab_labels_compact is not None and self._tab_labels_compact == compact_mode:
            self._update_tab_controls_layout()
            return
        self._tab_labels_compact = compact_mode
        labels = self._TAB_LABELS_COMPACT if compact_mode else self._TAB_LABELS_FULL
        with suppress(NoMatches):
            tabs = self.query_one("#cluster-view-tabs", CustomTabs)
            for tab_id in self.TAB_IDS:
                label = labels.get(tab_id)
                if not label:
                    continue
                with suppress(Exception):
                    tab_widget = cast(Any, tabs.query_one(f"#{tab_id}"))
                    tab_widget.label = label
                    if hasattr(tab_widget, "_label_text"):
                        tab_widget._label_text = label
        self._update_tab_controls_layout()

    def _get_tab_controls_layout_mode(self) -> str:
        """Return responsive mode for per-tab control groups."""
        width = self._current_viewport_width()
        if width >= self._TAB_CONTROLS_XWIDE_MIN_WIDTH:
            return "xwide"
        if width >= self._TAB_CONTROLS_WIDE_MIN_WIDTH:
            return "wide"
        if width >= self._TAB_CONTROLS_MEDIUM_MIN_WIDTH:
            return "medium"
        if width >= self._TAB_CONTROLS_NARROW_MIN_WIDTH:
            return "narrow"
        return "compact"

    def _get_tab_height_layout_mode(self) -> str:
        """Return responsive mode for tab layouts based on viewport height."""
        height = self._current_viewport_height()
        if height >= self._TAB_HEIGHT_SHORT_MIN_ROWS:
            return "tall"
        if height >= self._TAB_HEIGHT_TIGHT_MIN_ROWS:
            return "short"
        return "tight"

    def _update_tab_controls_layout(self) -> None:
        """Apply width-based layout classes to per-tab control containers."""
        width_mode = self._get_tab_controls_layout_mode()
        height_mode = self._get_tab_height_layout_mode()
        if (
            width_mode == self._tab_controls_layout_mode
            and height_mode == self._tab_height_layout_mode
        ):
            return
        self._tab_controls_layout_mode = width_mode
        self._tab_height_layout_mode = height_mode
        responsive_classes = ("xwide", "wide", "medium", "narrow", "compact")
        responsive_height_classes = ("height-tall", "height-short", "height-tight")
        with suppress(Exception):
            for controls_row in self.query(".cluster-tab-controls-row"):
                for class_name in responsive_classes:
                    controls_row.remove_class(class_name)
                controls_row.add_class(width_mode)
        with suppress(Exception):
            for tab_pane in self.query(".cluster-tab-pane"):
                for class_name in responsive_classes:
                    tab_pane.remove_class(class_name)
                for class_name in responsive_height_classes:
                    tab_pane.remove_class(class_name)
                tab_pane.add_class(width_mode)
                tab_pane.add_class(f"height-{height_mode}")
        for widget_id in ("#cluster-search-bar", "#cluster-loading-bar"):
            with suppress(Exception):
                widget = self.query_one(widget_id, CustomHorizontal)
                for class_name in responsive_classes:
                    widget.remove_class(class_name)
                widget.add_class(width_mode)
        self._apply_top_bar_compact_mode(width_mode)
        if self._loading_message:
            self._set_cluster_progress(
                self._cluster_load_progress,
                self._loading_message,
                is_error=self._progress_is_error,
            )

    def _apply_top_bar_compact_mode(self, mode: str) -> None:
        """Keep top bar controls readable across responsive modes."""
        with suppress(Exception):
            refresh_button = self.query_one("#refresh-btn", CustomButton)
            refresh_button.label = self._REFRESH_BUTTON_LABELS.get(mode, "Refresh")
            refresh_button.tooltip = (
                "Refresh cluster data" if mode in ("narrow", "compact") else None
            )
        with suppress(Exception):
            event_select = self.query_one(f"#{_EVENT_WINDOW_SELECT_ID}", Select[str])
            event_select.set_options(self._event_window_select_options(mode))
            event_select.value = self._event_window_hours_value
            event_select.tooltip = (
                "Event lookback window" if mode in ("narrow", "compact") else None
            )

    # =========================================================================
    # Message Handlers
    # =========================================================================

    def on_cluster_source_loaded(self, event: ClusterSourceLoaded) -> None:
        """Handle incremental data source arrival — refresh affected tabs progressively."""
        if not self._data_loaded:
            # Mark loaded early so tab switching works during progressive load
            self._data_loaded = True
            if self.is_current:
                self._schedule_status_refresh()
            else:
                self._status_on_resume = True

        if not self.is_current:
            self._refresh_on_resume = True
            if event.key == "nodes":
                self._status_on_resume = True
            return

        self._progress_seen_source_keys.add(event.key)
        reverse_map = self._build_reverse_map()
        affected_tabs = reverse_map.get(event.key, [])
        active_tab = self._get_active_tab_id()
        if active_tab in affected_tabs:
            self._populated_tabs.discard(active_tab)
            self._pending_source_tabs.add(active_tab)
            self._schedule_source_refresh()
        self._pending_source_keys.add(event.key)
        self._update_partial_load_progress()

        if event.key == "nodes":
            self._schedule_status_refresh()

    def _schedule_source_refresh(self) -> None:
        """Debounce incremental source updates to avoid refresh storms."""
        if self._source_refresh_timer is not None:
            return
        self._source_refresh_timer = self.set_timer(
            self._SOURCE_REFRESH_DEBOUNCE_SECONDS,
            self._flush_source_refresh,
        )

    def _schedule_status_refresh(self) -> None:
        """Debounce status bar updates during source bursts."""
        if self._status_refresh_timer is not None:
            return
        self._status_refresh_timer = self.set_timer(
            self._STATUS_BAR_DEBOUNCE_SECONDS,
            self._flush_status_refresh,
        )

    def _flush_status_refresh(self) -> None:
        """Flush one pending status update."""
        self._status_refresh_timer = None
        if not self.is_current:
            self._status_on_resume = True
            return
        self._update_status_bar()

    def _flush_source_refresh(self) -> None:
        """Refresh active tab once for a burst of source-loaded events."""
        self._source_refresh_timer = None
        if not self._pending_source_tabs:
            self._pending_source_keys.clear()
            return
        if not self.is_current:
            self._refresh_on_resume = True
            return
        active_tab = self._get_active_tab_id()
        pending = set(self._pending_source_tabs)
        self._pending_source_tabs.clear()
        self._pending_source_keys.clear()
        if active_tab in pending:
            self._refresh_tab(active_tab)
        self._last_source_refresh_at = time.monotonic()
        self._update_status_bar()

    def on_cluster_data_loaded(self, _: ClusterDataLoaded) -> None:
        self._last_updated = datetime.now()
        self._reload_data_on_resume = False
        self._data_loaded = True
        self._stop_connection_stall_watchdog()
        if self._source_refresh_timer is not None:
            self._source_refresh_timer.stop()
            self._source_refresh_timer = None
        if self._status_refresh_timer is not None:
            self._status_refresh_timer.stop()
            self._status_refresh_timer = None
        self._pending_source_tabs.clear()
        self._pending_source_keys.clear()
        self._progress_seen_source_keys.clear()
        self._set_cluster_progress(100, "Cluster data loaded")
        if not self.is_current:
            self._refresh_on_resume = True
            self._status_on_resume = True
            return

        partial_errors = self._presenter.partial_errors
        if partial_errors:
            # Show warning banner for partial failures
            failed_sources = ", ".join(partial_errors.keys())
            self._set_inline_loading_bars_visible(True)
            self._set_cluster_progress(
                100,
                f"Some data unavailable ({failed_sources}) - Press 'R' to retry",
                is_error=True,
            )
        else:
            self._set_inline_loading_bars_visible(True)

        # Hide all per-tab loading indicators
        self._hide_all_loading_indicators()
        self._set_all_table_overlays_visible(False)
        # Final refresh of active tab to ensure all data is shown
        active_tab = self._get_active_tab_id()
        self._populated_tabs.discard(active_tab)
        self._refresh_tab(active_tab)
        self._update_status_bar()

    def on_cluster_data_load_failed(self, event: ClusterDataLoadFailed) -> None:
        self._error_message = event.error
        self._reload_data_on_resume = False
        self._stop_connection_stall_watchdog()
        if self._source_refresh_timer is not None:
            self._source_refresh_timer.stop()
            self._source_refresh_timer = None
        if self._status_refresh_timer is not None:
            self._status_refresh_timer.stop()
            self._status_refresh_timer = None
        self._pending_source_tabs.clear()
        self._pending_source_keys.clear()
        self._progress_seen_source_keys.clear()
        if not self.is_current:
            self._refresh_on_resume = True
            self._status_on_resume = True
            return
        self._set_inline_loading_bars_visible(True)
        self._set_cluster_progress(
            self._cluster_load_progress,
            "Failed to load cluster data - Press 'R' to retry",
            is_error=True,
        )
        self._hide_all_loading_indicators()
        self._set_all_table_overlays_visible(False)
        self._show_error_state(event.error)
        self._set_active_tab(TAB_NODES)

    def on_input_changed(self, event: CustomInput.Changed) -> None:
        """Handle search input changes with 300ms debounce (M2)."""
        tab_id = self._tab_id_from_control_id(event.input.id, "search-input")
        if not tab_id or self._syncing_search_inputs:
            return
        self._update_search_query(
            event.value,
            source_input_id=event.input.id,
            immediate=False,
        )

    def on_input_submitted(self, event: CustomInput.Submitted) -> None:
        """Apply tab search immediately when Enter is pressed."""
        tab_id = self._tab_id_from_control_id(event.input.id, "search-input")
        if not tab_id:
            return
        self._update_search_query(
            event.value,
            source_input_id=event.input.id,
            immediate=True,
        )

    @on(CustomButton.Pressed, ".cluster-tab-search-btn")
    def _on_search_button_pressed(self, event: CustomButton.Pressed) -> None:
        """Run search immediately for the active tab."""
        tab_id = self._tab_id_from_control_id(event.button.id, "search-btn")
        if not tab_id:
            return
        input_id = self._control_id(tab_id, "search-input")
        try:
            search_value = self.query_one(f"#{input_id}", CustomInput).value
        except Exception:
            search_value = self.search_query
        self._update_search_query(
            search_value,
            source_input_id=input_id,
            immediate=True,
        )

    @on(CustomButton.Pressed, ".cluster-tab-clear-btn")
    def _on_clear_button_pressed(self, event: CustomButton.Pressed) -> None:
        """Clear search query across tabs and refresh immediately."""
        tab_id = self._tab_id_from_control_id(event.button.id, "clear-btn")
        if not tab_id:
            return
        input_id = self._control_id(tab_id, "search-input")
        self._update_search_query(
            "",
            source_input_id=input_id,
            immediate=True,
        )

    def _debounced_search(self) -> None:
        """Refresh only the active tab after search debounce."""
        self._search_timer = None
        if self._data_loaded:
            self._refresh_active_tab()

    def _update_search_query(
        self,
        value: str,
        *,
        source_input_id: str | None = None,
        immediate: bool,
    ) -> None:
        """Persist search query, keep tab controls in sync, and trigger refresh."""
        self.search_query = value
        self._sync_search_inputs(source_input_id=source_input_id)
        if self._search_timer is not None:
            self._search_timer.stop()  # type: ignore[union-attr]
            self._search_timer = None
        if immediate:
            if self._data_loaded:
                self._refresh_active_tab()
            return
        self._search_timer = self.set_timer(0.3, self._debounced_search)

    def _sync_search_inputs(self, *, source_input_id: str | None = None) -> None:
        """Mirror the active search query into all tab-local inputs."""
        self._syncing_search_inputs = True
        try:
            for tab_id in self.TAB_IDS:
                input_id = self._control_id(tab_id, "search-input")
                if source_input_id and input_id == source_input_id:
                    continue
                # Use cached widget ref to avoid DOM query per tab
                cached = self._cached_search_inputs.get(input_id)
                if cached is not None:
                    try:
                        if cached.value != self.search_query:
                            cached.value = self.search_query
                        continue
                    except Exception:
                        # Widget removed or invalid — fall through to re-query
                        self._cached_search_inputs.pop(input_id, None)
                with suppress(Exception):
                    input_widget = self.query_one(f"#{input_id}", CustomInput)
                    self._cached_search_inputs[input_id] = input_widget
                    if input_widget.value != self.search_query:
                        input_widget.value = self.search_query
        finally:
            self._syncing_search_inputs = False

    @on(CustomButton.Pressed, ".cluster-tab-filters-btn")
    def _on_filters_button_pressed(self, event: CustomButton.Pressed) -> None:
        """Open unified modal with all available filters for the tab."""
        tab_id = self._tab_id_from_control_id(event.button.id, "filters-btn")
        if not tab_id:
            return
        self._open_filters_modal(tab_id)

    @on(CustomButton.Pressed, "#refresh-btn")
    def _on_refresh_button_pressed(self, _: CustomButton.Pressed) -> None:
        """Run full cluster refresh from top-bar button keyboard press."""
        self.action_refresh()

    @on(Select.Changed, f"#{_POD_STATS_UNITS_SELECT_ID}")
    def _on_pod_stats_units_select_changed(self, event: Select.Changed) -> None:
        """Switch pod stats display units from dropdown selection."""
        if event.value is Select.BLANK:
            return
        self._set_pod_stats_units_mode(str(event.value))

    @on(Select.Changed, f"#{_NODE_DISTRIBUTION_UNITS_SELECT_ID}")
    def _on_node_distribution_units_select_changed(self, event: Select.Changed) -> None:
        """Switch node distribution total units from dropdown selection."""
        if event.value is Select.BLANK:
            return
        self._set_node_distribution_units_mode(str(event.value))

    def on_custom_button_clicked(self, event: CustomButton.Clicked) -> None:
        """Run full cluster refresh from top-bar mouse click."""
        if event.button.id != "refresh-btn":
            return
        self.action_refresh()

    @on(Select.Changed, ".cluster-tab-sort")
    def _on_sort_select_changed(self, event: Select.Changed) -> None:
        """Handle per-tab sort dropdown changes."""
        if event.value is Select.BLANK:
            return
        tab_id = self._tab_id_from_control_id(event.select.id, "sort")
        if not tab_id:
            return
        self._tab_sort_values[tab_id] = str(event.value)
        if tab_id == self._get_active_tab_id():
            self._refresh_active_tab()

    @on(Select.Changed, ".cluster-tab-order")
    def _on_sort_order_select_changed(self, event: Select.Changed) -> None:
        """Handle per-tab sort order dropdown changes."""
        if event.value is Select.BLANK:
            return
        tab_id = self._tab_id_from_control_id(event.select.id, "order")
        if not tab_id:
            return
        self._tab_sort_order_values[tab_id] = str(event.value)
        if tab_id == self._get_active_tab_id():
            self._refresh_active_tab()

    @on(Select.Changed, f"#{_EVENT_WINDOW_SELECT_ID}")
    def _on_event_window_changed(self, event: Select.Changed) -> None:
        """Handle event lookback window changes and refresh data."""
        if event.value is Select.BLANK:
            return
        selected_value = str(event.value)
        if selected_value == self._event_window_hours_value:
            return
        self._event_window_hours_value = selected_value
        self._presenter.set_event_window_hours(self._event_window_hours())
        if self._data_loaded and not self._presenter.is_loading:
            self.action_refresh()

    @on(CustomTabs.TabActivated, "#cluster-view-tabs")
    def _on_view_tab_activated(self, event: CustomTabs.TabActivated) -> None:
        """Sync active tab with content switcher and lazily refresh tab data."""
        tab_id = str(event.tab.id) if event.tab.id else ""
        if not tab_id:
            return
        if tab_id == self._ignore_next_cluster_tab_id:
            self._ignore_next_cluster_tab_id = None
            return
        self._set_active_tab(tab_id)

    # =========================================================================
    # Loading / Error Helpers
    # =========================================================================

    def _start_connection_stall_watchdog(self) -> None:
        """Track connection phase duration and fail fast on long stalls."""
        if self._connection_stall_timer is not None:
            with suppress(Exception):
                self._connection_stall_timer.stop()
            self._connection_stall_timer = None
        self._connection_phase_started_at = time.monotonic()
        self._connection_stall_timer = self.set_interval(
            self._CONNECTION_STALL_CHECK_INTERVAL_SECONDS,
            self._check_connection_stall,
        )

    def _stop_connection_stall_watchdog(self) -> None:
        """Stop connection-stall monitoring timer."""
        if self._connection_stall_timer is not None:
            with suppress(Exception):
                self._connection_stall_timer.stop()
            self._connection_stall_timer = None
        self._connection_phase_started_at = None

    def _check_connection_stall(self) -> None:
        """Show a deterministic timeout error when connection checks stall."""
        if not self.is_current:
            return
        if not self._presenter.is_loading:
            if (
                not self._data_loaded
                and self._error_message is None
                and self._cluster_load_progress < 100
                and self._connection_phase_started_at is not None
                and (
                    time.monotonic() - self._connection_phase_started_at
                    >= self._LOAD_INTERRUPTED_GRACE_SECONDS
                )
            ):
                self._stop_connection_stall_watchdog()
                self.post_message(
                    ClusterDataLoadFailed(
                        "Cluster loading was interrupted before data arrived. Press 'R' to retry."
                    )
                )
                return
            self._stop_connection_stall_watchdog()
            return
        # Once progress advances past the initial connection baseline, stall
        # monitoring is no longer needed.
        if self._cluster_load_progress > 5:
            self._connection_phase_started_at = None
            return
        if self._connection_phase_started_at is None:
            self._connection_phase_started_at = time.monotonic()
            return

        elapsed = time.monotonic() - self._connection_phase_started_at
        if elapsed >= self._CONNECTION_STALL_FAIL_SECONDS:
            self._stop_connection_stall_watchdog()
            with suppress(Exception):
                self.workers.cancel_all()
            self.post_message(
                ClusterDataLoadFailed(
                    "Cluster check timed out. Verify context and credentials, then press 'R' to retry."
                )
            )
            return

        if elapsed >= self._CONNECTION_STALL_WARN_SECONDS:
            self._set_cluster_progress(
                max(self._cluster_load_progress, 5),
                "Checking cluster... (slow)",
            )

    def _update_loading_message(self, message: str) -> None:
        if not self.is_current:
            return
        self._loading_message = message
        progress = self._progress_from_message(message)
        if progress > 5:
            self._connection_phase_started_at = None
        elif self._connection_phase_started_at is None:
            self._connection_phase_started_at = time.monotonic()
        self._set_cluster_progress(progress, self._normalize_loading_message(message))

    def _update_partial_load_progress(self) -> None:
        """Advance visible loading percent while partial sources stream in."""
        if not self._presenter.is_loading:
            return
        reverse_map = self._build_reverse_map()
        if not reverse_map:
            return
        # Use dict keys view directly for set operations (avoids copy)
        tracked_source_keys = reverse_map.keys()
        loaded_count = len(self._presenter.loaded_keys & tracked_source_keys)
        seen_count = len(self._progress_seen_source_keys & tracked_source_keys)
        resolved_count = max(loaded_count, seen_count)
        if resolved_count <= 0:
            return
        total_sources = len(tracked_source_keys)
        if total_sources <= 0:
            return
        baseline = 15 if self._data_loaded else 10
        estimated = baseline + int(
            (resolved_count / total_sources) * (self._LOAD_WORKING_MAX - baseline)
        )
        progress = max(self._cluster_load_progress, min(estimated, self._LOAD_WORKING_MAX))
        state_text = self._loading_message
        if state_text in ("Connecting...", "Checking cluster...", "Refreshing cluster data..."):
            state_text = "Loading cluster data..."
        if not state_text:
            state_text = "Loading cluster data..."
        self._set_cluster_progress(progress, state_text)

    def _normalize_loading_message(self, message: str) -> str:
        """Normalize worker loading messages for progress text."""
        if self._data_loaded and message in (
            "Connecting to cluster...",
            "Checking cluster connection...",
        ):
            return "Refreshing cluster data..."
        if message == "Connecting to cluster...":
            return "Connecting..."
        if message == "Checking cluster connection...":
            return "Checking cluster..."
        load_match = self._LOAD_PROGRESS_RE.match(message)
        if load_match:
            detail_suffix = message[load_match.end() :].strip()
            detail_suffix = detail_suffix.lstrip("-: ").strip()
            if detail_suffix:
                return detail_suffix
            return "Loading cluster data..."
        return message

    def _progress_from_message(self, message: str) -> int:
        """Infer progress percentage from presenter loading messages."""
        current = self._cluster_load_progress
        if message in ("Connecting to cluster...", "Checking cluster connection..."):
            baseline = 15 if self._data_loaded else 5
            return max(current, baseline)
        match = self._LOAD_PROGRESS_RE.match(message)
        if not match:
            return current
        completed = int(match.group(1))
        total = int(match.group(2))
        if total <= 0:
            return current
        working_progress = int((completed / total) * self._LOAD_WORKING_MAX)
        return max(current, min(working_progress, self._LOAD_WORKING_MAX))

    def _set_cluster_progress(
        self, percent: int, state_text: str, *, is_error: bool = False
    ) -> None:
        """Update cluster loading progress bar and phase text."""
        safe_percent = max(0, min(percent, 100))
        # Keep canonical loading-label format discoverable for regression tests.
        displayed = f"{safe_percent}% Loading..."
        _ = displayed
        self._cluster_load_progress = safe_percent
        self._cluster_progress_target = safe_percent
        state_plain = self._strip_markup(state_text).replace("\n", " ").strip()
        if not state_plain:
            state_plain = "Loading cluster data..."
        self._loading_message = state_plain
        self._progress_is_error = is_error

        if self._cluster_progress_display == self._cluster_progress_target:
            self._stop_cluster_progress_animation()
        else:
            self._ensure_cluster_progress_animation_running()
        self._render_cluster_progress()

    def _ensure_cluster_progress_animation_running(self) -> None:
        """Start smooth progress interpolation timer when needed."""
        if self._cluster_progress_animation_timer is not None:
            return
        self._cluster_progress_animation_timer = self.set_interval(
            self._PROGRESS_ANIMATION_INTERVAL_SECONDS,
            self._tick_cluster_progress_animation,
        )

    def _stop_cluster_progress_animation(self) -> None:
        """Stop smooth progress interpolation timer."""
        if self._cluster_progress_animation_timer is None:
            return
        with suppress(Exception):
            self._cluster_progress_animation_timer.stop()
        self._cluster_progress_animation_timer = None

    def _tick_cluster_progress_animation(self) -> None:
        """Advance the visible top progress percent towards its target."""
        target = self._cluster_progress_target
        current = self._cluster_progress_display
        delta = target - current
        if delta == 0:
            self._stop_cluster_progress_animation()
            return
        step = max(1, math.ceil(abs(delta) * self._PROGRESS_ANIMATION_STEP_RATIO))
        if delta > 0:
            current = min(target, current + step)
        else:
            current = max(target, current - step)
        self._cluster_progress_display = current
        self._render_cluster_progress()
        if current == target:
            self._stop_cluster_progress_animation()

    def _render_cluster_progress(self) -> None:
        """Render top-row progress bar and label from current progress state."""
        display_percent = max(0, min(self._cluster_progress_display, 100))
        safe_percent = max(0, min(self._cluster_load_progress, 100))
        state_plain = self._loading_message
        is_error = self._progress_is_error

        with suppress(NoMatches):
            progress_bar = self.query_one("#cluster-progress-bar", ProgressBar)
            progress_bar.update(total=100, progress=display_percent)

        loading_text_widget: CustomStatic | None = None
        with suppress(NoMatches):
            loading_text_widget = self.query_one("#loading-text", CustomStatic)

        full_text = f"{display_percent}% - {state_plain}"
        if not is_error and (safe_percent < 100 or self._presenter.is_loading):
            displayed = f"{display_percent}% Loading..."
            full_text = displayed
        else:
            mode = self._get_tab_controls_layout_mode()
            if mode == "xwide":
                max_chars = self._PROGRESS_TEXT_MAX_XWIDE
            elif mode == "wide":
                max_chars = self._PROGRESS_TEXT_MAX_WIDE
            elif mode == "medium":
                max_chars = self._PROGRESS_TEXT_MAX_MEDIUM
            elif mode == "narrow":
                max_chars = self._PROGRESS_TEXT_MAX_NARROW
            else:
                max_chars = self._PROGRESS_TEXT_MAX_COMPACT
            separator = " " if mode in ("narrow", "compact") else " - "
            prefix = f"{display_percent}%{separator}"
            if loading_text_widget is not None and loading_text_widget.size.width > 0:
                available_width = loading_text_widget.size.width
                if available_width <= len(prefix):
                    displayed = f"{display_percent}%"
                else:
                    max_chars = max(1, min(max_chars, available_width - len(prefix)))
                    compact_state = self._truncate_plain_text(state_plain, max_chars)
                    displayed = f"{prefix}{compact_state}"
            else:
                compact_state = self._truncate_plain_text(state_plain, max_chars)
                displayed = f"{prefix}{compact_state}"
        if loading_text_widget is not None:
            loading_text_widget.update(displayed)
            loading_text_widget.tooltip = full_text if displayed != full_text else None
            if is_error:
                loading_text_widget.add_class("status-error")
            else:
                loading_text_widget.remove_class("status-error")

    def _set_inline_loading_bars_visible(self, visible: bool) -> None:
        """Show or hide top-row cluster loading bar."""
        with suppress(NoMatches):
            # Keep the loading-bar slot mounted so the left controls don't
            # expand/collapse as loading state flips.
            self.query_one("#cluster-loading-bar", CustomHorizontal).display = True
        with suppress(NoMatches):
            self.query_one("#cluster-progress-container", CustomHorizontal).display = visible

    @staticmethod
    def _truncate_plain_text(text: str, max_chars: int) -> str:
        """Return a single-line string truncated with ellipsis when needed."""
        compact = " ".join(text.split())
        if max_chars <= 0 or len(compact) <= max_chars:
            return compact
        if max_chars == 1:
            return compact[:1]
        return f"{compact[: max_chars - 1].rstrip()}…"

    def _show_error_state(self, message: str) -> None:
        plain_message = self._strip_markup(message).replace("\n", " ").strip()
        lowered_message = plain_message.lower()
        summary_message = "Cluster data unavailable. Press 'R' to retry."
        if "timed out" in lowered_message:
            summary_message = "Cluster check timed out. Press 'R' to retry."
        elif plain_message:
            summary_message = self._truncate_plain_text(
                f"{plain_message} Press 'R' to retry.",
                self._OVERVIEW_ERROR_MAX_CHARS,
            )
        detail_message = f"Error: {plain_message or message}\n\nPress 'R' or click the refresh button to retry."
        with suppress(NoMatches):
            self.query_one("#overview-cluster-name", CustomStatic).update(summary_message)
        for cid in ("#health-container",):
            with suppress(NoMatches):
                container = self.query_one(cid, CustomContainer)
                container.remove_children()
                container.mount(
                    CustomStatic(detail_message, markup=False, classes="error-message")
                )

    def _update_status_bar(self) -> None:
        cluster_name = self._presenter.get_cluster_name()
        node_count = len(self._presenter.get_nodes())
        ts = self._last_updated.strftime("%H:%M:%S") if self._last_updated else "Never"
        snapshot = (cluster_name, node_count, ts)
        if snapshot == self._last_status_snapshot:
            return
        self._last_status_snapshot = snapshot

        cluster_name_widget = self._get_cached_static("cluster-name")
        node_count_widget = self._get_cached_static("node-count")
        last_updated_widget = self._get_cached_static("last-updated")

        if cluster_name_widget is not None:
            cluster_name_widget.update(cluster_name)
        if node_count_widget is not None:
            node_count_widget.update(str(node_count))
        if last_updated_widget is not None:
            last_updated_widget.update(ts)

    # =========================================================================
    # Generic Widget Update Helpers
    # =========================================================================

    # Map tab IDs to the data keys they depend on
    _TAB_DATA_KEYS: dict[str, list[str]] = {
        "tab-events": [
            "events",
            "critical_events",
            "event_summary",
        ],
        "tab-nodes": [
            "nodes",
            "node_conditions",
            "node_taints",
            "az_distribution",
            "instance_type_distribution",
            "kubelet_version_distribution",
            "node_groups_az_matrix",
            "node_groups",
            "high_pod_count_nodes",
        ],
        "tab-pods": [
            "nodes",
            "events",
            "pdbs",
            "all_workloads",
            "pod_request_stats",
            "charts_overview",
        ],
    }

    # Reverse mapping: data key -> set of tab IDs that use it
    _DATA_KEY_TO_TABS: dict[str, list[str]] = {}

    @classmethod
    def _build_reverse_map(cls) -> dict[str, list[str]]:
        if cls._DATA_KEY_TO_TABS:
            return cls._DATA_KEY_TO_TABS
        reverse: dict[str, list[str]] = {}
        for tab_id, keys in cls._TAB_DATA_KEYS.items():
            for key in keys:
                reverse.setdefault(key, []).append(tab_id)
        cls._DATA_KEY_TO_TABS = reverse
        return reverse

    def _refresh_active_tab(self) -> None:
        """Refresh active tab, applying current search/filter/sort controls."""
        if not self._data_loaded:
            return
        active_tab = self._get_active_tab_id()
        self._populated_tabs.discard(active_tab)
        self._refresh_tab(active_tab)

    def _strip_markup(self, value: str) -> str:
        """Remove lightweight rich markup tags from a cell text."""
        return self._MARKUP_TAG_RE.sub("", value).strip()

    def _normalize_cell_text(self, value: object) -> str:
        """Normalize cell value for filter matching."""
        return self._strip_markup(str(value)).strip()

    def _is_numeric_like_text(self, value: str) -> bool:
        """Return True when a cell value represents numeric data."""
        text = value.strip()
        if not text:
            return False
        if self._RATIO_LIKE_RE.match(text):
            return True
        return bool(self._NUMERIC_LIKE_RE.match(text))

    def _is_filterable_string_column(self, column_name: str) -> bool:
        """Allow only string-like columns for dropdown filter generation."""
        name = column_name.lower().strip()
        if self._AWS_AZ_COLUMN_RE.match(name) or self._AWS_AZ_GROUPED_COLUMN_RE.match(name):
            return False
        blocked_tokens = (
            "count",
            "%",
            "min",
            "max",
            "avg",
            "p95",
            "cpu",
            "mem",
            "replica",
            "value",
            "true",
            "false",
            "unknown",
            "pods",
            "ready",
            "allowed",
            "healthy",
            "expected",
            "nodes",
            "usage",
            "occurrence",
            "total",
        )
        return not any(token in name for token in blocked_tokens)

    def _encode_filter_value(self, column_name: str, cell_text: str) -> str:
        column_slug = self._column_slug(column_name)
        return f"col::{column_slug}::val::{cell_text.lower()}"

    @classmethod
    def _column_slug(cls, column_name: str) -> str:
        """Return normalized slug for a visible column label."""
        return cls._COL_KEY_SANITIZE_RE.sub("_", column_name.lower()).strip("_")

    def _build_tab_string_filter_options(
        self, table_data: list[tuple[list[tuple[str, int]], list[tuple]]]
    ) -> dict[str, tuple[str, tuple[tuple[str, str], ...]]]:
        """Build per-column, string-only filter options from tab datasets.

        Performance: pre-computes filterable column indices per table,
        uses local references for regex patterns, and breaks early when
        a column is both truncated and full.
        """
        column_labels: dict[str, str] = {}
        column_values: dict[str, dict[str, str]] = {}
        truncated_columns: set[str] = set()

        # Local refs to avoid repeated attribute lookups in tight inner loop
        _normalize = self._normalize_cell_text
        _is_numeric = self._is_numeric_like_text
        _has_alpha = self._HAS_ALPHA_RE.search
        _max_values = self._MAX_FILTER_VALUES_PER_COLUMN

        for columns, rows in table_data:
            # Pre-compute filterable columns for this table
            filterable: list[tuple[int, str, str]] = []
            for column_index, (column_name, _) in enumerate(columns):
                if not self._is_filterable_string_column(column_name):
                    continue
                column_slug = self._column_slug(column_name)
                if not column_slug:
                    continue
                column_labels.setdefault(column_slug, column_name)
                column_values.setdefault(column_slug, {})
                filterable.append((column_index, column_slug, column_name))

            if not filterable:
                continue

            for row in rows:
                row_len = len(row)
                for column_index, column_slug, _ in filterable:
                    if column_index >= row_len:
                        continue
                    text = _normalize(row[column_index])
                    if not text or not _has_alpha(text) or _is_numeric(text):
                        continue
                    normalized = text.lower()
                    values_for_column = column_values[column_slug]
                    if normalized in values_for_column:
                        continue
                    if len(values_for_column) >= _max_values:
                        truncated_columns.add(column_slug)
                        continue
                    values_for_column[normalized] = text

        options_by_column: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {}
        for column_slug, column_name in column_labels.items():
            values_for_column = column_values.get(column_slug, {})
            options: list[tuple[str, str]] = [("All", "all")]
            for normalized_value in sorted(values_for_column):
                text = values_for_column[normalized_value]
                options.append(
                    (text, self._encode_filter_value(column_name, text))
                )
            options_by_column[column_slug] = (column_name, tuple(options))

        self._last_filter_truncated_column_count = len(truncated_columns)
        return options_by_column

    def _filter_select_width_from_options(
        self,
        options: tuple[tuple[str, str], ...],
        *,
        filter_count: int = 1,
        control_label: str | None = None,
    ) -> int:
        """Compute trigger width from its visible label with responsive cap."""
        max_label_len = len(control_label.strip()) if control_label else 0
        if max_label_len == 0:
            max_label_len = max((len(label) for label, _ in options), default=10)
        requested_width = max(10, max_label_len + 4)
        responsive_available = max(
            self._FILTER_SELECT_MIN_RESPONSIVE_WIDTH,
            self._current_viewport_width() - self._FILTER_ROW_FIXED_OVERHEAD,
        )
        responsive_cap = max(
            self._FILTER_SELECT_MIN_RESPONSIVE_WIDTH,
            responsive_available // max(1, filter_count),
        )
        max_width = min(self._FILTER_SELECT_BASE_MAX_WIDTH, responsive_cap)
        return min(requested_width, max_width)

    def _apply_filter_select_width(
        self,
        control: Any,
        options: tuple[tuple[str, str], ...],
        *,
        filter_count: int = 1,
        control_label: str | None = None,
    ) -> None:
        """Apply dynamic width for a filter control."""
        target_width = self._filter_select_width_from_options(
            options,
            filter_count=filter_count,
            control_label=control_label,
        )
        control.styles.width = "1fr"
        control.styles.min_width = target_width
        control.styles.max_width = "100%"

    def _filter_trigger_label(
        self,
        column_name: str,
    ) -> str:
        """Build trigger label for multi-select column filter."""
        return column_name

    def _grid_dimension_for_filter_controls(self, control_count: int) -> int:
        """Return square grid side length for filter controls (N x N)."""
        return max(1, math.ceil(math.sqrt(max(0, control_count))))

    def _apply_filter_grid_layout(self, filter_row: CustomHorizontal, control_count: int) -> None:
        """Apply a near-square filter grid (N x M) to avoid long sparse rows."""
        if not hasattr(filter_row, "styles"):
            return

        grid_n = self._grid_dimension_for_filter_controls(control_count)
        grid_rows_count = max(1, math.ceil(max(0, control_count) / grid_n))
        fr_columns = " ".join(["1fr"] * grid_n)
        auto_rows = " ".join(["auto"] * grid_rows_count)
        filter_row.styles.grid_size_columns = grid_n
        filter_row.styles.grid_size_rows = grid_rows_count
        filter_row.styles.grid_columns = fr_columns
        filter_row.styles.grid_rows = auto_rows

    def _open_filters_modal(self, tab_id: str) -> None:
        """Open unified cluster filters modal for a tab."""
        options_by_column = self._tab_column_filter_options.get(tab_id, {})
        selected_values = self._tab_column_filter_values.get(tab_id, {})
        modal = _ClusterFiltersModal(
            options_by_column=options_by_column,
            selected_values=selected_values,
        )
        self.app.push_screen(
            modal,
            lambda result: self._on_filters_modal_dismissed(tab_id, result),
        )

    def _on_single_column_filter_modal_dismissed(
        self,
        tab_id: str,
        column_slug: str,
        result: set[str] | None,
    ) -> None:
        """Normalize single-column modal result through unified filter pipeline."""
        if result is None:
            return
        self._on_filters_modal_dismissed(
            tab_id,
            {column_slug: set(result)},
        )

    def _table_data_signature(
        self,
        table_data: list[tuple[list[tuple[str, int]], list[tuple]]],
    ) -> int:
        """Build compact signature for one tab's table payload snapshots."""
        signature = self._mix_table_signature(0, len(table_data))
        for columns, rows in table_data:
            column_names = tuple(column_name for column_name, _ in columns)
            signature = self._mix_table_signature(signature, hash(column_names))
            signature = self._mix_table_signature(signature, self._rows_signature(rows))
        return signature

    def _on_filters_modal_dismissed(
        self,
        tab_id: str,
        result: dict[str, set[str]] | None,
    ) -> None:
        """Persist modal filter selections and refresh active tab when needed."""
        if result is None:
            return
        options_by_column = self._tab_column_filter_options.get(tab_id, {})
        sanitized_map: dict[str, set[str]] = {}
        for column_slug, values in result.items():
            column_entry = options_by_column.get(column_slug)
            if not column_entry:
                continue
            _, options = column_entry
            valid_values = {value for _, value in options if value != "all"}
            selected_values = {value for value in values if value in valid_values}
            if selected_values and selected_values != valid_values:
                sanitized_map[column_slug] = selected_values
        self._tab_column_filter_values[tab_id] = sanitized_map
        self._update_filter_dialog_button(tab_id)
        if tab_id == self._get_active_tab_id():
            self._refresh_active_tab()

    def _update_filter_dialog_button(self, tab_id: str) -> None:
        """Update unified filter button label with active filter counts."""
        selected_map = self._tab_column_filter_values.get(tab_id, {})
        active_column_count = sum(1 for values in selected_map.values() if values)
        active_value_count = sum(len(values) for values in selected_map.values())
        truncated_count = self._tab_filter_truncated_columns.get(tab_id, 0)
        label = "Filters"
        if active_column_count > 0:
            label = f"Filters ({active_column_count}/{active_value_count})"
        if truncated_count > 0:
            label = f"{label}*"
        control_id = self._control_id(tab_id, "filters-btn")
        with suppress(NoMatches):
            button = self.query_one(f"#{control_id}", CustomButton)
            button.label = label
            if truncated_count > 0:
                button.tooltip = (
                    f"{truncated_count} filter column(s) were truncated to the first "
                    f"{self._MAX_FILTER_VALUES_PER_COLUMN} distinct values."
                )
            else:
                button.tooltip = None

    def _sync_tab_filter_options(
        self,
        tab_id: str,
        table_data: list[tuple[list[tuple[str, int]], list[tuple]]],
    ) -> None:
        """Update per-tab filter options and keep selected values valid."""
        now = time.monotonic()
        last_sync_at = self._tab_filter_last_sync_at.get(tab_id, 0.0)
        if (
            self._presenter.is_loading
            and tab_id in self._tab_filter_source_signatures
            and now - last_sync_at < self._FILTER_OPTION_SYNC_LOADING_INTERVAL_SECONDS
        ):
            self._update_filter_dialog_button(tab_id)
            return

        source_signature = self._table_data_signature(table_data)
        if source_signature == self._tab_filter_source_signatures.get(tab_id):
            self._tab_filter_last_sync_at[tab_id] = now
            self._update_filter_dialog_button(tab_id)
            return
        self._tab_filter_source_signatures[tab_id] = source_signature
        self._tab_filter_last_sync_at[tab_id] = now

        options_by_column = self._build_tab_string_filter_options(table_data)
        if tab_id == "tab-events":
            options_by_column = {
                column_slug: options_by_column[column_slug]
                for column_slug in self._EVENTS_FILTER_COLUMNS
                if column_slug in options_by_column
            }
        self._tab_column_filter_options[tab_id] = options_by_column
        previous_truncated = self._tab_filter_truncated_columns.get(tab_id, 0)
        self._tab_filter_truncated_columns[tab_id] = (
            self._last_filter_truncated_column_count
        )
        if previous_truncated == 0 and self._last_filter_truncated_column_count > 0:
            with suppress(Exception):
                if self.is_current:
                    self.app.notify(
                        "Some filter columns are truncated to keep the UI responsive.",
                        severity="warning",
                        timeout=4,
                    )

        selected_map: dict[str, set[str]] = {
            column_slug: set(values)
            for column_slug, values in self._tab_column_filter_values.get(tab_id, {}).items()
        }
        selected_map = {
            column_slug: selected_value
            for column_slug, selected_value in selected_map.items()
            if column_slug in options_by_column
        }
        for column_slug, (_, options) in options_by_column.items():
            valid_values = {value for _, value in options if value != "all"}
            selected_values = {
                value for value in selected_map.get(column_slug, set()) if value in valid_values
            }
            if selected_values == valid_values:
                selected_values = set()
            selected_map[column_slug] = selected_values
        self._tab_column_filter_values[tab_id] = selected_map
        self._update_filter_dialog_button(tab_id)

    def _row_matches_filter_value(
        self,
        row: tuple,
        columns: list[tuple[str, int]],
        filter_value: str,
        *,
        column_indices_by_slug: dict[str, tuple[int, ...]] | None = None,
    ) -> bool:
        """Check if a row matches encoded filter value on string column."""
        if filter_value == "all":
            return True
        match = self._FILTER_VALUE_RE.match(filter_value)
        if not match:
            return True
        column_slug = match.group("col")
        expected_value = match.group("val")

        if column_indices_by_slug is not None:
            matching_columns = column_indices_by_slug.get(column_slug, ())
        else:
            matching_columns = tuple(
                idx
                for idx, (column_name, _) in enumerate(columns)
                if self._column_slug(column_name) == column_slug
            )
        if not matching_columns:
            return True

        for idx in matching_columns:
            if idx >= len(row):
                continue
            cell_text = self._normalize_cell_text(row[idx]).lower()
            if cell_text == expected_value:
                return True
        return False

    @classmethod
    def _column_indices_for_filters(
        cls,
        columns: list[tuple[str, int]],
    ) -> dict[str, tuple[int, ...]]:
        """Build per-column slug -> row index mapping used during filter evaluation."""
        index_map: dict[str, list[int]] = {}
        for index, (column_name, _) in enumerate(columns):
            column_slug = cls._column_slug(column_name)
            if not column_slug:
                continue
            index_map.setdefault(column_slug, []).append(index)
        return {
            slug: tuple(indexes)
            for slug, indexes in index_map.items()
        }

    @classmethod
    def _decode_active_filter_values(
        cls,
        selected_filters: dict[str, set[str]],
    ) -> dict[str, set[str]]:
        """Decode encoded filter values into slug -> expected text map."""
        decoded: dict[str, set[str]] = {}
        for filter_values in selected_filters.values():
            if not filter_values or "all" in filter_values:
                continue
            for filter_value in filter_values:
                match = cls._FILTER_VALUE_RE.match(filter_value)
                if not match:
                    continue
                decoded.setdefault(match.group("col"), set()).add(match.group("val"))
        return decoded

    def _filter_rows_by_dropdown(
        self,
        rows: list[tuple],
        columns: list[tuple[str, int]],
        selected_filters: dict[str, set[str]],
    ) -> list[tuple]:
        """Apply active per-column multi-select filters (AND across columns)."""
        decoded_filters = self._decode_active_filter_values(selected_filters)
        if not decoded_filters:
            return rows

        column_indices_by_slug = self._column_indices_for_filters(columns)
        active_filters = {
            column_slug: expected_values
            for column_slug, expected_values in decoded_filters.items()
            if column_slug in column_indices_by_slug and expected_values
        }
        if not active_filters:
            return rows

        filtered_rows: list[tuple] = []
        for row in rows:
            row_matches = True
            for column_slug, expected_values in active_filters.items():
                matches_column = False
                for idx in column_indices_by_slug[column_slug]:
                    if idx >= len(row):
                        continue
                    cell_text = self._normalize_cell_text(row[idx]).lower()
                    if cell_text in expected_values:
                        matches_column = True
                        break
                if not matches_column:
                    row_matches = False
                    break
            if row_matches:
                filtered_rows.append(row)
        return filtered_rows

    def _sort_key_for_value(self, value: object) -> tuple[int, float, str]:
        """Produce a stable mixed-type sort key with numeric preference."""
        if isinstance(value, int | float):
            return (0, float(value), "")

        text = str(value).strip()
        normalized = text.replace(",", "")
        match = self._NUMBER_RE.search(normalized)
        if match:
            with suppress(ValueError):
                return (0, float(match.group(0)), text.lower())
        return (1, 0.0, text.lower())

    def _sort_rows_by_dropdown(self, rows: list[tuple]) -> list[tuple]:
        """Apply active-tab sort mode and order to table rows."""
        sort_mode = self._table_sort
        if sort_mode == "none":
            return rows

        sort_index = None
        if sort_mode.startswith("idx:"):
            with suppress(ValueError):
                sort_index = int(sort_mode.split(":", 1)[1])
        elif sort_mode.startswith("col"):
            with suppress(ValueError):
                sort_index = int(sort_mode.replace("col", ""))
        if sort_index is None:
            return rows

        reverse = self._table_sort_order == "desc"

        def _row_key(row: tuple) -> tuple[int, float, str]:
            if sort_index >= len(row):
                return (2, 0.0, "")
            return self._sort_key_for_value(row[sort_index])

        return sorted(rows, key=_row_key, reverse=reverse)

    def _apply_table_controls(
        self,
        rows: list[tuple],
        columns: list[tuple[str, int]],
        *,
        tab_id: str,
    ) -> list[tuple]:
        """Apply tab-specific dropdown filter and sorting controls to rows."""
        selected_filters = self._tab_column_filter_values.get(tab_id, {})
        self._table_sort = self._tab_sort_values.get(tab_id, "none")
        self._table_sort_order = self._tab_sort_order_values.get(tab_id, "asc")
        filtered_rows = self._filter_rows_by_dropdown(rows, columns, selected_filters)
        return self._sort_rows_by_dropdown(filtered_rows)

    @classmethod
    def _mix_table_signature(cls, signature: int, value: int) -> int:
        """Mix one value into a bounded, fixed-width table signature."""
        return (
            (signature * cls._TABLE_SIGNATURE_MIXER)
            ^ (value & cls._TABLE_SIGNATURE_MASK)
        ) & cls._TABLE_SIGNATURE_MASK

    @classmethod
    def _rows_signature(cls, rows: list[tuple]) -> int:
        """Build a bounded signature for a rendered table payload.

        Performance: for large tables (>500 rows), samples first, last, and
        evenly-spaced middle rows instead of hashing every row. This reduces
        O(n) to O(1) while still detecting most data changes.
        """
        row_count = len(rows)
        signature = cls._mix_table_signature(0, row_count)
        _SAMPLE_THRESHOLD = 500
        if row_count <= _SAMPLE_THRESHOLD:
            for row in rows:
                signature = cls._mix_table_signature(signature, hash(row))
        else:
            # Sample ~64 evenly spaced rows + first 8 + last 8
            step = max(1, row_count // 64)
            sample_indices = set(range(0, 8))
            sample_indices.update(range(row_count - 8, row_count))
            sample_indices.update(range(0, row_count, step))
            for idx in sorted(sample_indices):
                if 0 <= idx < row_count:
                    signature = cls._mix_table_signature(signature, hash(rows[idx]))
        return signature

    def _column_key_from_label(self, label: str, index: int) -> str:
        """Build stable, unique column keys from labels."""
        slug = self._COL_KEY_SANITIZE_RE.sub("_", label.lower()).strip("_")
        if not slug:
            slug = f"col_{index}"
        return f"{slug}_{index}"

    def _update_table(
        self,
        table_id: str,
        empty_id: str | None,
        columns: list[tuple[str, int]],
        rows: list[tuple],
        *,
        tab_id: str,
    ) -> None:
        """Update a DataTable widget with columns and rows."""
        controlled_rows = self._apply_table_controls(rows, columns, tab_id=tab_id)
        column_signature = tuple(
            self._column_key_from_label(col_name, index)
            for index, (col_name, _) in enumerate(columns)
        )
        rows_signature = self._rows_signature(controlled_rows)
        with suppress(NoMatches):
            table = self.query_one(f"#{table_id}", CustomDataTable)
            fixed_columns = self._fixed_column_count_for_table(table_id, columns)
            self._configure_cluster_table_header_tooltips(table, table_id, columns)
            self._apply_table_width_policy(table, columns)
            previous_column_signature = self._table_column_signatures.get(table_id)
            previous_rows_signature = self._table_row_signatures.get(table_id)
            columns_changed = previous_column_signature != column_signature
            rows_changed = previous_rows_signature != rows_signature
            if columns_changed or rows_changed:
                previous_selected_row: int | None = None
                previous_selected_row_data: tuple[Any, ...] | None = None
                current_cursor_row = table.cursor_row
                if isinstance(current_cursor_row, int) and current_cursor_row >= 0:
                    previous_selected_row = current_cursor_row
                    previous_selected_row_data = table.get_row_data(current_cursor_row)
                with table.batch_update():
                    if table.data_table is not None:
                        table.data_table.fixed_columns = fixed_columns
                    if columns_changed:
                        table.clear(columns=True)
                    else:
                        table.clear()
                    if columns_changed:
                        for index, (col_name, _) in enumerate(columns):
                            table.add_column(
                                col_name,
                                key=self._column_key_from_label(col_name, index),
                            )
                        self._table_column_signatures[table_id] = column_signature
                    if controlled_rows:
                        table.add_rows(controlled_rows)
                restored_row_index: int | None = None
                if previous_selected_row_data is not None:
                    _row_index_map = {
                        row: idx for idx, row in enumerate(controlled_rows)
                    }
                    restored_row_index = _row_index_map.get(previous_selected_row_data)
                if (
                    restored_row_index is None
                    and isinstance(previous_selected_row, int)
                    and 0 <= previous_selected_row < len(controlled_rows)
                ):
                    restored_row_index = previous_selected_row
                if restored_row_index is not None:
                    table.cursor_row = restored_row_index
                self._table_row_signatures[table_id] = rows_signature
            if table_id == "node-groups-table":
                self._stretch_table_columns(table)
            # Keep table headers visible for panels that don't render explicit
            # empty-state labels.
            table.display = True if controlled_rows else empty_id is None
        if empty_id:
            with suppress(NoMatches):
                empty = self.query_one(f"#{empty_id}", CustomStatic)
                if not controlled_rows:
                    empty.remove_class("hidden")
                else:
                    empty.add_class("hidden")

    def _fixed_column_count_for_table(
        self,
        table_id: str,
        columns: list[tuple[str, int]],
    ) -> int:
        """Return fixed column count for tables with locked leading columns."""
        locked_columns = self._TABLE_LOCKED_COLUMNS.get(table_id, ())
        if not locked_columns:
            return 0

        locked_names = set(locked_columns)
        locked_positions = [
            index for index, (column_name, _) in enumerate(columns) if column_name in locked_names
        ]
        if not locked_positions:
            return 0
        return max(locked_positions) + 1

    def _cluster_table_header_tooltips(
        self,
        table_id: str,
        columns: list[tuple[str, int]],
    ) -> dict[str, str]:
        """Build per-column tooltip mapping for a specific cluster table."""
        configured_tooltips = CLUSTER_TABLE_HEADER_TOOLTIPS.get(table_id, {})
        tooltips: dict[str, str] = {}
        for column_name, _ in columns:
            configured_tooltip = configured_tooltips.get(column_name)
            if configured_tooltip:
                tooltips[column_name] = configured_tooltip
                continue
            if table_id == "node-groups-table":
                normalized_name = column_name.strip().lower()
                if self._AWS_AZ_COLUMN_RE.match(normalized_name):
                    tooltips[column_name] = (
                        f"Number of nodes in availability zone {column_name}."
                    )
                    continue
                grouped_match = self._AWS_AZ_GROUPED_COLUMN_RE.match(normalized_name)
                if grouped_match:
                    region = grouped_match.group("region")
                    zones = grouped_match.group("zones")
                    tooltips[column_name] = (
                        f"Number of nodes per availability zone in region {region} "
                        f"(order: {zones})."
                    )
        return tooltips

    def _configure_cluster_table_header_tooltips(
        self,
        table: CustomDataTable,
        table_id: str,
        columns: list[tuple[str, int]],
    ) -> None:
        """Apply per-column header tooltips for cluster tables."""
        table.set_header_tooltips(
            self._cluster_table_header_tooltips(table_id, columns)
        )

    def _apply_table_width_policy(
        self,
        table: CustomDataTable,
        _columns: list[tuple[str, int]],
    ) -> None:
        """Force full-width tables to avoid narrow, unspanned cluster layouts."""
        table.styles.width = "1fr"
        table.styles.min_width = 0
        table.styles.max_width = "100%"

    def _stretch_table_columns(self, table: CustomDataTable) -> None:
        """Stretch table columns so the table consumes full tile width."""
        inner = table.data_table
        if inner is None:
            return

        with suppress(Exception):
            ordered_columns = list(inner.ordered_columns)
            if not ordered_columns:
                return

            table_width = int(getattr(inner.size, "width", 0))
            if table_width <= 0:
                return

            padding_width = max(0, 2 * int(getattr(inner, "cell_padding", 0)))
            natural_render_widths = [
                padding_width + max(1, int(column.content_width))
                for column in ordered_columns
            ]
            natural_total_width = sum(natural_render_widths)
            slack = table_width - natural_total_width

            if slack <= 0:
                for column in ordered_columns:
                    column.auto_width = True
                inner.refresh()
                return

            column_count = len(ordered_columns)
            extra_per_column = slack // column_count
            remainder = slack % column_count
            for index, column in enumerate(ordered_columns):
                extra = extra_per_column + (1 if index < remainder else 0)
                target_render_width = natural_render_widths[index] + extra
                # Column.width is content width (padding excluded).
                target_content_width = max(1, target_render_width - padding_width)
                column.width = target_content_width
                column.auto_width = False
            inner.refresh()

    def _current_viewport_width(self) -> int:
        """Return current viewport width with safe fallback outside app context."""
        with suppress(Exception):
            return max(80, int(self.app.size.width))
        with suppress(Exception):
            return max(80, int(self.size.width))
        return 160

    def _current_viewport_height(self) -> int:
        """Return current viewport height with safe fallback outside app context."""
        with suppress(Exception):
            return max(20, int(self.app.size.height))
        with suppress(Exception):
            return max(20, int(self.size.height))
        return 50

    def _update_static_tab(
        self,
        container_id: str,
        empty_id: str,
        content: str,
        *,
        markup: bool = True,
    ) -> None:
        """Update a static content tab (overview, health)."""
        with suppress(NoMatches):
            container = self.query_one(f"#{container_id}", CustomContainer)
            self.query_one(f"#{empty_id}", CustomStatic).add_class("hidden")
            container.remove_children()
            if container_id == "health-container":
                container.remove_class("hidden")
            if content:
                container.mount(CustomStatic(content, markup=markup, classes="overview-content"))
            elif container_id == "health-container":
                container.add_class("hidden")

    def _extract_numeric_value(self, value: str) -> float:
        """Extract first numeric token from a formatted value string."""
        normalized = self._strip_markup(value).replace("%", "").replace("!", "").strip()
        match = self._NUMBER_RE.search(normalized)
        if not match:
            return 0.0
        with suppress(ValueError):
            return float(match.group(0))
        return 0.0

    def _compact_numeric_token(
        self,
        raw_text: str,
        *,
        threshold: float | None = None,
    ) -> str:
        """Compact a numeric token using k/M suffixes when needed."""
        text = raw_text.strip()
        match = re.fullmatch(
            r"(?P<number>-?\d+(?:\.\d+)?)(?:\s*(?P<unit>[A-Za-z%]+))?",
            text,
        )
        if not match:
            return text

        with suppress(ValueError):
            numeric_value = float(match.group("number"))
            unit_suffix = match.group("unit") or ""
            compact_threshold = (
                self._DIGIT_COMPACT_THRESHOLD
                if threshold is None
                else threshold
            )
            if abs(numeric_value) < compact_threshold:
                value_text = (
                    str(int(numeric_value))
                    if numeric_value.is_integer()
                    else str(numeric_value)
                )
                return f"{value_text}{unit_suffix}"
            if abs(numeric_value) >= 1_000_000:
                compact_value = numeric_value / 1_000_000
                suffix = "M"
            else:
                compact_value = numeric_value / 1_000
                suffix = "k"
            compact_text = f"{compact_value:.1f}".rstrip("0").rstrip(".")
            return f"{compact_text}{suffix}{unit_suffix}"
        return text

    def _compact_digits_value(self, value: str) -> str:
        """Compact large numeric values so summary digits remain readable."""
        raw_text = self._DIGIT_DECORATION_RE.sub(
            "",
            self._strip_markup(value),
        ).replace(",", "").strip()
        if not raw_text:
            return "0"
        # Textual Digits lacks reliable "/" glyph support in this font setup.
        # Normalize req/limit-like pairs to ":" and compact each side.
        for separator in ("/", ":", "|"):
            if separator in raw_text:
                left_raw, right_raw = raw_text.split(separator, 1)
                left = self._compact_numeric_token(left_raw, threshold=1000)
                right = self._compact_numeric_token(right_raw, threshold=1000)
                return f"{left}/{right}"

        return self._compact_numeric_token(raw_text)

    def _render_summary_kpis(
        self,
        container_id: str,
        items: list[tuple[str, str, str]],
        *,
        empty_text: str,
    ) -> None:
        """Render summary KPI rows as one stable static block to avoid flicker."""
        label_width = max(
            (len(self._strip_markup(str(title))) for title, _, _ in items),
            default=0,
        )

        status_styles = {
            "success": "green",
            "warning": "yellow",
            "error": "red",
            "info": "white",
        }

        if not items:
            content = f"[dim]{empty_text}[/dim]"
        else:
            lines: list[str] = []
            for title, value, status in items:
                title_text = self._strip_markup(str(title))
                value_text = self._strip_markup(str(value))
                padded_title = title_text.ljust(label_width)
                value_style = status_styles.get(status, "white")
                lines.append(
                    f"[dim]{padded_title}[/dim] [{value_style}]{value_text}[/{value_style}]"
                )
            content = "\n".join(lines)

        with suppress(NoMatches):
            container = self.query_one(f"#{container_id}", CustomContainer)
            with suppress(NoMatches):
                content_widget = container.query_one(".summary-kpi-block", CustomStatic)
                content_widget.update(content)
                return
            container.remove_children()
            container.mount(
                CustomStatic(
                    content,
                    classes="summary-kpi-block",
                    markup=True,
                )
            )

    def _update_summary_digits_widget(
        self,
        widget_id: str,
        value: str,
        *,
        status: str = "success",
    ) -> None:
        """Update one mounted digits widget value and status indicators."""
        status_classes = ("success", "warning", "error", "muted", "accent")
        panel_status_classes = tuple(f"status-{name}" for name in status_classes)
        digits_widget = self._get_cached_digits(widget_id)
        static_widget: CustomStatic | None = None
        if digits_widget is None:
            static_widget = self._get_cached_metric_static(widget_id)
        if digits_widget is None and static_widget is None:
            return
        if widget_id.startswith("overview-pod-"):
            display_value = self._strip_markup(value).replace(",", "").strip() or "0"
        else:
            display_value = self._compact_digits_value(value)
        if digits_widget is not None:
            widget_obj: CustomDigits | CustomStatic = digits_widget
        else:
            assert static_widget is not None
            widget_obj = static_widget
        current_value = (
            str(getattr(digits_widget, "value", ""))
            if digits_widget is not None
            else self._strip_markup(
                str(getattr(static_widget, "renderable", ""))
            )
        )
        value_changed = current_value != display_value
        widget_obj.tooltip = (
            self._strip_markup(value)
            if display_value != self._strip_markup(value)
            else None
        )
        if status not in widget_obj.classes:
            for class_name in status_classes:
                widget_obj.remove_class(class_name)
            widget_obj.add_class(status)

        on_complete: Callable[[], None] | None = None
        parent_container = getattr(widget_obj, "parent", None)
        if isinstance(parent_container, CustomContainer):
            panel_class = f"status-{status}"
            with suppress(NoMatches):
                indicator = parent_container.query_one(
                    f"#{widget_id}-indicator",
                    CustomStatic,
                )
                if panel_class not in indicator.classes:
                    for class_name in panel_status_classes:
                        indicator.remove_class(class_name)
                    indicator.add_class(panel_class)
                if value_changed:
                    indicator.update("●")
                    def _hide_indicator(widget_id_local: str = widget_id) -> None:
                        self._schedule_summary_digit_indicator_hide(widget_id_local)

                    on_complete = _hide_indicator
                else:
                    indicator.update(" ")
        if value_changed:
            if digits_widget is None:
                static_widget = static_widget or self._get_cached_metric_static(widget_id)
                if static_widget is not None:
                    static_widget.update(display_value)
                    if on_complete is not None:
                        with suppress(Exception):
                            on_complete()
            elif widget_id.startswith("events-digits-"):
                digits_widget.update(display_value)
                if on_complete is not None:
                    with suppress(Exception):
                        on_complete()
            else:
                digits_widget.update_with_animation(display_value, on_complete=on_complete)

    def _update_overview_summary_widgets(self, presenter: ClusterPresenter) -> None:
        """Render summary overview metrics using mounted digits widgets."""
        if self._error_message:
            with suppress(NoMatches):
                self.query_one("#overview-cluster-name", CustomStatic).update(
                    self._error_message
                )
            return

        data = presenter.get_overview_data()
        ready_nodes = int(data.get("ready_nodes", 0))
        total_nodes = int(data.get("total_nodes", 0))
        not_ready_nodes = max(0, total_nodes - ready_nodes)
        warnings = int(data.get("warning_events", 0))
        errors = int(data.get("error_events", 0))
        blocking_pdbs = int(data.get("blocking_pdbs", 0))
        single_replica = int(data.get("single_replica_count", 0))

        status_nodes = "success" if not_ready_nodes == 0 else "warning"
        status_errors = "error" if errors > 0 else "success"
        status_warnings = "warning" if warnings > 0 else "success"
        status_pdb = "error" if blocking_pdbs > 0 else "success"
        status_single = "warning" if single_replica > 0 else "success"
        cluster_name = self._strip_markup(str(data.get("cluster_name", ""))).strip()
        if cluster_name.lower() == "eks cluster":
            cluster_name = ""
        with suppress(NoMatches):
            self.query_one("#overview-cluster-name", CustomStatic).update(
                cluster_name
            )
        self._update_summary_digits_widget(
            "overview-digits-ready",
            str(ready_nodes),
            status=status_nodes,
        )
        self._update_summary_digits_widget(
            "overview-digits-not-ready",
            str(not_ready_nodes),
            status=status_nodes,
        )
        self._update_summary_digits_widget(
            "overview-digits-warnings",
            str(warnings),
            status=status_warnings,
        )
        self._update_summary_digits_widget(
            "overview-digits-errors",
            str(errors),
            status=status_errors,
        )
        self._update_summary_digits_widget(
            "overview-digits-blocking-pdbs",
            str(blocking_pdbs),
            status=status_pdb,
        )
        self._update_summary_digits_widget(
            "overview-digits-single-replica",
            str(single_replica),
            status=status_single,
        )

    def _update_events_summary_widgets(self, presenter: ClusterPresenter) -> None:
        """Render event summary metrics using mounted digits widgets."""
        rows = presenter.get_event_summary_rows()
        value_by_title: dict[str, str] = {}
        for row in rows:
            if len(row) < 2:
                continue
            value_by_title[self._strip_markup(str(row[0]))] = self._strip_markup(str(row[1]))

        event_digits_map = (
            ("OOMKilling", "events-digits-oomkilling"),
            ("NodeNotReady", "events-digits-nodenotready"),
            ("FailedScheduling", "events-digits-failedscheduling"),
            ("BackOff", "events-digits-backoff"),
            ("Unhealthy", "events-digits-unhealthy"),
            ("FailedMount", "events-digits-failedmount"),
            ("Evicted", "events-digits-evicted"),
        )
        for event_name, widget_id in event_digits_map:
            value_text = value_by_title.get(event_name, "0")
            count = int(self._extract_numeric_value(value_text))
            self._update_summary_digits_widget(
                widget_id,
                value_text,
                status="success" if count == 0 else "error",
            )

    def _update_workload_footprint_widgets(self, presenter: ClusterPresenter) -> None:
        """Render workload footprint metrics for the workloads overview panel."""
        rows = presenter.get_stats_rows()
        stats_map = {
            (category, metric): value for category, metric, value in rows
        }

        charts_overview = presenter.get_charts_overview()
        charts_available = bool(charts_overview.get("available"))
        chart_total = int(charts_overview.get("total_charts", 0))
        team_total = int(charts_overview.get("team_count", 0))
        single_charts = int(charts_overview.get("single_replica_charts", 0))
        charts_with_pdb = int(charts_overview.get("charts_with_pdb", 0))
        pdb_coverage_rows = presenter.get_pdb_coverage_summary_rows()
        coverage_value_by_metric = {
            self._strip_markup(str(metric)): self._strip_markup(str(value))
            for metric, value in pdb_coverage_rows
            if isinstance(metric, str | int | float)
            and isinstance(value, str | int | float)
        }
        template_charts = int(
            self._extract_numeric_value(
                coverage_value_by_metric.get("Charts with PDB Template", "0")
            )
        )

        charts_without_template = max(0, chart_total - template_charts)
        charts_without_pdb = max(0, chart_total - charts_with_pdb)
        single_ratio_value = (
            f"{(single_charts / chart_total) * 100:.1f}%"
            if chart_total > 0
            else "0.0%"
        )

        if charts_available:
            team_total_value = str(team_total)
            workloads_total_value = self._strip_markup(
                str(stats_map.get(("Workloads", "Total"), "0"))
            )
            single_charts_value = str(single_charts)
            no_template_value = str(charts_without_template)
            no_pdb_value = str(charts_without_pdb)
        else:
            # Digits widget clips mixed alpha placeholders like "N/A".
            team_total_value = "-"
            workloads_total_value = "-"
            single_charts_value = "-"
            single_ratio_value = "-"
            no_template_value = "-"
            no_pdb_value = "-"

        self._update_summary_digits_widget(
            "workloads-footprint-team-total",
            team_total_value,
            status="success" if charts_available and team_total > 0 else "muted",
        )
        self._update_summary_digits_widget(
            "workloads-footprint-workloads-total",
            workloads_total_value,
            status=(
                "success"
                if int(self._extract_numeric_value(workloads_total_value)) > 0
                else "muted"
            ),
        )
        self._update_summary_digits_widget(
            "workloads-footprint-single-charts",
            single_charts_value,
            status=(
                "muted"
                if not charts_available
                else ("warning" if single_charts > 0 else "success")
            ),
        )
        self._update_summary_digits_widget(
            "workloads-footprint-single-ratio",
            single_ratio_value,
            status=(
                "muted"
                if not charts_available
                else ("warning" if self._extract_numeric_value(single_ratio_value) > 20 else "success")
            ),
        )
        self._update_summary_digits_widget(
            "workloads-footprint-charts-no-template",
            no_template_value,
            status=(
                "muted"
                if not charts_available
                else ("warning" if charts_without_template > 0 else "success")
            ),
        )
        self._update_summary_digits_widget(
            "workloads-footprint-charts-no-pdb",
            no_pdb_value,
            status=(
                "muted"
                if not charts_available
                else ("error" if charts_without_pdb > 0 else "success")
            ),
        )

    def _update_overview_pod_stats_widgets(self, presenter: ClusterPresenter) -> None:
        """Render pod request statistics using compact summary digits."""
        rows = presenter.get_overview_pod_stats_rows()
        value_by_metric: dict[str, tuple[str, str, str, str]] = {}
        for row in rows:
            if len(row) != 5:
                continue
            metric, minimum, average, maximum, p95 = row
            value_by_metric[self._strip_markup(str(metric))] = (
                self._strip_markup(str(minimum)),
                self._strip_markup(str(average)),
                self._strip_markup(str(maximum)),
                self._strip_markup(str(p95)),
            )

        cpu_req_values = value_by_metric.get(
            "CPU Request (m)",
            value_by_metric.get("CPU (m)", ("0", "0", "0", "0")),
        )
        cpu_lim_values = value_by_metric.get("CPU Limit (m)", ("0", "0", "0", "0"))
        mem_req_values = value_by_metric.get(
            "Memory Request (Mi)",
            value_by_metric.get("Memory (Mi)", ("0", "0", "0", "0")),
        )
        mem_lim_values = value_by_metric.get("Memory Limit (Mi)", ("0", "0", "0", "0"))

        def _pod_status(req: str, lim: str, default_status: str) -> str:
            return (
                default_status
                if self._extract_numeric_value(req) > 0
                or self._extract_numeric_value(lim) > 0
                else "muted"
            )

        pod_digit_pairs = (
            (
                "overview-pod-cpu-req-min",
                self._format_pod_stats_value(cpu_req_values[0], metric="cpu"),
                "overview-pod-cpu-lim-min",
                self._format_pod_stats_value(cpu_lim_values[0], metric="cpu"),
                _pod_status(cpu_req_values[0], cpu_lim_values[0], "success"),
            ),
            (
                "overview-pod-cpu-req-avg",
                self._format_pod_stats_value(cpu_req_values[1], metric="cpu"),
                "overview-pod-cpu-lim-avg",
                self._format_pod_stats_value(cpu_lim_values[1], metric="cpu"),
                _pod_status(cpu_req_values[1], cpu_lim_values[1], "accent"),
            ),
            (
                "overview-pod-cpu-req-max",
                self._format_pod_stats_value(cpu_req_values[2], metric="cpu"),
                "overview-pod-cpu-lim-max",
                self._format_pod_stats_value(cpu_lim_values[2], metric="cpu"),
                _pod_status(cpu_req_values[2], cpu_lim_values[2], "warning"),
            ),
            (
                "overview-pod-cpu-req-p95",
                self._format_pod_stats_value(cpu_req_values[3], metric="cpu"),
                "overview-pod-cpu-lim-p95",
                self._format_pod_stats_value(cpu_lim_values[3], metric="cpu"),
                _pod_status(cpu_req_values[3], cpu_lim_values[3], "warning"),
            ),
            (
                "overview-pod-mem-req-min",
                self._format_pod_stats_value(mem_req_values[0], metric="memory"),
                "overview-pod-mem-lim-min",
                self._format_pod_stats_value(mem_lim_values[0], metric="memory"),
                _pod_status(mem_req_values[0], mem_lim_values[0], "success"),
            ),
            (
                "overview-pod-mem-req-avg",
                self._format_pod_stats_value(mem_req_values[1], metric="memory"),
                "overview-pod-mem-lim-avg",
                self._format_pod_stats_value(mem_lim_values[1], metric="memory"),
                _pod_status(mem_req_values[1], mem_lim_values[1], "accent"),
            ),
            (
                "overview-pod-mem-req-max",
                self._format_pod_stats_value(mem_req_values[2], metric="memory"),
                "overview-pod-mem-lim-max",
                self._format_pod_stats_value(mem_lim_values[2], metric="memory"),
                _pod_status(mem_req_values[2], mem_lim_values[2], "warning"),
            ),
            (
                "overview-pod-mem-req-p95",
                self._format_pod_stats_value(mem_req_values[3], metric="memory"),
                "overview-pod-mem-lim-p95",
                self._format_pod_stats_value(mem_lim_values[3], metric="memory"),
                _pod_status(mem_req_values[3], mem_lim_values[3], "warning"),
            ),
        )
        for req_widget_id, req_value, lim_widget_id, lim_value, status in pod_digit_pairs:
            self._update_summary_digits_widget(
                req_widget_id,
                req_value,
                status=status,
            )
            self._update_summary_digits_widget(
                lim_widget_id,
                lim_value,
                status=status,
            )

    def _format_pod_stats_value(self, value: str, *, metric: str) -> str:
        """Format one pod stat value according to active pod units mode."""
        normalized = self._strip_markup(value).replace(",", "").strip()
        if not normalized:
            return "0"
        if not any(char.isdigit() for char in normalized):
            return normalized

        numeric_value = self._extract_numeric_value(normalized)
        if self._pod_stats_unit_mode == self._POD_STATS_UNIT_MODE_CORE_GB:
            if metric == "cpu":
                converted_value = numeric_value / 1000
                unit = "core"
            else:
                converted_value = numeric_value / 1024
                unit = "gb"
        else:
            converted_value = numeric_value
            unit = "m" if metric == "cpu" else "Mi"

        abs_value = abs(converted_value)
        compact_suffix = ""
        compact_value = converted_value
        if abs_value >= 1_000_000:
            compact_value = converted_value / 1_000_000
            compact_suffix = "M"
        elif abs_value >= 1_000:
            compact_value = converted_value / 1_000
            compact_suffix = "k"

        value_text = f"{compact_value:.3f}".rstrip("0").rstrip(".")
        if not value_text:
            value_text = "0"
        return f"{value_text}{compact_suffix}{unit}"

    @staticmethod
    def _format_capacity_value(value: float, decimals: int) -> str:
        """Format capacity number with fixed precision and trimmed trailing zeros."""
        if decimals <= 0:
            return str(round(value))
        value_text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
        return value_text or "0"

    def _format_node_distribution_totals(
        self,
        total_cpu_millicores: float,
        total_memory_bytes: float,
    ) -> tuple[str, str]:
        """Format node distribution totals according to active units mode."""
        if self._node_distribution_unit_mode == self._NODE_DISTRIBUTION_UNIT_MODE_CORE_GB:
            cpu_cores = total_cpu_millicores / 1000
            memory_gb = total_memory_bytes / (1000 ** 3)
            cpu_decimals = 1 if abs(cpu_cores) < 100 else 0
            memory_decimals = 1 if abs(memory_gb) < 100 else 0
            return (
                f"{self._format_capacity_value(cpu_cores, cpu_decimals)}core",
                f"{self._format_capacity_value(memory_gb, memory_decimals)}GB",
            )

        memory_gib = total_memory_bytes / (1024 ** 3)
        return (
            f"{self._format_capacity_value(total_cpu_millicores, 0)}m",
            f"{self._format_capacity_value(memory_gib, 1)}Gi",
        )

    def _update_overview_alloc_widgets(self, presenter: ClusterPresenter) -> None:
        """Render allocated analysis using compact summary digits."""
        rows = presenter.get_overview_alloc_rows()
        value_by_metric: dict[str, tuple[str, str, str]] = {}
        for row in rows:
            if len(row) != 4:
                continue
            metric, avg, maximum, p95 = row
            value_by_metric[self._strip_markup(str(metric))] = (
                self._strip_markup(str(avg)),
                self._strip_markup(str(maximum)),
                self._strip_markup(str(p95)),
            )

        def _alloc_status(value: str) -> str:
            numeric_value = self._extract_numeric_value(value)
            if numeric_value <= 0:
                return "muted"
            if numeric_value > 100:
                return "error"
            if numeric_value > 80:
                return "warning"
            return "success"

        alloc_mappings = (
            ("CPU Req %", "overview-alloc-cpu-req"),
            ("Mem Req %", "overview-alloc-mem-req"),
            ("CPU Lim %", "overview-alloc-cpu-lim"),
            ("Mem Lim %", "overview-alloc-mem-lim"),
        )
        for metric_name, prefix in alloc_mappings:
            avg, maximum, p95 = value_by_metric.get(metric_name, ("0%", "0%", "0%"))
            self._update_summary_digits_widget(
                f"{prefix}-avg",
                avg,
                status=_alloc_status(avg),
            )
            self._update_summary_digits_widget(
                f"{prefix}-max",
                maximum,
                status=_alloc_status(maximum),
            )
            self._update_summary_digits_widget(
                f"{prefix}-p95",
                p95,
                status=_alloc_status(p95),
            )

    def _update_nodes_summary_widgets(self, presenter: ClusterPresenter) -> None:
        """Render nodes-tab summary metrics as compact digits panels."""
        ready_nodes, total_nodes = presenter.count_ready_nodes()
        not_ready_nodes = max(0, total_nodes - ready_nodes)

        conditions = presenter.get_node_conditions()
        condition_alerts = 0
        condition_unknown = 0
        for condition_name, statuses in conditions.items():
            true_count = int(statuses.get("True", 0))
            false_count = int(statuses.get("False", 0))
            unknown_count = int(statuses.get("Unknown", 0))
            condition_unknown += unknown_count
            if condition_name == "Ready":
                condition_alerts += false_count
            else:
                condition_alerts += true_count

        taints_data = presenter.get_node_taints()
        tainted_nodes = int(taints_data.get("total_nodes_with_taints", 0))
        high_pod_nodes = len(presenter.get_high_pod_count_nodes())

        az_distribution = presenter.get_az_distribution()
        az_count = len(az_distribution)
        instance_type_count = len(presenter.get_instance_type_distribution())
        kubelet_version_count = len(presenter.get_kubelet_version_distribution())
        node_groups = presenter.get_node_groups()
        node_group_count = len(node_groups)
        nodes = presenter.get_nodes()

        def _to_float(value: Any) -> float:
            with suppress(TypeError, ValueError):
                return float(value)
            return 0.0

        total_cpu_allocatable = sum(
            _to_float(getattr(node, "cpu_allocatable", 0))
            for node in nodes
        )
        total_memory_allocatable_bytes = sum(
            _to_float(getattr(node, "memory_allocatable", 0))
            for node in nodes
        )
        total_cpu_value, total_memory_value = self._format_node_distribution_totals(
            total_cpu_allocatable,
            total_memory_allocatable_bytes,
        )

        if total_nodes <= 0:
            ready_status = "muted"
            not_ready_status = "muted"
            alerts_status = "muted"
            unknown_status = "muted"
            taint_status = "muted"
            high_pod_status = "muted"
        else:
            ready_status = "success" if not_ready_nodes == 0 else "warning"
            not_ready_status = "warning" if not_ready_nodes > 0 else "success"
            alerts_status = "error" if condition_alerts > 0 else "success"
            unknown_status = "warning" if condition_unknown > 0 else "success"
            taint_status = "warning" if tainted_nodes > 0 else "success"
            high_pod_status = "warning" if high_pod_nodes > 0 else "success"

        self._update_summary_digits_widget(
            "nodes-digits-ready",
            str(ready_nodes),
            status=ready_status,
        )
        self._update_summary_digits_widget(
            "nodes-digits-not-ready",
            str(not_ready_nodes),
            status=not_ready_status,
        )
        self._update_summary_digits_widget(
            "nodes-digits-cond-alerts",
            str(condition_alerts),
            status=alerts_status,
        )
        self._update_summary_digits_widget(
            "nodes-digits-cond-unknown",
            str(condition_unknown),
            status=unknown_status,
        )
        self._update_summary_digits_widget(
            "nodes-digits-tainted",
            str(tainted_nodes),
            status=taint_status,
        )
        self._update_summary_digits_widget(
            "nodes-digits-high-pod",
            str(high_pod_nodes),
            status=high_pod_status,
        )
        self._update_summary_digits_widget(
            "nodes-digits-az-count",
            str(az_count),
            status="success" if az_count > 0 else "muted",
        )
        self._update_summary_digits_widget(
            "nodes-digits-instance-types",
            str(instance_type_count),
            status="success" if instance_type_count > 0 else "muted",
        )
        self._update_summary_digits_widget(
            "nodes-digits-kubelet-vers",
            str(kubelet_version_count),
            status="success" if kubelet_version_count > 0 else "muted",
        )
        self._update_summary_digits_widget(
            "nodes-digits-group-count",
            str(node_group_count),
            status="success" if node_group_count > 0 else "muted",
        )
        self._update_summary_digits_widget(
            "nodes-digits-total-cpu",
            total_cpu_value,
            status="success" if total_cpu_allocatable > 0 else "muted",
        )
        self._update_summary_digits_widget(
            "nodes-digits-total-mem",
            total_memory_value,
            status="success" if total_memory_allocatable_bytes > 0 else "muted",
        )

    def _update_workloads_pdb_coverage_widgets(self, presenter: ClusterPresenter) -> None:
        """Render workload PDB coverage summary as summary digits."""
        chart_rows = presenter.get_pdb_coverage_summary_rows()
        runtime_rows = presenter.get_runtime_pdb_coverage_summary_rows()
        chart_values: dict[str, str] = {}
        runtime_values: dict[str, str] = {}

        for row in chart_rows:
            if len(row) < 2:
                continue
            metric, value = row[0], row[1]
            chart_values[self._strip_markup(str(metric))] = self._strip_markup(str(value))
        for row in runtime_rows:
            if len(row) < 2:
                continue
            metric, value = row[0], row[1]
            runtime_values[self._strip_markup(str(metric))] = self._strip_markup(str(value))

        total_charts = chart_values.get("Total Charts", "0")
        total_runtime = runtime_values.get("Total Runtime Workloads", "0")
        template_charts = chart_values.get("Charts with PDB Template", "0")
        enabled_charts = chart_values.get("Charts with PDB Enabled", "0")
        protected_runtime = runtime_values.get("Runtime Workloads with PDB", "0")
        chart_pdb_coverage = chart_values.get("PDB Coverage", "0%")
        template_coverage = chart_values.get("Template Coverage", "0%")
        runtime_pdb_coverage = runtime_values.get("Runtime PDB Coverage", "0%")

        total_chart_numeric = self._extract_numeric_value(total_charts)
        total_runtime_numeric = self._extract_numeric_value(total_runtime)
        template_numeric = self._extract_numeric_value(template_charts)
        enabled_chart_numeric = self._extract_numeric_value(enabled_charts)
        enabled_runtime_numeric = self._extract_numeric_value(protected_runtime)

        def _coverage_status(value: str) -> str:
            numeric_value = self._extract_numeric_value(value)
            if numeric_value <= 0:
                return "muted"
            if numeric_value < 30:
                return "error"
            if numeric_value < 50:
                return "warning"
            return "success"

        def _coverage_pair_status(chart_value: str, runtime_value: str) -> str:
            chart_numeric = self._extract_numeric_value(chart_value)
            runtime_numeric = self._extract_numeric_value(runtime_value)
            has_chart = total_chart_numeric > 0
            has_runtime = total_runtime_numeric > 0
            if not has_chart and not has_runtime:
                return "muted"
            values: list[float] = []
            if has_chart:
                values.append(chart_numeric)
            if has_runtime:
                values.append(runtime_numeric)
            if not values:
                return "muted"
            min_value = min(values)
            if min_value < 30:
                return "error"
            if min_value < 50:
                return "warning"
            return "success"

        template_status = (
            "muted"
            if total_chart_numeric <= 0
            else ("warning" if template_numeric < total_chart_numeric else "success")
        )
        enabled_status = (
            "muted"
            if total_chart_numeric <= 0 and total_runtime_numeric <= 0
            else (
                "warning"
                if (
                    (total_chart_numeric > 0 and enabled_chart_numeric < total_chart_numeric)
                    or (
                        total_runtime_numeric > 0
                        and enabled_runtime_numeric < total_runtime_numeric
                    )
                )
                else "success"
            )
        )

        self._update_summary_digits_widget(
            "workloads-pdb-total-charts",
            f"{total_charts} / {total_runtime}",
            status=(
                "success"
                if total_chart_numeric > 0 or total_runtime_numeric > 0
                else "muted"
            ),
        )
        self._update_summary_digits_widget(
            "workloads-pdb-template-charts",
            template_charts,
            status=template_status,
        )
        self._update_summary_digits_widget(
            "workloads-pdb-enabled-charts",
            f"{enabled_charts} / {protected_runtime}",
            status=enabled_status,
        )
        self._update_summary_digits_widget(
            "workloads-pdb-coverage",
            f"{chart_pdb_coverage} / {runtime_pdb_coverage}",
            status=_coverage_pair_status(chart_pdb_coverage, runtime_pdb_coverage),
        )
        self._update_summary_digits_widget(
            "workloads-pdb-template-coverage",
            template_coverage,
            status=_coverage_status(template_coverage),
        )

    # =========================================================================
    # Tab Refresh — lazy per-tab (M1)
    # =========================================================================

    # Loading indicator IDs per tab
    _TAB_LOADING_IDS: dict[str, str] = {
        "tab-nodes": "nodes-loading",
        "tab-pods": "pods-loading",
        "tab-events": "events-loading",
    }

    def _set_active_tab(self, tab_id: str) -> None:
        """Set active cluster tab and keep ContentSwitcher in sync."""
        target_tab = tab_id if tab_id in self.TAB_IDS else TAB_NODES
        self._active_tab_id = target_tab
        with suppress(Exception):
            tabs = self.query_one("#cluster-view-tabs", CustomTabs)
            if tabs.active != target_tab:
                self._ignore_next_cluster_tab_id = target_tab
                tabs.active = target_tab
        with suppress(Exception):
            self.query_one("#cluster-inner-switcher", ContentSwitcher).current = target_tab
        if self._data_loaded and target_tab not in self._populated_tabs:
            # Defer table rebuild so the tab switch renders immediately
            self.call_later(self._refresh_tab, target_tab)

    def _get_active_tab_id(self) -> str:
        """Get the currently active tab ID."""
        with suppress(NoMatches):
            tabs = self.query_one("#cluster-view-tabs", CustomTabs)
            return str(tabs.active) if tabs.active else self._active_tab_id
        return self._active_tab_id

    def _hide_all_loading_indicators(self) -> None:
        """Hide all per-tab loading indicators (C2)."""
        for tab_id in self.TAB_IDS:
            self._set_tab_loading_overlay_visible(tab_id, False)

    def _refresh_tab(self, tab_id: str) -> None:
        """Refresh a single tab's content."""
        p = self._presenter
        q = self.search_query
        table_snapshots: list[tuple[list[tuple[str, int]], list[tuple]]] = []

        def _update_table_with_snapshot(
            table_id: str,
            empty_id: str | None,
            columns: list[tuple[str, int]],
            rows: list[tuple],
        ) -> None:
            table_snapshots.append((columns, rows))
            self._update_table(
                table_id,
                empty_id,
                columns,
                rows,
                tab_id=tab_id,
            )

        if tab_id == "tab-events":
            self._update_events_summary_widgets(p)
            _update_table_with_snapshot(
                "events-detail-table",
                None,
                EVENTS_DETAIL_TABLE_COLUMNS,
                p.filter_rows(p.get_event_detail_rows(), q),
            )

        elif tab_id == "tab-nodes":
            self._update_nodes_summary_widgets(p)
            self._update_overview_alloc_widgets(p)
            _update_table_with_snapshot(
                "nodes-table",
                None,
                NODE_TABLE_COLUMNS,
                p.filter_rows(p.get_node_rows(), q),
            )
            _update_table_with_snapshot(
                "node-groups-table",
                None,
                p.get_node_group_columns(),
                p.filter_rows(p.get_node_group_rows(), q),
            )

        elif tab_id == "tab-pods":
            self._update_workload_footprint_widgets(p)
            self._update_overview_pod_stats_widgets(p)

        filter_snapshots = table_snapshots
        if tab_id == "tab-events" and table_snapshots:
            # Event filters are derived from detailed event rows.
            filter_snapshots = table_snapshots[-1:]
        self._sync_tab_filter_options(tab_id, filter_snapshots)

        # Keep full-tab loading overlay visible until all tab sources arrive.
        data_keys = self._TAB_DATA_KEYS.get(tab_id, [])
        loaded_keys = self._presenter.loaded_keys
        error_keys = set(self._presenter.partial_errors.keys())
        total_sources = len(data_keys)
        resolved_count = sum(
            1 for key in data_keys if key in loaded_keys or key in error_keys
        )
        error_count = sum(1 for key in data_keys if key in error_keys)
        all_resolved = total_sources == 0 or resolved_count >= total_sources
        has_any_payload = len(data_keys) > 0 and any(
            self._has_source_payload(key) for key in data_keys
        )

        tab_title = TAB_TITLES.get(tab_id, tab_id.removeprefix("tab-")).lower()
        loading_label = (
            self._TAB_LOADING_BASE_MESSAGES.get(tab_id, f"Loading {tab_title}...")
        )
        if total_sources > 0:
            loading_status = f"Sources: {resolved_count}/{total_sources} loaded"
        else:
            loading_status = "No data sources registered for this tab"
        if error_count:
            loading_status += f" ({error_count} unavailable)"
        self._set_tab_loading_text(
            tab_id,
            label_text=loading_label,
            status_text=loading_status,
        )
        self._set_tab_loading_overlay_visible(
            tab_id,
            not all_resolved and not has_any_payload,
        )

        # Resolve table overlays independently so one slow data source does not
        # hide other summary tables that already have data.
        for table_id in self._TAB_TABLE_IDS.get(tab_id, ()):
            table_keys = self._TABLE_DATA_KEYS.get(table_id, tuple(data_keys))
            table_resolved = (
                len(table_keys) == 0
                or all(key in loaded_keys or key in error_keys for key in table_keys)
            )
            has_partial_payload = (
                len(table_keys) > 0
                and any(self._has_source_payload(key) for key in table_keys)
            )
            self._set_table_overlay_visible(
                table_id,
                not table_resolved and not has_partial_payload,
            )

        if all_resolved:
            self._populated_tabs.add(tab_id)

    def _has_source_payload(self, source_key: str) -> bool:
        """Return True when presenter currently has non-empty data for source key."""
        value = self._presenter.get_source_value(source_key)
        if value is None:
            return False
        if source_key == "charts_overview" and isinstance(value, dict):
            # The unavailable fallback payload is structurally non-empty.
            # Treat it as "no payload" so workloads overlays remain truthful
            # until real source data arrives.
            return bool(value.get("available"))
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) > 0
        return True

    def _tab_has_any_payload(self, tab_id: str) -> bool:
        """Return True when any source powering the tab already has data."""
        data_keys = self._TAB_DATA_KEYS.get(tab_id, [])
        return any(self._has_source_payload(key) for key in data_keys)

    def _table_has_any_payload(self, table_id: str) -> bool:
        """Return True when any source feeding the table already has data."""
        table_keys = self._TABLE_DATA_KEYS.get(table_id, ())
        return any(self._has_source_payload(key) for key in table_keys)

    def _refresh_all_tabs(self) -> None:
        """Refresh all tabs using presenter data (used by backward-compat callers)."""
        self._populated_tabs.clear()
        for tab_id in self.TAB_IDS:
            self._refresh_tab(tab_id)

    # =========================================================================
    # Actions
    # =========================================================================

    def action_refresh(self) -> None:
        if bool(getattr(self.app, "skip_eks", False)):
            self._set_cluster_progress(100, "Cluster analysis disabled (--skip-eks)")
            self._set_inline_loading_bars_visible(True)
            self._hide_all_loading_indicators()
            self._set_all_table_overlays_visible(False)
            self._data_loaded = True
            self._refresh_tab(self._get_active_tab_id())
            return
        self._error_message = None
        self._reload_data_on_resume = False
        self._data_loaded = False
        self._populated_tabs.clear()
        self._reset_incremental_load_tracking()
        self._tab_filter_source_signatures.clear()
        self._tab_filter_truncated_columns = dict.fromkeys(self.TAB_IDS, 0)
        self._last_filter_truncated_column_count = 0
        if self._source_refresh_timer is not None:
            self._source_refresh_timer.stop()
            self._source_refresh_timer = None
        if self._status_refresh_timer is not None:
            self._status_refresh_timer.stop()
            self._status_refresh_timer = None
        self._reset_summary_widgets_for_refresh()
        self._cluster_load_progress = 0
        # Reset loading bar to show loading state
        self._set_inline_loading_bars_visible(True)
        self._set_cluster_progress(0, "Refreshing...")
        # Keep overlays non-blocking when cached data is already visible.
        for tab_id in self.TAB_IDS:
            self._set_tab_loading_overlay_visible(
                tab_id,
                not self._tab_has_any_payload(tab_id),
            )
        for tab_id in self.TAB_IDS:
            for table_id in self._TAB_TABLE_IDS.get(tab_id, ()):
                self._set_table_overlay_visible(
                    table_id,
                    not self._table_has_any_payload(table_id),
                )
        for tab_id in self.TAB_IDS:
            base_message = self._TAB_LOADING_BASE_MESSAGES.get(
                tab_id,
                "Loading...",
            )
            self._set_tab_loading_text(
                tab_id,
                label_text=base_message,
                status_text="Waiting for cluster data sources...",
            )
        self._start_connection_stall_watchdog()
        self._presenter.load_data(force_refresh=True)

    def action_focus_search(self) -> None:
        search_input_id = self._control_id(self._get_active_tab_id(), "search-input")
        self.set_timer(
            0.05,
            lambda: self.query_one(f"#{search_input_id}", CustomInput).focus(),
        )

    def _action_switch_tab(self, tab_num: str) -> None:
        tab_map = {
            "1": "tab-nodes",
            "2": "tab-pods",
            "3": "tab-events",
        }
        tab_id = tab_map.get(tab_num)
        if tab_id:
            self._set_active_tab(tab_id)

    def action_switch_tab_1(self) -> None:
        self._action_switch_tab("1")

    def action_switch_tab_2(self) -> None:
        self._action_switch_tab("2")

    def action_switch_tab_3(self) -> None:
        self._action_switch_tab("3")

    def action_show_help(self) -> None:
        self.app.notify(
            "Cluster Screen Help:\n\n"
            "Navigation:\n"
            "  1 - Nodes tab\n"
            "  2 - Workloads tab\n"
            "  3 - Events tab\n"
            "  r - Refresh data\n"
            "  / - Focus search\n"
            "  h - Open Overview\n"
            "  ? - Show this help",
            severity="information",
            timeout=30,
        )


__all__ = ["ClusterScreen"]
