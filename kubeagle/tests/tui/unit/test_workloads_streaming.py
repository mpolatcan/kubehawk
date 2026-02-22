"""Unit tests for WorkloadsScreen namespace streaming behavior."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from kubeagle.screens.workloads.config import (
    TAB_WORKLOADS_ALL,
    TAB_WORKLOADS_EXTREME_RATIOS,
)
from kubeagle.screens.workloads.presenter import WorkloadsSourceLoaded
from kubeagle.screens.workloads.workloads_screen import WorkloadsScreen


@pytest.mark.unit
def test_partial_update_with_new_rows_unblocks_overlay_and_refreshes_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First streamed rows should hide overlay and render table immediately."""
    screen = WorkloadsScreen()
    progress_calls: list[tuple[int, str]] = []
    hide_calls: list[bool] = []
    filter_refresh_calls: list[bool] = []
    table_refresh_calls: list[bool] = []
    scheduled_calls: list[bool] = []

    monkeypatch.setattr(
        WorkloadsScreen,
        "is_current",
        property(lambda _self: True),
    )
    monkeypatch.setattr(
        screen,
        "_set_load_progress",
        lambda progress, message: progress_calls.append((progress, message)),
    )
    monkeypatch.setattr(screen, "hide_loading_overlay", lambda: hide_calls.append(True))
    monkeypatch.setattr(
        screen,
        "_refresh_filter_options",
        lambda: filter_refresh_calls.append(True),
    )
    monkeypatch.setattr(
        screen,
        "_refresh_active_tab",
        lambda: table_refresh_calls.append(True),
    )
    monkeypatch.setattr(
        screen,
        "_schedule_partial_refresh",
        lambda: scheduled_calls.append(True),
    )

    screen.on_workloads_source_loaded(
        WorkloadsSourceLoaded(
            "all_workloads",
            completed=1,
            total=4,
            row_count=7,
            has_new_rows=True,
        )
    )

    assert progress_calls
    assert hide_calls == [True]
    assert filter_refresh_calls == [True]
    assert table_refresh_calls == [True]
    assert scheduled_calls == []
    assert screen._stream_overlay_released is True
    assert screen._last_streamed_row_count == 7


@pytest.mark.unit
def test_partial_update_without_new_rows_uses_scheduled_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Namespace updates without new rows should keep refresh throttling path."""
    screen = WorkloadsScreen()
    screen._last_streamed_row_count = 5
    screen._stream_overlay_released = True
    progress_calls: list[tuple[int, str]] = []
    hide_calls: list[bool] = []
    filter_refresh_calls: list[bool] = []
    table_refresh_calls: list[bool] = []
    scheduled_calls: list[bool] = []

    monkeypatch.setattr(
        WorkloadsScreen,
        "is_current",
        property(lambda _self: True),
    )
    monkeypatch.setattr(
        screen,
        "_set_load_progress",
        lambda progress, message: progress_calls.append((progress, message)),
    )
    monkeypatch.setattr(screen, "hide_loading_overlay", lambda: hide_calls.append(True))
    monkeypatch.setattr(
        screen,
        "_refresh_filter_options",
        lambda: filter_refresh_calls.append(True),
    )
    monkeypatch.setattr(
        screen,
        "_refresh_active_tab",
        lambda: table_refresh_calls.append(True),
    )
    monkeypatch.setattr(
        screen,
        "_schedule_partial_refresh",
        lambda: scheduled_calls.append(True),
    )

    screen.on_workloads_source_loaded(
        WorkloadsSourceLoaded(
            "all_workloads",
            completed=2,
            total=4,
            row_count=5,
            has_new_rows=False,
        )
    )

    assert progress_calls
    assert hide_calls == []
    assert filter_refresh_calls == []
    assert table_refresh_calls == []
    assert scheduled_calls == [True]
    assert screen._last_streamed_row_count == 5


@pytest.mark.unit
def test_partial_update_with_additional_new_rows_uses_scheduled_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the first streamed rows, new chunks should follow throttled refresh path."""
    screen = WorkloadsScreen()
    screen._last_streamed_row_count = 3
    screen._stream_overlay_released = True
    filter_refresh_calls: list[bool] = []
    table_refresh_calls: list[bool] = []
    scheduled_calls: list[bool] = []

    monkeypatch.setattr(
        WorkloadsScreen,
        "is_current",
        property(lambda _self: True),
    )
    monkeypatch.setattr(screen, "_set_load_progress", lambda progress, message: None)
    monkeypatch.setattr(
        screen,
        "_refresh_filter_options",
        lambda: filter_refresh_calls.append(True),
    )
    monkeypatch.setattr(
        screen,
        "_refresh_active_tab",
        lambda: table_refresh_calls.append(True),
    )
    monkeypatch.setattr(
        screen,
        "_schedule_partial_refresh",
        lambda: scheduled_calls.append(True),
    )

    screen.on_workloads_source_loaded(
        WorkloadsSourceLoaded(
            "all_workloads",
            completed=2,
            total=5,
            row_count=8,
            has_new_rows=True,
        )
    )

    assert filter_refresh_calls == []
    assert table_refresh_calls == []
    assert scheduled_calls == [True]
    assert screen._last_streamed_row_count == 8


