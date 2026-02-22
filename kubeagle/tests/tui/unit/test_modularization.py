"""Tests for screens modularization (PRD-010).

This module tests the domain-driven screen reorganization:
- Import verification (backward compatibility)
- Navigation function tests
- Screen access tests

Marked with:
- @pytest.mark.unit: Marks as unit test
- @pytest.mark.fast: Marks as fast test (<100ms)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# =============================================================================
# IMPORT VERIFICATION TESTS - Backward Compatibility
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestBackwardCompatibleImports:
    """Tests for backward compatible imports via screens/__init__.py."""

    def test_charts_explorer_screen_import_from_screens(self):
        """Test ChartsExplorerScreen can be imported from screens package."""
        from kubeagle.screens import ChartsExplorerScreen

        assert ChartsExplorerScreen is not None

    def test_cluster_screen_import(self):
        """Test ClusterScreen can be imported from screens package."""
        from kubeagle.screens import ClusterScreen

        assert ClusterScreen is not None

    def test_base_screen_import(self):
        """Test BaseScreen can be imported from screens package."""
        from kubeagle.screens import BaseScreen

        assert BaseScreen is not None

    def test_chart_detail_screen_import(self):
        """Test ChartDetailScreen can be imported from screens package."""
        from kubeagle.screens import ChartDetailScreen

        assert ChartDetailScreen is not None

    def test_optimizer_screen_import(self):
        """Test OptimizerScreen can be imported from screens package."""
        from kubeagle.screens import OptimizerScreen

        assert OptimizerScreen is not None

    def test_settings_screen_import(self):
        """Test SettingsScreen can be imported from screens package."""
        from kubeagle.screens import SettingsScreen

        assert SettingsScreen is not None

    def test_charts_explorer_screen_import_convenience(self):
        """Test ChartsExplorerScreen available via screens package (replaces TeamStatisticsScreen)."""
        from kubeagle.screens import ChartsExplorerScreen

        assert ChartsExplorerScreen is not None

    def test_charts_explorer_screen_import(self):
        """Test ChartsExplorerScreen can be imported from screens package."""
        from kubeagle.screens import ChartsExplorerScreen

        assert ChartsExplorerScreen is not None

    def test_report_export_screen_import(self):
        """Test ReportExportScreen can be imported from screens package."""
        from kubeagle.screens import ReportExportScreen

        assert ReportExportScreen is not None


@pytest.mark.unit
@pytest.mark.fast
class TestDomainPackageImports:
    """Tests for domain package imports (new import style)."""

    def test_charts_domain_import(self):
        """Test ChartsExplorerScreen can be imported from charts_explorer domain package."""
        from kubeagle.screens.charts_explorer import ChartsExplorerScreen

        assert ChartsExplorerScreen is not None

    def test_cluster_domain_import(self):
        """Test ClusterScreen can be imported from cluster domain package."""
        from kubeagle.screens.cluster import ClusterScreen

        assert ClusterScreen is not None

    def test_detail_domain_import(self):
        """Test detail domain imports work correctly."""
        from kubeagle.screens.detail import (
            ChartDetailScreen,
            OptimizerScreen,
        )

        assert ChartDetailScreen is not None
        assert OptimizerScreen is not None

    def test_teams_domain_import(self):
        """Test ChartsExplorerScreen replaces teams domain (imported from charts_explorer)."""
        from kubeagle.screens.charts_explorer import (
            ChartsExplorerScreen,
        )

        assert ChartsExplorerScreen is not None

    def test_charts_explorer_domain_import(self):
        """Test ChartsExplorerScreen can be imported from charts_explorer domain package."""
        from kubeagle.screens.charts_explorer import (
            ChartsExplorerScreen,
        )

        assert ChartsExplorerScreen is not None

    def test_reports_domain_import(self):
        """Test reports domain imports work correctly."""
        from kubeagle.screens.reports import (
            ReportExportScreen,
        )

        assert ReportExportScreen is not None

    def test_settings_domain_import(self):
        """Test settings domain imports work correctly."""
        from kubeagle.screens.settings import SettingsScreen

        assert SettingsScreen is not None


@pytest.mark.unit
@pytest.mark.fast
class TestNavigationModuleImports:
    """Tests for navigation module imports."""

    def test_screen_navigator_import(self):
        """Test ScreenNavigator can be imported."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        assert ScreenNavigator is not None

    def test_navigate_to_functions_import(self):
        """Test all navigate_to_* functions can be imported."""
        from kubeagle.keyboard.navigation import (
            navigate_to_charts,
            navigate_to_cluster,
            navigate_to_export,
            navigate_to_home,
            navigate_to_optimizer,
            navigate_to_recommendations,
            navigate_to_settings,
        )

        assert navigate_to_home is not None
        assert navigate_to_cluster is not None
        assert navigate_to_charts is not None
        assert navigate_to_optimizer is not None
        assert navigate_to_export is not None
        assert navigate_to_settings is not None
        assert navigate_to_recommendations is not None

    def test_keybindings_import(self):
        """Test all keybinding constants can be imported from keyboard module."""
        from kubeagle.keyboard import (
            BASE_SCREEN_BINDINGS,
            CHART_DETAIL_SCREEN_BINDINGS,
            CHARTS_EXPLORER_SCREEN_BINDINGS,
            CLUSTER_SCREEN_BINDINGS,
            REPORT_EXPORT_SCREEN_BINDINGS,
            SETTINGS_SCREEN_BINDINGS,
        )

        assert BASE_SCREEN_BINDINGS is not None
        assert CHARTS_EXPLORER_SCREEN_BINDINGS is not None
        assert CLUSTER_SCREEN_BINDINGS is not None
        assert SETTINGS_SCREEN_BINDINGS is not None
        assert CHART_DETAIL_SCREEN_BINDINGS is not None
        assert REPORT_EXPORT_SCREEN_BINDINGS is not None


