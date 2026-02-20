"""Report Export screen for generating and exporting reports."""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from rich.markup import escape
from textual.events import Resize
from textual.message import Message
from textual.reactive import reactive
from textual.screen import Screen
from textual.timer import Timer
from textual.worker import get_current_worker

from kubeagle.controllers import ChartsController, ClusterController
from kubeagle.keyboard import REPORT_EXPORT_SCREEN_BINDINGS
from kubeagle.keyboard.navigation import ScreenNavigator
from kubeagle.models.optimization import (
    UnifiedOptimizerController,
)
from kubeagle.screens.mixins.main_navigation_tabs_mixin import (
    MAIN_NAV_TAB_EXPORT,
    MainNavigationTabsMixin,
)
from kubeagle.screens.mixins.worker_mixin import (
    WorkerMixin,
)
from kubeagle.screens.reports.config import (
    DEFAULT_FILENAME,
    DEFAULT_REPORT_FORMAT,
    DEFAULT_REPORT_TYPE,
    PREVIEW_CHAR_LIMIT,
    REPORT_EXPORT_MEDIUM_MIN_WIDTH,
    REPORT_EXPORT_SHORT_MIN_HEIGHT,
    REPORT_EXPORT_WIDE_MIN_WIDTH,
    STATUS_CLEAR_DELAY,
)
from kubeagle.utils.report_generator import (
    ReportData,
    TUIReportGenerator,
    collect_report_data,
)
from kubeagle.widgets import (
    CustomButton,
    CustomConfirmDialog,
    CustomContainer,
    CustomFooter,
    CustomHeader,
    CustomHorizontal,
    CustomInput,
    CustomLoadingIndicator,
    CustomMarkdownViewer as TextualMarkdownViewer,
    CustomRadioSet,
    CustomStatic,
    CustomVertical,
)

if TYPE_CHECKING:
    from kubeagle.app import EKSHelmReporterApp

logger = logging.getLogger(__name__)

# Regex for invalid filename characters
_INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_REPORT_EXPORT_LAYOUT_CLASSES = ("wide", "medium", "narrow")
_REPORT_EXPORT_HEIGHT_CLASSES = ("normal-height", "short-height")


# ============================================================================
# Worker Messages for Cross-thread Communication
# ============================================================================


class ReportDataLoaded(Message):
    """Message indicating report data has been loaded."""

    def __init__(
        self,
        report_data: ReportData | None,
        duration_ms: float,
        partial: bool = False,
    ) -> None:
        super().__init__()
        self.report_data = report_data
        self.duration_ms = duration_ms
        self.partial = partial


class ReportDataLoadFailed(Message):
    """Message indicating report data loading failed."""

    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


