"""Unit tests for EKSHelmReporterApp - class attributes, instantiation, methods.

This module tests:
- App class attributes (BINDINGS, CSS_PATH, TITLE)
- Constructor parameter handling
- Method existence for all navigation and action methods
- Settings loading behaviour

Note: Tests avoid running the full Textual event loop (no app.run_test())
to keep them fast and deterministic. Where the App requires settings loading,
we allow it to use defaults (no config file side effects).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from textual.app import App
from textual.binding import Binding

from kubeagle.app import EKSHelmReporterApp
from kubeagle.constants import APP_TITLE, DARK_THEME
from kubeagle.keyboard.app import APP_BINDINGS
from kubeagle.models.state.app_state import AppState

# =============================================================================
# Class Attributes
# =============================================================================


class TestAppClassAttributes:
    """Test EKSHelmReporterApp class-level attributes."""

    def test_app_has_bindings(self) -> None:
        """App must declare BINDINGS."""
        assert hasattr(EKSHelmReporterApp, "BINDINGS")

    def test_app_bindings_are_binding_objects(self) -> None:
        """BINDINGS must be a list of Binding objects."""
        for binding in EKSHelmReporterApp.BINDINGS:
            assert isinstance(binding, Binding)

    def test_app_has_css_path(self) -> None:
        """App must declare CSS_PATH."""
        assert hasattr(EKSHelmReporterApp, "CSS_PATH")

    def test_app_css_path_value(self) -> None:
        """CSS_PATH must reference app.tcss."""
        assert "app.tcss" in str(EKSHelmReporterApp.CSS_PATH)

    def test_app_title_set(self) -> None:
        """App TITLE class attribute must match APP_TITLE constant."""
        assert EKSHelmReporterApp.TITLE == APP_TITLE

    def test_app_sub_title_not_required(self) -> None:
        """App may or may not have SUB_TITLE; this is informational."""
        # SUB_TITLE is optional in Textual apps.
        # If present, it should be a string.
        sub_title = getattr(EKSHelmReporterApp, "SUB_TITLE", None)
        if sub_title is not None:
            assert isinstance(sub_title, str)

    def test_app_bindings_match_app_bindings_constant(self) -> None:
        """BINDINGS should be APP_BINDINGS from keyboard module."""
        assert EKSHelmReporterApp.BINDINGS is APP_BINDINGS

    def test_app_inherits_from_textual_app(self) -> None:
        """EKSHelmReporterApp must inherit from textual.app.App."""
        assert issubclass(EKSHelmReporterApp, App)


# =============================================================================
# Instantiation
# =============================================================================


class TestAppInstantiation:
    """Test EKSHelmReporterApp constructor and parameter handling."""

    def test_default_instantiation(self) -> None:
        """App can be created with no arguments."""
        app = EKSHelmReporterApp()
        assert app is not None

    def test_with_charts_path(self) -> None:
        """App stores charts_path when provided."""
        path = Path("/tmp/charts")
        app = EKSHelmReporterApp(charts_path=path)
        assert app.charts_path == path
        # Settings should be overridden with CLI value
        assert app.settings.charts_path == str(path)

    def test_with_context(self) -> None:
        """App stores context when provided."""
        app = EKSHelmReporterApp(context="my-cluster")
        assert app.context == "my-cluster"

    def test_with_skip_eks(self) -> None:
        """App stores skip_eks flag when provided."""
        app = EKSHelmReporterApp(skip_eks=True)
        assert app.skip_eks is True

    def test_with_output_path(self) -> None:
        """App stores output_path when provided."""
        path = Path("/tmp/output")
        app = EKSHelmReporterApp(output_path=path)
        assert app.output_path == path
        assert app.settings.export_path == str(path)

    def test_with_active_charts_path(self) -> None:
        """App stores active_charts_path when provided."""
        path = Path("/tmp/active-charts")
        app = EKSHelmReporterApp(active_charts_path=path)
        assert app.active_charts_path == path
        assert app.settings.active_charts_path == str(path)

    def test_with_from_cluster(self) -> None:
        """App stores from_cluster flag and overrides settings."""
        app = EKSHelmReporterApp(from_cluster=True)
        assert app.from_cluster is True
        assert app.settings.use_cluster_values is True

    def test_default_charts_path_is_none(self) -> None:
        """Default charts_path is None."""
        app = EKSHelmReporterApp()
        assert app.charts_path is None

    def test_default_skip_eks_is_false(self) -> None:
        """Default skip_eks is False."""
        app = EKSHelmReporterApp()
        assert app.skip_eks is False

    def test_default_context_is_none(self) -> None:
        """Default context is None."""
        app = EKSHelmReporterApp()
        assert app.context is None


# =============================================================================
# Method Existence
# =============================================================================


class TestAppMethodsExist:
    """Verify that all expected methods exist on EKSHelmReporterApp."""

    def test_has_on_mount(self) -> None:
        """App must implement on_mount."""
        assert hasattr(EKSHelmReporterApp, "on_mount")
        assert callable(EKSHelmReporterApp.on_mount)

    def test_has_on_unmount(self) -> None:
        """App must implement on_unmount."""
        assert hasattr(EKSHelmReporterApp, "on_unmount")
        assert callable(EKSHelmReporterApp.on_unmount)

    def test_has_action_nav_home(self) -> None:
        """App must implement action_nav_home."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "action_nav_home")
        assert callable(app.action_nav_home)

    def test_has_action_nav_cluster(self) -> None:
        """App must implement action_nav_cluster."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "action_nav_cluster")
        assert callable(app.action_nav_cluster)

    def test_has_action_nav_charts(self) -> None:
        """App must implement action_nav_charts."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "action_nav_charts")
        assert callable(app.action_nav_charts)

    def test_has_action_nav_workloads(self) -> None:
        """App must implement action_nav_workloads."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "action_nav_workloads")
        assert callable(app.action_nav_workloads)

    def test_has_action_nav_optimizer(self) -> None:
        """App must implement action_nav_optimizer."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "action_nav_optimizer")
        assert callable(app.action_nav_optimizer)

    def test_has_action_nav_export(self) -> None:
        """App must implement action_nav_export."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "action_nav_export")
        assert callable(app.action_nav_export)

    def test_has_action_nav_settings(self) -> None:
        """App must implement action_nav_settings."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "action_nav_settings")
        assert callable(app.action_nav_settings)

    def test_has_action_nav_recommendations(self) -> None:
        """App must implement action_nav_recommendations."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "action_nav_recommendations")
        assert callable(app.action_nav_recommendations)

    def test_has_action_refresh(self) -> None:
        """App must implement action_refresh."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "action_refresh")
        assert callable(app.action_refresh)

    def test_has_action_show_help(self) -> None:
        """App must implement action_show_help."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "action_show_help")
        assert callable(app.action_show_help)

    def test_has_action_quit(self) -> None:
        """App must implement action_quit."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "action_quit")
        assert callable(app.action_quit)

    def test_has_action_back(self) -> None:
        """App must implement action_back."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "action_back")
        assert callable(app.action_back)


# =============================================================================
# Settings
# =============================================================================


class TestAppSettings:
    """Test settings loading and state initialization."""

    def test_has_load_settings(self) -> None:
        """App must implement _load_settings."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "_load_settings")
        assert callable(app._load_settings)

    def test_has_apply_theme(self) -> None:
        """App must implement _apply_theme."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "_apply_theme")
        assert callable(app._apply_theme)

    def test_registers_kubeagle_themes(self) -> None:
        """Custom KubEagle dark theme should be available at app startup."""
        app = EKSHelmReporterApp()
        assert DARK_THEME in app.available_themes

    def test_initial_state_object(self) -> None:
        """App must initialise a state (AppState) object."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "state")
        assert isinstance(app.state, AppState)

    def test_settings_object_exists(self) -> None:
        """App must have a settings attribute after construction."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "settings")

    def test_settings_has_charts_path(self) -> None:
        """Settings must have charts_path field."""
        app = EKSHelmReporterApp()
        assert hasattr(app.settings, "charts_path")

    def test_settings_has_theme(self) -> None:
        """Settings must have theme field."""
        app = EKSHelmReporterApp()
        assert hasattr(app.settings, "theme")

    def test_on_unmount_saves_settings(self) -> None:
        """on_unmount is a method that saves settings (existence check)."""
        app = EKSHelmReporterApp()
        assert hasattr(app, "on_unmount")
        assert callable(app.on_unmount)

    def test_charts_path_cli_override(self) -> None:
        """CLI charts_path overrides settings charts_path."""
        path = Path("/custom/charts")
        app = EKSHelmReporterApp(charts_path=path)
        assert app.settings.charts_path == str(path)
        # Also sets state
        assert app.state.charts_path == str(path)

    def test_output_path_cli_override(self) -> None:
        """CLI output_path overrides settings export_path."""
        path = Path("/custom/export")
        app = EKSHelmReporterApp(output_path=path)
        assert app.settings.export_path == str(path)
        assert app.state.export_path == str(path)

    def test_normalize_optional_path_recovers_clear_suffix(self) -> None:
        """Path normalizer should recover accidental 'clear' suffix append."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "charts"
            base_path.mkdir(parents=True, exist_ok=True)
            normalized = EKSHelmReporterApp._normalize_optional_path(
                f"{base_path}clear"
            )
            assert normalized == str(base_path.absolute())

    def test_normalize_optional_path_keeps_nonrecoverable_path(self) -> None:
        """Path normalizer should keep unresolved paths in absolute form."""
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = str(Path(tmpdir) / "missingclear")
            normalized = EKSHelmReporterApp._normalize_optional_path(raw_path)
            assert normalized == str(Path(raw_path).absolute())