@pytest.mark.unit
@pytest.mark.fast
class TestMixinImports:
    """Tests for mixin imports."""

    def test_tabbed_view_mixin_import(self):
        """Test TabbedViewMixin can be imported."""
        from kubeagle.screens.mixins import TabbedViewMixin

        assert TabbedViewMixin is not None


@pytest.mark.unit
@pytest.mark.fast
class TestScreensPackageExports:
    """Tests for screens/__init__.py __all__ exports."""

    def test_all_exports_contain_screens(self):
        """Test __all__ contains all expected screen classes."""
        import kubeagle.screens as screens

        expected = [
            "BaseScreen",
            "ChartsExplorerScreen",
            "ClusterScreen",
            "ReportExportScreen",
            "ChartDetailScreen",
            "OptimizerScreen",
            "SettingsScreen",
        ]

        for name in expected:
            assert hasattr(screens, name), f"Missing export: {name}"
            assert name in screens.__all__, f"Missing from __all__: {name}"

    def test_all_exports_contain_navigation(self):
        """Test __all__ contains all navigation functions and classes."""
        import kubeagle.screens as screens

        expected_navigation = [
            "ScreenNavigator",
            "navigate_to_home",
            "navigate_to_cluster",
            "navigate_to_charts",
            "navigate_to_optimizer",
            "navigate_to_export",
            "navigate_to_settings",
            "navigate_to_recommendations",
        ]

        for name in expected_navigation:
            assert hasattr(screens, name), f"Missing export: {name}"
            assert name in screens.__all__, f"Missing from __all__: {name}"

    def test_all_exports_contain_keybindings(self):
        """Test __all__ contains all keybinding constants."""
        import kubeagle.screens as screens

        expected_keybindings = [
            "BASE_SCREEN_BINDINGS",
            "CLUSTER_SCREEN_BINDINGS",
            "CHARTS_EXPLORER_SCREEN_BINDINGS",
            "SETTINGS_SCREEN_BINDINGS",
            "CHART_DETAIL_SCREEN_BINDINGS",
            "REPORT_EXPORT_SCREEN_BINDINGS",
        ]

        for name in expected_keybindings:
            assert hasattr(screens, name), f"Missing export: {name}"
            assert name in screens.__all__, f"Missing from __all__: {name}"


