"""Unit tests for Charts Explorer refresh behavior on optimizer tab."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from kubeagle.constants.enums import Severity
from kubeagle.models.analysis.violation import ViolationResult
from kubeagle.models.charts.chart_info import ChartInfo
from kubeagle.screens.charts_explorer.charts_explorer_screen import (
    ChartsExplorerDataLoaded,
    ChartsExplorerOptimizerPartialLoaded,
    ChartsExplorerPartialDataLoaded,
    ChartsExplorerScreen,
)
from kubeagle.screens.charts_explorer.config import (
    TAB_CHARTS,
    TAB_VIOLATIONS,
    ViewFilter,
)
from kubeagle.screens.detail.components.violations_view import (
    ViolationRefreshRequested,
)
from kubeagle.screens.detail.presenter import (
    OptimizerDataLoaded,
    OptimizerDataLoadFailed,
)


def _make_violation(chart_name: str) -> ViolationResult:
    return ViolationResult(
        id="RES002",
        chart_name=chart_name,
        chart_path=f"/tmp/{chart_name}/values.yaml",
        team="team-a",
        rule_name="No CPU Limits",
        rule_id="RES002",
        category="resources",
        severity=Severity.WARNING,
        description="Missing CPU limit",
        current_value="No CPU limit",
        recommended_value="resources.limits.cpu: 500m",
        fix_available=True,
    )


@pytest.mark.unit
def test_action_refresh_uses_force_refresh_on_optimizer_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refresh action should force a full charts reload on violations tab."""
    screen = ChartsExplorerScreen(testing=True, initial_tab=TAB_VIOLATIONS)
    screen._active_tab = TAB_VIOLATIONS
    called: dict[str, bool] = {}

    monkeypatch.setattr(screen, "show_loading_overlay", lambda _message: called.setdefault("overlay", True))

    def _capture_start_load_worker(*, force_refresh: bool = False, interrupt_if_loading: bool = False) -> None:
        called["force_refresh"] = force_refresh
        called["interrupt_if_loading"] = interrupt_if_loading

    monkeypatch.setattr(screen, "_start_load_worker", _capture_start_load_worker)

    screen.action_refresh()

    assert called["overlay"] is True
    assert called["force_refresh"] is True
    assert called["interrupt_if_loading"] is True


@pytest.mark.unit
def test_action_refresh_keeps_charts_tab_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refresh action should keep charts tab force-refresh behavior unchanged."""
    screen = ChartsExplorerScreen(testing=True, initial_tab=TAB_CHARTS)
    screen._active_tab = TAB_CHARTS
    called: dict[str, bool] = {}

    monkeypatch.setattr(screen, "show_loading_overlay", lambda _message: called.setdefault("overlay", True))

    def _capture_start_load_worker(*, force_refresh: bool = False, interrupt_if_loading: bool = False) -> None:
        called["force_refresh"] = force_refresh
        called["interrupt_if_loading"] = interrupt_if_loading

    monkeypatch.setattr(screen, "_start_load_worker", _capture_start_load_worker)

    screen.action_refresh()

    assert called["overlay"] is True
    assert called["force_refresh"] is True
    assert called["interrupt_if_loading"] is False


@pytest.mark.unit
def test_violation_refresh_requested_reloads_charts_with_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply/Retry refresh message should fully reload charts before optimizer rerun."""
    screen = ChartsExplorerScreen(testing=True)
    called: dict[str, bool] = {}

    monkeypatch.setattr(screen, "show_loading_overlay", lambda _message: called.setdefault("overlay", True))

    def _capture_start_load_worker(*, force_refresh: bool = False, interrupt_if_loading: bool = False) -> None:
        called["force_refresh"] = force_refresh
        called["interrupt_if_loading"] = interrupt_if_loading

    monkeypatch.setattr(screen, "_start_load_worker", _capture_start_load_worker)

    screen.on_violation_refresh_requested(ViolationRefreshRequested())

    assert called["overlay"] is True
    assert called["force_refresh"] is True
    assert called["interrupt_if_loading"] is True


