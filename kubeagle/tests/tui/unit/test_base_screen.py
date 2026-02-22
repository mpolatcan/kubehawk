"""Tests for BaseScreen - abstract base class for all TUI screens.

Tests cover class attributes, method existence, navigation actions,
search/filter pattern, loading state management, and datatable helpers.
"""

from __future__ import annotations

import inspect

from kubeagle.keyboard import BASE_SCREEN_BINDINGS
from kubeagle.keyboard.navigation import ScreenNavigator
from kubeagle.screens.base_screen import BaseScreen

# ===========================================================================
# Helper: Concrete subclass for testing (BaseScreen is abstract)
# ===========================================================================


class _ConcreteScreen(BaseScreen):
    """Concrete subclass of BaseScreen for testing purposes."""

    async def load_data(self) -> None:
        """No-op implementation of abstract method."""
        pass


# ===========================================================================
# TestBaseScreenClassAttributes
# ===========================================================================


class TestBaseScreenClassAttributes:
    """Tests for BaseScreen class-level attributes and inheritance."""

    def test_has_bindings(self) -> None:
        """BaseScreen.BINDINGS should be set to BASE_SCREEN_BINDINGS."""
        assert hasattr(BaseScreen, "BINDINGS")
        assert BaseScreen.BINDINGS is BASE_SCREEN_BINDINGS

    def test_is_screen_subclass(self) -> None:
        """BaseScreen should be a subclass of textual.screen.Screen."""
        from textual.screen import Screen

        assert issubclass(BaseScreen, Screen)

    def test_is_screen_navigator_subclass(self) -> None:
        """BaseScreen should be a subclass of ScreenNavigator."""
        assert issubclass(BaseScreen, ScreenNavigator)

    def test_base_screen_is_abstract(self) -> None:
        """BaseScreen has abstract method load_data, so direct instantiation
        is not possible without implementing it."""
        assert getattr(BaseScreen.load_data, "__isabstractmethod__", False) is True

    def test_bindings_is_list(self) -> None:
        """BINDINGS should be a list of tuples."""
        assert isinstance(BaseScreen.BINDINGS, list)
        assert len(BaseScreen.BINDINGS) > 0

    def test_bindings_contain_escape(self) -> None:
        """BINDINGS should contain an escape binding."""
        keys = [b[0] for b in BaseScreen.BINDINGS]
        assert "escape" in keys

    def test_bindings_contain_refresh(self) -> None:
        """BINDINGS should contain a refresh binding."""
        keys = [b[0] for b in BaseScreen.BINDINGS]
        assert "r" in keys


# ===========================================================================
# TestBaseScreenMethodsExist
# ===========================================================================


class TestBaseScreenMethodsExist:
    """Tests to verify all expected methods exist on BaseScreen."""

    def test_has_compose(self) -> None:
        """BaseScreen should have a compose method."""
        assert hasattr(BaseScreen, "compose")
        assert callable(BaseScreen.compose)

    def test_has_on_mount(self) -> None:
        """BaseScreen should have an on_mount method."""
        assert hasattr(BaseScreen, "on_mount")
        assert callable(BaseScreen.on_mount)

    def test_has_on_unmount(self) -> None:
        """BaseScreen should have an on_unmount method."""
        assert hasattr(BaseScreen, "on_unmount")
        assert callable(BaseScreen.on_unmount)

    def test_has_set_title(self) -> None:
        """BaseScreen should have a set_title method."""
        assert hasattr(BaseScreen, "set_title")
        assert callable(BaseScreen.set_title)

    def test_has_show_loading_overlay(self) -> None:
        """BaseScreen should have a show_loading_overlay method."""
        assert hasattr(BaseScreen, "show_loading_overlay")
        assert callable(BaseScreen.show_loading_overlay)

    def test_has_hide_loading_overlay(self) -> None:
        """BaseScreen should have a hide_loading_overlay method."""
        assert hasattr(BaseScreen, "hide_loading_overlay")
        assert callable(BaseScreen.hide_loading_overlay)

    def test_has_show_error_state(self) -> None:
        """BaseScreen should have a show_error_state method."""
        assert hasattr(BaseScreen, "show_error_state")
        assert callable(BaseScreen.show_error_state)

    def test_has_update_loading_message(self) -> None:
        """BaseScreen should have an update_loading_message method."""
        assert hasattr(BaseScreen, "update_loading_message")
        assert callable(BaseScreen.update_loading_message)

    def test_has_clear_table(self) -> None:
        """BaseScreen should have a clear_table method."""
        assert hasattr(BaseScreen, "clear_table")
        assert callable(BaseScreen.clear_table)

    def test_has_update_filter_stats(self) -> None:
        """BaseScreen should have an update_filter_stats method."""
        assert hasattr(BaseScreen, "update_filter_stats")
        assert callable(BaseScreen.update_filter_stats)

    def test_has_clear_search(self) -> None:
        """BaseScreen should have a clear_search method."""
        assert hasattr(BaseScreen, "clear_search")
        assert callable(BaseScreen.clear_search)

    def test_has_load_data_abstract(self) -> None:
        """BaseScreen should have an abstract load_data method."""
        assert hasattr(BaseScreen, "load_data")
        assert getattr(BaseScreen.load_data, "__isabstractmethod__", False) is True

    def test_has_screen_title_property(self) -> None:
        """BaseScreen should have a screen_title property."""
        assert hasattr(BaseScreen, "screen_title")
        assert isinstance(inspect.getattr_static(BaseScreen, "screen_title"), property)


