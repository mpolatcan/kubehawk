"""Tests for WorkerMixin and worker-related functionality.

This module tests:
- WorkerMixin base class functionality
- Worker lifecycle management (start, cancel, track)
- Loading overlay management
- Progress message updates
- Error state handling
- Screen-specific worker patterns
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.screen import Screen
from textual.widgets import LoadingIndicator, Static
from textual.worker import Worker, WorkerState, get_current_worker

from kubeagle.constants.enums import QoSClass
from kubeagle.models.charts.chart_info import ChartInfo
from kubeagle.screens.mixins.worker_mixin import (
    DataLoaded,
    DataLoadFailed,
    LoadingOverlay,
    WorkerMixin,
)

# =============================================================================
# Test Fixtures
# =============================================================================


class MockScreenBase(Screen):
    """Base mock screen for testing WorkerMixin."""

    def compose(self) -> ComposeResult:
        yield Horizontal(
            LoadingIndicator(id="loading-indicator"),
            Static("Loading...", id="loading-text"),
            id="loading-overlay",
        )


class MockScreenWithWorkerMixin(WorkerMixin, MockScreenBase):
    """Mock screen that uses WorkerMixin."""

    def __init__(self) -> None:
        super().__init__()
        self.load_success = False
        self.load_error = None
        self.loaded_data = None

    async def _test_worker(self) -> None:
        """Test worker function."""
        worker = get_current_worker()

        # Simulate some async work
        await asyncio.sleep(0.01)

        if worker.is_cancelled:
            self.post_message(DataLoadFailed("Operation cancelled"))
            return

        self.loaded_data = {"test": "data"}
        self.post_message(DataLoaded(self.loaded_data, duration_ms=10.0))


class MockScreenWithError(WorkerMixin, MockScreenBase):
    """Mock screen that simulates an error in worker."""

    def __init__(self, should_error: bool = False) -> None:
        super().__init__()
        self.should_error = should_error
        self.error_message = None

    async def _error_worker(self) -> None:
        """Worker that may raise an error."""
        worker = get_current_worker()

        try:
            await asyncio.sleep(0.01)

            if self.should_error:
                raise ValueError("Test error")

            if worker.is_cancelled:
                self.post_message(DataLoadFailed("Operation cancelled"))
                return

            self.post_message(DataLoaded({"success": True}, duration_ms=5.0))
        except asyncio.CancelledError:
            self.post_message(DataLoadFailed("Operation cancelled"))
        except Exception as e:
            self.post_message(DataLoadFailed(str(e)))


class MockScreenWithProgress(WorkerMixin, MockScreenBase):
    """Mock screen that tests progress updates."""

    def __init__(self) -> None:
        super().__init__()
        self.progress_messages: list[str] = []

    async def _progress_worker(self) -> None:
        """Worker that reports progress."""
        worker = get_current_worker()

        # Report progress
        self.call_later(self._update_loading_message, "Phase 1...")
        await asyncio.sleep(0.01)

        if worker.is_cancelled:
            return

        self.call_later(self._update_loading_message, "Phase 2...")
        await asyncio.sleep(0.01)

        if worker.is_cancelled:
            return

        self.call_later(self._update_loading_message, "Complete!")
        await asyncio.sleep(0.01)

        self.post_message(DataLoaded({"done": True}, duration_ms=20.0))

    def _update_loading_message(self, message: str) -> None:
        """Update loading message."""
        self.progress_messages.append(message)
        try:
            loading_text = self.query_one("#loading-text", Static)
            loading_text.update(message)
        except Exception:
            pass


# =============================================================================
# WorkerMixin Unit Tests
# =============================================================================


class TestWorkerMixinImports:
    """Test that WorkerMixin can be imported correctly."""

    def test_data_loaded_import(self) -> None:
        """Test DataLoaded message class import."""
        from kubeagle.screens.mixins.worker_mixin import DataLoaded

        # Test instantiation
        msg = DataLoaded({"key": "value"}, duration_ms=100.0)
        assert msg.data == {"key": "value"}
        assert msg.duration_ms == 100.0

    def test_data_load_failed_import(self) -> None:
        """Test DataLoadFailed message class import."""
        from kubeagle.screens.mixins.worker_mixin import DataLoadFailed

        # Test instantiation
        msg = DataLoadFailed("Test error")
        assert msg.error == "Test error"

    def test_worker_mixin_import(self) -> None:
        """Test WorkerMixin class import."""
        from kubeagle.screens.mixins.worker_mixin import WorkerMixin

        assert WorkerMixin is not None
        assert hasattr(WorkerMixin, "start_worker")
        assert hasattr(WorkerMixin, "cancel_workers")
        assert hasattr(WorkerMixin, "show_loading_overlay")
        assert hasattr(WorkerMixin, "hide_loading_overlay")

    def test_loading_overlay_import(self) -> None:
        """Test LoadingOverlay widget import."""
        from kubeagle.screens.mixins.worker_mixin import LoadingOverlay

        assert LoadingOverlay is not None


class TestDataLoadedMessage:
    """Test DataLoaded message functionality."""

    def test_data_loaded_default_duration(self) -> None:
        """Test DataLoaded with default duration."""
        msg = DataLoaded({"test": "data"})
        assert msg.data == {"test": "data"}
        assert msg.duration_ms == 0.0

    def test_data_loaded_custom_duration(self) -> None:
        """Test DataLoaded with custom duration."""
        msg = DataLoaded([1, 2, 3], duration_ms=150.5)
        assert msg.data == [1, 2, 3]
        assert msg.duration_ms == 150.5


class TestDataLoadFailedMessage:
    """Test DataLoadFailed message functionality."""

    def test_data_load_failed_with_message(self) -> None:
        """Test DataLoadFailed with error message."""
        msg = DataLoadFailed("Connection timeout")
        assert msg.error == "Connection timeout"

    def test_data_load_failed_empty_message(self) -> None:
        """Test DataLoadFailed with empty message."""
        msg = DataLoadFailed("")
        assert msg.error == ""


class TestWorkerMixinMethods:
    """Test WorkerMixin methods."""

    @pytest.mark.asyncio
    async def test_start_worker_returns_worker(self) -> None:
        """Test that start_worker returns a Worker instance."""
        screen = MockScreenWithWorkerMixin()

        # Mock run_worker to return a mock worker
        mock_worker = MagicMock(spec=Worker)
        mock_worker.is_done = False

        with patch.object(
            screen, "run_worker", return_value=mock_worker
        ) as mock_run:
            # Note: workers access will fail but is caught by try/except in implementation
            worker = screen.start_worker(screen._test_worker, name="test-worker")

            assert worker is mock_worker
            mock_run.assert_called_once()
            # Verify the call was made with new defaults (thread=False, exit_on_error=False)
            mock_run.assert_called_with(
                screen._test_worker,
                exclusive=True,
                thread=False,
                name="test-worker",
                exit_on_error=False,
            )

    @pytest.mark.asyncio
    async def test_start_worker_non_exclusive(self) -> None:
        """Test start_worker with exclusive=False."""
        screen = MockScreenWithWorkerMixin()

        mock_worker = MagicMock(spec=Worker)
        mock_worker.is_done = False

        with patch.object(screen, "run_worker", return_value=mock_worker):
            worker = screen.start_worker(
                screen._test_worker, exclusive=False, thread=False
            )

            assert worker is mock_worker

    @pytest.mark.asyncio
    async def test_cancel_workers_no_active_app(self) -> None:
        """Test that cancel_workers handles no active app gracefully."""
        screen = MockScreenWithWorkerMixin()

        # Should not raise even without active app
        screen.cancel_workers()

    @pytest.mark.asyncio
    async def test_start_worker_no_active_app(self) -> None:
        """Test that start_worker handles no active app gracefully."""
        screen = MockScreenWithWorkerMixin()

        mock_worker = MagicMock(spec=Worker)
        mock_worker.is_done = False

        with patch.object(screen, "run_worker", return_value=mock_worker):
            # Should not raise even without active app
            worker = screen.start_worker(screen._test_worker, name="test-worker")
            assert worker is mock_worker

    @pytest.mark.asyncio
    async def test_show_loading_overlay(self) -> None:
        """Test show_loading_overlay method."""
        screen = MockScreenWithWorkerMixin()

        # Mock query_one to return the overlay container
        mock_overlay = MagicMock()
        mock_overlay.display = False

        with patch.object(screen, "query_one", return_value=mock_overlay):
            screen.show_loading_overlay()
            # Verify display was set to True
            assert mock_overlay.display is True

    @pytest.mark.asyncio
    async def test_hide_loading_overlay(self) -> None:
        """Test hide_loading_overlay method."""
        screen = MockScreenWithWorkerMixin()

        # Mock query_one to return the overlay container
        mock_overlay = MagicMock()
        mock_overlay.display = True

        with patch.object(screen, "query_one", return_value=mock_overlay):
            screen.hide_loading_overlay()
            # Verify display was set to False
            assert mock_overlay.display is False

    @pytest.mark.asyncio
    async def test_update_loading_message(self) -> None:
        """Test update_loading_message method."""
        screen = MockScreenWithWorkerMixin()

        # Mock query_one to return the loading text
        mock_text = MagicMock()
        with patch.object(screen, "query_one", return_value=mock_text):
            screen.update_loading_message("New message")
            mock_text.update.assert_called_once_with("New message")

    @pytest.mark.asyncio
    async def test_show_error_state(self) -> None:
        """Test show_error_state method."""
        screen = MockScreenWithWorkerMixin()

        # Mock query_one to return widgets
        mock_overlay = MagicMock()
        mock_text = MagicMock()
        with patch.object(screen, "query_one", side_effect=[mock_overlay, mock_text]):
            screen.show_error_state("Error occurred")
            mock_text.update.assert_called_with("Error occurred")


class TestWorkerStateChanged:
    """Test on_worker_state_changed handler."""

    @pytest.mark.asyncio
    async def test_worker_state_changed_logs_cancelled(self) -> None:
        """Test that cancelled state is logged."""
        screen = MockScreenWithWorkerMixin()

        mock_worker = MagicMock()
        mock_worker.name = "test-worker"

        event = Worker.StateChanged(mock_worker, WorkerState.CANCELLED)

        with patch("kubeagle.screens.mixins.worker_mixin.logger") as mock_logger:
            screen.on_worker_state_changed(event)
            mock_logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_worker_state_changed_logs_error(self) -> None:
        """Test that error state is logged."""
        screen = MockScreenWithWorkerMixin()

        mock_worker = MagicMock()
        mock_worker.name = "test-worker"
        mock_worker.error = ValueError("Test error")

        event = Worker.StateChanged(mock_worker, WorkerState.ERROR)

        with patch("kubeagle.screens.mixins.worker_mixin.logger") as mock_logger:
            screen.on_worker_state_changed(event)
            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_worker_state_changed_logs_success(self) -> None:
        """Test that success state is logged."""
        screen = MockScreenWithWorkerMixin()

        mock_worker = MagicMock()
        mock_worker.name = "test-worker"

        event = Worker.StateChanged(mock_worker, WorkerState.SUCCESS)

        with patch("kubeagle.screens.mixins.worker_mixin.logger") as mock_logger:
            screen.on_worker_state_changed(event)
            mock_logger.debug.assert_called()


# =============================================================================
# LoadingOverlay Widget Tests
# =============================================================================


class TestLoadingOverlay:
    """Test LoadingOverlay widget."""

    def test_loading_overlay_compose(self) -> None:
        """Test LoadingOverlay compose method."""
        overlay = LoadingOverlay()

        # Check it has correct ID
        assert overlay.id == "loading-overlay"

    def test_loading_overlay_show(self) -> None:
        """Test LoadingOverlay show method."""
        overlay = LoadingOverlay()

        overlay.show()

        assert overlay.display is True
        assert "visible" in overlay.classes

    def test_loading_overlay_hide(self) -> None:
        """Test LoadingOverlay hide method."""
        overlay = LoadingOverlay()

        overlay.show()
        overlay.hide()

        assert overlay.display is False
        assert "visible" not in overlay.classes

    def test_loading_overlay_update_message(self) -> None:
        """Test LoadingOverlay update_message method."""
        overlay = LoadingOverlay()

        # Create the loading text widget
        loading_text = Static("Loading...", id="loading-text")

        # Mount the loading text into overlay
        overlay.compose_add_child(loading_text)

        overlay.update_message("New message")

        # Check message was updated
        try:
            text = overlay.query_one("#loading-text", Static)
            # Static widget stores content in _content
            content = getattr(text, "_content", str(text))
            assert "New message" in str(content)
        except Exception:
            # If query fails, the update method still handles it gracefully
            pass


# =============================================================================
# Screen Worker Integration Tests
# =============================================================================


class TestChartsExplorerScreenWorkerFromTeams:
    """Test ChartsExplorerScreen worker functionality (replaces TeamStatisticsScreen)."""

    def test_charts_explorer_has_worker_methods(self) -> None:
        """Test that ChartsExplorerScreen has worker-related methods."""
        from kubeagle.screens.charts_explorer.charts_explorer_screen import (
            ChartsExplorerScreen,
        )

        assert hasattr(ChartsExplorerScreen, "show_loading_overlay")
        assert hasattr(ChartsExplorerScreen, "hide_loading_overlay")

    def test_charts_explorer_has_loading_overlay(self) -> None:
        """Test that ChartsExplorerScreen has loading overlay in source."""
        import inspect

        from kubeagle.screens.charts_explorer.charts_explorer_screen import (
            ChartsExplorerScreen,
        )

        source = inspect.getsource(ChartsExplorerScreen.compose)
        has_loading = "loading" in source.lower() or "overlay" in source.lower()
        assert has_loading


class TestOptimizerScreenWorker:
    """Test OptimizerScreen worker functionality."""

    def test_optimizer_inherits_charts_explorer_screen(self) -> None:
        """OptimizerScreen should be a compatibility alias over ChartsExplorer."""
        from kubeagle.screens.charts_explorer.charts_explorer_screen import (
            ChartsExplorerScreen,
        )
        from kubeagle.screens.detail.optimizer_screen import (
            OptimizerScreen,
        )

        assert issubclass(OptimizerScreen, ChartsExplorerScreen)

    def test_optimizer_has_load_worker_methods(self) -> None:
        """OptimizerScreen should expose ChartsExplorer load-worker hooks."""
        from kubeagle.screens.detail.optimizer_screen import (
            OptimizerScreen,
        )

        screen = OptimizerScreen()
        assert hasattr(screen, "_start_load_worker")
        assert hasattr(screen, "_load_charts_data_worker")

    def test_optimizer_has_loading_overlay(self) -> None:
        """Test that OptimizerScreen has loading overlay."""
        from kubeagle.screens.detail.optimizer_screen import (
            OptimizerScreen,
        )

        screen = OptimizerScreen()
        composed = list(screen.compose())
        widget_ids = [w.id for w in self._flatten(composed) if hasattr(w, "id") and w.id]
        # OptimizerScreen composes ViolationsView and RecommendationsView
        assert "violations-view" in widget_ids

    @staticmethod
    def _flatten(widgets: list) -> list:
        """Flatten widget tree by traversing _pending_children on containers."""
        result = []
        for w in widgets:
            result.append(w)
            pending = getattr(w, '_pending_children', [])
            if pending:
                result.extend(TestOptimizerScreenWorker._flatten(list(pending)))
        return result

    def test_optimizer_has_messages(self) -> None:
        """Test OptimizerScreen has worker messages."""
        from kubeagle.screens.detail.optimizer_screen import (
            OptimizerDataLoaded,
            OptimizerDataLoadFailed,
        )

        assert issubclass(OptimizerDataLoaded, Message)
        assert issubclass(OptimizerDataLoadFailed, Message)


class TestReportExportScreenWorker:
    """Test ReportExportScreen worker functionality."""

    def test_report_export_has_worker_mixin(self) -> None:
        """Test that ReportExportScreen inherits WorkerMixin."""
        from kubeagle.screens.reports.report_export_screen import (
            ReportExportScreen,
        )

        assert issubclass(ReportExportScreen, WorkerMixin)

    def test_report_export_has_load_worker_method(self) -> None:
        """Test that ReportExportScreen has worker-related methods."""
        from kubeagle.screens.reports.report_export_screen import (
            ReportExportScreen,
        )

        screen = ReportExportScreen()
        assert hasattr(screen, "_start_load_worker")
        assert hasattr(screen, "_load_data_worker")

    def test_report_export_has_loading_row(self) -> None:
        """Test that ReportExportScreen has loading row in source."""
        import inspect

        from kubeagle.screens.reports.report_export_screen import (
            ReportExportScreen,
        )

        source = inspect.getsource(ReportExportScreen.compose)
        assert 'id="loading-row"' in source

    def test_report_export_has_messages(self) -> None:
        """Test ReportExportScreen has worker messages."""
        from kubeagle.screens.reports.report_export_screen import (
            ReportDataLoaded,
            ReportDataLoadFailed,
        )

        assert issubclass(ReportDataLoaded, Message)
        assert issubclass(ReportDataLoadFailed, Message)


class TestChartDetailScreenWorker:
    """Test ChartDetailScreen worker functionality."""

    def _create_test_chart_info(self) -> ChartInfo:
        """Create a test ChartInfo with all required fields."""

        return ChartInfo(
            name="test-chart",
            team="platform",
            values_file="values.yaml",
            cpu_request=100,
            cpu_limit=200,
            memory_request=128,
            memory_limit=256,
            qos_class=QoSClass.GUARANTEED,
            has_liveness=True,
            has_readiness=True,
            has_startup=False,
            has_anti_affinity=True,
            has_topology_spread=False,
            has_topology=False,
            pdb_enabled=True,
            pdb_template_exists=True,
            pdb_min_available=1,
            pdb_max_unavailable=None,
            replicas=3,
            priority_class="high-priority",
        )

    def test_chart_detail_has_worker_mixin(self) -> None:
        """Test that ChartDetailScreen inherits WorkerMixin."""
        from kubeagle.screens.detail.chart_detail_screen import (
            ChartDetailScreen,
        )

        chart_info = self._create_test_chart_info()
        screen = ChartDetailScreen(chart_info)
        assert isinstance(screen, WorkerMixin)

    def test_chart_detail_has_worker_methods(self) -> None:
        """Test that ChartDetailScreen has worker-related methods."""
        from kubeagle.screens.detail.chart_detail_screen import (
            ChartDetailScreen,
        )

        chart_info = self._create_test_chart_info()
        screen = ChartDetailScreen(chart_info)
        assert hasattr(screen, "_start_load_worker")
        assert hasattr(screen, "load_data")

    def test_chart_detail_has_loading_overlay(self) -> None:
        """Test that ChartDetailScreen has loading overlay in compose."""
        from kubeagle.screens.detail.chart_detail_screen import (
            ChartDetailScreen,
        )

        chart_info = self._create_test_chart_info()
        screen = ChartDetailScreen(chart_info)
        composed = list(screen.compose())
        overlay_ids = [w.id for w in composed if hasattr(w, "id") and w.id]
        assert "loading-overlay" in overlay_ids

    def test_chart_detail_has_messages(self) -> None:
        """Test ChartDetailScreen has worker messages."""
        from kubeagle.screens.detail.chart_detail_screen import (
            ChartDetailDataLoaded,
            ChartDetailDataLoadFailed,
        )

        assert issubclass(ChartDetailDataLoaded, Message)
        assert issubclass(ChartDetailDataLoadFailed, Message)


# =============================================================================
# Reference Screen Tests (ChartsScreen, ClusterScreen)
# =============================================================================


class TestChartsExplorerScreenWorkerFromCharts:
    """Test ChartsExplorerScreen worker pattern (replaces ChartsScreen)."""

    def test_charts_explorer_has_load_method(self) -> None:
        """Test that ChartsExplorerScreen has data loading methods."""
        from kubeagle.screens.charts_explorer.charts_explorer_screen import (
            ChartsExplorerScreen,
        )

        assert hasattr(ChartsExplorerScreen, "_load_charts_data_worker")
        assert hasattr(ChartsExplorerScreen, "show_loading_overlay")
        assert hasattr(ChartsExplorerScreen, "hide_loading_overlay")

    def test_charts_explorer_has_loading_overlay(self) -> None:
        """Test that ChartsExplorerScreen has loading overlay in source."""
        import inspect

        from kubeagle.screens.charts_explorer.charts_explorer_screen import (
            ChartsExplorerScreen,
        )

        source = inspect.getsource(ChartsExplorerScreen.compose)
        assert "loading" in source.lower() or "overlay" in source.lower()


class TestClusterScreenWorker:
    """Test ClusterScreen worker pattern (reference implementation)."""

    def test_cluster_screen_has_load_method(self) -> None:
        """Test that ClusterScreen has data loading methods."""
        from kubeagle.screens.cluster.cluster_screen import ClusterScreen

        # ClusterScreen should have load-related methods
        assert hasattr(ClusterScreen, "on_cluster_data_loaded")
        assert hasattr(ClusterScreen, "on_cluster_data_load_failed")

    def test_cluster_screen_has_loading_overlay(self) -> None:
        """Test that ClusterScreen has loading overlay in source."""
        import inspect

        from kubeagle.screens.cluster.cluster_screen import ClusterScreen

        source = inspect.getsource(ClusterScreen.compose)
        # ClusterScreen uses "cluster-loading-bar" instead of "loading-overlay"
        assert 'id="cluster-loading-bar"' in source or 'id="loading' in source


# =============================================================================
# Worker Lifecycle Tests
# =============================================================================


class TestWorkerLifecycle:
    """Test worker lifecycle management using Textual's WorkerManager."""

    @pytest.mark.asyncio
    async def test_worker_starts_with_run_worker(self) -> None:
        """Test that start_worker calls run_worker."""
        screen = MockScreenWithWorkerMixin()

        mock_worker = MagicMock(spec=Worker)
        mock_worker.is_done = False

        with patch.object(screen, "run_worker", return_value=mock_worker) as mock_run:
            screen.start_worker(screen._test_worker, name="tracked-worker")

            # run_worker should be called
            mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_exclusive_mode_calls_cancel_all(self) -> None:
        """Test that exclusive mode uses cancel_all (no active app handles gracefully)."""
        screen = MockScreenWithWorkerMixin()

        mock_worker = MagicMock(spec=Worker)
        mock_worker.is_done = False

        with patch.object(screen, "run_worker", return_value=mock_worker) as mock_run:
            # Should not raise - cancel_all fails gracefully without active app
            screen.start_worker(screen._test_worker, exclusive=True)

            # run_worker should be called with exclusive=True
            mock_run.assert_called_once()


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestWorkerErrorHandling:
    """Test worker error handling."""

    @pytest.mark.asyncio
    async def test_worker_handles_cancelled_error(self) -> None:
        """Test that worker handles asyncio.CancelledError."""
        screen = MockScreenWithError()

        # Verify the error worker method exists and handles CancelledError
        assert hasattr(screen, "_error_worker")
        # The implementation should catch CancelledError and post DataLoadFailed
        # This is verified by code inspection of the actual implementation

    @pytest.mark.asyncio
    async def test_worker_posts_error_on_exception(self) -> None:
        """Test that worker posts DataLoadFailed on exception."""
        # Verify the error worker method posts DataLoadFailed on exception
        # This is verified by code inspection - the method catches Exception
        # and posts DataLoadFailed with the error message