@pytest.mark.unit
def test_start_optimizer_worker_force_refresh_resets_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force refresh should drop optimizer caches before starting a new worker."""
    screen = ChartsExplorerScreen(testing=True)
    screen._violations_signature = "sig"
    screen._cached_violations = []
    screen._cached_violation_counts = {"demo": 1}
    screen._cached_helm_recommendations = [{"kind": "helm"}]
    screen._cached_helm_recommendations_signature = "sig"

    run_calls: list[tuple[str, bool]] = []
    cancel_calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(screen, "_ensure_violations_view_initialized", lambda: None)
    monkeypatch.setattr(screen, "_cancel_workers_by_name", lambda *names: cancel_calls.append(tuple(names)))

    def _capture_run_worker(_worker: object, *, name: str, exclusive: bool) -> None:
        run_calls.append((name, exclusive))

    monkeypatch.setattr(screen, "run_worker", _capture_run_worker)

    screen._start_optimizer_worker(force_refresh=True)

    assert screen._violations_signature is None
    assert screen._cached_violations is None
    assert screen._cached_violation_counts is None
    assert screen._cached_helm_recommendations is None
    assert screen._cached_helm_recommendations_signature is None
    assert screen._optimizer_loading is True
    assert run_calls == [("charts-explorer-optimizer", True)]
    assert ("charts-explorer-violations",) in cancel_calls


@pytest.mark.unit
def test_start_optimizer_worker_force_refresh_restarts_while_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force refresh should restart optimizer worker even if one is already running."""
    screen = ChartsExplorerScreen(testing=True)
    screen._optimizer_loading = True
    run_calls: list[str] = []
    cancel_calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(screen, "_ensure_violations_view_initialized", lambda: None)
    monkeypatch.setattr(screen, "_cancel_workers_by_name", lambda *names: cancel_calls.append(tuple(names)))
    monkeypatch.setattr(
        screen,
        "run_worker",
        lambda _worker, *, name, exclusive: run_calls.append(name),
    )

    screen._start_optimizer_worker(force_refresh=True)

    assert any("charts-explorer-optimizer" in names for names in cancel_calls)
    assert "charts-explorer-optimizer" in run_calls
    assert screen._optimizer_loading is True


@pytest.mark.unit
def test_optimizer_partial_event_updates_progress_and_stream_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial optimizer events should increment streamed findings and progress text."""
    screen = ChartsExplorerScreen(testing=True, initial_tab=TAB_VIOLATIONS)
    screen._optimizer_generation = 12
    progress_messages: list[str] = []
    monkeypatch.setattr(
        screen,
        "_update_optimizer_loading_message",
        lambda message, progress_percent=None: progress_messages.append(message),
    )
    monkeypatch.setattr(
        ChartsExplorerScreen,
        "is_current",
        property(lambda _self: False),
    )

    screen.on_charts_explorer_optimizer_partial_loaded(
        ChartsExplorerOptimizerPartialLoaded(
            violations=[_make_violation("chart-one")],
            completed_charts=3,
            total_charts=10,
            optimizer_generation=12,
        )
    )

    assert len(screen._streaming_optimizer_violations) == 1
    assert progress_messages
    assert "(3/10 charts, 1 findings)" in progress_messages[-1]


@pytest.mark.unit
def test_optimizer_partial_event_ignores_stale_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial events from cancelled optimizer generations should be ignored."""
    screen = ChartsExplorerScreen(testing=True, initial_tab=TAB_VIOLATIONS)
    screen._optimizer_generation = 2
    progress_messages: list[str] = []
    monkeypatch.setattr(
        screen,
        "_update_optimizer_loading_message",
        lambda message: progress_messages.append(message),
    )

    screen.on_charts_explorer_optimizer_partial_loaded(
        ChartsExplorerOptimizerPartialLoaded(
            violations=[_make_violation("chart-stale")],
            completed_charts=1,
            total_charts=2,
            optimizer_generation=1,
        )
    )

    assert screen._streaming_optimizer_violations == []
    assert progress_messages == []