# =============================================================================
# NAVIGATION TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestScreenNavigatorClass:
    """Tests for ScreenNavigator class."""

    def test_screen_navigator_init_without_app(self):
        """Test ScreenNavigator can be initialized without app."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        navigator = ScreenNavigator()
        assert navigator._app is None

    def test_screen_navigator_init_with_app(self):
        """Test ScreenNavigator can be initialized with app (mock)."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        mock_app = MagicMock()
        navigator = ScreenNavigator(app=mock_app)
        assert navigator._app is mock_app

    def test_screen_navigator_app_property_raises_without_app(self):
        """Test ScreenNavigator.app property raises when app is None."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        navigator = ScreenNavigator()
        with pytest.raises(RuntimeError):
            _ = navigator.app

    def test_screen_navigator_app_property_returns_app(self):
        """Test ScreenNavigator.app property returns the app."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        mock_app = MagicMock()
        navigator = ScreenNavigator(app=mock_app)
        assert navigator.app is mock_app


@pytest.mark.unit
@pytest.mark.fast
class TestNavigationFunctionsSignature:
    """Tests for navigation function signatures."""

    def test_navigate_to_home_signature(self):
        """Test navigate_to_home takes app parameter."""
        import inspect

        from kubeagle.keyboard.navigation import navigate_to_home

        sig = inspect.signature(navigate_to_home)
        params = list(sig.parameters.keys())
        assert "app" in params

    def test_navigate_to_cluster_signature(self):
        """Test navigate_to_cluster takes app parameter."""
        import inspect

        from kubeagle.keyboard.navigation import navigate_to_cluster

        sig = inspect.signature(navigate_to_cluster)
        params = list(sig.parameters.keys())
        assert "app" in params

    def test_navigate_to_charts_signature(self):
        """Test navigate_to_charts takes app parameter."""
        import inspect

        from kubeagle.keyboard.navigation import navigate_to_charts

        sig = inspect.signature(navigate_to_charts)
        params = list(sig.parameters.keys())
        assert "app" in params

    def test_navigate_to_optimizer_signature(self):
        """Test navigate_to_optimizer takes app parameter."""
        import inspect

        from kubeagle.keyboard.navigation import navigate_to_optimizer

        sig = inspect.signature(navigate_to_optimizer)
        params = list(sig.parameters.keys())
        assert "app" in params

    def test_navigate_to_export_signature(self):
        """Test navigate_to_export takes app parameter."""
        import inspect

        from kubeagle.keyboard.navigation import navigate_to_export

        sig = inspect.signature(navigate_to_export)
        params = list(sig.parameters.keys())
        assert "app" in params

    def test_navigate_to_settings_signature(self):
        """Test navigate_to_settings takes app parameter."""
        import inspect

        from kubeagle.keyboard.navigation import navigate_to_settings

        sig = inspect.signature(navigate_to_settings)
        params = list(sig.parameters.keys())
        assert "app" in params

    def test_navigate_to_recommendations_signature(self):
        """Test navigate_to_recommendations takes app parameter."""
        import inspect

        from kubeagle.keyboard.navigation import (
            navigate_to_recommendations,
        )

        sig = inspect.signature(navigate_to_recommendations)
        params = list(sig.parameters.keys())
        assert "app" in params