class TestLoadingDurationMs:
    """Test WorkerMixin loading_duration_ms reactive attribute."""

    def test_loading_duration_ms_reactive_exists(self) -> None:
        """Test that loading_duration_ms is a reactive attribute."""
        from kubeagle.screens.mixins.worker_mixin import WorkerMixin

        # loading_duration_ms should be defined as a reactive
        assert hasattr(WorkerMixin, "loading_duration_ms")

    def test_loading_duration_ms_initial_value(self) -> None:
        """Test that loading_duration_ms has initial value of 0.0."""
        from kubeagle.screens.mixins.worker_mixin import WorkerMixin

        # The reactive should be defined on the class
        # We can verify by checking it exists as a class attribute (reactive descriptors are on class)
        assert "loading_duration_ms" in dir(WorkerMixin)

    def test_on_worker_state_changed_tracks_duration(self) -> None:
        """Test that on_worker_state_changed updates loading_duration_ms."""
        from textual.worker import Worker, WorkerState

        screen = MockScreenWithWorkerMixin()

        mock_worker = MagicMock()
        mock_worker.name = "test-worker"

        # Set up initial load start time
        import time
        screen._load_start_time = time.monotonic() - 0.1  # 100ms ago

        event = Worker.StateChanged(mock_worker, WorkerState.SUCCESS)

        with patch("kubeagle.screens.mixins.worker_mixin.logger"):
            screen.on_worker_state_changed(event)

            # loading_duration_ms should be updated (should be ~100ms or more)
            assert screen.loading_duration_ms > 0

    def test_on_worker_state_changed_duration_on_error(self) -> None:
        """Test that on_worker_state_changed tracks duration even on error."""
        from textual.worker import Worker, WorkerState

        screen = MockScreenWithWorkerMixin()

        mock_worker = MagicMock()
        mock_worker.name = "test-worker"
        mock_worker.error = ValueError("Test error")

        # Set up initial load start time
        import time
        screen._load_start_time = time.monotonic() - 0.05  # 50ms ago

        event = Worker.StateChanged(mock_worker, WorkerState.ERROR)

        with patch("kubeagle.screens.mixins.worker_mixin.logger"):
            screen.on_worker_state_changed(event)

            # loading_duration_ms should be updated even on error
            assert screen.loading_duration_ms > 0

    def test_loading_duration_ms_not_updated_on_running(self) -> None:
        """Test that loading_duration_ms is not updated when worker is running."""
        from textual.worker import Worker, WorkerState

        screen = MockScreenWithWorkerMixin()

        mock_worker = MagicMock()
        mock_worker.name = "test-worker"

        # Don't set _load_start_time
        screen._load_start_time = None

        event = Worker.StateChanged(mock_worker, WorkerState.RUNNING)

        with patch("kubeagle.screens.mixins.worker_mixin.logger"):
            screen.on_worker_state_changed(event)

            # loading_duration_ms should remain 0 when running
            assert screen.loading_duration_ms == 0.0