@pytest.mark.unit
def test_optimizer_partial_event_clears_table_loading_before_stream_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Current violations tab should drop table loading overlay on streamed updates."""
    screen = ChartsExplorerScreen(testing=True, initial_tab=TAB_VIOLATIONS)
    screen._optimizer_generation = 9
    screen._active_tab = TAB_VIOLATIONS
    progress_messages: list[str] = []
    monkeypatch.setattr(
        screen,
        "_update_optimizer_loading_message",
        lambda message, progress_percent=None: progress_messages.append(message),
    )
    monkeypatch.setattr(
        ChartsExplorerScreen,
        "is_current",
        property(lambda _self: True),
    )

    class _FakeViolationsView:
        def __init__(self) -> None:
            self.loading_calls: list[bool] = []
            self.recommendations_loading_calls: list[bool] = []
            self.partial_updates = 0
            self.last_violations: list[ViolationResult] = []
            self.recommendation_updates = 0

        def set_table_loading(self, loading: bool) -> None:
            self.loading_calls.append(loading)

        def set_recommendations_loading(
            self,
            loading: bool,
            _message: str = "Loading recommendations...",
        ) -> None:
            self.recommendations_loading_calls.append(loading)

        def update_recommendations_data(
            self,
            _recommendations: list[dict[str, object]],
            _charts: list,
            *,
            partial: bool = False,
        ) -> None:
            _ = partial
            self.recommendation_updates += 1

        def update_partial_data(
            self,
            violations: list[ViolationResult],
            _charts: list,
            *,
            progress_message: str | None = None,
        ) -> None:
            self.partial_updates += 1
            self.last_violations = list(violations)
            assert progress_message is not None

    fake_view = _FakeViolationsView()
    monkeypatch.setattr(
        screen,
        "query_one",
        lambda _selector, *_args, **_kwargs: fake_view,
    )

    screen.on_charts_explorer_optimizer_partial_loaded(
        ChartsExplorerOptimizerPartialLoaded(
            violations=[_make_violation("chart-live")],
            recommendations=[{"id": "rec-1", "title": "partial"}],
            completed_charts=1,
            total_charts=5,
            optimizer_generation=9,
        )
    )

    assert fake_view.loading_calls
    assert fake_view.loading_calls[-1] is False
    assert fake_view.recommendations_loading_calls
    assert fake_view.recommendations_loading_calls[-1] is False
    assert fake_view.recommendation_updates == 1
    assert fake_view.partial_updates == 1
    assert len(fake_view.last_violations) == 1
    assert progress_messages


@pytest.mark.unit
def test_optimizer_partial_event_throttles_ui_rerenders_between_first_and_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mid-stream payloads should avoid frequent full table rerenders."""
    screen = ChartsExplorerScreen(testing=True, initial_tab=TAB_VIOLATIONS)
    screen._optimizer_generation = 7
    screen._active_tab = TAB_VIOLATIONS
    monkeypatch.setattr(
        screen,
        "_update_optimizer_loading_message",
        lambda _message, _progress_percent=None: None,
    )
    monkeypatch.setattr(
        ChartsExplorerScreen,
        "is_current",
        property(lambda _self: True),
    )

    class _FakeViolationsView:
        def __init__(self) -> None:
            self.partial_updates = 0

        def set_table_loading(self, _loading: bool) -> None:
            return

        def set_recommendations_loading(
            self,
            _loading: bool,
            _message: str = "Loading recommendations...",
        ) -> None:
            return

        def update_recommendations_data(
            self,
            _recommendations: list[dict[str, object]],
            _charts: list,
            *,
            partial: bool = False,
        ) -> None:
            _ = partial
            return

        def update_partial_data(
            self,
            _violations: list[ViolationResult],
            _charts: list,
            *,
            progress_message: str | None = None,
        ) -> None:
            assert progress_message is not None
            self.partial_updates += 1

    fake_view = _FakeViolationsView()
    monkeypatch.setattr(
        screen,
        "query_one",
        lambda _selector, *_args, **_kwargs: fake_view,
    )
    monkeypatch.setattr(
        "kubeagle.screens.charts_explorer.charts_explorer_screen.time.monotonic",
        lambda: 100.0,
    )

    # First payload should always render immediately.
    screen.on_charts_explorer_optimizer_partial_loaded(
        ChartsExplorerOptimizerPartialLoaded(
            violations=[_make_violation("chart-a")],
            recommendations=[{"id": "rec-a"}],
            completed_charts=1,
            total_charts=5,
            optimizer_generation=7,
        )
    )
    # Mid-stream payload at same monotonic timestamp should be throttled.
    screen.on_charts_explorer_optimizer_partial_loaded(
        ChartsExplorerOptimizerPartialLoaded(
            violations=[_make_violation("chart-b")],
            recommendations=[{"id": "rec-b"}],
            completed_charts=2,
            total_charts=5,
            optimizer_generation=7,
        )
    )
    # Final payload should always render even within throttle window.
    screen.on_charts_explorer_optimizer_partial_loaded(
        ChartsExplorerOptimizerPartialLoaded(
            violations=[_make_violation("chart-c")],
            recommendations=[{"id": "rec-c"}],
            completed_charts=5,
            total_charts=5,
            optimizer_generation=7,
        )
    )

    assert fake_view.partial_updates == 2


