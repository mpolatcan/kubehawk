"""Base screen class for KubEagle TUI.

This module provides BaseScreen, an abstract base class that encapsulates
common patterns across all screens in the application to reduce code duplication.

MIGRATION GUIDE FOR SCREENS:
============================

1. LOADING STATE MANAGEMENT:
   - Use show_loading_overlay(message) to show loading state
   - Use hide_loading_overlay() to hide loading state
   - Use show_error_state(message) for error display
   - Include #loading-overlay, #loading-message in your compose()

2. DATATABLE HELPERS:
   - Use populate_data_table(table_id, columns, data) for standard tables
   - Use show_empty_state(table_id, columns, message) for empty data
   - Use clear_table(table_id) to reset a table

3. SEARCH/FILTER PATTERN:
   - Include #filter-bar with #filter-stats and #search-indicator in compose()
   - Call init_search_filter() in on_mount()
   - Use apply_search_filter(query, data, columns) to filter data
   - Call update_filter_stats(message) to update filter display

4. CSS CLASSES AVAILABLE:
   - .loading, .error, .success, .warning
   - .has-filter, .empty-state, .empty-state-title
   - .stat-blocking, .stat-critical, .stat-high, .stat-medium, .stat-safe, .stat-total
   - .risk-critical, .risk-high, .risk-medium, .risk-safe

5. NAVIGATION BINDINGS (included by default):
   - ESC: Back
   - R: Refresh
   - H: Home, C: Charts, O: Optimizer, E: Export, Ctrl+S: Settings, ?: Help

6. NAVIGATION HELPERS (from navigation module):
   - navigate_to_home(app)
   - navigate_to_cluster(app)
   - navigate_to_charts(app)
   - navigate_to_optimizer(app)
   - navigate_to_export(app)
   - navigate_to_settings(app)
   - navigate_to_recommendations(app)
   - navigate_to_chart_detail(app, chart)
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any, cast

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Container
from textual.css.query import NoMatches, WrongType
from textual.screen import Screen

from kubeagle.keyboard import BASE_SCREEN_BINDINGS
from kubeagle.keyboard.navigation import (
    ScreenNavigator,
    navigate_to_charts,
    navigate_to_cluster,
    navigate_to_export,
    navigate_to_home,
    navigate_to_optimizer,
    navigate_to_recommendations,
    navigate_to_settings,
)
from kubeagle.widgets import (
    CustomDataTable,
    CustomFooter,
    CustomHeader,
    CustomStatic,
)

# Note: Clock functionality is handled by Textual's built-in Header widget
# Auto-clock is enabled by default in Textual's Header

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kubeagle.app import EKSHelmReporterApp


class BaseScreen(Screen, ScreenNavigator):
    """Abstract base class for TUI screens with common patterns.

    This class provides:
    - Standard title setting for the app window
    - Common on_mount lifecycle pattern
    - Loading state management helpers
    - DataTable population helpers
    - Search/filter pattern helpers
    - Common CSS classes for loading, error, and status states
    - Refresh action pattern
    - Navigation actions (inherits from ScreenNavigator)

    Subclasses must implement:
    - screen_title: The title to display in the window
    - load_data: Async method to load screen data

    Example:
        class MyScreen(BaseScreen):
            BINDINGS = BASE_SCREEN_BINDINGS

            @property
            def screen_title(self) -> str:
                return "My Screen Title"

            async def load_data(self) -> None:
                # Load data and update UI
                ...
    """

    # Keybindings from navigation module (keyboard.py for backward compat)
    BINDINGS = BASE_SCREEN_BINDINGS

    def __init__(self) -> None:
        """Initialize the base screen."""
        # Initialize ScreenNavigator without app (will use self.app when needed)
        ScreenNavigator.__init__(self, None)
        Screen.__init__(self)
        self.search_query: str = ""
        self._filter_stats: CustomStatic | None = None
        self._search_indicator: CustomStatic | None = None

    @property
    def screen_title(self) -> str:
        """Title displayed in the application window.

        Returns:
            The screen title string.
        """
        return "KubEagle"

    @property
    def app(self) -> EKSHelmReporterApp:
        """Get the application instance."""
        return cast("EKSHelmReporterApp", super().app)

    def compose(self) -> ComposeResult:
        """Compose the screen with common widgets.

        Yields:
            Widgets for the screen.
        """
        yield CustomHeader()
        yield Container(id="base-content")
        yield CustomFooter()

    def set_title(self, title: str) -> None:
        """Set the application window title.

        Args:
            title: The title to display.
        """
        self.app.title = f"KubEagle - {title}"

    def on_mount(self) -> None:
        """Called when the screen is mounted.

        Sets the window title and schedules data loading.
        """
        self.set_title(self.screen_title)
        self.call_later(self.load_data)

    def on_unmount(self) -> None:
        """Cancel any running workers and clear stale state when the screen is unmounted."""
        with suppress(Exception):
            self.workers.cancel_all()
        self._filter_stats = None
        self._search_indicator = None

    @abstractmethod
    async def load_data(self) -> None:
        """Load data for the screen.

        This method is called after the screen is mounted.
        Subclasses should implement this to fetch/load their data.
        """
        ...

    # =========================================================================
    # LOADING STATE MANAGEMENT
    # =========================================================================

    def show_loading_overlay(
        self, message: str = "Loading...", is_error: bool = False
    ) -> None:
        """Show the loading overlay with optional message.

        Args:
            message: The message to display.
            is_error: Whether this is an error state.
        """
        with suppress(NoMatches, WrongType):
            overlay = self.query_one("#loading-overlay")
            overlay.display = True
            msg_widget = self.query_one("#loading-message", CustomStatic)
            msg_widget.update(escape(message))
            if is_error:
                msg_widget.add_class("error")
                msg_widget.remove_class("loading")
            else:
                msg_widget.remove_class("error")
                msg_widget.add_class("loading")

    def hide_loading_overlay(self) -> None:
        """Hide the loading overlay."""
        with suppress(NoMatches, WrongType):
            overlay = self.query_one("#loading-overlay")
            overlay.display = False

    def show_error_state(self, message: str) -> None:
        """Show an error state in the loading overlay.

        Args:
            message: The error message to display.
        """
        self.show_loading_overlay(message, is_error=True)

    def update_loading_message(self, message: str) -> None:
        """Update the loading message without showing/hiding overlay.

        Args:
            message: The message to display.
        """
        with suppress(NoMatches, WrongType):
            msg_widget = self.query_one("#loading-message", CustomStatic)
            msg_widget.update(escape(message))

    # =========================================================================
    # DATATABLE HELPERS
    # =========================================================================

    _TABLE_BATCH_INSERT_THRESHOLD = 500

    def populate_data_table(
        self,
        table_id: str,
        columns: list[str],
        data: list[list],
        sort_column: int = -1,
    ) -> None:
        """Populate a DataTable with columns and data.

        For large datasets (>500 rows), rows are added in batches to
        avoid blocking the UI event loop for extended periods.

        Args:
            table_id: The ID of the DataTable widget.
            columns: List of column names.
            data: List of rows, where each row is a list of cell values.
            sort_column: Column index to sort by (-1 for no initial sort).
        """
        table = self.query_one(table_id, CustomDataTable)
        table.clear(columns=True)

        # Add columns
        for col_name in columns:
            table.add_column(col_name)

        # Add rows - use batch insertion for large datasets
        row_count = len(data)
        if row_count > self._TABLE_BATCH_INSERT_THRESHOLD:
            table.add_rows([tuple(row) for row in data])
        else:
            for row in data:
                table.add_row(*row)

        # Sort if requested
        if sort_column >= 0 and sort_column < len(columns):
            with suppress(Exception):
                table.sort(columns[sort_column])

    def show_empty_state(
        self,
        table_id: str,
        columns: list[str],
        message: str,
        title: str = "OK",
    ) -> None:
        """Show an empty state in a DataTable.

        Args:
            table_id: The ID of the DataTable widget.
            columns: List of column names.
            message: The empty state message.
            title: The title for the first column.
        """
        self.populate_data_table(
            table_id,
            columns,
            [[title, message] + ["-"] * (len(columns) - 2)],
        )

    def clear_table(self, table_id: str) -> None:
        """Clear a DataTable's data and columns.

        Args:
            table_id: The ID of the DataTable widget.
        """
        with suppress(NoMatches, WrongType):
            table = self.query_one(table_id, CustomDataTable)
            table.clear(columns=True)

    # =========================================================================
    # SEARCH/FILTER PATTERN
    # =========================================================================

    def init_search_filter(
        self,
        filter_stats_id: str = "filter-stats",
        search_indicator_id: str = "search-indicator",
    ) -> None:
        """Initialize search/filter widget references.

        Call this from on_mount() after widgets are available.

        Args:
            filter_stats_id: ID of the filter stats Static widget.
            search_indicator_id: ID of the search indicator Static widget.
        """
        with suppress(NoMatches, WrongType):
            self._filter_stats = self.query_one(f"#{filter_stats_id}", CustomStatic)
            self._search_indicator = self.query_one(f"#{search_indicator_id}", CustomStatic)
            self.update_filter_stats()

    def apply_search_filter(
        self,
        query: str,
        data: list[Any],
        search_columns: list[int],
        accessor_func: Callable[[Any], str] | None = None,
    ) -> list[Any]:
        """Apply a search filter to data.

        Args:
            query: The search query string.
            data: The data to filter.
            search_columns: List of column indices to search.
            accessor_func: Optional function to extract searchable text from item.
                          If None, uses str() on the item.

        Returns:
            Filtered list of items.
        """
        if not query.strip():
            return data

        query_lower = query.lower()

        if accessor_func:
            return [item for item in data if query_lower in accessor_func(item).lower()]

        return [
            item
            for item in data
            if any(
                query_lower in str(item[col]).lower()
                for col in search_columns
                if col < len(item)
            )
        ]

    def update_filter_stats(self, message: str | None = None) -> None:
        """Update the filter stats display.

        Args:
            message: Custom message to display. If None, shows search query status.
        """
        if self._filter_stats:
            if message:
                self._filter_stats.update(message)
                if "matching" in message.lower() or "filtered" in message.lower():
                    self._filter_stats.add_class("has-filter")
                else:
                    self._filter_stats.remove_class("has-filter")
            elif self.search_query:
                self._filter_stats.update(
                    f'Showing results matching: "{self.search_query}"'
                )
                self._filter_stats.add_class("has-filter")
            else:
                self._filter_stats.update("Showing all")
                self._filter_stats.remove_class("has-filter")

        if self._search_indicator:
            if self.search_query:
                self._search_indicator.update(f"[b]Search:[/b] {self.search_query}")
                self._search_indicator.add_class("active")
            else:
                self._search_indicator.remove_class("active")

    def set_search_query(self, query: str) -> None:
        """Set the current search query and update display.

        Args:
            query: The search query string.
        """
        self.search_query = query
        self.update_filter_stats()

    def clear_search(self) -> None:
        """Clear the current search query."""
        self.search_query = ""
        self.update_filter_stats()

    # =========================================================================
    # SUMMARY BAR HELPERS
    # =========================================================================

    def update_summary_bar(
        self,
        title: str,
        stats: list[tuple[str, str]],
        summary_id: str = "summary-bar",
    ) -> None:
        """Update the summary bar with a title and stats.

        Args:
            title: The summary title.
            stats: List of (css_class, text) tuples for stats.
            summary_id: ID of the summary Static widget.
        """
        with suppress(NoMatches, WrongType):
            summary_bar = self.query_one(f"#{summary_id}", CustomStatic)
            title_html = f'<span id="summary-title">{title}</span>'
            stats_parts = [f'<span class="{css}">{text}</span>' for css, text in stats]
            stats_html = "<br/>".join(stats_parts)
            summary_bar.update(
                f'{title_html}<br/><span id="summary-stats">{stats_html}</span>'
            )

    # =========================================================================
    # REFRESH ACTION
    # =========================================================================

    def action_refresh(self) -> None:
        """Handle refresh action.

        Shows loading overlay and re-loads data.
        """
        self.show_loading_overlay("Refreshing...")
        self.call_later(self.load_data)

    # =========================================================================
    # NAVIGATION ACTIONS (from ScreenNavigator)
    # =========================================================================

    def action_nav_home(self) -> None:
        """Navigate to home screen."""
        navigate_to_home(self.app)

    def action_nav_cluster(self) -> None:
        """Navigate to cluster screen."""
        navigate_to_cluster(self.app)

    def action_nav_charts(self) -> None:
        """Navigate to charts screen."""
        navigate_to_charts(self.app)

    def action_nav_optimizer(self) -> None:
        """Navigate to optimizer screen."""
        navigate_to_optimizer(self.app)

    def action_nav_export(self) -> None:
        """Navigate to export screen."""
        navigate_to_export(self.app)

    def action_nav_settings(self) -> None:
        """Navigate to settings screen."""
        navigate_to_settings(self.app)

    def action_nav_recommendations(self) -> None:
        """Navigate to recommendations screen."""
        navigate_to_recommendations(self.app)

    def action_show_help(self) -> None:
        """Show help dialog."""
        self.app.notify(
            "Keybindings:\n"
            "  ESC - Back\n"
            "  R - Refresh\n"
            "  H - Summary\n"
            "  C - Charts\n"
            "  O - Optimizer\n"
            "  E - Export\n"
            "  Ctrl+S - Settings\n"
            "  ? - Help",
            severity="information",
            timeout=30,
        )


__all__ = ["BaseScreen"]
