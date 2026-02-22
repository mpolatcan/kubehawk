"""Shared top-level navigation tabs for primary application screens."""

from __future__ import annotations

from contextlib import suppress

from kubeagle.widgets import CustomHorizontal, CustomTabs

MAIN_NAV_TAB_CLUSTER = "main-tab-cluster"
MAIN_NAV_TAB_CHARTS = "main-tab-charts"
MAIN_NAV_TAB_WORKLOADS = "main-tab-workloads"
MAIN_NAV_TAB_EXPORT = "main-tab-export"
MAIN_NAV_TAB_SETTINGS = "main-tab-settings"


class MainNavigationTabsMixin:
    """Mixin to compose and handle top-level app navigation tabs."""

    _syncing_primary_navigation_tab = False
    _primary_navigation_ready = False

    def compose_main_navigation_tabs(self, *, active_tab_id: str) -> CustomHorizontal:
        """Return the shared navigation tab row."""
        return CustomHorizontal(
            CustomTabs(
                id="primary-nav-tabs",
                tabs=[
                    {"id": MAIN_NAV_TAB_CLUSTER, "label": "Cluster"},
                    {"id": MAIN_NAV_TAB_CHARTS, "label": "Charts"},
                    {"id": MAIN_NAV_TAB_WORKLOADS, "label": "Workloads"},
                    {"id": MAIN_NAV_TAB_EXPORT, "label": "Export"},
                    {"id": MAIN_NAV_TAB_SETTINGS, "label": "Settings"},
                ],
                active=active_tab_id,
                on_change=self._on_primary_navigation_tab_changed,
            ),
            id="primary-nav-tabs-row",
        )

    def _set_primary_navigation_tab(self, tab_id: str) -> None:
        """Programmatically set active top-level tab without re-navigation."""
        with suppress(Exception):
            nav_tabs = self.query_one("#primary-nav-tabs", CustomTabs)  # type: ignore[unresolved-attribute]
            if nav_tabs.active != tab_id:
                self._syncing_primary_navigation_tab = True
                try:
                    nav_tabs.active = tab_id
                finally:
                    self._syncing_primary_navigation_tab = False

    def _enable_primary_navigation_tabs(self) -> None:
        """Allow user-triggered top navigation tab changes to navigate screens."""
        self._primary_navigation_ready = True

    def _on_primary_navigation_tab_changed(self, tab_id: str) -> None:
        """Navigate between primary screens when top-level tab changes."""
        if not tab_id:
            return
        if not self._primary_navigation_ready:
            return
        if self._syncing_primary_navigation_tab:
            return

        if tab_id == MAIN_NAV_TAB_CLUSTER:
            self.app.action_nav_cluster()  # type: ignore[unresolved-attribute]
            return
        if tab_id == MAIN_NAV_TAB_CHARTS:
            self.app.action_nav_charts()  # type: ignore[unresolved-attribute]
            return
        if tab_id == MAIN_NAV_TAB_WORKLOADS:
            self.app.action_nav_workloads()  # type: ignore[unresolved-attribute]
            return
        if tab_id == MAIN_NAV_TAB_EXPORT:
            self.app.action_nav_export()  # type: ignore[unresolved-attribute]
            return
        if tab_id == MAIN_NAV_TAB_SETTINGS:
            self.app.action_nav_settings()  # type: ignore[unresolved-attribute]


__all__ = [
    "MAIN_NAV_TAB_CHARTS",
    "MAIN_NAV_TAB_CLUSTER",
    "MAIN_NAV_TAB_EXPORT",
    "MAIN_NAV_TAB_SETTINGS",
    "MAIN_NAV_TAB_WORKLOADS",
    "MainNavigationTabsMixin",
]
