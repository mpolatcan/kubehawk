"""Settings screen for KubEagle TUI."""

from __future__ import annotations

from contextlib import suppress

from textual.app import ComposeResult
from textual.events import Resize
from textual.timer import Timer
from textual.widgets import TextArea
from textual.worker import Worker, WorkerState

from kubeagle.constants.screens.settings import (
    BUTTON_CANCEL,
    BUTTON_SAVE,
    SETTINGS_SECTION_AI_FIX,
    SETTINGS_SECTION_GENERAL,
    SETTINGS_SECTION_THRESHOLDS,
)
from kubeagle.constants.values import (
    PLACEHOLDER_AI_FIX_BULK_PARALLELISM,
    PLACEHOLDER_EXPORT_PATH,
    PLACEHOLDER_LIMIT_REQUEST,
    PLACEHOLDER_REFRESH_INTERVAL,
)
from kubeagle.keyboard import SETTINGS_SCREEN_BINDINGS
from kubeagle.models.state.config_manager import AppSettings, ConfigManager
from kubeagle.optimizer.full_ai_fixer import (
    get_default_full_fix_system_prompt_template,
    is_full_fix_prompt_template,
)
from kubeagle.screens.base_screen import BaseScreen
from kubeagle.screens.mixins.main_navigation_tabs_mixin import (
    MAIN_NAV_TAB_SETTINGS,
    MainNavigationTabsMixin,
)
from kubeagle.screens.settings.config import BUTTON_RESET
from kubeagle.screens.settings.presenter import SettingsPresenter
from kubeagle.widgets import (
    CustomButton,
    CustomConfirmDialog,
    CustomFooter,
    CustomHeader,
    CustomInput,
    CustomLoadingIndicator,
    CustomSelect as Select,
    CustomStatic,
    CustomSwitch,
    CustomTextArea,
    CustomVertical,
)
from kubeagle.widgets.containers import (
    CustomContainer,
    CustomHorizontal,
)

INPUT_TOOLTIPS: dict[str, str] = {
    "limit-request-input": (
        "Ratio of limits to requests to flag (e.g., 3.0 = limits 3x requests)."
    ),
    "optimizer-analysis-source-input": (
        "Optimizer analysis mode: auto (render with fallback), rendered, or values."
    ),
    "helm-template-timeout-input": (
        "Timeout in seconds for `helm template` verification."
    ),
    "ai-fix-llm-provider-select": (
        "Preferred LLM provider for AI full-fix generation."
    ),
    "ai-fix-codex-model-select": (
        "Model passed to Codex CLI when provider is Codex."
    ),
    "ai-fix-claude-model-select": (
        "Model passed to Claude Agent SDK when provider is Claude."
    ),
    "ai-fix-full-fix-prompt-input": (
        "Edit optimizer system prompt template used by AI fix. "
        "Use placeholders: {{VIOLATIONS}}, {{SEED_YAML}}, {{ALLOWED_FILES}}, "
        "{{RETRY_BLOCK}}, {{CANONICAL_GUIDANCE}}."
    ),
    "ai-fix-bulk-parallelism-input": (
        "Maximum number of chart bundles generated in parallel during AI bulk fix."
    ),
}

AI_FIX_PROVIDER_OPTIONS: list[tuple[str, str]] = [
    ("Codex", "codex"),
    ("Claude", "claude"),
]

OPTIMIZER_ANALYSIS_SOURCE_OPTIONS: list[tuple[str, str]] = [
    ("Auto (rendered fallback)", "auto"),
    ("Rendered", "rendered"),
    ("Values", "values"),
]

AI_FIX_CODEX_MODEL_OPTIONS: list[tuple[str, str]] = [
    ("Auto (CLI default)", "auto"),
    ("GPT-5.3 Codex", "gpt-5.3-codex"),
    ("GPT-5.3 Codex Spark", "gpt-5.3-codex-spark"),
    ("GPT-5.2 Codex", "gpt-5.2-codex"),
    ("GPT-5.2", "gpt-5.2"),
    ("GPT-5.1 Codex Max", "gpt-5.1-codex-max"),
    ("GPT-5 Codex", "gpt-5-codex"),
    ("GPT-5", "gpt-5"),
    ("o3", "o3"),
]