@pytest.mark.unit
def test_partial_update_throttles_large_stream_chunks_without_interval_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Large streaming tables should skip repaint when growth/interval thresholds are not met."""
    screen = WorkloadsScreen()
    screen._last_streamed_row_count = 400
    screen._stream_overlay_released = True
    screen._last_partial_refresh_row_count = 400
    screen._last_partial_refresh_at_monotonic = 100.0
    scheduled_calls: list[bool] = []

    monkeypatch.setattr(
        WorkloadsScreen,
        "is_current",
        property(lambda _self: True),
    )
    monkeypatch.setattr(screen, "_set_load_progress", lambda progress, message: None)
    monkeypatch.setattr(
        screen,
        "_schedule_partial_refresh",
        lambda: scheduled_calls.append(True),
    )
    monkeypatch.setattr(
        "kubeagle.screens.workloads.workloads_screen.time.monotonic",
        lambda: 100.1,
    )

    screen.on_workloads_source_loaded(
        WorkloadsSourceLoaded(
            "all_workloads",
            completed=4,
            total=20,
            row_count=420,
            has_new_rows=True,
        )
    )

    assert scheduled_calls == []
    assert screen._last_streamed_row_count == 420
    assert screen._last_partial_refresh_row_count == 400


@pytest.mark.unit
def test_partial_update_repaints_large_stream_chunks_when_interval_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Large streaming tables should repaint once minimum interval has elapsed."""
    screen = WorkloadsScreen()
    screen._last_streamed_row_count = 400
    screen._stream_overlay_released = True
    screen._last_partial_refresh_row_count = 400
    screen._last_partial_refresh_at_monotonic = 100.0
    scheduled_calls: list[bool] = []

    monkeypatch.setattr(
        WorkloadsScreen,
        "is_current",
        property(lambda _self: True),
    )
    monkeypatch.setattr(screen, "_set_load_progress", lambda progress, message: None)
    monkeypatch.setattr(
        screen,
        "_schedule_partial_refresh",
        lambda: scheduled_calls.append(True),
    )
    monkeypatch.setattr(
        "kubeagle.screens.workloads.workloads_screen.time.monotonic",
        lambda: 100.7,
    )

    screen.on_workloads_source_loaded(
        WorkloadsSourceLoaded(
            "all_workloads",
            completed=4,
            total=20,
            row_count=420,
            has_new_rows=True,
        )
    )

    assert scheduled_calls == [True]
    assert screen._last_streamed_row_count == 420
    assert screen._last_partial_refresh_row_count == 420