# =============================================================================
# Terminal Size Policy
# =============================================================================


class TestTerminalSizePolicy:
    """Test app-level terminal size support policy."""

    def test_terminal_size_supported_at_minimum(self) -> None:
        """120x36 should be treated as supported."""
        app = EKSHelmReporterApp()
        app._current_terminal_size = lambda: (120, 36)  # type: ignore[method-assign]
        assert app._is_terminal_size_supported() is True

    def test_terminal_size_not_supported_below_minimum_width(self) -> None:
        """Width below minimum should be unsupported."""
        app = EKSHelmReporterApp()
        app._current_terminal_size = lambda: (119, 36)  # type: ignore[method-assign]
        assert app._is_terminal_size_supported() is False

    def test_terminal_size_not_supported_below_minimum_height(self) -> None:
        """Height below minimum should be unsupported."""
        app = EKSHelmReporterApp()
        app._current_terminal_size = lambda: (120, 35)  # type: ignore[method-assign]
        assert app._is_terminal_size_supported() is False


# =============================================================================
# Binding Coverage
# =============================================================================


class TestAppBindingCoverage:
    """Verify that critical navigation bindings are present."""

    @staticmethod
    def _binding_keys() -> list[str]:
        """Return all binding key strings from App BINDINGS."""
        return [b.key for b in EKSHelmReporterApp.BINDINGS]

    def test_has_escape_binding(self) -> None:
        """App must bind escape for back navigation."""
        assert "escape" in self._binding_keys()

    def test_has_home_binding(self) -> None:
        """App must bind 'h' for home navigation."""
        assert "h" in self._binding_keys()

    def test_has_cluster_binding(self) -> None:
        """App must bind 'c' for cluster navigation."""
        assert "c" in self._binding_keys()

    def test_has_charts_binding(self) -> None:
        """App must bind 'C' for charts navigation."""
        assert "C" in self._binding_keys()

    def test_does_not_have_optimizer_binding(self) -> None:
        """App should not bind 'o' globally for optimizer navigation."""
        assert "o" not in self._binding_keys()

    def test_has_export_binding(self) -> None:
        """App must bind 'e' for export navigation."""
        assert "e" in self._binding_keys()

    def test_has_settings_binding(self) -> None:
        """App must bind 'ctrl+s' for settings navigation."""
        assert "ctrl+s" in self._binding_keys()

    def test_has_quit_binding(self) -> None:
        """App must bind 'q' for quit."""
        assert "q" in self._binding_keys()

    def test_has_refresh_binding(self) -> None:
        """App must bind 'r' for refresh."""
        assert "r" in self._binding_keys()

    def test_has_help_binding(self) -> None:
        """App must bind '?' for help."""
        assert "?" in self._binding_keys()

    def test_has_recommendations_binding(self) -> None:
        """App must bind 'R' for recommendations navigation."""
        assert "R" in self._binding_keys()