AI_FIX_CLAUDE_MODEL_OPTIONS: list[tuple[str, str]] = [
    ("Auto (SDK default)", "auto"),
    ("Default", "default"),
    ("Sonnet", "sonnet"),
    ("Opus", "opus"),
    ("Haiku", "haiku"),
]

AI_FIX_CODEX_MODEL_VALUES: set[str] = {value for _, value in AI_FIX_CODEX_MODEL_OPTIONS}
AI_FIX_CLAUDE_MODEL_VALUES: set[str] = {value for _, value in AI_FIX_CLAUDE_MODEL_OPTIONS}


class SettingsScreen(MainNavigationTabsMixin, BaseScreen):
    """Application settings and configuration."""

    BINDINGS = SETTINGS_SCREEN_BINDINGS
    CSS_PATH = "../../css/screens/settings_screen.tcss"
    _RESIZE_DEBOUNCE_SECONDS = 0.12
    _SHORTCUTS_FOCUS_DELAY_SECONDS = 0.12

    def __init__(self) -> None:
        super().__init__()
        self._settings: AppSettings = AppSettings()
        self._status_class = ""
        self._dirty = False
        self._presenter: SettingsPresenter | None = None
        self._resize_debounce_timer: Timer | None = None

    @property
    def screen_title(self) -> str:
        return "Settings"

    async def load_data(self) -> None:
        """Settings screen doesn't need async data loading."""
        pass

    def compose(self) -> ComposeResult:
        yield CustomHeader()
        yield self.compose_main_navigation_tabs(active_tab_id=MAIN_NAV_TAB_SETTINGS)
        yield CustomContainer(
            CustomContainer(
                CustomStatic(
                    "Settings",
                    classes="settings-title",
                    id="settings-title",
                ),
                CustomContainer(
                    # Left Column
                    CustomContainer(
                        CustomContainer(
                            CustomStatic(SETTINGS_SECTION_GENERAL, classes="section-header"),
                            CustomStatic("Refresh Interval (seconds)", classes="setting-label"),
                            CustomInput(
                                value=str(self._settings.refresh_interval),
                                placeholder=PLACEHOLDER_REFRESH_INTERVAL,
                                id="refresh-interval-input",
                                restrict=r"[0-9]+",
                            ),
                            CustomStatic("Auto-Refresh", classes="setting-label"),
                            CustomSwitch(
                                value=self._settings.auto_refresh,
                                id="auto-refresh-switch",
                            ),
                            CustomStatic("Report Output Path", classes="setting-label"),
                            CustomInput(
                                value=self._settings.export_path,
                                placeholder=PLACEHOLDER_EXPORT_PATH,
                                id="export-path-input",
                            ),
                            CustomStatic(
                                "Optimizer Analysis Source (auto/rendered/values)",
                                classes="setting-label",
                            ),
                            Select(
                                OPTIMIZER_ANALYSIS_SOURCE_OPTIONS,
                                value=(
                                    str(self._settings.optimizer_analysis_source or "auto").strip().lower()
                                    if str(self._settings.optimizer_analysis_source or "auto").strip().lower()
                                    in {"auto", "rendered", "values"}
                                    else "auto"
                                ),
                                allow_blank=False,
                                id="optimizer-analysis-source-input",
                            ),
                            CustomStatic(
                                "Helm Template Timeout (seconds)",
                                classes="setting-label",
                            ),
                            CustomInput(
                                value=str(self._settings.helm_template_timeout_seconds),
                                placeholder="30",
                                id="helm-template-timeout-input",
                                restrict=r"[0-9]+",
                            ),
                            classes="section-group",
                            id="general-settings-section",
                        ),
                        classes="section-column",
                        id="settings-left-column",
                    ),
                    # Right Column
                    CustomContainer(
                        CustomContainer(
                            CustomStatic(SETTINGS_SECTION_THRESHOLDS, classes="section-header"),
                            CustomStatic(
                                "Limit/Request Ratio Threshold", classes="setting-label"
                            ),
                            CustomInput(
                                value=str(self._settings.limit_request_ratio_threshold),
                                placeholder=PLACEHOLDER_LIMIT_REQUEST,
                                id="limit-request-input",
                                restrict=r"[0-9.]+",
                            ),
                            CustomStatic(SETTINGS_SECTION_AI_FIX, classes="section-header"),
                            CustomContainer(
                                CustomStatic(
                                    "Model Provider",
                                    classes="setting-label",
                                ),
                                Select(
                                    AI_FIX_PROVIDER_OPTIONS,
                                    value=(
                                        str(self._settings.ai_fix_llm_provider or "codex").strip().lower()
                                        if str(self._settings.ai_fix_llm_provider or "codex").strip().lower()
                                        in {"codex", "claude"}
                                        else "codex"
                                    ),
                                    allow_blank=False,
                                    id="ai-fix-llm-provider-select",
                                ),
                                CustomStatic(
                                    "Codex Model",
                                    classes="setting-label",
                                ),
                                Select(
                                    AI_FIX_CODEX_MODEL_OPTIONS,
                                    value=(
                                        str(self._settings.ai_fix_codex_model or "auto").strip().lower()
                                        if str(self._settings.ai_fix_codex_model or "auto").strip().lower()
                                        in AI_FIX_CODEX_MODEL_VALUES
                                        else "auto"
                                    ),
                                    allow_blank=False,
                                    id="ai-fix-codex-model-select",
                                ),
                                CustomStatic(
                                    "Claude Model",
                                    classes="setting-label",
                                ),
                                Select(
                                    AI_FIX_CLAUDE_MODEL_OPTIONS,
                                    value=(
                                        str(self._settings.ai_fix_claude_model or "auto").strip().lower()
                                        if str(self._settings.ai_fix_claude_model or "auto").strip().lower()
                                        in AI_FIX_CLAUDE_MODEL_VALUES
                                        else "auto"
                                    ),
                                    allow_blank=False,
                                    id="ai-fix-claude-model-select",
                                ),
                                CustomStatic(
                                    "Bulk Fix Paralellism",
                                    classes="setting-label",
                                ),
                                CustomInput(
                                    value=str(self._settings.ai_fix_bulk_parallelism),
                                    placeholder=PLACEHOLDER_AI_FIX_BULK_PARALLELISM,
                                    id="ai-fix-bulk-parallelism-input",
                                    restrict=r"[0-9]+",
                                ),
                                CustomStatic(
                                    "Optimizer System Prompt",
                                    classes="setting-label",
                                ),
                                CustomTextArea(
                                    text=self._resolve_ai_fix_system_prompt_editor_text(
                                        self._settings.ai_fix_full_fix_system_prompt
                                    ),
                                    placeholder="Edit optimizer system prompt template...",
                                    id="ai-fix-full-fix-prompt-input",
                                    show_line_numbers=True,
                                ),
                                id="ai-fix-settings-body",
                            ),
                            classes="section-group",
                            id="threshold-settings-section",
                        ),
                        classes="section-column",
                        id="settings-right-column",
                    ),
                    id="settings-sections",
                ),
                id="settings-scroll",
            ),
            # Status and Actions
            CustomContainer(
                CustomVertical(
                    CustomLoadingIndicator(id="loading-indicator"),
                    CustomStatic("", id="status-message"),
                    id="status-row",
                ),
                CustomHorizontal(
                    CustomButton(BUTTON_SAVE, id="save-btn", variant="default"),
                    CustomButton(BUTTON_RESET, id="reset-btn", variant="warning"),
                    CustomButton(BUTTON_CANCEL, id="cancel-btn", variant="default"),
                    id="settings-actions",
                    classes="button-row",
                ),
                id="settings-actions-bar",
            ),
            id="settings-form",
        )

        yield CustomFooter()

    def on_mount(self) -> None:
        """Called when screen is mounted."""
        super().on_mount()
        self.app.title = "KubEagle - Settings"
        self._set_primary_navigation_tab(MAIN_NAV_TAB_SETTINGS)
        self._enable_primary_navigation_tabs()
        self._settings = getattr(self.app, "settings", AppSettings())
        self._presenter = SettingsPresenter(self)
        self._populate_form(self._settings)
        with suppress(Exception):
            self.query_one("#settings-title", CustomStatic).tooltip = (
                "Configure paths, refresh behavior, and alert thresholds."
            )
        self._apply_hover_tooltips()
        self.call_later(self._update_responsive_layout)
        self.set_timer(
            self._SHORTCUTS_FOCUS_DELAY_SECONDS,
            self._focus_shortcuts_anchor,
        )

    def on_resize(self, _: Resize) -> None:
        """Adjust Settings layout for narrow and wide terminal widths."""
        self._schedule_resize_update()

    def on_unmount(self) -> None:
        """Stop timers when screen is removed from DOM."""
        self._release_background_work_for_navigation()

    def on_screen_suspend(self) -> None:
        """Pause transient resize work while this screen is inactive."""
        self._release_background_work_for_navigation()

    def on_screen_resume(self) -> None:
        """Re-sync top navigation tab when returning to settings."""
        self.app.title = "KubEagle - Settings"
        self._set_primary_navigation_tab(MAIN_NAV_TAB_SETTINGS)
        self.call_later(self._update_responsive_layout)

    def prepare_for_screen_switch(self) -> None:
        """Release background work before another screen becomes active."""
        self._release_background_work_for_navigation()

    def _release_background_work_for_navigation(self) -> None:
        """Stop resize timers that are only useful while the screen is visible."""
        if self._resize_debounce_timer is not None:
            self._resize_debounce_timer.stop()
            self._resize_debounce_timer = None

    def _schedule_resize_update(self) -> None:
        """Debounce relayout work to avoid resize-event storms."""
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

    def _current_layout_size(self) -> tuple[int, int]:
        """Return the most reliable viewport dimensions for responsive breakpoints."""
        width = int(self.size.width)
        height = int(self.size.height)
        with suppress(Exception):
            width = max(width, int(self.app.size.width))
            height = max(height, int(self.app.size.height))
        return width, height

    def _update_responsive_layout(self) -> None:
        """Update section and action layouts based on terminal width."""
        width, height = self._current_layout_size()
        use_two_column_layout = width >= 90
        use_stacked_actions = width < 44
        use_compact_height = height < 30

        try:
            sections = self.query_one("#settings-sections", CustomContainer)
            sections.remove_class("-single-column", "-two-column")
            sections.add_class("-two-column" if use_two_column_layout else "-single-column")
        except Exception:
            pass

        try:
            actions = self.query_one("#settings-actions", CustomHorizontal)
            actions.remove_class("-stacked")
            if use_stacked_actions:
                actions.add_class("-stacked")
        except Exception:
            pass

        try:
            actions_bar = self.query_one("#settings-actions-bar", CustomContainer)
            actions_bar.set_class(use_compact_height, "-compact")
        except Exception:
            pass

        try:
            form = self.query_one("#settings-form", CustomContainer)
            form.set_class(use_compact_height, "-compact")
        except Exception:
            pass

    def _focus_shortcuts_anchor(self) -> None:
        """Keep initial focus off text inputs so nav shortcuts work immediately."""
        if not self.is_current:
            return
        with suppress(Exception):
            self.query_one("#save-btn", CustomButton).focus()

    def _resolve_ai_fix_system_prompt_editor_text(self, configured_prompt: str | None) -> str:
        """Resolve editable prompt text shown in Settings for legacy and template modes."""
        configured = str(configured_prompt or "").strip()
        default_template = get_default_full_fix_system_prompt_template()
        if not configured:
            return default_template
        if is_full_fix_prompt_template(configured):
            return configured
        return (
            "Additional system instructions (legacy override migrated):\n"
            f"{configured}\n\n"
            "Treat the additional instructions above as strict requirements.\n\n"
            f"{default_template}"
        ).strip()

    def _apply_hover_tooltips(self) -> None:
        """Attach help text as hover tooltips instead of inline descriptions."""
        for input_id, tooltip in INPUT_TOOLTIPS.items():
            with suppress(Exception):
                input_widget = self.query_one(f"#{input_id}", CustomInput)
                input_widget.tooltip = tooltip
                input_widget.input.tooltip = tooltip
                continue
            with suppress(Exception):
                select_widget = self.query_one(f"#{input_id}", Select)
                select_widget.tooltip = tooltip
                continue
            with suppress(Exception):
                text_area_widget = self.query_one(f"#{input_id}", CustomTextArea)
                text_area_widget.tooltip = tooltip
                text_area_widget.text_area.tooltip = tooltip

    def on_custom_input_changed(self, _: CustomInput.Changed) -> None:
        """Track dirty state when any input changes."""
        self._dirty = True

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Track dirty state when any text area changes."""
        self._dirty = True

    def on_select_changed(self, _: object) -> None:
        """Track dirty state when any select value changes."""
        self._dirty = True

    def on_switch_changed(self, _: object) -> None:
        """Track dirty state when any switch toggles."""
        self._dirty = True

    def _update_status(self, message: str, is_error: bool = False) -> None:
        """Update the status message displayed to the user."""
        self._status_class = "status-error" if is_error else "status-success"
        status_widget = self.query_one("#status-message", CustomStatic)
        if is_error and "\n" in message:
            lines = message.strip().split("\n")
            formatted = "\n".join(f"  - {line}" for line in lines if line.strip())
            status_widget.update(f"Validation errors:\n{formatted}")
        else:
            status_widget.update(message)
        status_widget.remove_class("status-success", "status-error")
        status_widget.add_class(self._status_class)

    def _clear_status(self) -> None:
        """Clear the status message."""
        self._status_class = ""
        status_widget = self.query_one("#status-message", CustomStatic)
        status_widget.update("")

    def _get_input_value(self, input_id: str) -> str:
        """Get the value from an input widget."""
        input_widget = self.query_one(f"#{input_id}", CustomInput)
        return input_widget.value

    def _get_int_value(self, input_id: str, default: int) -> int:
        """Get an integer value from an input widget."""
        value_str = self._get_input_value(input_id)
        try:
            return int(value_str)
        except ValueError:
            return default

    def _get_float_value(self, input_id: str, default: float) -> float:
        """Get a float value from an input widget."""
        value_str = self._get_input_value(input_id)
        try:
            return float(value_str)
        except ValueError:
            return default

    def _get_select_value(self, select_id: str, fallback: str) -> str:
        """Get selected value from a select widget."""
        try:
            select_widget = self.query_one(f"#{select_id}", Select)
            raw_value = getattr(select_widget, "value", fallback)
            value = str(raw_value or "").strip().lower()
            return value or fallback
        except Exception:
            return fallback

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        """Handle button press events."""
        button_id = event.button.id

        if button_id == "save-btn":
            self._save_settings()
        elif button_id == "cancel-btn":
            self._cancel()
        elif button_id == "reset-btn":
            self._reset_defaults()

    def action_save_settings(self) -> None:
        """Save settings (triggered by Ctrl+S)."""
        self._save_settings()

    def action_pop_screen(self) -> None:
        """Override escape to check for unsaved changes."""
        self._cancel()

    def action_nav_settings(self) -> None:
        """Navigate to Settings screen (stay here)."""
        pass  # Already on settings

    def action_reset_defaults(self) -> None:
        """Reset to defaults (triggered by Ctrl+R)."""
        self._reset_defaults()

    def action_cancel(self) -> None:
        """Cancel and return to previous screen (alias for action_pop_screen)."""
        self._cancel()

    def action_refresh(self) -> None:
        """Refresh settings (reload from file)."""
        if self._presenter is None:
            return
        self._presenter.load_settings()
        self._settings = self._presenter.settings
        self._clear_status()
        self._populate_form(self._settings)
        self._dirty = False
        self._update_status("Settings reloaded from file.")

    def _populate_form(self, settings: AppSettings) -> None:
        """Populate all form fields from the given settings."""
        self.query_one("#refresh-interval-input", CustomInput).value = str(
            settings.refresh_interval
        )
        self.query_one("#auto-refresh-switch", CustomSwitch).value = (
            settings.auto_refresh
        )
        self.query_one("#export-path-input", CustomInput).value = (
            settings.export_path
        )
        self.query_one("#limit-request-input", CustomInput).value = str(
            settings.limit_request_ratio_threshold
        )
        with suppress(Exception):
            select_widget = self.query_one("#optimizer-analysis-source-input", Select)
            analysis_source = str(settings.optimizer_analysis_source or "auto")
            normalized_analysis_source = analysis_source.strip().lower()
            select_widget.value = (
                normalized_analysis_source
                if normalized_analysis_source in {"auto", "rendered", "values"}
                else "auto"
            )
        self.query_one("#helm-template-timeout-input", CustomInput).value = str(
            settings.helm_template_timeout_seconds
        )
        with suppress(Exception):
            select_widget = self.query_one("#ai-fix-llm-provider-select", Select)
            provider = str(settings.ai_fix_llm_provider or "codex").strip().lower()
            select_widget.value = provider if provider in {"codex", "claude"} else "codex"
        with suppress(Exception):
            select_widget = self.query_one("#ai-fix-codex-model-select", Select)
            codex_model = str(settings.ai_fix_codex_model or "auto").strip().lower()
            select_widget.value = (
                codex_model
                if codex_model in AI_FIX_CODEX_MODEL_VALUES
                else "auto"
            )
        with suppress(Exception):
            select_widget = self.query_one("#ai-fix-claude-model-select", Select)
            claude_model = str(settings.ai_fix_claude_model or "auto").strip().lower()
            select_widget.value = (
                claude_model
                if claude_model in AI_FIX_CLAUDE_MODEL_VALUES
                else "auto"
            )
        with suppress(Exception):
            self.query_one("#ai-fix-bulk-parallelism-input", CustomInput).value = str(
                settings.ai_fix_bulk_parallelism
            )
        with suppress(Exception):
            self.query_one("#ai-fix-full-fix-prompt-input", CustomTextArea).text = str(
                self._resolve_ai_fix_system_prompt_editor_text(
                    settings.ai_fix_full_fix_system_prompt
                )
            )

    def _show_loading(self, show: bool) -> None:
        """Show or hide the loading indicator."""
        try:
            indicator = self.query_one(
                "#loading-indicator", CustomLoadingIndicator
            )
            if show:
                indicator.add_class("-visible")
            else:
                indicator.remove_class("-visible")
        except Exception:
            pass  # Widget not found yet

    def _collect_input_values(self) -> dict[str, str]:
        """Collect all input field values into a dict for the presenter."""
        return {
            "charts-path-input": self._settings.charts_path,
            "active-charts-input": self._settings.active_charts_path,
            "codeowners-input": self._settings.codeowners_path,
            "theme-input": str(self._settings.theme),
            "refresh-interval-input": self._get_input_value(
                "refresh-interval-input"
            ),
            "export-path-input": self._get_input_value("export-path-input"),
            "event-age-input": str(self._settings.event_age_hours),
            "limit-request-input": self._get_input_value("limit-request-input"),
            "optimizer-analysis-source-input": self._get_select_value(
                "optimizer-analysis-source-input",
                "auto",
            ),
            "helm-template-timeout-input": self._get_input_value(
                "helm-template-timeout-input"
            ),
            "ai-fix-llm-provider-select": self._get_select_value(
                "ai-fix-llm-provider-select",
                "codex",
            ),
            "ai-fix-codex-model-select": self._get_select_value(
                "ai-fix-codex-model-select",
                "auto",
            ),
            "ai-fix-claude-model-select": self._get_select_value(
                "ai-fix-claude-model-select",
                "auto",
            ),
            "ai-fix-bulk-parallelism-input": self._get_input_value(
                "ai-fix-bulk-parallelism-input"
            ),
            "ai-fix-full-fix-prompt-input": self.query_one(
                "#ai-fix-full-fix-prompt-input", CustomTextArea
            ).text,
        }

    def _collect_switch_values(self) -> dict[str, bool]:
        """Collect all switch field values into a dict for the presenter."""
        return {
            "auto-refresh-switch": self.query_one(
                "#auto-refresh-switch", CustomSwitch
            ).value,
        }

    def _save_settings(self) -> None:
        """Save the current settings via presenter (async via worker)."""
        if self._presenter is None:
            return
        self._show_loading(True)
        self._clear_status()

        input_values = self._collect_input_values()
        switch_values = self._collect_switch_values()
        presenter = self._presenter

        def _do_save() -> tuple[bool, str]:
            return presenter.validate_and_save(
                input_values, switch_values
            )

        self.run_worker(_do_save, thread=True, name="save-settings")

    def _scroll_to_first_error(self, error_message: str) -> None:
        """Scroll to the first input that has a validation error."""
        error_lower = error_message.lower()
        # Map error keywords to input IDs
        error_to_input = {
            "refresh interval": "refresh-interval-input",
            "limit/request": "limit-request-input",
            "optimizer analysis source": "optimizer-analysis-source-input",
            "helm template timeout": "helm-template-timeout-input",
            "ai fix provider": "ai-fix-llm-provider-select",
            "codex model": "ai-fix-codex-model-select",
            "claude model": "ai-fix-claude-model-select",
            "bulk parallelism": "ai-fix-bulk-parallelism-input",
            "ai fix system prompt": "ai-fix-full-fix-prompt-input",
            "optimizer system prompt": "ai-fix-full-fix-prompt-input",
        }
        for keyword, input_id in error_to_input.items():
            if keyword in error_lower:
                try:
                    widget = self.query_one(f"#{input_id}", CustomInput)
                    widget.scroll_visible()
                    widget.focus()
                except Exception:
                    with suppress(Exception):
                        select_widget = self.query_one(f"#{input_id}", Select)
                        select_widget.scroll_visible()
                        select_widget.focus()
                return

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker completion for save/reset operations."""
        if (
            event.worker.name == "save-settings"
            and event.state == WorkerState.SUCCESS
        ):
            self._show_loading(False)
            result = event.worker.result
            if (
                not isinstance(result, tuple)
                or len(result) != 2
                or not isinstance(result[0], bool)
                or not isinstance(result[1], str)
            ):
                self._update_status("Failed to save settings.", is_error=True)
                return

            success, message = result
            self._update_status(message, is_error=not success)
            if success:
                self._dirty = False
                if self._presenter is not None:
                    self._settings = self._presenter.settings
                    self.app.settings = self._presenter.settings
                    apply_optimizer_settings = getattr(
                        self.app, "apply_optimizer_settings", None
                    )
                    if callable(apply_optimizer_settings):
                        apply_optimizer_settings()
            else:
                self._scroll_to_first_error(message)
        elif (
            event.worker.name == "save-settings"
            and event.state == WorkerState.ERROR
        ):
            self._show_loading(False)
            self._update_status("Failed to save settings.", is_error=True)
        elif (
            event.worker.name == "reset-defaults"
            and event.state == WorkerState.SUCCESS
        ):
            self._show_loading(False)
            result = event.worker.result
            if not isinstance(result, AppSettings):
                self._update_status("Failed to reset settings.", is_error=True)
                return
            default_settings = result
            self._settings = default_settings
            self.app.settings = default_settings
            self._populate_form(default_settings)
            self._dirty = False
            self._update_status("Settings reset to defaults and saved.")
            apply_optimizer_settings = getattr(
                self.app, "apply_optimizer_settings", None
            )
            if callable(apply_optimizer_settings):
                apply_optimizer_settings()
        elif (
            event.worker.name == "reset-defaults"
            and event.state == WorkerState.ERROR
        ):
            self._show_loading(False)
            self._update_status("Failed to reset settings.", is_error=True)
        elif event.state == WorkerState.CANCELLED:
            # Prevent loading indicator from getting stuck on worker cancellation
            # (e.g., user navigates away while save is in progress)
            self._show_loading(False)

    def _reset_defaults(self) -> None:
        """Reset all settings to defaults."""

        def _handle_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._show_loading(True)
                self._clear_status()
                self.run_worker(
                    ConfigManager.reset, thread=True, name="reset-defaults"
                )

        self.app.push_screen(
            CustomConfirmDialog(
                message="Reset all settings to factory defaults?",
                title="Reset Defaults",
            ),
            _handle_confirm,
        )

    def _cancel(self) -> None:
        """Cancel and return to previous screen, with unsaved changes warning."""
        if self._dirty:

            def _handle_confirm_result(confirmed: bool | None) -> None:
                if confirmed:
                    self._dirty = False
                    self.app.pop_screen()

            self.app.push_screen(
                CustomConfirmDialog(
                    message="Discard unsaved changes?",
                    title="",
                ),
                _handle_confirm_result,
            )
        else:
            self.app.pop_screen()


__all__ = ["SettingsScreen"]