@pytest.mark.unit
def test_show_loading_overlay_keeps_existing_charts_table_interactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refresh overlay should stay hidden when charts data is already visible."""
    screen = ChartsExplorerScreen(testing=True)
    screen.charts = [cast(ChartInfo, object())]

    class _FakeOverlay:
        def __init__(self) -> None:
            self.display = True
            self.classes: set[str] = {"visible"}

        def add_class(self, class_name: str) -> None:
            self.classes.add(class_name)

        def remove_class(self, class_name: str) -> None:
            self.classes.discard(class_name)

        def update(self, _message: str) -> None:
            return

    overlay = _FakeOverlay()
    monkeypatch.setattr(
        screen,
        "query_one",
        lambda _selector, *_args, **_kwargs: overlay,
    )

    screen.show_loading_overlay("Refreshing...")

    assert overlay.display is False
    assert "visible" not in overlay.classes


@pytest.mark.unit
def test_show_loading_overlay_can_force_visible_with_cached_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mode switches should be able to keep the table overlay visible."""
    screen = ChartsExplorerScreen(testing=True)
    screen.charts = [cast(ChartInfo, object())]

    class _FakeOverlay:
        def __init__(self) -> None:
            self.display = False
            self.classes: set[str] = set()

        def add_class(self, class_name: str) -> None:
            self.classes.add(class_name)

        def remove_class(self, class_name: str) -> None:
            self.classes.discard(class_name)

    class _FakeMessage:
        def __init__(self) -> None:
            self.value = ""
            self.classes: set[str] = set()

        def update(self, message: str) -> None:
            self.value = message

        def add_class(self, class_name: str) -> None:
            self.classes.add(class_name)

        def remove_class(self, class_name: str) -> None:
            self.classes.discard(class_name)

    overlay = _FakeOverlay()
    message = _FakeMessage()

    def _query_one(selector: str, *_args: object, **_kwargs: object) -> object:
        if selector == "#loading-overlay":
            return overlay
        if selector == "#loading-message":
            return message
        raise AssertionError(f"unexpected selector: {selector}")

    monkeypatch.setattr(screen, "query_one", _query_one)

    screen.show_loading_overlay(
        "Refreshing...",
        allow_cached_passthrough=False,
    )

    assert overlay.display is True
    assert "visible" in overlay.classes
    assert message.value == "Refreshing..."