# =============================================================================
# Navigation Regression
# =============================================================================


class _NavigationHarness:
    """Lightweight object for exercising app navigation methods."""

    _SCREEN_HOME_NAME = "nav-home"
    _SCREEN_CLUSTER_NAME = "nav-cluster"
    _SCREEN_WORKLOADS_NAME = "nav-workloads"

    def __init__(self, current_screen: Any, *, skip_eks: bool) -> None:
        self.screen = current_screen
        self.skip_eks = skip_eks
        self.prepare_calls = 0
        self.activate_calls = 0

    def _block_actions_for_unsupported_terminal(self) -> bool:
        return False

    def _prepare_current_screen_for_navigation(self) -> None:
        self.prepare_calls += 1

    def _activate_installed_screen(
        self,
        screen_name: str,
        screen_factory: Any,
        *,
        prefer_switch: bool = False,
    ) -> None:
        _ = screen_name
        _ = screen_factory
        _ = prefer_switch
        self.activate_calls += 1


class TestNavigationRegression:
    """Guard against no-op navigation canceling active screen work."""

    def test_nav_cluster_noop_when_already_on_cluster(self) -> None:
        """Pressing cluster key on cluster screen should not trigger prepare/activate."""
        from kubeagle.screens import ClusterScreen

        harness = _NavigationHarness(ClusterScreen(), skip_eks=False)
        EKSHelmReporterApp.action_nav_cluster(harness)  # type: ignore[arg-type]

        assert harness.prepare_calls == 0
        assert harness.activate_calls == 0

    def test_nav_home_noop_when_home_maps_to_cluster(self) -> None:
        """When skip_eks is off, Home points to Cluster and should no-op there."""
        from kubeagle.screens import ClusterScreen

        harness = _NavigationHarness(ClusterScreen(), skip_eks=False)
        EKSHelmReporterApp.action_nav_home(harness)  # type: ignore[arg-type]

        assert harness.prepare_calls == 0
        assert harness.activate_calls == 0

    def test_nav_cluster_prepares_when_switching_from_other_screen(self) -> None:
        """Switching to cluster from a different screen should still prepare/activate."""
        harness = _NavigationHarness(object(), skip_eks=False)
        EKSHelmReporterApp.action_nav_cluster(harness)  # type: ignore[arg-type]

        assert harness.prepare_calls == 1
        assert harness.activate_calls == 1

    def test_nav_workloads_noop_when_already_on_workloads(self) -> None:
        """Pressing workloads nav on workloads screen should not prepare/activate."""
        from kubeagle.screens import WorkloadsScreen

        harness = _NavigationHarness(WorkloadsScreen(), skip_eks=False)
        EKSHelmReporterApp.action_nav_workloads(harness)  # type: ignore[arg-type]

        assert harness.prepare_calls == 0
        assert harness.activate_calls == 0

    def test_nav_workloads_prepares_when_switching_from_other_screen(self) -> None:
        """Switching to workloads from another screen should prepare/activate."""
        harness = _NavigationHarness(object(), skip_eks=False)
        EKSHelmReporterApp.action_nav_workloads(harness)  # type: ignore[arg-type]

        assert harness.prepare_calls == 1
        assert harness.activate_calls == 1


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestAppBindingCoverage",
    "TestAppClassAttributes",
    "TestAppInstantiation",
    "TestAppMethodsExist",
    "TestAppSettings",
    "TestNavigationRegression",
    "TestTerminalSizePolicy",
]
