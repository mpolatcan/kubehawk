"""Impact Analysis Dialog — modal showing resource impact for filtered violations.

Opens from the "Impact Analysis" button in the violations action bar.
Receives pre-filtered violations and charts, computes impact in a background
worker, and displays the result in a ResourceImpactView.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.screen import ModalScreen

from kubeagle.screens.detail.components.resource_impact_view import (
    ResourceImpactView,
)
from kubeagle.widgets import (
    CustomButton,
    CustomContainer,
    CustomHorizontal,
    CustomStatic,
)

if TYPE_CHECKING:
    from kubeagle.models.analysis.violation import ViolationResult
    from kubeagle.models.charts.chart_info import ChartInfo
    from kubeagle.models.optimization import UnifiedOptimizerController

logger = logging.getLogger(__name__)


class ImpactAnalysisDialog(ModalScreen[None]):
    """Modal dialog that computes and displays resource impact analysis."""

    BINDINGS = [("escape", "cancel", "Close")]

    def __init__(
        self,
        *,
        charts: list[ChartInfo],
        violations: list[ViolationResult],
        optimizer_controller: UnifiedOptimizerController,
    ) -> None:
        super().__init__(classes="selection-modal-screen")
        self._charts = charts
        self._violations = violations
        self._optimizer_controller = optimizer_controller

    def compose(self) -> ComposeResult:
        with CustomContainer(
            classes="impact-analysis-dialog-shell selection-modal-shell",
        ):
            yield CustomStatic(
                "Impact Analysis",
                classes="selection-modal-title selection-modal-label",
                markup=False,
            )
            yield ResourceImpactView(id="impact-analysis-view")
            with CustomHorizontal(classes="selection-modal-actions"):
                yield CustomButton(
                    "Close",
                    id="impact-dialog-close-btn",
                    compact=True,
                )

    def on_mount(self) -> None:
        """Start background impact computation."""
        with contextlib.suppress(Exception):
            impact_view = self.query_one("#impact-analysis-view", ResourceImpactView)
            impact_view.set_loading(True, "Computing impact analysis...")
        self._compute_impact()

    def _compute_impact(self) -> None:
        """Run ResourceImpactCalculator in a background thread."""
        try:
            from kubeagle.optimizer.resource_impact_calculator import (
                ResourceImpactCalculator,
            )
        except Exception:
            logger.exception("Failed to import ResourceImpactCalculator")
            return

        calculator = ResourceImpactCalculator()
        charts = list(self._charts)
        violations = list(self._violations)
        controller = self._optimizer_controller

        def _do_compute() -> None:
            result = calculator.compute_impact(
                charts,
                violations,
                optimizer_controller=controller,
            )
            self.app.call_from_thread(
                self._apply_result, result, charts, violations, controller,
            )

        self.run_worker(_do_compute, thread=True, name="impact-dialog-compute", exclusive=True)

    def _apply_result(
        self,
        result: object,
        charts: list[object],
        violations: list[object],
        controller: object,
    ) -> None:
        """Apply the computed result to the impact view on the main thread."""
        with contextlib.suppress(Exception):
            impact_view = self.query_one("#impact-analysis-view", ResourceImpactView)
            impact_view.set_source_data(
                result,  # type: ignore[arg-type]
                charts=charts,  # type: ignore[arg-type]
                violations=violations,  # type: ignore[arg-type]
                optimizer_controller=controller,
            )

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        if event.button.id == "impact-dialog-close-btn":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