class ReportExportScreen(MainNavigationTabsMixin, ScreenNavigator, WorkerMixin, Screen):
    """Screen for configuring and exporting reports."""

    BINDINGS = REPORT_EXPORT_SCREEN_BINDINGS
    CSS_PATH = "../../css/screens/report_export_screen.tcss"
    _RESIZE_DEBOUNCE_SECONDS = 0.08

    def __init__(self) -> None:
        Screen.__init__(self)
        ScreenNavigator.__init__(self, None)
        # Initialize WorkerMixin attributes (not calling WorkerMixin.__init__
        # to avoid double-init through MRO super() chain)
        self._load_start_time: float | None = None
        self._active_worker_name: str | None = None
        self._report_data: ReportData | None = None
        self._is_exporting: bool = False
        self._is_copying: bool = False
        self._layout_mode: str | None = None
        self._height_mode: str | None = None
        self._resize_debounce_timer: Timer | None = None
        self._partial_preview_rendered: bool = False
        self._partial_load_notice_shown: bool = False
        self._reload_on_resume: bool = False

    # Reactive state - use config.py constants for defaults
    report_format = reactive(DEFAULT_REPORT_FORMAT)
    report_type = reactive(DEFAULT_REPORT_TYPE)
    preview_content = reactive("")
    export_status = reactive("")

    def compose(self):
        """Compose the screen layout."""
        yield CustomHeader()
        yield self.compose_main_navigation_tabs(active_tab_id=MAIN_NAV_TAB_EXPORT)

        yield CustomContainer(
            # Left panel - Options
            CustomVertical(
                CustomStatic("Report Options", classes="section-title ui-section-title"),
                CustomVertical(
                    CustomStatic("Report Format", classes="optimizer-filter-group-title"),
                    CustomContainer(
                        CustomRadioSet(
                            "Full Report",
                            "Brief Report",
                            "Summary Only",
                            id="format-group",
                            compact=True,
                        ),
                        classes="optimizer-filter-group-body",
                    ),
                    classes="export-radio-group optimizer-filter-group",
                ),
                CustomVertical(
                    CustomStatic("Report Type", classes="optimizer-filter-group-title"),
                    CustomContainer(
                        CustomRadioSet(
                            "EKS Cluster",
                            "Helm Charts",
                            "Combined",
                            id="type-group",
                            compact=True,
                        ),
                        classes="optimizer-filter-group-body",
                    ),
                    classes="export-radio-group optimizer-filter-group",
                ),
                CustomStatic(
                    "Filename",
                    id="filename-label",
                    classes="section-subtitle ui-section-subtitle",
                ),
                CustomInput(placeholder=DEFAULT_FILENAME, id="filename-input"),
                CustomStatic("Output", id="output-path-title", classes="optimizer-filter-group-title"),
                CustomStatic("", id="output-path-label", classes="ui-panel-wrapper", markup=False),
                classes="options-panel ui-panel-wrapper",
            ),
            # Right panel - Preview
            CustomVertical(
                CustomStatic("Report Preview", classes="section-title ui-section-title"),
                CustomContainer(
                    TextualMarkdownViewer(
                        "",
                        id="preview-markdown",
                        classes="preview-content",
                        show_table_of_contents=False,
                    ),
                    CustomContainer(
                        CustomVertical(
                            CustomLoadingIndicator(id="loading-indicator"),
                            CustomStatic("Loading report data...", id="loading-message"),
                            CustomButton("Retry", id="retry-btn"),
                            id="loading-row",
                        ),
                        classes="ui-loading-overlay",
                        id="loading-overlay",
                    ),
                    id="preview-stack",
                ),
                classes="preview-panel ui-panel-wrapper",
            ),
            id="report-main-content",
        )

        # Bottom - Actions (buttons disabled until data loads)
        yield CustomVertical(
            CustomHorizontal(
                CustomStatic("", classes="actions-spacer"),
                CustomButton(
                    "Export",
                    id="btn-export",
                    disabled=True,
                ),
                CustomStatic("", classes="actions-button-gap"),
                CustomButton(
                    "Copy",
                    id="btn-copy",
                    disabled=True,
                ),
                CustomStatic("", classes="actions-spacer"),
                id="actions-buttons-row",
            ),
            CustomStatic("", id="export-status", classes="muted"),
            classes="actions-panel ui-actions-bar",
        )

        yield CustomFooter()

    async def on_mount(self) -> None:
        """Called when screen is mounted."""
        self.app.title = "KubEagle - Report Export"
        self._set_primary_navigation_tab(MAIN_NAV_TAB_EXPORT)
        self._enable_primary_navigation_tabs()
        self._update_responsive_layout()
        self._set_preview_mode()
        # Hide retry button initially
        retry_btn = self.query_one("#retry-btn", CustomButton)
        retry_btn.display = False
        self._sync_radio_groups_from_state()
        # Initialize output path label
        self._update_output_path_label()
        # Start the worker for background data loading
        self._start_load_worker()

    def on_resize(self, _: Resize) -> None:
        """Re-apply responsive breakpoint classes after terminal resize."""
        self._schedule_resize_update()

    def on_unmount(self) -> None:
        """Cancel all workers and timers when screen is removed from DOM."""
        self._release_background_work_for_navigation()
        with suppress(Exception):
            self.workers.cancel_all()

    def on_screen_suspend(self) -> None:
        """Pause transient updates and defer in-flight initial load when hidden."""
        self._release_background_work_for_navigation()

    def prepare_for_screen_switch(self) -> None:
        """Release background work before another screen becomes active."""
        self._release_background_work_for_navigation()

    def _release_background_work_for_navigation(self) -> None:
        """Stop hidden-screen timers/workers to keep navigation responsive."""
        if self._resize_debounce_timer is not None:
            self._resize_debounce_timer.stop()
            self._resize_debounce_timer = None
        if self.is_loading:
            # Keep export data load alive to avoid restart thrash during rapid
            # cross-screen navigation.
            self._reload_on_resume = False

    def on_screen_resume(self) -> None:
        """Resume deferred loading when returning to this screen."""
        self.app.title = "KubEagle - Report Export"
        self._set_primary_navigation_tab(MAIN_NAV_TAB_EXPORT)
        if self._reload_on_resume and not self.is_loading:
            self._reload_on_resume = False
            self._start_load_worker()

    def _schedule_resize_update(self) -> None:
        """Debounce relayout work to avoid excessive resize churn."""
        if self._resize_debounce_timer is not None:
            self._resize_debounce_timer.stop()
            self._resize_debounce_timer = None
        self._resize_debounce_timer = self.set_timer(
            self._RESIZE_DEBOUNCE_SECONDS,
            self._run_debounced_resize_update,
        )

    def _run_debounced_resize_update(self) -> None:
        self._resize_debounce_timer = None
        self._update_responsive_layout()

    def _get_layout_mode(self) -> str:
        """Return active responsive mode based on terminal width."""
        width = self.size.width
        if width >= REPORT_EXPORT_WIDE_MIN_WIDTH:
            return "wide"
        if width >= REPORT_EXPORT_MEDIUM_MIN_WIDTH:
            return "medium"
        return "narrow"

    def _update_responsive_layout(self) -> None:
        """Apply responsive classes on root and main content containers."""
        mode = self._get_layout_mode()
        height_mode = (
            "short-height"
            if self.size.height < REPORT_EXPORT_SHORT_MIN_HEIGHT
            else "normal-height"
        )
        if mode == self._layout_mode and height_mode == self._height_mode:
            return

        previous_layout = self._layout_mode
        previous_height = self._height_mode
        self._layout_mode = mode
        self._height_mode = height_mode

        if previous_layout is not None:
            self.remove_class(previous_layout)
        else:
            self.remove_class(*_REPORT_EXPORT_LAYOUT_CLASSES)
        self.add_class(mode)

        if previous_height is not None:
            self.remove_class(previous_height)
        else:
            self.remove_class(*_REPORT_EXPORT_HEIGHT_CLASSES)
        self.add_class(height_mode)

        try:
            main_content = self.query_one("#report-main-content", CustomContainer)
            for class_name in _REPORT_EXPORT_LAYOUT_CLASSES:
                main_content.remove_class(class_name)
            main_content.add_class(mode)
        except Exception:
            pass

    def _start_load_worker(self) -> None:
        """Start the worker for background report data loading."""
        self.is_loading = True
        self._report_data = None
        self._partial_preview_rendered = False
        self._partial_load_notice_shown = False
        self._set_export_buttons_enabled(False)
        self._clear_export_status()
        self._set_preview_mode()
        self.show_loading_overlay("Loading report data...")
        self.start_worker(self._load_data_worker, name="report-data", exclusive=True)

    async def _load_data_worker(self) -> None:
        """Worker function that loads report data in background.

        This runs in a separate thread to keep the UI responsive.
        """
        start_time = time.time()
        worker = get_current_worker()

        try:
            app = cast("EKSHelmReporterApp", self.app)
            raw_charts_path = app.settings.charts_path
            charts_path: Path | None = (
                Path(raw_charts_path) if raw_charts_path else None
            )
            cluster_context = getattr(self, "context", None) or getattr(
                app, "context", None
            )

            # Update loading state
            self.call_later(self._update_loading_message, "Initializing controllers...")

            # Initialize controllers
            cluster_ctrl: ClusterController | None = None
            charts_ctrl: ChartsController | None = None
            analysis_source = (
                str(getattr(app.settings, "optimizer_analysis_source", "auto")).strip()
                or "auto"
            )
            render_timeout_seconds = max(
                1,
                int(getattr(app.settings, "helm_template_timeout_seconds", 30)),
            )
            optimizer = UnifiedOptimizerController(
                analysis_source=analysis_source,
                render_timeout_seconds=render_timeout_seconds,
            )

            # Setup cluster controller
            try:
                cluster_ctrl = ClusterController(context=cluster_context)
            except Exception:
                cluster_ctrl = None

            # Check for cancellation
            if worker.is_cancelled:
                return

            # Setup charts controller
            if charts_path and charts_path.exists():
                self.call_later(self._update_loading_message, "Analyzing charts...")
                codeowners_path: Path | None = None
                if app.settings.codeowners_path:
                    codeowners_path = Path(app.settings.codeowners_path)
                elif Path(charts_path, "CODEOWNERS").exists():
                    codeowners_path = Path(charts_path, "CODEOWNERS")
                charts_ctrl = ChartsController(
                    charts_path, codeowners_path=codeowners_path
                )
            else:
                charts_ctrl = None

            # Check for cancellation
            if worker.is_cancelled:
                return

            def _post_partial_report(report_data: ReportData) -> None:
                if worker.is_cancelled or not self.is_attached:
                    return
                self.post_message(
                    ReportDataLoaded(
                        report_data=report_data,
                        duration_ms=(time.time() - start_time) * 1000,
                        partial=True,
                    )
                )

            # Collect all report data
            self.call_later(self._update_loading_message, "Collecting report data...")
            self._report_data = await collect_report_data(
                cluster_controller=cluster_ctrl,
                charts_controller=charts_ctrl,
                optimizer_controller=optimizer,
                charts_path=str(charts_path) if charts_path else None,
                context=cluster_context,
                on_partial=_post_partial_report,
            )

            # Check for cancellation
            if worker.is_cancelled:
                return

            # Calculate duration and post success
            duration_ms = (time.time() - start_time) * 1000

            self.post_message(
                ReportDataLoaded(
                    report_data=self._report_data,
                    duration_ms=duration_ms,
                    partial=False,
                )
            )

        except asyncio.CancelledError:
            # Refresh/teardown cancellation is expected; avoid flashing error UI.
            return
        except Exception as e:
            logger.exception("Failed to load report data")
            self.post_message(ReportDataLoadFailed(str(e)))

    def _update_loading_message(self, message: str) -> None:
        """Update loading message (called from worker thread)."""
        if not self.is_current:
            return
        try:
            loading_text = self.query_one("#loading-message", CustomStatic)
            loading_text.update(message)
        except Exception:
            pass

    def show_loading_overlay(
        self, message: str = "Loading...", *, is_error: bool = False
    ) -> None:
        """Show loading overlay."""
        try:
            overlay = self.query_one("#loading-overlay", CustomContainer)
            overlay.display = True
            overlay.add_class("visible")

            loading_row = self.query_one("#loading-row", CustomVertical)
            loading_text = self.query_one("#loading-message", CustomStatic)
            retry_btn = self.query_one("#retry-btn", CustomButton)

            loading_row.remove_class("error")
            loading_text.remove_class("error")
            loading_text.update(escape(message))
            retry_btn.display = False
            if is_error:
                loading_row.add_class("error")
                loading_text.add_class("error")
        except Exception:
            pass

    def hide_loading_overlay(self) -> None:
        """Hide loading overlay and reset error state."""
        try:
            overlay = self.query_one("#loading-overlay", CustomContainer)
            overlay.display = False
            overlay.remove_class("visible")
            loading_row = self.query_one("#loading-row", CustomVertical)
            loading_row.remove_class("error")
            retry_btn = self.query_one("#retry-btn", CustomButton)
            retry_btn.display = False
            loading_text = self.query_one("#loading-message", CustomStatic)
            loading_text.remove_class("error")
        except Exception:
            pass

    def _set_export_buttons_enabled(self, enabled: bool) -> None:
        """Enable or disable all export action buttons."""
        button_map = {
            str(button.id): button
            for button in self.query(CustomButton)
            if button.id in {"btn-export", "btn-copy"}
        }
        for btn_id in ("btn-export", "btn-copy"):
            btn = button_map.get(btn_id)
            if btn is not None:
                btn.disabled = not enabled

    async def on_report_data_loaded(self, event: ReportDataLoaded) -> None:
        """Handle successful report data load."""
        self._reload_on_resume = False
        self._report_data = event.report_data
        self.hide_loading_overlay()

        if event.partial:
            # Allow export/copy on partial data while background loading continues.
            self._set_export_buttons_enabled(True)
            self._clear_export_status()
            if not self._partial_load_notice_shown:
                self._partial_load_notice_shown = True
                self.notify(
                    "Partial data loaded. Loading remaining sections...",
                    severity="information",
                )
            # Render partial preview once to avoid repeated heavy regeneration churn.
            if not self._partial_preview_rendered:
                self._partial_preview_rendered = True
                await self._generate_preview(show_overlay=False)
        else:
            self._set_export_buttons_enabled(True)
            self._partial_load_notice_shown = False
            self._clear_export_status()
            self._partial_preview_rendered = False
            await self._generate_preview(show_overlay=True)

    def on_report_data_load_failed(self, event: ReportDataLoadFailed) -> None:
        """Handle failed report data load."""
        self._reload_on_resume = False
        self.hide_loading_overlay()
        self.show_error_state(event.error)
        self._set_export_buttons_enabled(False)
        self._update_export_status(f"Error loading data: {escape(event.error)}", is_error=True)
        self._report_data = None

    def show_error_state(self, message: str, retry: bool = True) -> None:
        """Show error state with retry button."""
        try:
            self.show_loading_overlay(f"Error loading data: {message}", is_error=True)
            retry_btn = self.query_one("#retry-btn", CustomButton)
            retry_btn.display = retry
        except Exception:
            pass

    async def _generate_preview(self, *, show_overlay: bool = True) -> None:
        """Generate the report preview asynchronously."""
        self._set_preview_mode()

        try:
            if not self._report_data:
                await self._render_preview_content(
                    "No data available. Check cluster connection and charts path."
                )
                return

            if show_overlay:
                self.show_loading_overlay("Generating preview...")

            # Run report generation in thread pool to avoid blocking UI
            data = cast(ReportData, self._report_data)
            report = await asyncio.to_thread(self.generate_report, data)
            self.preview_content = report
            await self._render_preview_content(self._build_preview_text(report))
        except Exception as e:
            await self._render_preview_content(f"Error: {escape(str(e))}")
        finally:
            if show_overlay:
                self.hide_loading_overlay()

    def _set_preview_mode(self) -> None:
        """Keep markdown preview visible for the fixed markdown export mode."""
        try:
            markdown_preview = self.query_one("#preview-markdown", TextualMarkdownViewer)
            markdown_preview.display = True
        except Exception:
            pass

    def _build_preview_text(self, report: str) -> str:
        """Build preview text with optional truncation notice."""
        if len(report) <= PREVIEW_CHAR_LIMIT:
            return report

        truncated = report[:PREVIEW_CHAR_LIMIT]
        return (
            f"{truncated}\n\n---\n"
            f"*Preview truncated. Full report: {len(report)} characters.*"
        )

    async def _render_preview_content(self, content: str) -> None:
        """Render preview content in markdown viewer or syntax view."""
        self._set_preview_mode()
        markdown_preview = self.query_one(
            "#preview-markdown", TextualMarkdownViewer
        )
        await markdown_preview.document.update(content)

    def generate_report(self, data: ReportData) -> str:
        """Generate the report content based on current settings.

        Args:
            data: The ReportData object containing all report data
        """
        if not data:
            return "# No data available for report generation"

        # Filter data based on report_type
        filtered_data = self._filter_report_data(data)

        # Generate report using TUIReportGenerator
        generator = TUIReportGenerator(filtered_data)

        return generator.generate_markdown_report(self.report_format)

    def _filter_report_data(self, data: ReportData) -> ReportData:
        """Filter report data based on report_type setting.

        Args:
            data: The original ReportData object

        Returns:
            Filtered ReportData based on report_type (eks, charts, or combined)
        """
        if self.report_type == "eks":
            # EKS only - return data with empty charts and violations
            return ReportData(
                nodes=data.nodes,
                event_summary=data.event_summary,
                pdbs=data.pdbs,
                single_replica_workloads=data.single_replica_workloads,
                charts=[],
                violations=[],
                cluster_name=data.cluster_name,
                context=data.context,
                timestamp=data.timestamp,
            )
        if self.report_type == "charts":
            # Charts only - return data with empty EKS data
            return ReportData(
                nodes=[],
                event_summary=None,
                pdbs=[],
                single_replica_workloads=[],
                charts=data.charts,
                violations=data.violations,
                cluster_name=data.cluster_name,
                context=data.context,
                timestamp=data.timestamp,
            )
        # Combined (default) - return all data
        return data

    def action_refresh(self) -> None:
        """Refresh report data."""
        self._start_load_worker()

    async def action_export_report(self) -> None:
        """Export the report to file (Ctrl+E handler)."""
        if self._is_exporting:
            return
        self._is_exporting = True
        self._set_loading_state("btn-export", True)
        await self._save_file_async()

    async def action_copy_clipboard(self) -> None:
        """Copy report to clipboard (Y handler)."""
        if self._is_copying:
            return
        self._is_copying = True
        self._set_loading_state("btn-copy", True)
        await self._export_to_clipboard()

    async def _export_to_clipboard(self) -> None:
        """Copy report to clipboard."""
        if self._report_data is None:
            self.notify("No report data loaded. Please wait for data to load or retry.", severity="error")
            self._update_export_status("Error: No data loaded", is_error=True)
            self._is_copying = False
            self._set_loading_state("btn-copy", False)
            return
        try:
            self._update_export_status("Copying to clipboard...")
            data = self._report_data
            # Run report generation in thread pool to avoid blocking UI
            report = await asyncio.to_thread(self.generate_report, data)
            # Try platform-appropriate clipboard command
            await asyncio.to_thread(self._copy_to_system_clipboard, report)
            self._update_export_status("Copied to clipboard!", is_success=True)
            self.notify("Report copied to clipboard", severity="information")
        except Exception as e:
            self._update_export_status(f"Error: {str(e)}", is_error=True)
            self.notify(f"Error copying to clipboard: {e}", severity="error")
        finally:
            # Clear loading states and re-enable buttons
            self._set_loading_state("btn-copy", False)
            self._is_copying = False

    def _copy_to_system_clipboard(self, report: str) -> None:
        """Copy text to system clipboard using platform-appropriate command."""
        system = platform.system()
        if system == "Darwin":
            self._run_pbcopy(report)
            return
        if system == "Windows":
            cmd = ["clip.exe"]
        else:
            # Linux - try xclip
            self._run_xclip(report)
            return
        try:
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
            process.communicate(input=report)
        except FileNotFoundError:
            tool = cmd[0]
            msg = f"Clipboard tool '{tool}' not found."
            if system == "Linux":
                msg += " Install xclip: sudo apt install xclip"
            raise RuntimeError(msg) from None

    def _run_pbcopy(self, report: str) -> None:
        """Run macOS clipboard copy command (backward-compatible helper)."""
        process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
        process.communicate(input=report)

    def _run_xclip(self, report: str) -> None:
        """Run Linux clipboard copy command (backward-compatible helper)."""
        process = subprocess.Popen(
            ["xclip", "-selection", "clipboard"],
            stdin=subprocess.PIPE,
            text=True,
        )
        process.communicate(input=report)

    @staticmethod
    def _normalize_radio_set_id(set_id: str | None) -> str | None:
        """Normalize wrapper inner IDs to outer CustomRadioSet IDs."""
        if not set_id:
            return None
        if set_id.endswith("-inner"):
            return set_id[: -len("-inner")]
        return set_id

    def _sync_radio_groups_from_state(self) -> None:
        """Sync radio groups from current reactive screen state."""
        format_index = {
            "full": 0,
            "brief": 1,
            "summary": 2,
        }.get(self.report_format, 0)
        type_index = {
            "eks": 0,
            "charts": 1,
            "combined": 2,
        }.get(self.report_type, 2)

        with suppress(Exception):
            self.query_one("#format-group", CustomRadioSet).pressed_index = format_index
        with suppress(Exception):
            self.query_one("#type-group", CustomRadioSet).pressed_index = type_index

    def _apply_radio_selection(self, set_id: str, pressed_index: int) -> None:
        """Apply report option changes based on radio group and selected index."""
        # Report Format group
        if set_id == "format-group":
            format_map = ("full", "brief", "summary")
            if 0 <= pressed_index < len(format_map):
                self.report_format = format_map[pressed_index]
            return

        # Report Type group
        if set_id == "type-group":
            type_map = ("eks", "charts", "combined")
            if 0 <= pressed_index < len(type_map):
                self.report_type = type_map[pressed_index]
            return

    async def on_radio_set_changed(self, event: object) -> None:
        """Handle radio set changes."""
        event_obj = cast(Any, event)
        radio_set = getattr(event_obj, "radio_set", None)
        raw_set_id = getattr(radio_set, "id", None)
        set_id = self._normalize_radio_set_id(raw_set_id)
        pressed_index = getattr(radio_set, "pressed_index", -1)
        if not set_id or pressed_index < 0:
            return

        self._apply_radio_selection(set_id, pressed_index)

        # Regenerate preview only if data is loaded
        if self._report_data:
            await self._generate_preview()

    def _update_export_status(
        self, message: str, *, is_error: bool = False, is_success: bool = False
    ) -> None:
        """Update the export status text with appropriate styling."""
        try:
            status_widget = self.query_one("#export-status", CustomStatic)
            status_widget.update(message)
            status_widget.remove_class("muted", "status-error", "status-success")
            if is_error:
                status_widget.add_class("status-error")
            elif is_success:
                status_widget.add_class("status-success")
            else:
                status_widget.add_class("muted")
            # Keep progress/error messages visible; auto-clear only success.
            if is_success and message:
                self.set_timer(STATUS_CLEAR_DELAY, self._clear_export_status)
        except Exception:
            pass

    def _clear_export_status(self) -> None:
        """Clear the export status message."""
        try:
            status_widget = self.query_one("#export-status", CustomStatic)
            status_widget.update("")
            status_widget.remove_class("status-error", "status-success")
            status_widget.add_class("muted")
        except Exception:
            pass

    def _validate_filename(self, filename: str) -> str | None:
        """Validate filename and return error message if invalid, None if valid."""
        if not filename or not filename.strip():
            return "Filename cannot be empty"
        if _INVALID_FILENAME_RE.search(Path(filename).name):
            return "Filename contains invalid characters"
        return None

    def _set_loading_state(self, button_id: str, is_loading: bool) -> None:
        """Set loading state for a button."""
        button = self.query_one(f"#{button_id}", CustomButton)

        if is_loading:
            button.add_class("btn-loading")
            button.disabled = True
        else:
            button.remove_class("btn-loading")
            button.disabled = False

    async def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-export" and not self._is_exporting:
            self._is_exporting = True
            self._set_loading_state("btn-export", True)
            await self._save_file_async()
        elif event.button.id == "btn-copy" and not self._is_copying:
            self._is_copying = True
            self._set_loading_state("btn-copy", True)
            await self._export_to_clipboard()
        elif event.button.id == "retry-btn":
            self.action_refresh()

    def _update_output_path_label(self) -> None:
        """Update the output path label to show the resolved file path."""
        try:
            filename_input = self.query_one("#filename-input", CustomInput)
            default_ext = ".md"
            default_filename = Path(DEFAULT_FILENAME).stem + default_ext
            filename = filename_input.value or default_filename
            resolved = Path(filename).resolve()
            label = self.query_one("#output-path-label", CustomStatic)
            full_path = str(resolved)
            max_len = 44
            if label.region.width > 0:
                # Account for horizontal padding and keep a minimum readable span.
                max_len = max(18, label.region.width - 2)
            display_path = self._truncate_middle(full_path, max_len=max_len)
            label.update(display_path)
            label.tooltip = full_path if display_path != full_path else None
        except Exception:
            pass

    @staticmethod
    def _truncate_middle(value: str, *, max_len: int) -> str:
        """Truncate long strings in the middle to keep both path ends visible."""
        if len(value) <= max_len:
            return value
        if max_len < 8:
            return value[:max_len]
        available = max_len - 1
        if "/" in value or "\\" in value:
            tail = max(8, int(available * 0.65))
            head = max(1, available - tail)
        else:
            head = available // 2
            tail = available - head
        return f"{value[:head]}…{value[-tail:]}"

    def on_custom_input_changed(self, event: CustomInput.Changed) -> None:
        """Update output path label live while typing in filename input."""
        self._handle_filename_input_update(event.input.id)

    def on_custom_input_submitted(self, event: CustomInput.Submitted) -> None:
        """Update output path label when filename input is submitted."""
        self._handle_filename_input_update(event.input.id)

    def _handle_filename_input_update(self, input_id: str | None) -> None:
        """Refresh resolved output path when the filename field changes."""
        if input_id == "filename-input":
            self._update_output_path_label()

    async def _save_file_async(self) -> None:
        """Save report to file (async implementation)."""
        if self._report_data is None:
            self.notify("No report data loaded. Please wait for data to load or retry.", severity="error")
            self._update_export_status("Error: No data loaded", is_error=True)
            self._is_exporting = False
            self._set_loading_state("btn-export", False)
            return

        filename_input = self.query_one("#filename-input", CustomInput)
        default_ext = ".md"
        default_filename = Path(DEFAULT_FILENAME).stem + default_ext
        filename = filename_input.value or default_filename

        # Validate filename
        validation_error = self._validate_filename(filename)
        if validation_error:
            self._update_export_status(f"Error: {validation_error}", is_error=True)
            self.notify(validation_error, severity="error")
            self._is_exporting = False
            self._set_loading_state("btn-export", False)
            return

        save_path = Path(filename).resolve()

        # Check for existing file and confirm overwrite via dialog
        if save_path.exists():
            def on_confirm(result: bool | None) -> None:
                if result:
                    self.call_later(self._do_export, save_path)
                else:
                    self._set_loading_state("btn-export", False)
                    self._is_exporting = False
                    self._update_export_status("Export cancelled")

            self.app.push_screen(
                CustomConfirmDialog(
                    message=f"File already exists:\n{save_path.name}\n\nOverwrite?",
                    title="Confirm Overwrite",
                ),
                on_confirm,
            )
            return

        await self._do_export(save_path)

    async def _do_export(self, save_path: Path) -> None:
        """Perform the actual file export after confirmation."""
        if self._report_data is None:
            self._update_export_status("Error: No data loaded", is_error=True)
            self._is_exporting = False
            self._set_loading_state("btn-export", False)
            return

        self._update_export_status("Exporting to file...")

        data = self._report_data
        # Generate report in thread pool to avoid blocking UI
        report = await asyncio.to_thread(self.generate_report, data)

        try:
            # Run file I/O in thread pool to avoid blocking UI
            await asyncio.to_thread(save_path.write_text, report)
            self._update_export_status(f"Saved to {save_path}", is_success=True)
            self.notify(f"Report saved to {save_path}", severity="information")
        except Exception as e:
            self._update_export_status(f"Error: {str(e)}", is_error=True)
            self.notify(f"Error saving file: {e}", severity="error")
        finally:
            self._set_loading_state("btn-export", False)
            self._is_exporting = False


__all__ = ["ReportExportScreen"]