# ===========================================================================
# TestBaseScreenNavActions
# ===========================================================================


class TestBaseScreenNavActions:
    """Tests to verify all navigation action methods exist."""

    def test_has_action_refresh(self) -> None:
        """BaseScreen should have an action_refresh method."""
        assert hasattr(BaseScreen, "action_refresh")
        assert callable(BaseScreen.action_refresh)

    def test_has_action_nav_home(self) -> None:
        """BaseScreen should have an action_nav_home method."""
        assert hasattr(BaseScreen, "action_nav_home")
        assert callable(BaseScreen.action_nav_home)

    def test_has_action_nav_cluster(self) -> None:
        """BaseScreen should have an action_nav_cluster method."""
        assert hasattr(BaseScreen, "action_nav_cluster")
        assert callable(BaseScreen.action_nav_cluster)

    def test_has_action_nav_charts(self) -> None:
        """BaseScreen should have an action_nav_charts method."""
        assert hasattr(BaseScreen, "action_nav_charts")
        assert callable(BaseScreen.action_nav_charts)

    def test_has_action_nav_optimizer(self) -> None:
        """BaseScreen should have an action_nav_optimizer method."""
        assert hasattr(BaseScreen, "action_nav_optimizer")
        assert callable(BaseScreen.action_nav_optimizer)

    def test_has_action_show_help(self) -> None:
        """BaseScreen should have an action_show_help method."""
        assert hasattr(BaseScreen, "action_show_help")
        assert callable(BaseScreen.action_show_help)

    def test_has_action_nav_export(self) -> None:
        """BaseScreen should have an action_nav_export method."""
        assert hasattr(BaseScreen, "action_nav_export")
        assert callable(BaseScreen.action_nav_export)

    def test_has_action_nav_settings(self) -> None:
        """BaseScreen should have an action_nav_settings method."""
        assert hasattr(BaseScreen, "action_nav_settings")
        assert callable(BaseScreen.action_nav_settings)

    def test_has_action_nav_recommendations(self) -> None:
        """BaseScreen should have an action_nav_recommendations method."""
        assert hasattr(BaseScreen, "action_nav_recommendations")
        assert callable(BaseScreen.action_nav_recommendations)


# ===========================================================================
# TestBaseScreenMethodSignatures
# ===========================================================================


class TestBaseScreenMethodSignatures:
    """Tests for method signatures to catch accidental API changes."""

    def test_show_loading_overlay_params(self) -> None:
        """show_loading_overlay should accept message and is_error."""
        sig = inspect.signature(BaseScreen.show_loading_overlay)
        params = list(sig.parameters.keys())
        assert "message" in params
        assert "is_error" in params

    def test_screen_title_default(self) -> None:
        """Default screen_title property should return 'KubEagle'."""
        assert BaseScreen.screen_title.fget is not None
        # Cannot call on uninstantiated class; check the property exists
        # The default from source is 'KubEagle'
        source = inspect.getsource(BaseScreen.screen_title.fget)
        assert "KubEagle" in source