@pytest.mark.unit
def test_partial_progress_without_new_rows_releases_overlay_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First namespace progress should release overlay even with zero streamed rows."""
    screen = WorkloadsScreen()
    screen._stream_overlay_released = False
    hide_calls: list[bool] = []
    scheduled_calls: list[bool] = []
    stop_failsafe_calls: list[bool] = []

    monkeypatch.setattr(
        WorkloadsScreen,
        "is_current",
        property(lambda _self: True),
    )
    monkeypatch.setattr(screen, "_set_load_progress", lambda progress, message: None)
    monkeypatch.setattr(screen, "hide_loading_overlay", lambda: hide_calls.append(True))
    monkeypatch.setattr(
        screen,
        "_schedule_partial_refresh",
        lambda: scheduled_calls.append(True),
    )
    monkeypatch.setattr(
        screen,
        "_stop_loading_overlay_failsafe_timer",
        lambda: stop_failsafe_calls.append(True),
    )

    screen.on_workloads_source_loaded(
        WorkloadsSourceLoaded(
            "all_workloads",
            completed=1,
            total=6,
            row_count=0,
            has_new_rows=False,
        )
    )

    assert hide_calls == [True]
    assert stop_failsafe_calls == [True]
    assert scheduled_calls == [True]
    assert screen._stream_overlay_released is True


@pytest.mark.unit
def test_release_background_work_for_navigation_resets_loading_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suspending the screen should keep workers alive and arm a render-on-resume."""
    screen = WorkloadsScreen()
    screen._presenter._is_loading = True
    screen._is_loading = True
    screen._stream_overlay_released = False

    hide_calls: list[bool] = []
    stop_calls: list[bool] = []
    stop_partial_calls: list[bool] = []
    stop_search_calls: list[bool] = []
    stop_resume_calls: list[bool] = []

    monkeypatch.setattr(screen, "hide_loading_overlay", lambda: hide_calls.append(True))
    monkeypatch.setattr(
        screen,
        "_stop_loading_overlay_failsafe_timer",
        lambda: stop_calls.append(True),
    )
    monkeypatch.setattr(
        screen,
        "_stop_partial_refresh_timer",
        lambda: stop_partial_calls.append(True),
    )
    monkeypatch.setattr(
        screen,
        "_stop_search_debounce_timer",
        lambda: stop_search_calls.append(True),
    )
    monkeypatch.setattr(
        screen,
        "_stop_resume_reload_timer",
        lambda: stop_resume_calls.append(True),
    )

    screen._release_background_work_for_navigation()

    # Workers are kept alive (not cancelled) so data can finish in the background
    assert screen._render_on_resume is True
    assert screen._is_loading is False
    assert screen._stream_overlay_released is True
    assert stop_calls == [True]
    assert stop_partial_calls == [True]
    assert stop_search_calls == [True]
    assert stop_resume_calls == [True]
    assert hide_calls == [True]


@pytest.mark.unit
def test_on_screen_resume_schedules_cancelled_reload_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Screen resume should schedule the delayed reload-check loop."""
    screen = WorkloadsScreen()
    screen._reload_on_resume = True

    scheduled_calls: list[bool] = []
    app = SimpleNamespace(title="")

    monkeypatch.setattr(WorkloadsScreen, "app", property(lambda _self: app))
    monkeypatch.setattr(screen, "_set_primary_navigation_tab", lambda _tab_id: None)
    monkeypatch.setattr(
        screen,
        "_schedule_resume_reload_check",
        lambda *, immediate=False: scheduled_calls.append(immediate),
    )

    screen.on_screen_resume()

    assert scheduled_calls == [True]
    assert screen._reload_on_resume is True
    assert app.title == "KubEagle - Workloads"


@pytest.mark.unit
def test_programmatic_tab_switch_avoids_duplicate_refresh_from_synthetic_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting a tab in code should refresh once even if TabActivated follows."""
    screen = WorkloadsScreen()
    refresh_calls: list[bool] = []
    tabs = SimpleNamespace(active=TAB_WORKLOADS_ALL)
    switcher = SimpleNamespace(current=TAB_WORKLOADS_ALL)

    def _query_one(selector: str, _widget_type: object) -> object:
        if selector == "#workloads-view-tabs":
            return tabs
        if selector == "#workloads-content-switcher":
            return switcher
        raise AssertionError(f"Unexpected selector: {selector}")

    monkeypatch.setattr(screen, "query_one", _query_one)
    monkeypatch.setattr(screen, "_refresh_active_tab", lambda: refresh_calls.append(True))
    # call_later defers to the event loop; execute immediately in unit tests
    monkeypatch.setattr(screen, "call_later", lambda fn, *a, **kw: fn(*a, **kw))

    screen._set_active_tab(TAB_WORKLOADS_EXTREME_RATIOS)
    screen._on_view_tab_activated(
        SimpleNamespace(tab=SimpleNamespace(id=TAB_WORKLOADS_EXTREME_RATIOS))
    )

    assert refresh_calls == [True]