@pytest.mark.unit
def test_partial_data_load_unblocks_overlay_after_first_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forced mode-switch overlay should clear once first partial payload arrives."""
    screen = ChartsExplorerScreen(testing=True)
    screen._mode_generation = 7
    screen._loading = True
    screen._active_tab = TAB_CHARTS
    screen._force_overlay_until_load_complete = True

    hide_calls: list[bool] = []
    repopulate_calls: list[bool] = []

    monkeypatch.setattr(
        ChartsExplorerScreen,
        "is_current",
        property(lambda _self: True),
    )
    monkeypatch.setattr(
        screen,
        "_sync_loaded_charts_state",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(screen, "_set_charts_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(screen, "hide_loading_overlay", lambda: hide_calls.append(True))
    monkeypatch.setattr(
        screen,
        "_schedule_charts_tab_repopulate",
        lambda *, force=False: repopulate_calls.append(force),
    )

    screen.on_charts_explorer_partial_data_loaded(
        ChartsExplorerPartialDataLoaded(
            charts=[cast(ChartInfo, object())],
            completed=1,
            total=4,
            mode_generation=7,
        )
    )

    assert screen._force_overlay_until_load_complete is False
    assert hide_calls == [True]
    assert repopulate_calls == [False]


@pytest.mark.unit
def test_start_optimizer_worker_keeps_cached_results_interactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optimizer refresh should not block table interactions when cached data exists."""
    screen = ChartsExplorerScreen(testing=True)
    screen._cached_violations = [_make_violation("cached-chart")]
    screen._cached_helm_recommendations = [{"id": "rec-1", "title": "cached"}]

    class _FakeViolationsView:
        def __init__(self) -> None:
            self.table_loading_calls: list[bool] = []
            self.recommendations_loading_calls: list[bool] = []

        def _hide_error_banner(self) -> None:
            return

        def set_table_loading(self, loading: bool) -> None:
            self.table_loading_calls.append(loading)

        def set_recommendations_loading(
            self,
            loading: bool,
            _message: str = "Loading recommendations...",
        ) -> None:
            self.recommendations_loading_calls.append(loading)

    fake_view = _FakeViolationsView()
    monkeypatch.setattr(screen, "_ensure_violations_view_initialized", lambda: None)
    monkeypatch.setattr(screen, "_cancel_workers_by_name", lambda *_names: None)
    monkeypatch.setattr(
        screen,
        "query_one",
        lambda _selector, *_args, **_kwargs: fake_view,
    )
    monkeypatch.setattr(
        screen,
        "run_worker",
        lambda _worker, *, name, exclusive: None,
    )

    screen._start_optimizer_worker()

    assert fake_view.table_loading_calls
    assert fake_view.table_loading_calls[-1] is False
    assert fake_view.recommendations_loading_calls
    assert fake_view.recommendations_loading_calls[-1] is False


@pytest.mark.unit
def test_finish_optimizer_worker_generation_ignores_stale_worker() -> None:
    """Cancelled/older optimizer workers must not clear active loading state."""
    screen = ChartsExplorerScreen(testing=True)
    screen._optimizer_generation = 5
    screen._optimizer_loading = True

    screen._finish_optimizer_worker_generation(4)

    assert screen._optimizer_loading is True


@pytest.mark.unit
def test_finish_optimizer_worker_generation_clears_current_worker() -> None:
    """Active optimizer worker completion should clear loading state."""
    screen = ChartsExplorerScreen(testing=True)
    screen._optimizer_generation = 7
    screen._optimizer_loading = True

    screen._finish_optimizer_worker_generation(7)

    assert screen._optimizer_loading is False


