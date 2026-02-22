"""Tabbed view mixin for screens with TabbedContent."""

from __future__ import annotations

import logging

from kubeagle.widgets.tabs import CustomTabbedContent

logger = logging.getLogger(__name__)


class TabbedViewMixin:
    """Mixin providing tab management patterns for screens.

    This mixin provides:
    - Tab switching helpers
    - Current tab tracking
    - Tab change notification

    Usage:
        class MyScreen(TabbedViewMixin, BaseScreen):
            bindings = [...]

            def compose(self):
                with CustomTabbedContent(id="tabbed-content"):
                    with CustomTabPane("Tab 1", id="tab-1"):
                        ...
                    with CustomTabPane("Tab 2", id="tab-2"):
                        ...
    """

    # Instance attribute for tracking current tab
    _current_tab: str = "all"

    # =========================================================================
    # TAB MANAGEMENT
    # =========================================================================

    def switch_tab(self, tab_id: str) -> None:
        """Switch to the specified tab.

        Args:
            tab_id: The ID of the tab to switch to.
        """
        try:
            # Mixin requires DOMNode subclass which provides query_one
            tabbed_content: CustomTabbedContent = self.query_one(  # type: ignore[unresolved-attribute]
                "#tabbed-content", CustomTabbedContent
            )
            tabbed_content.active = tab_id
            self._current_tab = tab_id
        except Exception:
            pass

    def action_switch_tab_1(self) -> None:
        """Switch to tab 1."""
        self.switch_tab("tab-1")

    def action_switch_tab_2(self) -> None:
        """Switch to tab 2."""
        self.switch_tab("tab-2")

    def action_switch_tab_3(self) -> None:
        """Switch to tab 3."""
        self.switch_tab("tab-3")

    def action_switch_tab_4(self) -> None:
        """Switch to tab 4."""
        self.switch_tab("tab-4")

    def action_switch_tab_5(self) -> None:
        """Switch to tab 5."""
        self.switch_tab("tab-5")


__all__ = ["TabbedViewMixin"]