@pytest.mark.unit
def test_attempt_reload_on_resume_retries_while_worker_still_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume check should keep polling while previous worker is still active."""
    screen = WorkloadsScreen()
    screen._reload_on_resume = True
    screen._presenter._is_loading = True
    scheduled_calls: list[bool] = []

    monkeypatch.setattr(
        WorkloadsScreen,
        "is_current",
        property(lambda _self: True),
    )
    monkeypatch.setattr(
        screen,
        "_schedule_resume_reload_check",
        lambda *, immediate=False: scheduled_calls.append(immediate),
    )

    screen._attempt_reload_on_resume()

    assert scheduled_calls == [False]
    assert screen._reload_on_resume is True


@pytest.mark.unit
def test_attempt_reload_on_resume_starts_load_once_worker_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume check should restart loading once cancelation has fully settled."""
    screen = WorkloadsScreen()
    screen._reload_on_resume = True
    screen._presenter._is_loading = False
    started_calls: list[str] = []

    monkeypatch.setattr(
        WorkloadsScreen,
        "is_current",
        property(lambda _self: True),
    )
    monkeypatch.setattr(
        screen,
        "_start_load_worker",
        lambda *, force_refresh=False, message="Loading workloads...": started_calls.append(message),
    )

    screen._attempt_reload_on_resume()

    assert started_calls == ["Loading workloads..."]
    assert screen._reload_on_resume is False


@pytest.mark.unit
def test_input_changed_debounces_search_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typing in search should schedule a debounced table refresh."""
    screen = WorkloadsScreen()
    scheduled_calls: list[bool] = []
    event = SimpleNamespace(
        input=SimpleNamespace(id="workloads-search-input"),
        value="api  ",
    )

    monkeypatch.setattr(
        screen,
        "_schedule_search_refresh",
        lambda: scheduled_calls.append(True),
    )

    screen.on_input_changed(cast(Any, event))

    assert screen._search_query == "api"
    assert scheduled_calls == [True]


@pytest.mark.unit
def test_input_submitted_triggers_immediate_search_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Submitting search should bypass debounce and refresh immediately."""
    screen = WorkloadsScreen()
    apply_calls: list[bool] = []
    event = SimpleNamespace(
        input=SimpleNamespace(id="workloads-search-input"),
        value="worker",
    )

    monkeypatch.setattr(
        screen,
        "_apply_search_refresh",
        lambda *, immediate=False: apply_calls.append(immediate),
    )

    screen.on_input_submitted(cast(Any, event))

    assert screen._search_query == "worker"
    assert apply_calls == [True]