@pytest.mark.unit
def test_ensure_optimizer_data_loaded_waits_for_committed_charts_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optimizer load should wait until charts payload is committed."""
    screen = ChartsExplorerScreen(testing=False)
    screen._loading = False
    screen._optimizer_loading = False
    screen._optimizer_loaded = False
    screen._charts_payload_ready_for_optimizer = False
    screen._reload_optimizer_on_resume = False

    called: dict[str, bool] = {"started": False}
    monkeypatch.setattr(screen, "_apply_optimizer_team_filter", lambda: None)
    monkeypatch.setattr(
        screen,
        "_start_optimizer_worker",
        lambda **_kwargs: called.__setitem__("started", True),
    )

    screen._ensure_optimizer_data_loaded()

    assert called["started"] is False
    assert screen._reload_optimizer_on_resume is True


@pytest.mark.unit
def test_ensure_optimizer_data_loaded_starts_after_committed_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optimizer load should start immediately once charts payload is ready."""
    screen = ChartsExplorerScreen(testing=False)
    screen._loading = False
    screen._optimizer_loading = False
    screen._optimizer_loaded = False
    screen._charts_payload_ready_for_optimizer = True
    screen._reload_optimizer_on_resume = False

    called: dict[str, bool] = {"started": False}
    monkeypatch.setattr(screen, "_apply_optimizer_team_filter", lambda: None)
    monkeypatch.setattr(
        screen,
        "_start_optimizer_worker",
        lambda **_kwargs: called.__setitem__("started", True),
    )

    screen._ensure_optimizer_data_loaded()

    assert called["started"] is True
    assert screen._reload_optimizer_on_resume is False


@pytest.mark.unit
def test_on_optimizer_data_loaded_ignores_stale_generation() -> None:
    """Stale optimizer payloads must not overwrite newer generation state."""
    screen = ChartsExplorerScreen(testing=True)
    screen._optimizer_generation = 5
    screen._optimizer_loaded = False
    screen._streaming_optimizer_violations = []

    event = OptimizerDataLoaded(
        violations=[_make_violation("stale")],
        recommendations=[],
        charts=[],
        total_charts=0,
        duration_ms=0.0,
        optimizer_generation=4,
    )
    screen.on_optimizer_data_loaded(event)

    assert screen._optimizer_loaded is False
    assert screen._streaming_optimizer_violations == []


@pytest.mark.unit
def test_on_optimizer_data_load_failed_ignores_stale_generation() -> None:
    """Stale optimizer error events should not clear active stream payloads."""
    screen = ChartsExplorerScreen(testing=True)
    screen._optimizer_generation = 6
    screen._optimizer_loaded = True
    screen._streaming_optimizer_violations = [_make_violation("active")]

    event = OptimizerDataLoadFailed(
        "stale-failure",
        optimizer_generation=5,
    )
    screen.on_optimizer_data_load_failed(event)

    assert screen._optimizer_loaded is True
    assert len(screen._streaming_optimizer_violations) == 1


@pytest.mark.unit
def test_set_active_tab_charts_resets_optimizer_view_filter() -> None:
    """Returning to charts content should not keep Optimizer tab highlighted."""
    screen = ChartsExplorerScreen(testing=True)
    screen.current_view = ViewFilter.WITH_VIOLATIONS
    screen._active_tab = TAB_VIOLATIONS

    screen._set_active_tab(TAB_CHARTS)

    assert screen._active_tab == TAB_CHARTS
    assert screen.current_view == ViewFilter.ALL


@pytest.mark.unit
def test_data_loaded_on_violations_tab_triggers_optimizer_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh chart payload should immediately trigger optimizer load on violations tab."""
    screen = ChartsExplorerScreen(testing=False, initial_tab=TAB_VIOLATIONS)
    screen._active_tab = TAB_VIOLATIONS

    fake_app = SimpleNamespace(notify=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ChartsExplorerScreen, "app", property(lambda _self: fake_app))
    monkeypatch.setattr(ChartsExplorerScreen, "is_current", property(lambda _self: True))
    monkeypatch.setattr(
        screen,
        "_sync_loaded_charts_state",
        lambda charts, _active_charts: setattr(screen, "charts", list(charts)),
    )
    monkeypatch.setattr(screen, "_set_charts_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(screen, "hide_loading_overlay", lambda: None)

    called: dict[str, bool] = {"optimizer": False}
    monkeypatch.setattr(
        screen,
        "_ensure_optimizer_data_loaded",
        lambda: called.__setitem__("optimizer", True),
    )

    screen.on_charts_explorer_data_loaded(
        ChartsExplorerDataLoaded(
            charts=[cast(ChartInfo, object())],
            active_charts=None,
            mode_generation=screen._mode_generation,
        )
    )

    assert screen._charts_payload_ready_for_optimizer is True
    assert called["optimizer"] is True