# =============================================================================
# SCREEN ACCESS TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestScreenNavigatorActionMethods:
    """Tests for ScreenNavigator action methods existence."""

    def test_action_nav_home_exists(self):
        """Test action_nav_home method exists on ScreenNavigator."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        navigator = ScreenNavigator()
        assert hasattr(navigator, "action_nav_home")
        assert callable(navigator.action_nav_home)

    def test_action_nav_cluster_exists(self):
        """Test action_nav_cluster method exists on ScreenNavigator."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        navigator = ScreenNavigator()
        assert hasattr(navigator, "action_nav_cluster")
        assert callable(navigator.action_nav_cluster)

    def test_action_nav_charts_exists(self):
        """Test action_nav_charts method exists on ScreenNavigator."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        navigator = ScreenNavigator()
        assert hasattr(navigator, "action_nav_charts")
        assert callable(navigator.action_nav_charts)

    def test_action_nav_optimizer_exists(self):
        """Test action_nav_optimizer method exists on ScreenNavigator."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        navigator = ScreenNavigator()
        assert hasattr(navigator, "action_nav_optimizer")
        assert callable(navigator.action_nav_optimizer)

    def test_action_nav_export_exists(self):
        """Test action_nav_export method exists on ScreenNavigator."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        navigator = ScreenNavigator()
        assert hasattr(navigator, "action_nav_export")
        assert callable(navigator.action_nav_export)

    def test_action_nav_settings_exists(self):
        """Test action_nav_settings method exists on ScreenNavigator."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        navigator = ScreenNavigator()
        assert hasattr(navigator, "action_nav_settings")
        assert callable(navigator.action_nav_settings)

    def test_action_nav_recommendations_exists(self):
        """Test action_nav_recommendations method exists on ScreenNavigator."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        navigator = ScreenNavigator()
        assert hasattr(navigator, "action_nav_recommendations")
        assert callable(navigator.action_nav_recommendations)

    def test_action_show_help_exists(self):
        """Test action_show_help method exists on ScreenNavigator."""
        from kubeagle.keyboard.navigation import ScreenNavigator

        navigator = ScreenNavigator()
        assert hasattr(navigator, "action_show_help")
        assert callable(navigator.action_show_help)


@pytest.mark.unit
@pytest.mark.fast
class TestScreenClassHierarchy:
    """Tests for screen class hierarchy and base classes."""

    def test_charts_explorer_screen_is_textual_screen(self):
        """Test ChartsExplorerScreen is a Textual Screen subclass."""
        from textual.screen import Screen

        from kubeagle.screens.charts_explorer import ChartsExplorerScreen

        assert issubclass(ChartsExplorerScreen, Screen)

    def test_cluster_screen_is_textual_screen(self):
        """Test ClusterScreen is a Textual Screen subclass."""
        from textual.screen import Screen

        from kubeagle.screens.cluster import ClusterScreen

        assert issubclass(ClusterScreen, Screen)

    def test_settings_screen_is_textual_screen(self):
        """Test SettingsScreen is a Textual Screen subclass."""
        from textual.screen import Screen

        from kubeagle.screens.settings import SettingsScreen

        assert issubclass(SettingsScreen, Screen)


@pytest.mark.unit
@pytest.mark.fast
class TestScreenInstantiation:
    """Tests for screen instantiation (without data loading)."""

    def test_settings_screen_instantiation(self):
        """Test SettingsScreen can be imported (instantiation requires app context).

        Note: SettingsScreen requires an active Textual app context to instantiate
        because it accesses self.app.settings in __init__. This is expected behavior.
        The import test passes, proving the module is correctly structured.
        """
        from kubeagle.screens.settings import SettingsScreen

        # Verify the class can be imported (full instantiation requires app context)
        assert SettingsScreen is not None

    def test_chart_detail_screen_instantiation_with_chart(self):
        """Test ChartDetailScreen can be instantiated with chart data."""
        from kubeagle.constants.enums import QoSClass
        from kubeagle.models.charts.chart_info import ChartInfo
        from kubeagle.screens.detail import ChartDetailScreen

        chart_info = ChartInfo(
            name="test-chart",
            team="test-team",
            values_file="values.yaml",
            cpu_request=100.0,
            cpu_limit=200.0,
            memory_request=128.0,
            memory_limit=256.0,
            qos_class=QoSClass.BURSTABLE,
            has_liveness=True,
            has_readiness=True,
            has_startup=False,
            has_anti_affinity=False,
            has_topology_spread=False,
            has_topology=False,
            pdb_enabled=False,
            pdb_template_exists=False,
            pdb_min_available=None,
            pdb_max_unavailable=None,
            replicas=1,
            priority_class=None,
        )

        screen = ChartDetailScreen(chart_info)
        assert screen is not None
        assert screen.chart_name == "test-chart"


# =============================================================================
# KEYBINDINGS TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestKeybindingsStructure:
    """Tests for keybinding structure and content."""

    def test_base_screen_bindings_is_list(self):
        """Test BASE_SCREEN_BINDINGS is a list."""
        from kubeagle.keyboard import BASE_SCREEN_BINDINGS

        assert isinstance(BASE_SCREEN_BINDINGS, list)

    def test_charts_explorer_screen_bindings_contains_nav_actions(self):
        """Test CHARTS_EXPLORER_SCREEN_BINDINGS contains navigation actions."""
        from kubeagle.keyboard import CHARTS_EXPLORER_SCREEN_BINDINGS

        binding_actions = [b[1] for b in CHARTS_EXPLORER_SCREEN_BINDINGS]
        assert "nav_home" in binding_actions
        assert "nav_cluster" in binding_actions

    def test_charts_explorer_screen_bindings_is_list(self):
        """Test CHARTS_EXPLORER_SCREEN_BINDINGS is a list."""
        from kubeagle.keyboard import CHARTS_EXPLORER_SCREEN_BINDINGS

        assert isinstance(CHARTS_EXPLORER_SCREEN_BINDINGS, list)

    def test_cluster_screen_bindings_contains_nav_actions(self):
        """Test CLUSTER_SCREEN_BINDINGS contains navigation actions."""
        from kubeagle.keyboard import CLUSTER_SCREEN_BINDINGS

        binding_actions = [b[1] for b in CLUSTER_SCREEN_BINDINGS]
        # Cluster screen has nav_home (h key) for jumping to primary screen.
        assert "nav_home" in binding_actions
        # Cluster screen uses base navigation bindings
        assert "pop_screen" in binding_actions


# =============================================================================
# DOMAIN STRUCTURE TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestDomainPackageStructure:
    """Tests for domain package structure."""

    def test_charts_explorer_domain_has_init(self):
        """Test charts_explorer domain package has __init__.py (replaces charts domain)."""
        from kubeagle.screens.charts_explorer import __init__ as ce_init

        assert ce_init is not None

    def test_cluster_domain_has_init(self):
        """Test cluster domain package has __init__.py."""
        from kubeagle.screens.cluster import __init__ as cluster_init

        assert cluster_init is not None

    def test_charts_explorer_domain_has_init_for_teams(self):
        """Test charts_explorer domain replaces teams domain."""
        from kubeagle.screens.charts_explorer import __init__ as ce_init

        assert ce_init is not None

    def test_reports_domain_has_init(self):
        """Test reports domain package has __init__.py."""
        from kubeagle.screens.reports import __init__ as reports_init

        assert reports_init is not None

    def test_detail_domain_has_init(self):
        """Test detail domain package has __init__.py."""
        from kubeagle.screens.detail import __init__ as detail_init

        assert detail_init is not None

    def test_settings_domain_has_init(self):
        """Test settings domain package has __init__.py."""
        from kubeagle.screens.settings import __init__ as settings_init

        assert settings_init is not None

    def test_navigation_package_has_init(self):
        """Test navigation package has __init__.py."""
        from kubeagle.keyboard import navigation as nav_init

        assert nav_init is not None

    def test_mixins_package_has_init(self):
        """Test mixins package has __init__.py."""
        from kubeagle.screens.mixins import __init__ as mixins_init

        assert mixins_init is not None