@pytest.mark.unit
def test_refresh_table_formats_rows_from_pre_filtered_workloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tab table refresh should reuse one filtered workload list for row rendering."""
    screen = WorkloadsScreen()
    filtered_workloads = [SimpleNamespace(name="api")]
    filtered_calls: list[bool] = []
    formatted_calls: list[list[SimpleNamespace]] = []

    class _FakeDataTable:
        fixed_columns = 0

    class _FakeTable:
        def __init__(self) -> None:
            self.data_table = _FakeDataTable()
            self.rows: list[tuple[str, ...]] = []
            self.cursor_row: int | None = None

        class _BatchContext:
            def __enter__(self) -> None:
                return None

            def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
                return False

        def batch_update(self) -> _BatchContext:
            return self._BatchContext()

        def clear(self, *, columns: bool) -> None:
            return None

        def set_header_tooltips(self, _tooltips: dict[str, str]) -> None:
            return None

        def set_default_tooltip(self, _text: str) -> None:
            return None

        def add_column(self, _name: str, *, key: str) -> None:
            return None

        def add_rows(self, rows: list[tuple[str, ...]]) -> None:
            self.rows = rows

    fake_table = _FakeTable()
    monkeypatch.setattr(
        screen._presenter,
        "get_filtered_workloads",
        lambda **_kwargs: filtered_calls.append(True) or filtered_workloads,
    )
    monkeypatch.setattr(
        screen._presenter,
        "format_workload_rows",
        lambda workloads, *, columns: (
            formatted_calls.append(list(workloads)) or [("api",)]
        ),
    )
    monkeypatch.setattr(
        screen._presenter,
        "get_resource_rows",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("get_resource_rows should not be called")
        ),
    )
    monkeypatch.setattr(screen, "query_one", lambda _selector, _widget_type: fake_table)

    screen._refresh_table(TAB_WORKLOADS_ALL)

    assert filtered_calls == [True]
    assert formatted_calls == [filtered_workloads]
    assert fake_table.rows == [("api",)]


@pytest.mark.unit
def test_refresh_table_preserves_selected_workload_row_across_stream_repaint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selection should remain on the same workload identity after table rebuild."""
    screen = WorkloadsScreen()
    old_selected_workload = SimpleNamespace(
        namespace="team-a",
        kind="Deployment",
        name="api",
    )
    screen._row_workload_map_by_table["workloads-all-table"] = {
        0: old_selected_workload
    }

    reordered_workloads = [
        SimpleNamespace(namespace="team-a", kind="Deployment", name="worker"),
        SimpleNamespace(namespace="team-a", kind="Deployment", name="api"),
    ]

    class _FakeDataTable:
        fixed_columns = 0

    class _FakeTable:
        def __init__(self) -> None:
            self.data_table = _FakeDataTable()
            self.rows: list[tuple[str, ...]] = []
            self.cursor_row: int | None = 0

        class _BatchContext:
            def __enter__(self) -> None:
                return None

            def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
                return False

        def batch_update(self) -> _BatchContext:
            return self._BatchContext()

        def clear(self, *, columns: bool) -> None:
            return None

        def set_header_tooltips(self, _tooltips: dict[str, str]) -> None:
            return None

        def set_default_tooltip(self, _text: str) -> None:
            return None

        def add_column(self, _name: str, *, key: str) -> None:
            return None

        def add_rows(self, rows: list[tuple[str, ...]]) -> None:
            self.rows = rows

    fake_table = _FakeTable()
    monkeypatch.setattr(
        screen._presenter,
        "get_filtered_workloads",
        lambda **_kwargs: reordered_workloads,
    )
    monkeypatch.setattr(
        screen._presenter,
        "format_workload_rows",
        lambda workloads, *, columns: [(str(workload.name),) for workload in workloads],
    )
    monkeypatch.setattr(screen, "query_one", lambda _selector, _widget_type: fake_table)

    screen._refresh_table(TAB_WORKLOADS_ALL)

    assert fake_table.cursor_row == 1
    assert screen._row_workload_map_by_table["workloads-all-table"][1].name == "api"


@pytest.mark.unit
def test_refresh_active_tab_reuses_filtered_workloads_for_summary_and_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active-tab refresh should reuse one filtered workload list across summary+table."""
    screen = WorkloadsScreen()
    filtered_workloads = [SimpleNamespace(name="api")]
    presenter_calls: list[str] = []
    summary_payloads: list[tuple[list[Any], int]] = []
    table_payloads: list[tuple[str, list[Any]]] = []

    monkeypatch.setattr(screen, "_active_view_filter", lambda: "all")
    monkeypatch.setattr(screen, "_current_filter_kwargs", lambda: {})
    monkeypatch.setattr(
        screen._presenter,
        "get_filtered_workloads",
        lambda **_kwargs: presenter_calls.append("filtered") or filtered_workloads,
    )
    monkeypatch.setattr(
        screen._presenter,
        "get_scoped_workload_count",
        lambda **_kwargs: presenter_calls.append("scoped") or 12,
    )
    monkeypatch.setattr(
        screen,
        "_refresh_summary",
        lambda *, filtered_workloads=None, scoped_total=None: summary_payloads.append(
            (list(filtered_workloads or []), int(scoped_total or 0))
        ),
    )
    monkeypatch.setattr(
        screen,
        "_refresh_table",
        lambda tab_id, *, filtered_workloads=None: table_payloads.append(
            (tab_id, list(filtered_workloads or []))
        ),
    )

    screen._refresh_active_tab()

    # When there is no search query, get_scoped_workload_count is skipped
    # (len(filtered_workloads) is used instead) to avoid a redundant filter pass.
    assert presenter_calls == ["filtered"]
    assert summary_payloads == [(filtered_workloads, len(filtered_workloads))]
    assert table_payloads == [(TAB_WORKLOADS_ALL, filtered_workloads)]