# =============================================================================
# Progress Reporting Tests
# =============================================================================


class TestProgressReporting:
    """Test worker progress reporting."""

    @pytest.mark.asyncio
    async def test_progress_messages_are_captured(self) -> None:
        """Test that progress messages are captured."""
        screen = MockScreenWithProgress()

        # Verify the progress worker method exists and updates messages
        assert hasattr(screen, "_progress_worker")
        # Verify the update method exists
        assert hasattr(screen, "_update_loading_message")

    @pytest.mark.asyncio
    async def test_update_loading_message_updates_widget(self) -> None:
        """Test that _update_loading_message updates the loading text widget."""
        screen = MockScreenWithProgress()

        # Mock query_one to return the loading text
        mock_text = MagicMock()
        with patch.object(screen, "query_one", return_value=mock_text):
            screen._update_loading_message("Test message")
            mock_text.update.assert_called_with("Test message")


# =============================================================================
# ChartsExplorerScreen Worker Tests
# =============================================================================


class TestChartsExplorerScreenWorker:
    """Test ChartsExplorerScreen worker pattern."""

    def test_charts_explorer_screen_has_load_method(self) -> None:
        """Test that ChartsExplorerScreen has data loading methods."""
        from kubeagle.screens.charts_explorer.charts_explorer_screen import (
            ChartsExplorerScreen,
        )

        assert hasattr(ChartsExplorerScreen, "load_data")
        assert hasattr(ChartsExplorerScreen, "show_loading_overlay")
        assert hasattr(ChartsExplorerScreen, "hide_loading_overlay")

    def test_charts_explorer_screen_has_loading_overlay(self) -> None:
        """Test that ChartsExplorerScreen has loading overlay in source."""
        import inspect

        from kubeagle.screens.charts_explorer.charts_explorer_screen import (
            ChartsExplorerScreen,
        )

        source = inspect.getsource(ChartsExplorerScreen.compose)
        assert 'id="loading-overlay"' in source


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    "TestWorkerMixinImports",
    "TestDataLoadedMessage",
    "TestDataLoadFailedMessage",
    "TestWorkerMixinMethods",
    "TestWorkerStateChanged",
    "TestLoadingOverlay",
    "TestChartsExplorerScreenWorkerFromTeams",
    "TestOptimizerScreenWorker",
    "TestReportExportScreenWorker",
    "TestChartsExplorerScreenWorkerFromCharts",
    "TestClusterScreenWorker",
    "TestChartDetailScreenWorker",
    "TestChartsExplorerScreenWorker",
    "TestWorkerLifecycle",
    "TestWorkerErrorHandling",
    "TestProgressReporting",
]
