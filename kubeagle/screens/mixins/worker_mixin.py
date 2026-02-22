"""WorkerMixin - Standardized Worker lifecycle management for async data loading.

This module provides a mixin class that implements consistent patterns for:
- Background worker management using Textual Workers
- Loading state management with overlays
- Progress reporting during data loading
- Error handling with retry support
- Loading duration tracking
- Reactive state management (is_loading, data, error)

Standard Reactive Pattern:
- Workers set is_loading, data, error reactive attributes
- on_worker_state_changed updates reactives
- watch_* methods handle UI updates based on reactive changes
- loading_duration_ms tracks load time

IMPORTANT: WorkerMixin now uses Textual's built-in `self.workers` (WorkerManager)
for worker lifecycle management. The old `_workers` list is no longer used.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from textual._context import NoActiveAppError
from textual.containers import Container
from textual.css.query import NoMatches, WrongType
from textual.message import Message
from textual.reactive import reactive
from textual.worker import Worker, WorkerState

from kubeagle.widgets import CustomStatic

logger = logging.getLogger(__name__)


# ============================================================================
# Base Message Classes for Worker Communication
# ============================================================================


class DataLoaded(Message):
    """Base message indicating successful data load.

    Attributes:
        data: The loaded data payload
        duration_ms: Time taken to load data in milliseconds
    """

    def __init__(self, data: Any, duration_ms: float = 0.0) -> None:
        super().__init__()
        self.data = data
        self.duration_ms = duration_ms


class DataLoadFailed(Message):
    """Base message indicating failed data load.

    Attributes:
        error: Error message describing the failure
    """

    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


# ============================================================================
# WorkerMixin Base Class
# ============================================================================


class WorkerMixin:
    """Mixin providing standardized Worker lifecycle management.

    This mixin should be inherited by screens that perform async data loading.
    It provides:

    - `start_worker()`: Standardized worker creation with automatic cleanup
    - `cancel_workers()`: Cancel all running workers (uses `self.workers`)
    - `on_worker_state_changed()`: Default handler for worker state changes
    - Loading state helper methods: `show_loading_overlay()`, `hide_loading_overlay()`
    - Progress reporting via `update_loading_message()`
    - Error state handling with `show_error_state()`
    - Reactive state: is_loading, data, error

    Usage:
        ```python
        class MyScreen(WorkerMixin, Screen):
            # Reactive state (automatically managed)
            is_loading = reactive(False)
            data = reactive[list[dict]]([])
            error = reactive[str | None](None)

            def on_mount(self) -> None:
                self.start_worker(self._load_data_worker, name="my-worker")

            async def _load_data_worker(self) -> None:
                self.is_loading = True
                self.error = None
                try:
                    self.update_loading_message("Loading...")
                    data = await fetch_data()
                    self.data = data
                except Exception as e:
                    self.error = str(e)
                finally:
                    self.is_loading = False
        ```

    Note:
        This mixin uses Textual's `self.workers` (WorkerManager) for all worker
        lifecycle management. No manual worker tracking is required.
    """

    # Standard reactive attributes for state management
    is_loading = reactive(False)
    data = reactive[list[dict]]([])
    error = reactive[str | None](None)
    loading_duration_ms = reactive(0.0, init=False)  # Track loading duration

    def __init__(self) -> None:
        # Call super().__init__() to ensure proper initialization of parent classes
        # This is critical for Screen subclasses to ensure _running is set
        super().__init__()
        # Track load timing
        self._load_start_time: float | None = None
        self._active_worker_name: str | None = None

    def watch_is_loading(self, loading: bool) -> None:
        """Watch for loading state changes.

        Args:
            loading: The new loading state.
        """
        if loading:
            self.show_loading_overlay()
        else:
            self.hide_loading_overlay()

    def watch_data(self, data: list[dict]) -> None:
        """Watch for data changes.

        Args:
            data: The new data value.
        """
        pass

    def watch_error(self, error: str | None) -> None:
        """Watch for error state changes.

        Args:
            error: The error message or None if cleared.
        """
        if error:
            self.show_error_state(error)

    def start_worker(
        self,
        worker_func: Callable[..., Awaitable[Any]],
        *,
        exclusive: bool = True,
        thread: bool = False,
        name: str | None = None,
        exit_on_error: bool = False,
    ) -> Worker[Any]:
        """Start a worker for background data loading.

        This method handles:
        - Canceling existing workers if `exclusive=True` (uses `self.workers.cancel_all()`)
        - Proper thread/async execution mode (thread=False by default for async I/O)
        - Error handling via exit_on_error=False (doesn't crash app on errors)
        - Loading duration tracking (records start time for duration measurement)

        Args:
            worker_func: Async function to run in worker
            exclusive: If True, cancel previous workers before starting new one
            thread: If False, run in async event loop (preferred for I/O operations).
                   Use True only for CPU-bound blocking operations.
            name: Optional worker name for debugging
            exit_on_error: If False, errors don't crash the app (default False).
                          Set to True if you want the worker to complete with ERROR state.

        Returns:
            The Worker instance
        """
        # Cancel existing workers if exclusive mode (using built-in self.workers)
        # Note: self.workers is provided by Textual's Screen/DOMNode classes
        if exclusive:
            with suppress(NoActiveAppError):
                self.workers.cancel_all()  # type: ignore[attr-defined]

        # Record load start time for duration tracking
        self._load_start_time = time.monotonic()
        self._active_worker_name = name

        # Create and start worker (must be called on a Screen instance)
        return self.run_worker(  # type: ignore[attr-defined]
            worker_func,
            exclusive=exclusive,
            thread=thread,
            name=name,
            exit_on_error=exit_on_error,
        )

    def cancel_workers(self) -> None:
        """Cancel all running workers using Textual's built-in WorkerManager.

        This method uses `self.workers.cancel_all()` which is the official
        Textual pattern for canceling all workers. No manual tracking needed.

        Note:
            If WorkerManager is not available (edge case), this method
            silently returns without error.
        """
        with suppress(NoActiveAppError):
            self.workers.cancel_all()  # type: ignore[attr-defined]

    def on_unmount(self) -> None:
        """Cancel all workers when the screen is unmounted.

        This prevents leaked workers from continuing to run invisibly
        after screen navigation (pop_screen, switch_screen).
        """
        self.cancel_workers()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes.

        This default handler:
        - Logs state changes for debugging
        - Updates is_loading reactive on completion or error
        - Logs errors with full traceback
        - Tracks loading duration on success

        Override this method to add custom state handling.

        Args:
            event: The worker state change event
        """
        # Calculate duration
        duration_ms = 0.0
        if self._load_start_time is not None and event.state in (
            WorkerState.SUCCESS,
            WorkerState.CANCELLED,
            WorkerState.ERROR,
        ):
            duration_ms = (time.monotonic() - self._load_start_time) * 1000
            self.loading_duration_ms = duration_ms  # type: ignore[attr-defined]
            self._load_start_time = None

        if event.state == WorkerState.CANCELLED:
            logger.debug(f"Worker '{event.worker.name}' was cancelled ({duration_ms:.2f}ms)")
            self.is_loading = False  # type: ignore[attr-defined]
        elif event.state == WorkerState.ERROR:
            logger.error(f"Worker '{event.worker.name}' error: {event.worker.error} ({duration_ms:.2f}ms)")
            self.is_loading = False  # type: ignore[attr-defined]
            self.error = str(event.worker.error)  # type: ignore[attr-defined]
        elif event.state == WorkerState.SUCCESS:
            logger.debug(f"Worker '{event.worker.name}' completed successfully ({duration_ms:.2f}ms)")
            self.is_loading = False  # type: ignore[attr-defined]

    # =========================================================================
    # Loading State Management - Default implementations
    # =========================================================================

    def show_loading_overlay(
        self, message: str = "Loading...", *, is_error: bool = False
    ) -> None:
        """Show loading overlay with loading indicator.

        Args:
            message: The message to display.
            is_error: Whether this is an error state (not used in default impl).

        Override this method in subclasses to provide screen-specific loading UI.
        The default implementation expects a `#loading-overlay` container in compose().
        """
        with suppress(NoMatches, WrongType):
            overlay = self.query_one(  # type: ignore[attr-defined]
                "#loading-overlay", Container
            )
            overlay.display = True
            # Update loading text if available
            with suppress(NoMatches, WrongType):
                loading_text = self.query_one(  # type: ignore[attr-defined]
                    "#loading-text", CustomStatic
                )
                loading_text.update(message)
                if is_error:
                    loading_text.add_class("error-text")

    def hide_loading_overlay(self) -> None:
        """Hide loading overlay.

        Override this method in subclasses to provide screen-specific behavior.
        """
        with suppress(NoMatches, WrongType):
            overlay = self.query_one(  # type: ignore[attr-defined]
                "#loading-overlay", Container
            )
            overlay.display = False

    def update_loading_message(self, message: str) -> None:
        """Update the loading message.

        This method is designed to be called from worker threads via `call_later()`.
        Override this method in subclasses to provide screen-specific progress updates.

        Args:
            message: The progress message to display
        """
        with suppress(NoMatches, WrongType):
            loading_text = self.query_one(  # type: ignore[attr-defined]
                "#loading-text", CustomStatic
            )
            loading_text.update(message)

    def show_error_state(self, message: str, retry: bool = True) -> None:
        """Show error state with optional retry button.

        Override this method in subclasses to provide screen-specific error handling.

        Args:
            message: Error message to display
            retry: If True, show a retry button (default True)
        """
        _ = retry
        with suppress(NoMatches, WrongType):
            self.query_one(  # type: ignore[attr-defined]
                "#loading-overlay", Container
            )
            loading_text = self.query_one(  # type: ignore[attr-defined]
                "#loading-text", CustomStatic
            )
            loading_text.update(message)
            loading_text.add_class("error-text")



# ============================================================================
# Composable Loading Overlay Widget
# ============================================================================


class LoadingOverlay(Container):
    """Standard loading overlay component.

    This widget provides a centered loading indicator with optional message.
    Use `compose_loading_overlay()` to include it in screens.
    """

    def __init__(self) -> None:
        super().__init__(id="loading-overlay")

    def show(self) -> None:
        """Show the loading overlay."""
        self.display = True
        self.add_class("visible")

    def hide(self) -> None:
        """Hide the loading overlay."""
        self.display = False
        self.remove_class("visible")

    def update_message(self, message: str) -> None:
        """Update the loading message.

        Args:
            message: The message to display
        """
        with suppress(NoMatches, WrongType):
            text = self.query_one("#loading-text", CustomStatic)
            text.update(message)

    def show_error(self, message: str) -> None:
        """Show an error message.

        Args:
            message: The error message to display
        """
        with suppress(NoMatches, WrongType):
            text = self.query_one("#loading-text", CustomStatic)
            text.update(message)
            text.add_class("error-text")


__all__ = [
    "DataLoadFailed",
    "DataLoaded",
    "LoadingOverlay",
    "WorkerMixin",
]
