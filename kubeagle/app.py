"""Main application class for KubEagle TUI."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.css.query import NoMatches, WrongType
from textual.events import Resize
from textual.screen import Screen

from kubeagle.constants import (
    APP_TITLE,
    DARK_THEME,
    INSIDERONE_DARK_THEME,
    THEME_DEFAULT,
)
from kubeagle.constants.enums import ThemeMode
from kubeagle.keyboard.app import APP_BINDINGS
from kubeagle.models.state.app_state import AppState
from kubeagle.models.state.config_manager import (
    AppSettings,
    ConfigError,
    ConfigLoadError,
    ConfigManager,
    ConfigSaveError,
)
from kubeagle.optimizer.rules import configure_rule_thresholds
from kubeagle.themes import register_kubeagle_themes
from kubeagle.widgets import CustomStatic


class TerminalSizeUnsupportedScreen(Screen[None]):
    """Blocking screen shown when terminal is smaller than supported size."""

    DEFAULT_CSS = """
    TerminalSizeUnsupportedScreen {
        align: center middle;
        background: $background;
    }

    #terminal-size-panel {
        width: 1fr;
        max-width: 88;
        margin: 1 2;
        padding: 1 2;
        border: round $warning;
        background: $surface;
        layout: vertical;
    }

    .terminal-size-title {
        color: $warning;
        text-style: bold;
        content-align: center middle;
        text-align: center;
        margin-bottom: 1;
    }

    .terminal-size-line {
        color: $text;
        content-align: center middle;
        text-align: center;
    }
    """

    def __init__(
        self,
        *,
        min_width: int,
        min_height: int,
        current_width: int,
        current_height: int,
    ) -> None:
        super().__init__()
        self._min_width = min_width
        self._min_height = min_height
        self._current_width = current_width
        self._current_height = current_height

    def compose(self) -> ComposeResult:
        """Compose unsupported-size information."""
        yield Container(
            CustomStatic(
                "Terminal size not supported",
                classes="terminal-size-title",
            ),
            CustomStatic(
                f"Current: {self._current_width}x{self._current_height}",
                id="terminal-size-current",
                classes="terminal-size-line",
            ),
            CustomStatic(
                f"Supported from: {self._min_width}x{self._min_height}",
                classes="terminal-size-line",
            ),
            CustomStatic(
                "Increase terminal size to continue.",
                classes="terminal-size-line",
            ),
            id="terminal-size-panel",
        )

    def update_current_size(self, width: int, height: int) -> None:
        """Update the current size line while this screen is visible."""
        self._current_width = width
        self._current_height = height
        with suppress(NoMatches, WrongType):
            self.query_one("#terminal-size-current", CustomStatic).update(
                f"Current: {self._current_width}x{self._current_height}",
            )

    def on_resize(self, _: Resize) -> None:
        """Re-check terminal support whenever size changes."""
        self.update_current_size(self.app.size.width, self.app.size.height)
        with suppress(Exception):
            enforce_terminal_size = getattr(
                self.app, "_enforce_terminal_size_policy", None,
            )
            if callable(enforce_terminal_size):
                self.app.call_after_refresh(enforce_terminal_size)


class EKSHelmReporterApp(App[None]):
    """Main TUI application for KubEagle."""

    TITLE = APP_TITLE
    CSS_PATH = "css/app.tcss"
    BINDINGS: list[Binding] = APP_BINDINGS
    MIN_SUPPORTED_TERMINAL_WIDTH = 120
    MIN_SUPPORTED_TERMINAL_HEIGHT = 36
    _SCREEN_CLUSTER_NAME = "nav-cluster"
    _SCREEN_CHARTS_NAME = "nav-charts"
    _SCREEN_WORKLOADS_NAME = "nav-workloads"
    _SCREEN_EXPORT_NAME = "nav-export"
    _SCREEN_SETTINGS_NAME = "nav-settings"
    _PATH_SUFFIX_RECOVERY_TOKENS = ("clear", "apply", "cancel")

    # Type hint for settings attribute
    settings: AppSettings
    state: AppState

    def __init__(
        self,
        charts_path: Path | None = None,
        skip_eks: bool = False,
        context: str | None = None,
        active_charts_path: Path | None = None,
        from_cluster: bool = False,
        output_path: Path | None = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.charts_path = charts_path
        self.skip_eks = skip_eks
        self.context = context
        self.active_charts_path = active_charts_path
        self.from_cluster = from_cluster
        self.output_path = output_path

        # Initialize app state
        self.state = AppState()
        register_kubeagle_themes(self)

        # Load settings on startup
        self._load_settings()

    def _load_settings(self) -> None:
        """Load application settings from persistent storage."""
        try:
            self.settings = ConfigManager.load()
        except ConfigLoadError:
            # Use defaults if loading fails
            self.settings = AppSettings()

        # Normalize stored file paths to keep behavior stable across launch CWDs.
        self.settings.charts_path = self._normalize_optional_path(self.settings.charts_path)
        self.settings.active_charts_path = self._normalize_optional_path(
            self.settings.active_charts_path
        )
        self.settings.codeowners_path = self._normalize_optional_path(
            self.settings.codeowners_path
        )

        # Apply CLI overrides if provided
        if self.charts_path is not None:
            normalized_charts_path = self._normalize_optional_path(str(self.charts_path))
            self.settings.charts_path = normalized_charts_path
            self.state.charts_path = normalized_charts_path
        if self.active_charts_path is not None:
            self.settings.active_charts_path = self._normalize_optional_path(
                str(self.active_charts_path)
            )
        if self.from_cluster:
            self.settings.use_cluster_values = True
        if self.output_path is not None:
            self.settings.export_path = str(self.output_path)
            self.state.export_path = str(self.output_path)

        # Apply theme
        self._apply_theme()
        self.apply_optimizer_settings()

    @staticmethod
    def _normalize_optional_path(value: str | None) -> str:
        """Normalize optional settings path to absolute form.

        Also recovers common accidental suffixes appended by UI interactions
        (e.g. ``/repo/pathclear``) when the trimmed path exists.
        """
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        normalized_path = Path(raw_value).expanduser().absolute()
        if normalized_path.exists():
            return str(normalized_path)

        lower_raw = raw_value.lower()
        for suffix in EKSHelmReporterApp._PATH_SUFFIX_RECOVERY_TOKENS:
            if not lower_raw.endswith(suffix):
                continue
            trimmed_raw = raw_value[: -len(suffix)].rstrip()
            if not trimmed_raw:
                continue
            trimmed_path = Path(trimmed_raw).expanduser().absolute()
            if trimmed_path.exists():
                return str(trimmed_path)

        return str(normalized_path)

    def apply_optimizer_settings(self) -> None:
        """Apply settings that influence optimizer rule evaluation."""
        configure_rule_thresholds(
            limit_request_ratio_threshold=self.settings.limit_request_ratio_threshold
        )

    def _apply_theme(self) -> None:
        """Apply stored theme preference with backward-compatible alias mapping."""
        theme_name = str(self.settings.theme or "").strip()
        normalized = theme_name.lower()

        if normalized in {
            ThemeMode.LIGHT.value,
            "custom-light",
            "textual-light",
            "kubeagle-light",
        }:
            resolved_theme = THEME_DEFAULT
        elif normalized in {
            DARK_THEME.lower(),
            "kubeagle-dark",
        }:
            resolved_theme = DARK_THEME
        elif normalized in {
            INSIDERONE_DARK_THEME.lower(),
            "insiderone-dark",
            ThemeMode.DARK.value,
            "custom-dark",
            "textual-dark",
        }:
            resolved_theme = INSIDERONE_DARK_THEME
        else:
            resolved_theme = THEME_DEFAULT

        self.settings.theme = resolved_theme
        self.theme = resolved_theme

    def on_mount(self) -> None:
        """Called when app is mounted."""
        from kubeagle.screens import ClusterScreen

        self._activate_installed_screen(
            self._SCREEN_CLUSTER_NAME,
            ClusterScreen,
        )
        self.call_after_refresh(self._enforce_terminal_size_policy)

    def on_resize(self, _: Resize) -> None:
        """Enforce terminal-size support policy on resize."""
        self._enforce_terminal_size_policy()

    def _current_terminal_size(self) -> tuple[int, int]:
        """Return current terminal width and height."""
        with suppress(Exception):
            return int(self.size.width), int(self.size.height)
        return 0, 0

    def _is_terminal_size_supported(self) -> bool:
        """Return whether current terminal size is within supported bounds."""
        if self.is_headless:
            return True
        width, height = self._current_terminal_size()
        return (
            width >= self.MIN_SUPPORTED_TERMINAL_WIDTH
            and height >= self.MIN_SUPPORTED_TERMINAL_HEIGHT
        )

    def _is_terminal_size_guard_active(self) -> bool:
        """Return whether unsupported-size guard screen is currently visible."""
        if not self.screen_stack:
            return False
        return isinstance(self.screen, TerminalSizeUnsupportedScreen)

    def _enforce_terminal_size_policy(self) -> None:
        """Show/hide unsupported-size screen based on current terminal size."""
        if not self.screen_stack:
            return

        width, height = self._current_terminal_size()
        if self._is_terminal_size_supported():
            if self._is_terminal_size_guard_active():
                self.pop_screen()
            return

        if self._is_terminal_size_guard_active():
            guard_screen = self.screen
            if isinstance(guard_screen, TerminalSizeUnsupportedScreen):
                guard_screen.update_current_size(width, height)
            return

        self.push_screen(
            TerminalSizeUnsupportedScreen(
                min_width=self.MIN_SUPPORTED_TERMINAL_WIDTH,
                min_height=self.MIN_SUPPORTED_TERMINAL_HEIGHT,
                current_width=width,
                current_height=height,
            )
        )

    def _block_actions_for_unsupported_terminal(self) -> bool:
        """Return True when user actions should be blocked for unsupported sizes."""
        self._enforce_terminal_size_policy()
        return self._is_terminal_size_guard_active()

    def _prepare_current_screen_for_navigation(self) -> None:
        """Let the current screen release heavy background work before switching."""
        if not self.screen_stack:
            return
        current_screen = self.screen
        prepare = getattr(current_screen, "prepare_for_screen_switch", None)
        if callable(prepare):
            with suppress(Exception):
                prepare()

    def _activate_existing_screen(self, screen_type: type[Screen]) -> bool:
        """Pop back to an existing screen instance when present in the stack."""
        if isinstance(self.screen, screen_type):
            return True
        target_screen: Screen | None = None
        for stacked_screen in reversed(self.screen_stack):
            if isinstance(stacked_screen, screen_type):
                target_screen = stacked_screen
                break
        if target_screen is None:
            return False
        while self.screen is not target_screen and len(self.screen_stack) > 1:
            self.pop_screen()
        return isinstance(self.screen, screen_type)

    def _ensure_installed_screen(
        self,
        screen_name: str,
        screen_factory: Callable[[], Screen],
    ) -> Screen:
        """Return an installed screen, installing it lazily if needed."""
        try:
            return self.get_screen(screen_name)
        except KeyError:
            screen = screen_factory()
            self.install_screen(screen, screen_name)
            return screen

    def _activate_installed_screen(
        self,
        screen_name: str,
        screen_factory: Callable[[], Screen],
        *,
        prefer_switch: bool = False,
    ) -> Screen:
        """Activate an installed screen by popping to it or pushing it."""
        target_screen = self._ensure_installed_screen(screen_name, screen_factory)
        if self.screen is target_screen:
            return target_screen
        if target_screen in self.screen_stack:
            while self.screen is not target_screen and len(self.screen_stack) > 1:
                self.pop_screen()
            return target_screen
        if prefer_switch and len(self.screen_stack) == 1:
            try:
                self.switch_screen(screen_name)
            except IndexError:
                # In certain headless/automation flows the default root screen can
                # have an empty result-callback stack; fall back to push.
                self.push_screen(screen_name)
            return target_screen
        self.push_screen(screen_name)
        return target_screen

    def action_nav_home(self) -> None:
        """Navigate to the primary landing screen (Cluster summary)."""
        if self._block_actions_for_unsupported_terminal():
            return
        from kubeagle.screens import ClusterScreen

        current_screen = self.screen
        if isinstance(current_screen, ClusterScreen):
            current_screen.action_switch_tab_1()
            return
        self._prepare_current_screen_for_navigation()
        self._activate_installed_screen(
            self._SCREEN_CLUSTER_NAME,
            ClusterScreen,
            prefer_switch=True,
        )
        current_screen = self.screen
        if isinstance(current_screen, ClusterScreen):
            current_screen.action_switch_tab_1()

    def action_nav_cluster(self) -> None:
        """Navigate to cluster overview."""
        if self._block_actions_for_unsupported_terminal():
            return
        from kubeagle.screens import ClusterScreen

        current_screen = self.screen
        if isinstance(current_screen, ClusterScreen):
            current_screen.action_switch_tab_1()
            return
        self._prepare_current_screen_for_navigation()
        self._activate_installed_screen(
            self._SCREEN_CLUSTER_NAME,
            ClusterScreen,
            prefer_switch=True,
        )
        current_screen = self.screen
        if isinstance(current_screen, ClusterScreen):
            current_screen.action_switch_tab_1()

    def action_nav_workloads(self) -> None:
        """Navigate to workloads explorer."""
        if self._block_actions_for_unsupported_terminal():
            return
        from kubeagle.screens import WorkloadsScreen

        if isinstance(self.screen, WorkloadsScreen):
            return

        self._prepare_current_screen_for_navigation()
        self._activate_installed_screen(
            self._SCREEN_WORKLOADS_NAME,
            WorkloadsScreen,
            prefer_switch=True,
        )

    def action_nav_charts(self) -> None:
        """Navigate to charts explorer."""
        if self._block_actions_for_unsupported_terminal():
            return
        from kubeagle.screens import ChartsExplorerScreen

        current_screen = self.screen
        if isinstance(current_screen, ChartsExplorerScreen):
            current_screen.action_show_charts_tab()
            return
        self._prepare_current_screen_for_navigation()
        self._activate_installed_screen(
            self._SCREEN_CHARTS_NAME,
            ChartsExplorerScreen,
            prefer_switch=True,
        )
        current_screen = self.screen
        if isinstance(current_screen, ChartsExplorerScreen):
            current_screen.action_show_charts_tab()

    def action_nav_optimizer(self) -> None:
        """Navigate to charts explorer violations tab."""
        if self._block_actions_for_unsupported_terminal():
            return
        from kubeagle.screens import ChartsExplorerScreen
        from kubeagle.screens.detail import OptimizerScreen

        current_screen = self.screen
        if isinstance(current_screen, ChartsExplorerScreen):
            current_screen.action_show_violations_tab()
            return

        self._prepare_current_screen_for_navigation()
        if self._activate_existing_screen(ChartsExplorerScreen):
            current_screen = self.screen
            if isinstance(current_screen, ChartsExplorerScreen):
                current_screen.action_show_violations_tab()
            return

        self.push_screen(OptimizerScreen(include_cluster=not self.skip_eks))

    def action_nav_export(self) -> None:
        """Navigate to report export."""
        if self._block_actions_for_unsupported_terminal():
            return
        from kubeagle.screens import ReportExportScreen

        if isinstance(self.screen, ReportExportScreen):
            return
        self._prepare_current_screen_for_navigation()
        self._activate_installed_screen(
            self._SCREEN_EXPORT_NAME,
            ReportExportScreen,
            prefer_switch=True,
        )

    def action_nav_settings(self) -> None:
        """Navigate to settings."""
        if self._block_actions_for_unsupported_terminal():
            return
        from kubeagle.screens import SettingsScreen

        if isinstance(self.screen, SettingsScreen):
            return
        self._prepare_current_screen_for_navigation()
        self._activate_installed_screen(
            self._SCREEN_SETTINGS_NAME,
            SettingsScreen,
            prefer_switch=True,
        )

    def action_nav_recommendations(self) -> None:
        """Navigate to charts explorer violations/recommendations view."""
        if self._block_actions_for_unsupported_terminal():
            return
        from kubeagle.screens import ChartsExplorerScreen
        from kubeagle.screens.detail import OptimizerScreen

        current_screen = self.screen
        if isinstance(current_screen, ChartsExplorerScreen):
            current_screen.action_show_recommendations_tab()
            return

        self._prepare_current_screen_for_navigation()
        if self._activate_existing_screen(ChartsExplorerScreen):
            current_screen = self.screen
            if isinstance(current_screen, ChartsExplorerScreen):
                current_screen.action_show_recommendations_tab()
            return

        self.push_screen(
            OptimizerScreen(
                initial_view="recommendations",
                include_cluster=not self.skip_eks,
            )
        )

    def action_show_help(self) -> None:
        """Show help dialog."""
        if self._block_actions_for_unsupported_terminal():
            return
        self.notify(
            "Keybindings:\n"
            "Navigation:\n"
            "  h: Home\n"
            "  c: Cluster (tabs 1-3)\n"
            "  C: Charts Explorer\n"
            "  Workloads: Primary tab next to Charts\n"
            "  o: Violations tab\n"
            "  R: Violations + Recommendations\n"
            "  e: Export\n"
            "  Ctrl+S: Settings\n"
            "Cluster Screen Tabs:\n"
            "  1: Summary\n"
            "  2: Nodes\n"
            "  3: Workloads\n"
            "Actions:\n"
            "  ?: Help\n"
            "  r: Refresh\n"
            "  q / Esc: Back / Close\n"
            "DataTable:\n"
            "  s: Sort (when focused)",
            severity="information",
            title="Help",
        )

    async def action_refresh(self) -> None:
        """Refresh data."""
        if self._block_actions_for_unsupported_terminal():
            return
        # Trigger refresh on current screen if it has a refresh action
        current_screen = self.screen
        refresh_method = getattr(current_screen, "action_refresh", None)
        if refresh_method is not None:
            if inspect.iscoroutinefunction(refresh_method):
                await refresh_method()
            else:
                refresh_method()
        else:
            self.notify("Refreshing data...", severity="information")

    def action_quit(self) -> None:  # type: ignore[override]
        """Quit the application."""
        self.exit()

    async def action_back(self) -> None:
        """Go back to the previous screen."""
        if self._is_terminal_size_guard_active():
            return
        if self._block_actions_for_unsupported_terminal():
            return
        # Only pop if we're not on the base screen
        if len(self.screen_stack) > 1:
            self.pop_screen()

    def on_unmount(self) -> None:
        """Save settings when app exits."""
        try:
            ConfigManager.save(self.settings)
        except ConfigSaveError as e:
            self.notify(f"Failed to save settings: {e}", severity="error")


__all__ = [
    "EKSHelmReporterApp",
]
