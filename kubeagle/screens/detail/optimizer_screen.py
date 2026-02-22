"""Compatibility shim for the removed standalone Optimizer screen.

Optimizer functionality is now hosted inside ChartsExplorer:
- Violations view
- Embedded recommendations section
"""

from __future__ import annotations

from kubeagle.screens.charts_explorer import ChartsExplorerScreen
from kubeagle.screens.charts_explorer.config import (
    TAB_RECOMMENDATIONS,
    TAB_VIOLATIONS,
)
from kubeagle.screens.detail.presenter import (
    OptimizerDataLoaded,
    OptimizerDataLoadFailed,
)


class OptimizerScreen(ChartsExplorerScreen):
    """Backward-compatible alias that opens ChartsExplorer optimizer tabs."""

    def __init__(
        self,
        team_filter: str | None = None,
        testing: bool = False,
        initial_view: str = "violations",
        include_cluster: bool = True,
    ) -> None:
        self.team_filter = team_filter
        self._include_cluster = include_cluster
        normalized_view = (
            "recommendations" if initial_view == "recommendations" else "violations"
        )
        initial_tab = (
            TAB_RECOMMENDATIONS
            if normalized_view == "recommendations"
            else TAB_VIOLATIONS
        )
        super().__init__(
            initial_tab=initial_tab,
            team_filter=team_filter,
            include_cluster=include_cluster,
            testing=testing,
        )
        self._initial_view = normalized_view
        self._current_view = normalized_view

    def action_view_violations(self) -> None:
        self._current_view = "violations"
        self.action_show_violations_tab()

    def action_view_recommendations(self) -> None:
        self._current_view = "recommendations"
        self.action_show_recommendations_tab()

    def action_show_violations_tab(self) -> None:
        self._current_view = "violations"
        super().action_show_violations_tab()

    def action_show_recommendations_tab(self) -> None:
        self._current_view = "recommendations"
        super().action_show_violations_tab()


__all__ = [
    "OptimizerDataLoadFailed",
    "OptimizerDataLoaded",
    "OptimizerScreen",
]
