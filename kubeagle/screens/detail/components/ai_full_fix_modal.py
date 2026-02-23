"""AI full-fix modal with YAML and unified diff editors."""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from rich.markup import escape
from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.color import Gradient
from textual.events import Resize
from textual.renderables.bar import Bar as RichBarRenderable
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import RichLog, TextArea
from textual.widgets._text_area import TREE_SITTER

from kubeagle.widgets import (
    CustomButton,
    CustomCollapsible,
    CustomContainer,
    CustomHorizontal,
    CustomLoadingIndicator,
    CustomProgressBar as ProgressBar,
    CustomStatic,
    CustomTree,
    CustomVertical,
)


class AIFullFixModalResult(TypedDict):
    """Dismiss payload for single AI full-fix modal."""

    action: str
    values_patch_text: str
    template_diff_text: str
    artifact_key: str
    execution_log_text: str


@dataclass(slots=True)
class ChartBundleEditorState:
    """Editor state for one chart in bulk AI modal."""

    chart_key: str
    chart_name: str
    violations: list[str] = field(default_factory=list)
    values_patch_text: str = "{}\n"
    template_diff_text: str = ""
    template_patches_json: str = "[]"
    raw_llm_output_text: str = ""
    artifact_key: str = ""
    execution_log_text: str = ""
    values_preview_text: str = "{}\n"
    template_preview_text: str = ""
    values_diff_text: str = ""
    status_text: str = "Pending generation."
    can_apply: bool = False
    is_processing: bool = False
    is_waiting: bool = False
    fix_started_at_monotonic: float | None = None
    last_fix_elapsed_seconds: float | None = None


@dataclass(slots=True)
class _TemplatePreviewSection:
    """One template file preview section in bundle editor."""

    file_path: str
    content: str
    language: str = "yaml"


def _preferred_text_area_theme(preferred: str | None) -> str:
    raw = str(preferred or "").strip().lower()
    if (
        raw in {"light", "kubeagle-light", "textual-light", "custom-light"}
        or "light" in raw
    ):
        return "github_light"
    return "monokai"


def _select_supported_language(
    editor: TextArea,
    *,
    requested: str,
    fallbacks: Iterable[str] = (),
) -> str | None:
    available_languages = {str(language).strip().lower() for language in editor.available_languages}
    aliases = {
        "yml": "yaml",
        "md": "markdown",
        "txt": "text",
        "plain": "text",
        "plaintext": "text",
        "patch": "diff",
    }
    for candidate in (requested, *fallbacks):
        normalized = str(candidate or "").strip().lower()
        if not normalized:
            continue
        mapped = aliases.get(normalized, normalized)
        if mapped in available_languages:
            return mapped
        if mapped == "diff" and "markdown" in available_languages:
            return "markdown"
        if mapped == "text" and "markdown" in available_languages:
            return "markdown"
    return None


def _apply_supported_theme(editor: TextArea, preferred_theme: str) -> None:
    available_themes = tuple(editor.available_themes)
    if not available_themes:
        return
    if preferred_theme in available_themes:
        editor.theme = preferred_theme
        return
    for fallback in ("vscode_dark", "monokai", "dracula", "github_light"):
        if fallback in available_themes:
            editor.theme = fallback
            return
    editor.theme = available_themes[0]


def _normalize_preview_language(language: str) -> str:
    normalized = str(language or "").strip().lower()
    aliases = {
        "yml": "yaml",
        "md": "markdown",
        "txt": "text",
        "plain": "text",
        "plaintext": "text",
        "patch": "diff",
    }
    return aliases.get(normalized, normalized or "text")


def _rich_theme_for_preview(theme: str) -> str:
    normalized = str(theme or "").strip().lower()
    if normalized in {"github_light", "css"}:
        return "default"
    if normalized in {"vscode_dark", "dracula", "monokai"}:
        return "monokai"
    return "default"


if TREE_SITTER:
    class _CodePreview(TextArea):
        """Read-only syntax preview with TextArea parsing when tree-sitter is present."""

        def __init__(
            self,
            text: str = "",
            *,
            language: str = "yaml",
            theme: str = "monokai",
            show_line_numbers: bool = True,
            id: str | None = None,
            classes: str = "",
        ) -> None:
            initial_text = str(text)
            initial_language = str(language or "text")
            initial_theme = str(theme or "monokai")
            super().__init__(
                initial_text,
                language=initial_language,
                theme=initial_theme,
                show_line_numbers=show_line_numbers,
                highlight_cursor_line=False,
                soft_wrap=False,
                read_only=True,
                id=id,
                classes=classes,
            )
            self.set_code(initial_text, language=initial_language, theme=initial_theme)

        def set_code(
            self,
            text: str,
            *,
            language: str | None = None,
            theme: str | None = None,
        ) -> None:
            current_language = str(self.language or "").strip() or "text"
            requested_language = str(language or current_language)
            selected_language = _select_supported_language(
                self,
                requested=requested_language,
                fallbacks=(current_language, "yaml", "markdown", "json", "toml", "text"),
            )
            if selected_language is not None:
                self.language = selected_language
            self.load_text(str(text))
            _apply_supported_theme(self, str(theme or self.theme or "monokai"))
else:
    class _CodePreview(RichLog):
        """Read-only syntax preview with Rich fallback when tree-sitter is unavailable."""

        _FALLBACK_LANGUAGES: tuple[str, ...] = (
            "yaml",
            "json",
            "toml",
            "markdown",
            "diff",
            "xml",
            "html",
            "text",
        )
        _FALLBACK_THEMES: tuple[str, ...] = (
            "vscode_dark",
            "monokai",
            "dracula",
            "github_light",
            "css",
        )

        def __init__(
            self,
            text: str = "",
            *,
            language: str = "yaml",
            theme: str = "monokai",
            show_line_numbers: bool = True,
            id: str | None = None,
            classes: str = "",
        ) -> None:
            super().__init__(
                id=id,
                classes=classes,
                highlight=False,
                markup=False,
                wrap=False,
            )
            self._text = ""
            self._language = _normalize_preview_language(language)
            self._theme = str(theme or "monokai")
            self._show_line_numbers = bool(show_line_numbers)
            self.set_code(text, language=self._language, theme=self._theme)

        @property
        def text(self) -> str:
            return self._text

        @property
        def language(self) -> str:
            return self._language

        @property
        def theme(self) -> str:
            return self._theme

        @property
        def available_languages(self) -> tuple[str, ...]:
            return self._FALLBACK_LANGUAGES

        @property
        def available_themes(self) -> tuple[str, ...]:
            return self._FALLBACK_THEMES

        def set_code(
            self,
            text: str,
            *,
            language: str | None = None,
            theme: str | None = None,
        ) -> None:
            self._text = str(text)
            if language is not None:
                self._language = _normalize_preview_language(language)
            if theme is not None:
                self._theme = str(theme)

            self.clear()
            syntax_theme = _rich_theme_for_preview(self._theme)
            syntax_language = self._language if self._language in self._FALLBACK_LANGUAGES else "text"
            self.write(
                Syntax(
                    self._text,
                    syntax_language,
                    theme=syntax_theme,
                    line_numbers=self._show_line_numbers,
                    word_wrap=False,
                ),
                scroll_end=False,
            )


_STATUS_HIGHLIGHT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(COMPLETED|OK|VERIFIED|APPLIED|SUCCESS)\b", re.IGNORECASE), "green"),
    (re.compile(r"\b(PENDING|IN\s+PROGRESS|UNRESOLVED|WIRING_ISSUE|UNVERIFIED|SKIPPED)\b", re.IGNORECASE), "yellow"),
    (re.compile(r"\b(FAILED|ERROR|TIMED\s+OUT|TIMEOUT|BLOCKED)\b", re.IGNORECASE), "red"),
)
_SECONDS_TOKEN_PATTERN = re.compile(r"(\d+(?:\.\d+)?)s", re.IGNORECASE)
_BUNDLE_VERIFICATION_COUNTS_PATTERN = re.compile(
    (
        r"bundle verification:\s*(\d+)\s+verified,\s*(\d+)\s+"
        r"(?:wiring issue(?:s)?|unresolved),\s*(\d+)\s+unverified"
    ),
    re.IGNORECASE,
)


def _highlight_status_keywords(text: str) -> str:
    highlighted = escape(str(text or ""))
    for pattern, color in _STATUS_HIGHLIGHT_RULES:
        highlighted = pattern.sub(lambda match, tone=color: f"[{tone}]{match.group(0)}[/]", highlighted)
    return highlighted


def _format_status_text(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return "[dim]Waiting for status updates...[/]"

    formatted: list[str] = []
    for line in lines:
        key, has_separator, value = line.partition(":")
        if has_separator:
            key_clean = key.strip()
            value_clean = value.strip()
            normalized_key = key_clean.lower()
            if normalized_key == "timing":
                formatted.append(f"• [dim][bold]{escape(key_clean)}[/]: {escape(value_clean)}[/]")
            elif normalized_key == "hint":
                formatted.append(f"• [#ff9f0a][bold]{escape(key_clean)}[/]: {escape(value_clean)}[/#ff9f0a]")
            else:
                formatted.append(f"• [bold]{escape(key_clean)}[/]: {_highlight_status_keywords(value_clean)}")
            continue
        formatted.append(f"• {_highlight_status_keywords(line)}")
    return "\n".join(formatted).strip()


def _apply_gradient_left_to_right(text: Text, gradient: Gradient, width: int) -> None:
    """Apply gradient left-to-right across the progress bar width."""
    if not width:
        return
    max_width = width - 1
    if max_width <= 0:
        text.stylize(Style.from_color(gradient.get_color(0).rich_color))
        return

    text_length = len(text)
    for offset in range(text_length):
        text.stylize(
            Style.from_color(gradient.get_rich_color(offset / max_width)),
            offset,
            offset + 1,
        )


class _ForwardGradientBarRenderable(RichBarRenderable):
    """Bar renderable with forward gradient direction (left -> right)."""

    def __rich_console__(self, console: Any, options: Any) -> Any:
        highlight_style = console.get_style(self.highlight_style)
        background_style = console.get_style(self.background_style)

        width = self.width or options.max_width
        start, end = self.highlight_range

        start = max(start, 0)
        end = min(end, width)

        output_bar = Text("", end="")

        if start == end == 0 or end < 0 or start > end:
            output_bar.append(Text(self.BAR * width, style=background_style, end=""))
            yield output_bar
            return

        start = round(start * 2) / 2
        end = round(end * 2) / 2
        half_start = start - int(start) > 0
        half_end = end - int(end) > 0

        output_bar.append(
            Text(self.BAR * (int(start - 0.5)), style=background_style, end="")
        )
        if not half_start and start > 0:
            output_bar.append(Text(self.HALF_BAR_RIGHT, style=background_style, end=""))

        highlight_bar = Text("", end="")
        bar_width = int(end) - int(start)
        if half_start:
            highlight_bar.append(
                Text(
                    self.HALF_BAR_LEFT + self.BAR * (bar_width - 1),
                    style=highlight_style,
                    end="",
                )
            )
        else:
            highlight_bar.append(
                Text(self.BAR * bar_width, style=highlight_style, end="")
            )
        if half_end:
            highlight_bar.append(
                Text(self.HALF_BAR_RIGHT, style=highlight_style, end="")
            )

        if self.gradient is not None:
            _apply_gradient_left_to_right(highlight_bar, self.gradient, width)
        output_bar.append(highlight_bar)

        if not half_end and end - width != 0:
            output_bar.append(Text(self.HALF_BAR_LEFT, style=background_style, end=""))
        output_bar.append(
            Text(self.BAR * (int(width) - int(end) - 1), style=background_style, end="")
        )

        for range_name, (range_start, range_end) in self.clickable_ranges.items():
            output_bar.apply_meta(
                {"@click": f"range_clicked('{range_name}')"}, range_start, range_end
            )

        yield output_bar


class _ForwardGradientProgressBar(ProgressBar):
    """ProgressBar that uses left-to-right gradient mapping."""

    BAR_RENDERABLE = _ForwardGradientBarRenderable


class AIFullFixModal(ModalScreen[AIFullFixModalResult | None]):
    """Single-violation AI full-fix editor modal."""

    BINDINGS = [("escape", "cancel", "Close")]
    _DIALOG_MIN_WIDTH = 140
    _DIALOG_MAX_WIDTH = 190
    _DIALOG_MIN_HEIGHT = 32
    _DIALOG_MAX_HEIGHT = 48

    def __init__(
        self,
        *,
        title: str,
        subtitle: str,
        values_patch_text: str = "{}\n",
        template_diff_text: str = "",
        status_text: str = "Generating fix...",
        can_apply: bool = False,
        artifact_key: str = "",
        execution_log_text: str = "",
    ) -> None:
        super().__init__(classes="selection-modal-screen")
        self._title = title
        self._subtitle = subtitle
        self._values_patch_text = values_patch_text
        self._template_diff_text = template_diff_text
        self._status_text = status_text
        self._can_apply = can_apply
        self._artifact_key = artifact_key
        self._execution_log_text = execution_log_text

    def compose(self) -> ComposeResult:
        with CustomContainer(classes="ai-full-fix-modal-shell selection-modal-shell"):
            yield CustomStatic(self._title, classes="selection-modal-title", markup=False)
            yield CustomStatic(self._subtitle, classes="fix-details-modal-subtitle", markup=False)
            yield CustomStatic(
                _format_status_text(self._status_text),
                id="ai-full-fix-status",
                classes="selection-modal-summary ai-full-fix-status-block",
            )
            with CustomHorizontal(id="ai-full-fix-editors"):
                with CustomVertical(classes="ai-full-fix-editor-pane"):
                    yield CustomStatic("Values (YAML)", classes="apply-fixes-modal-panel-title ui-section-title", markup=False)
                    yield TextArea(
                        text=self._values_patch_text,
                        language="yaml",
                        theme="monokai",
                        show_line_numbers=True,
                        highlight_cursor_line=False,
                        id="ai-full-fix-values-editor",
                    )
                with CustomVertical(classes="ai-full-fix-editor-pane"):
                    yield CustomStatic("Template Diff (Unified Diff)", classes="apply-fixes-modal-panel-title ui-section-title", markup=False)
                    yield TextArea(
                        text=self._template_diff_text,
                        language="diff",
                        theme="monokai",
                        show_line_numbers=True,
                        highlight_cursor_line=False,
                        id="ai-full-fix-diff-editor",
                    )
            with CustomHorizontal(classes="ai-full-fix-actions"):
                yield CustomButton("Regenerate", id="ai-full-fix-regenerate", classes="selection-modal-action-btn")
                yield CustomButton("Apply", id="ai-full-fix-apply", variant="primary", classes="selection-modal-action-btn")
                yield CustomButton("Copy Values", id="ai-full-fix-copy-values", classes="selection-modal-action-btn")
                yield CustomButton("Copy Diff", id="ai-full-fix-copy-diff", classes="selection-modal-action-btn")
                yield CustomButton("Close", id="ai-full-fix-close", classes="selection-modal-action-btn")

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        self._sync_action_buttons_state()
        # Defer editor highlighting so the modal shell renders immediately.
        self.call_later(self._deferred_on_mount)

    def _deferred_on_mount(self) -> None:
        """Run editor highlighting after the modal shell is visible."""
        self._configure_editor_highlighting()
        with contextlib.suppress(Exception):
            self.query_one("#ai-full-fix-values-editor", TextArea).focus()

    def on_resize(self, _: Resize) -> None:
        self._apply_dynamic_layout()

    def on_unmount(self) -> None:
        timer = getattr(self, "_pulse_timer", None)
        if timer is not None:
            timer.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def set_status(self, text: str, *, can_apply: bool) -> None:
        """Update status line and apply button availability."""
        self._status_text = text
        self._can_apply = can_apply
        with contextlib.suppress(Exception):
            self.query_one("#ai-full-fix-status", CustomStatic).update(_format_status_text(text))
        self._sync_action_buttons_state()

    def set_values_patch_text(self, text: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#ai-full-fix-values-editor", TextArea).text = text

    def set_template_diff_text(self, text: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#ai-full-fix-diff-editor", TextArea).text = text

    def set_execution_context(
        self,
        *,
        artifact_key: str,
        execution_log_text: str,
    ) -> None:
        self._artifact_key = str(artifact_key or "")
        self._execution_log_text = str(execution_log_text or "")

    def _collect_payload(self, action: str) -> AIFullFixModalResult:
        values_text = ""
        diff_text = ""
        with contextlib.suppress(Exception):
            values_text = self.query_one("#ai-full-fix-values-editor", TextArea).text
        with contextlib.suppress(Exception):
            diff_text = self.query_one("#ai-full-fix-diff-editor", TextArea).text
        return {
            "action": action,
            "values_patch_text": values_text,
            "template_diff_text": diff_text,
            "artifact_key": self._artifact_key,
            "execution_log_text": self._execution_log_text,
        }

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "ai-full-fix-close":
            self.dismiss(None)
            return
        if button_id == "ai-full-fix-copy-values":
            payload = self._collect_payload("copy-values")
            text = payload["values_patch_text"]
            if not text.strip():
                self.notify("Values patch is empty", severity="warning")
                return
            self.app.copy_to_clipboard(text)
            self.notify("Values patch copied", severity="information")
            return
        if button_id == "ai-full-fix-copy-diff":
            payload = self._collect_payload("copy-diff")
            text = payload["template_diff_text"]
            if not text.strip():
                self.notify("Template diff is empty", severity="warning")
                return
            self.app.copy_to_clipboard(text)
            self.notify("Template diff copied", severity="information")
            return
        action_map = {
            "ai-full-fix-regenerate": "regenerate",
            "ai-full-fix-apply": "apply",
        }
        action = action_map.get(button_id)
        if action:
            self.dismiss(self._collect_payload(action))

    @classmethod
    def _is_processing_status(cls, status_text: str) -> bool:
        normalized = str(status_text or "").lower()
        if not normalized.strip():
            return False
        return any(
            token in normalized
            for token in (
                "generating",
                "generating fix",
                "preparing",
                "preparing deterministic fix seed",
                "trying direct-edit mode",
                "direct-edit:",
                "trying json contract mode",
                "running codex (attempt",
                "running claude (attempt",
                "render verification in progress",
                "verifying fix",
                "finalizing response",
            )
        )

    def _actions_locked(self) -> bool:
        return self._is_processing_status(self._status_text)

    def _sync_action_buttons_state(self) -> None:
        locked = self._actions_locked()
        for button_id in (
            "#ai-full-fix-regenerate",
            "#ai-full-fix-copy-values",
            "#ai-full-fix-copy-diff",
        ):
            with contextlib.suppress(Exception):
                self.query_one(button_id, CustomButton).disabled = locked
        with contextlib.suppress(Exception):
            self.query_one("#ai-full-fix-apply", CustomButton).disabled = locked or not self._can_apply

    def _apply_dynamic_layout(self) -> None:
        available_width = max(
            self._DIALOG_MIN_WIDTH,
            getattr(self.app.size, "width", self._DIALOG_MAX_WIDTH) - 4,
        )
        dialog_width = min(self._DIALOG_MAX_WIDTH, available_width)
        available_height = max(
            self._DIALOG_MIN_HEIGHT,
            getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT) - 2,
        )
        dialog_height = min(self._DIALOG_MAX_HEIGHT, available_height)
        with contextlib.suppress(Exception):
            shell = self.query_one(".ai-full-fix-modal-shell", CustomContainer)
            shell.styles.width = str(dialog_width)
            shell.styles.min_width = str(dialog_width)
            shell.styles.max_width = str(dialog_width)
            shell.styles.height = str(dialog_height)
            shell.styles.min_height = str(dialog_height)
            shell.styles.max_height = str(dialog_height)

    def _configure_editor_highlighting(self) -> None:
        settings_theme = getattr(getattr(self.app, "settings", None), "theme", "dark")
        editor_theme = _preferred_text_area_theme(str(settings_theme))
        editor_specs = (
            ("#ai-full-fix-values-editor", "yaml"),
            ("#ai-full-fix-diff-editor", "diff"),
        )
        for editor_id, requested_language in editor_specs:
            with contextlib.suppress(Exception):
                editor = self.query_one(editor_id, TextArea)
                language = _select_supported_language(
                    editor,
                    requested=requested_language,
                    fallbacks=("yaml", "markdown"),
                )
                editor.language = language
                _apply_supported_theme(editor, editor_theme)


class AIFullFixBulkModalResult(TypedDict):
    """Dismiss payload for bulk chart-bundled AI full-fix modal."""

    action: str
    bundles: dict[str, dict[str, str]]
    selected_chart_key: str


class AIFullFixBulkModal(ModalScreen[AIFullFixBulkModalResult | None]):
    """Bulk AI full-fix editor modal with one bundle per chart."""

    BINDINGS = [("escape", "cancel", "Close")]
    _DEFAULT_LOADING_LABEL = "Generating fix..."
    _DIALOG_MIN_WIDTH = 150
    _DIALOG_MAX_WIDTH = 196
    _DIALOG_MIN_HEIGHT = 34
    _DIALOG_MAX_HEIGHT = 49
    _TEMPLATE_EDITOR_ID_PREFIX = "ai-full-fix-bulk-template-file-editor-"
    _PULSE_FRAMES: tuple[str, ...] = ("◐", "◓", "◑", "◒")
    _BULK_PROGRESS_GRADIENT = Gradient(
        (0.0, "rgb(255,0,0)"),
        (0.5, "rgb(255,255,0)"),
        (1.0, "rgb(0,255,0)"),
        quality=120,
    )

    def __init__(
        self,
        *,
        title: str,
        bundles: list[ChartBundleEditorState],
    ) -> None:
        super().__init__(classes="selection-modal-screen")
        self._title = title
        self._bundles: dict[str, ChartBundleEditorState] = {
            bundle.chart_key: bundle for bundle in bundles
        }
        self._order: list[str] = [bundle.chart_key for bundle in bundles]
        self._selected_chart_key: str = self._order[0] if self._order else ""
        self._active_loading_jobs: int = 0
        self._manual_action_lock: bool = False
        self._inline_action_handler: Callable[[AIFullFixBulkModalResult], Awaitable[None]] | None = None
        self._inline_action_task: asyncio.Task[None] | None = None
        self._pulse_index: int = 0
        self._pulse_timer: Timer | None = None
        self._bulk_fix_started_at_monotonic: float | None = None
        self._bulk_last_elapsed_seconds: float | None = None
        self._ui_update_seq: int = 0
        started_at = time.monotonic()
        for bundle in self._bundles.values():
            if bundle.is_processing:
                bundle.is_waiting = False
                if bundle.fix_started_at_monotonic is None:
                    bundle.fix_started_at_monotonic = started_at
            started = bundle.fix_started_at_monotonic
            if started is not None:
                self._record_bulk_fix_started(started)

    def compose(self) -> ComposeResult:
        with CustomContainer(classes="ai-full-fix-bulk-modal-shell selection-modal-shell"):
            yield CustomStatic(self._title, classes="selection-modal-title", markup=False)
            with CustomHorizontal(id="ai-full-fix-bulk-progress-row"):
                yield CustomStatic(
                    "Completed 0/0 charts",
                    id="ai-full-fix-bulk-progress-counter",
                    markup=False,
                )
                yield _ForwardGradientProgressBar(
                    total=max(1, len(self._bundles)),
                    show_eta=False,
                    show_percentage=False,
                    gradient=self._BULK_PROGRESS_GRADIENT,
                    id="ai-full-fix-bulk-progress-bar",
                )
                yield CustomStatic(
                    "Elapsed 0.0s",
                    id="ai-full-fix-bulk-progress-elapsed",
                    markup=False,
                )
            with CustomHorizontal(id="ai-full-fix-bulk-content"):
                with CustomVertical(id="ai-full-fix-bulk-chart-list-pane"):
                    yield CustomStatic("Charts", classes="apply-fixes-modal-panel-title ui-section-title", markup=False)
                    yield CustomTree("Charts", id="ai-full-fix-bulk-violations-tree")
                with CustomVertical(id="ai-full-fix-bulk-editor-pane"):
                    yield CustomStatic(
                        "",
                        id="ai-full-fix-bulk-chart-title",
                        classes="apply-fixes-modal-panel-title ui-section-title",
                        markup=False,
                    )
                    with CustomHorizontal(id="ai-full-fix-bulk-editors"):
                        with CustomVertical(id="ai-full-fix-bulk-values-pane", classes="ai-full-fix-editor-pane"):
                            yield CustomStatic("Updated Values (YAML)", classes="apply-fixes-modal-panel-title ui-section-title", markup=False)
                            with CustomContainer(id="ai-full-fix-bulk-values-wrap"):
                                yield TextArea(
                                    text="{}\n",
                                    language="yaml",
                                    theme="monokai",
                                    show_line_numbers=True,
                                    highlight_cursor_line=False,
                                    id="ai-full-fix-bulk-values-editor",
                                )
                                with CustomContainer(
                                    id="ai-full-fix-bulk-values-loading-overlay",
                                    classes="hidden",
                                ):
                                    yield CustomLoadingIndicator(id="ai-full-fix-bulk-values-loading-indicator")
                                    yield CustomStatic(
                                        "Generating fix...",
                                        id="ai-full-fix-bulk-values-loading-label",
                                        markup=False,
                                    )
                        with CustomVertical(id="ai-full-fix-bulk-diff-pane", classes="ai-full-fix-editor-pane"):
                            yield CustomStatic("Updated Templates", classes="apply-fixes-modal-panel-title ui-section-title", markup=False)
                            with CustomContainer(id="ai-full-fix-bulk-diff-wrap"):
                                yield CustomVertical(id="ai-full-fix-bulk-template-files-list")
                                with CustomContainer(
                                    id="ai-full-fix-bulk-diff-loading-overlay",
                                    classes="hidden",
                                ):
                                    yield CustomLoadingIndicator(id="ai-full-fix-bulk-diff-loading-indicator")
                                    yield CustomStatic(
                                        "Generating fix...",
                                        id="ai-full-fix-bulk-diff-loading-label",
                                        markup=False,
                                    )
            with CustomHorizontal(classes="ai-full-fix-actions"):
                yield CustomButton("Apply", id="ai-full-fix-bulk-apply", variant="primary", classes="selection-modal-action-btn")
                yield CustomButton("Regenerate Chart", id="ai-full-fix-bulk-regenerate", classes="selection-modal-action-btn")
                yield CustomButton("Show Diff", id="ai-full-fix-bulk-show-diff", classes="selection-modal-action-btn")
                yield CustomButton("LLM Output", id="ai-full-fix-bulk-raw-llm", classes="selection-modal-action-btn")
                yield CustomButton("Close", id="ai-full-fix-bulk-close", classes="selection-modal-action-btn")

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        self._sync_action_buttons_state()
        self._sync_loading_overlays()
        self._pulse_timer = self.set_interval(0.24, self._tick_pulse)
        # Defer heavy work so the modal shell renders immediately.
        self.call_later(self._deferred_on_mount)

    async def _deferred_on_mount(self) -> None:
        """Run expensive mount-time setup off the initial layout path."""
        tree_data = await asyncio.to_thread(self._compute_tree_data)
        self._apply_tree_data(tree_data)
        self._sync_bulk_progress()
        self._configure_editor_highlighting()
        await self._load_selected_bundle_into_editors()
        self._sync_action_buttons_state()
        self._sync_loading_overlays()
        with contextlib.suppress(Exception):
            self.query_one("#ai-full-fix-bulk-violations-tree", CustomTree).focus()

    def on_resize(self, _: Resize) -> None:
        self._apply_dynamic_layout()

    def on_unmount(self) -> None:
        if self._pulse_timer is not None:
            self._pulse_timer.stop()
            self._pulse_timer = None

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _compute_tree_data(
        self,
    ) -> tuple[str, list[tuple[str, str, str, bool, list[str]]]]:
        """Pre-compute all tree labels and data without touching widgets.

        Returns ``(root_label, nodes)`` where each node is
        ``(chart_key, label, color, is_selected, violations)``.
        This method is safe to call from a background thread.
        """
        total_violations = sum(len(b.violations) for b in self._bundles.values())
        viol_word = "violation" if total_violations == 1 else "violations"
        root_label = f"Charts ({total_violations} {viol_word})"

        nodes: list[tuple[str, str, str, bool, list[str]]] = []
        for chart_key in self._order:
            bundle = self._bundles[chart_key]
            count = len(bundle.violations)
            viol_word = "violation" if count == 1 else "violations"
            marker = self._chart_marker(bundle)
            elapsed_suffix = self._tree_elapsed_label(bundle)
            label = (
                f"{marker} {bundle.chart_name} ({count} {viol_word})"
                f"{elapsed_suffix}"
            )
            color = self._chart_row_color(bundle)
            is_selected = chart_key == self._selected_chart_key
            nodes.append((chart_key, label, color, is_selected, list(bundle.violations)))
        return root_label, nodes

    def _apply_tree_data(
        self,
        tree_data: tuple[str, list[tuple[str, str, str, bool, list[str]]]],
    ) -> None:
        """Apply pre-computed tree data to the widget (must run on main thread)."""
        root_label, nodes = tree_data
        with contextlib.suppress(Exception):
            tree = self.query_one("#ai-full-fix-bulk-violations-tree", CustomTree)
            tree.reset(root_label)
            tree.root.expand()
            for chart_key, label, color, is_selected, violations in nodes:
                chart_node = tree.root.add(Text(label, style=color))
                chart_node.data = {"chart_key": chart_key}
                if is_selected:
                    chart_node.expand()
                for violation in violations:
                    leaf = chart_node.add_leaf(violation)
                    leaf.data = {"chart_key": chart_key}
        self._sync_bulk_progress()

    def _populate_violations_tree(self) -> None:
        """Synchronous tree rebuild (used in on_mount and direct calls)."""
        tree_data = self._compute_tree_data()
        self._apply_tree_data(tree_data)

    def _bulk_progress_counts(self) -> tuple[int, int]:
        total = len(self._bundles)
        if total <= 0:
            return 0, 0
        completed = sum(
            1
            for bundle in self._bundles.values()
            if not bundle.is_processing
            and (bundle.can_apply or self._is_completed_status(bundle.status_text))
        )
        return completed, total

    def _sync_bulk_progress(self) -> None:
        completed, total = self._bulk_progress_counts()
        chart_label = "chart" if total == 1 else "charts"
        with contextlib.suppress(Exception):
            self.query_one("#ai-full-fix-bulk-progress-counter", CustomStatic).update(
                f"Completed {completed}/{total} {chart_label}"
            )
        with contextlib.suppress(Exception):
            self.query_one("#ai-full-fix-bulk-progress-bar", ProgressBar).update(
                total=max(1, total),
                progress=max(0, min(completed, total)),
            )
        with contextlib.suppress(Exception):
            self.query_one("#ai-full-fix-bulk-progress-elapsed", CustomStatic).update(
                self._bulk_elapsed_label()
            )

    def _bulk_total_elapsed_seconds(self) -> float:
        if self._bulk_fix_started_at_monotonic is None:
            return 0.0
        now = time.monotonic()
        has_live_processing = any(
            bundle.is_processing and bundle.fix_started_at_monotonic is not None
            for bundle in self._bundles.values()
        )
        if has_live_processing:
            elapsed = max(0.0, now - self._bulk_fix_started_at_monotonic)
            self._bulk_last_elapsed_seconds = elapsed
            return elapsed
        if self._bulk_last_elapsed_seconds is not None:
            return max(0.0, self._bulk_last_elapsed_seconds)
        elapsed = max(0.0, now - self._bulk_fix_started_at_monotonic)
        self._bulk_last_elapsed_seconds = elapsed
        return elapsed

    def _bulk_elapsed_label(self) -> str:
        if self._bulk_fix_started_at_monotonic is None:
            return "Waiting..."
        return f"Elapsed {self._bulk_total_elapsed_seconds():.1f}s"

    def _collect_current_editor_into_state(self) -> None:
        if not self._selected_chart_key:
            return
        bundle = self._bundles[self._selected_chart_key]
        with contextlib.suppress(Exception):
            edited_text = self.query_one(
                "#ai-full-fix-bulk-values-editor",
                TextArea,
            ).text
            bundle.values_preview_text = edited_text
            bundle.values_patch_text = edited_text
        rendered_template_preview = self._template_preview_text_from_rendered_sections()
        if rendered_template_preview.strip():
            bundle.template_preview_text = rendered_template_preview

    def _template_preview_text_from_rendered_sections(self) -> str:
        sections: list[str] = []
        with contextlib.suppress(Exception):
            for collapsible in self.query(".ai-full-fix-template-collapsible"):
                if not isinstance(collapsible, CustomCollapsible):
                    continue
                file_path = str(getattr(collapsible, "title", "")).strip()
                if not file_path:
                    continue
                content = ""
                with contextlib.suppress(Exception):
                    content = collapsible.query_one(TextArea).text
                section_body = content.rstrip()
                if section_body:
                    sections.append(f"# FILE: {file_path}\n{section_body}")
                else:
                    sections.append(f"# FILE: {file_path}")
        if not sections:
            return ""
        combined = "\n\n".join(sections).strip()
        return f"{combined}\n"

    async def _load_selected_bundle_into_editors(self) -> None:
        if not self._selected_chart_key:
            return
        bundle = self._bundles[self._selected_chart_key]
        with contextlib.suppress(Exception):
            self.query_one("#ai-full-fix-bulk-chart-title", CustomStatic).update(
                bundle.chart_name
            )
        with contextlib.suppress(Exception):
            editor = self.query_one(
                "#ai-full-fix-bulk-values-editor",
                TextArea,
            )
            editor.load_text(self._resolve_values_editor_text(bundle))
        await self._render_template_file_sections(self._resolve_template_preview_text(bundle))
        self._configure_editor_highlighting()
        self._sync_action_buttons_state()
        self._sync_loading_overlays()

    @staticmethod
    def _resolve_values_editor_text(bundle: ChartBundleEditorState) -> str:
        preview_text = str(bundle.values_preview_text or "")
        if preview_text.strip() and preview_text.strip() != "{}":
            return preview_text
        patch_text = str(bundle.values_patch_text or "")
        if patch_text.strip() and patch_text.strip() != "{}":
            return patch_text
        return preview_text or "{}\n"

    @staticmethod
    def _resolve_template_preview_text(bundle: ChartBundleEditorState) -> str:
        preview_text = str(bundle.template_preview_text or "")
        if preview_text.strip():
            return preview_text
        diff_text = str(bundle.template_diff_text or "")
        if diff_text.strip():
            return diff_text
        return ""

    def _serialize_bundles(self) -> dict[str, dict[str, str]]:
        payload: dict[str, dict[str, str]] = {}
        for chart_key, bundle in self._bundles.items():
            payload[chart_key] = {
                "chart_name": bundle.chart_name,
                "values_patch_text": bundle.values_patch_text,
                "template_diff_text": bundle.template_diff_text,
                "template_patches_json": bundle.template_patches_json,
                "raw_llm_output_text": bundle.raw_llm_output_text,
                "artifact_key": bundle.artifact_key,
                "execution_log_text": bundle.execution_log_text,
                "values_preview_text": bundle.values_preview_text,
                "template_preview_text": bundle.template_preview_text,
                "values_diff_text": bundle.values_diff_text,
                "status_text": bundle.status_text,
                "can_apply": "true" if bundle.can_apply else "false",
                "is_processing": "true" if bundle.is_processing else "false",
                "is_waiting": "true" if bundle.is_waiting else "false",
            }
        return payload

    def set_bundle_state(
        self,
        *,
        chart_key: str,
        values_patch_text: str,
        template_diff_text: str,
        template_patches_json: str | None = None,
        raw_llm_output_text: str | None = None,
        artifact_key: str | None = None,
        execution_log_text: str | None = None,
        values_preview_text: str,
        template_preview_text: str,
        values_diff_text: str,
        status_text: str,
        can_apply: bool,
    ) -> None:
        if chart_key not in self._bundles:
            return
        bundle = self._bundles[chart_key]
        was_processing = bool(bundle.is_processing)
        bundle.values_patch_text = values_patch_text
        bundle.template_diff_text = template_diff_text
        if template_patches_json is not None:
            bundle.template_patches_json = template_patches_json
        if raw_llm_output_text is not None:
            bundle.raw_llm_output_text = raw_llm_output_text
        if artifact_key is not None:
            bundle.artifact_key = artifact_key
        if execution_log_text is not None:
            bundle.execution_log_text = execution_log_text
        bundle.values_preview_text = values_preview_text
        bundle.template_preview_text = template_preview_text
        bundle.values_diff_text = values_diff_text
        bundle.status_text = status_text
        bundle.can_apply = bool(can_apply) or self._status_allows_verified_subset_apply(status_text)
        bundle.is_processing = self._is_processing_status(status_text) and not bool(bundle.can_apply)
        self._sync_bundle_elapsed_tracking(bundle, was_processing=was_processing)
        # Defer heavy UI updates so the caller (streaming LLM) is not blocked.
        load_editors = chart_key == self._selected_chart_key
        self.call_later(
            self._deferred_ui_update, load_editors=load_editors
        )

    def set_bundle_status(
        self,
        *,
        chart_key: str,
        status_text: str,
        can_apply: bool | None = None,
    ) -> None:
        """Update only status/can_apply for one chart bundle."""
        if chart_key not in self._bundles:
            return
        bundle = self._bundles[chart_key]
        was_processing = bool(bundle.is_processing)
        bundle.status_text = status_text
        if can_apply is not None:
            bundle.can_apply = bool(can_apply) or self._status_allows_verified_subset_apply(status_text)
        elif not bundle.can_apply:
            bundle.can_apply = self._status_allows_verified_subset_apply(status_text)
        bundle.is_processing = self._is_processing_status(status_text) and not bool(bundle.can_apply)
        if bundle.can_apply:
            bundle.is_processing = False
        self._sync_bundle_elapsed_tracking(bundle, was_processing=was_processing)
        # Defer heavy UI updates so the caller (streaming LLM) is not blocked.
        load_editors = chart_key == self._selected_chart_key
        self.call_later(
            self._deferred_ui_update, load_editors=load_editors, sync_buttons=True
        )

    async def _deferred_ui_update(
        self,
        *,
        load_editors: bool = False,
        sync_buttons: bool = False,
    ) -> None:
        """Deferred UI refresh: offloads tree computation to a thread, then applies on main thread."""
        self._ui_update_seq += 1
        seq = self._ui_update_seq
        tree_data = await asyncio.to_thread(self._compute_tree_data)
        if seq != self._ui_update_seq:
            return  # a newer update superseded this one
        self._apply_tree_data(tree_data)
        if load_editors:
            await self._load_selected_bundle_into_editors()
        if sync_buttons or not load_editors:
            self._sync_action_buttons_state()
            self._sync_loading_overlays()

    def begin_loading(self, *, message: str | None = None) -> None:
        """Show per-editor loading overlays while async generation is running."""
        self._set_loading_message(message or self._DEFAULT_LOADING_LABEL)
        self._active_loading_jobs += 1
        self._sync_loading_overlays()

    def end_loading(self) -> None:
        """Hide per-editor loading overlays when async generation completes."""
        self._active_loading_jobs = max(0, self._active_loading_jobs - 1)
        if self._active_loading_jobs == 0:
            self._set_loading_message(self._DEFAULT_LOADING_LABEL)
        self._sync_loading_overlays()

    def clear_loading(self) -> None:
        """Force reset loading overlays (safety valve for async edge cases)."""
        self._active_loading_jobs = 0
        self._sync_loading_overlays()

    def set_inline_action_handler(
        self,
        handler: Callable[[AIFullFixBulkModalResult], Awaitable[None]] | None,
    ) -> None:
        """Set async handler for in-place actions without dismiss/reopen."""
        self._inline_action_handler = handler

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "ai-full-fix-bulk-close":
            self.dismiss(None)
            return
        action_map = {
            "ai-full-fix-bulk-regenerate": "regenerate",
            "ai-full-fix-bulk-apply": "apply",
            "ai-full-fix-bulk-show-diff": "show-diff",
            "ai-full-fix-bulk-raw-llm": "raw-llm",
        }
        action = action_map.get(button_id)
        if action:
            self._collect_current_editor_into_state()
            payload: AIFullFixBulkModalResult = {
                "action": action,
                "bundles": self._serialize_bundles(),
                "selected_chart_key": self._selected_chart_key,
            }
            if action in {"regenerate", "show-diff", "raw-llm"} and self._inline_action_handler is not None:
                self._run_inline_action(payload)
                return
            self.dismiss(payload)

    async def on_custom_tree_node_selected(self, event: CustomTree.NodeSelected) -> None:
        if event.tree.id != "ai-full-fix-bulk-violations-tree":
            return
        data = getattr(event.node, "data", None)
        if not isinstance(data, dict):
            return
        chart_key = str(data.get("chart_key", "")).strip()
        if not chart_key or chart_key not in self._bundles:
            return
        self._collect_current_editor_into_state()
        self._selected_chart_key = chart_key
        await self._load_selected_bundle_into_editors()

    def _apply_dynamic_layout(self) -> None:
        available_width = max(
            self._DIALOG_MIN_WIDTH,
            getattr(self.app.size, "width", self._DIALOG_MAX_WIDTH) - 4,
        )
        dialog_width = min(self._DIALOG_MAX_WIDTH, available_width)
        available_height = max(
            self._DIALOG_MIN_HEIGHT,
            getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT) - 2,
        )
        dialog_height = min(self._DIALOG_MAX_HEIGHT, available_height)
        with contextlib.suppress(Exception):
            shell = self.query_one(".ai-full-fix-bulk-modal-shell", CustomContainer)
            shell.styles.width = str(dialog_width)
            shell.styles.min_width = str(dialog_width)
            shell.styles.max_width = str(dialog_width)
            shell.styles.height = str(dialog_height)
            shell.styles.min_height = str(dialog_height)
            shell.styles.max_height = str(dialog_height)

    def _sync_loading_overlays(self) -> None:
        selected_loading = self._selected_bundle_loading_state()
        for overlay_id in (
            "#ai-full-fix-bulk-values-loading-overlay",
            "#ai-full-fix-bulk-diff-loading-overlay",
        ):
            with contextlib.suppress(Exception):
                overlay = self.query_one(overlay_id, CustomContainer)
                if selected_loading:
                    overlay.remove_class("hidden")
                else:
                    overlay.add_class("hidden")
        self._sync_action_buttons_state()

    def _selected_bundle_loading_state(self) -> bool:
        if self._manual_action_lock and self._active_loading_jobs > 0:
            return True
        selected_bundle = self._bundles.get(self._selected_chart_key)
        if selected_bundle is None:
            return self._active_loading_jobs > 0
        if selected_bundle.is_waiting:
            return not self._bundle_has_renderable_results(selected_bundle)
        if selected_bundle.is_processing:
            return not self._bundle_has_renderable_results(selected_bundle)
        return False

    def _bundle_has_renderable_results(self, bundle: ChartBundleEditorState) -> bool:
        values_text = self._resolve_values_editor_text(bundle).strip()
        if values_text and values_text != "{}":
            return True
        template_text = self._resolve_template_preview_text(bundle).strip()
        if template_text:
            return True
        return bool(str(bundle.values_diff_text or "").strip())

    def _apply_action_enabled(self) -> bool:
        bundle = self._bundles.get(self._selected_chart_key)
        if bundle is None:
            return False
        if bundle.is_waiting or bundle.is_processing:
            return False
        return bool(bundle.can_apply)

    def _action_buttons_locked(self) -> bool:
        if self._manual_action_lock:
            return True
        selected_bundle = self._bundles.get(self._selected_chart_key)
        if selected_bundle is None:
            return self._active_loading_jobs > 0
        return bool(selected_bundle.is_processing or selected_bundle.is_waiting)

    def _sync_apply_button_state(self) -> None:
        with contextlib.suppress(Exception):
            apply_button = self.query_one("#ai-full-fix-bulk-apply", CustomButton)
            apply_button.disabled = self._action_buttons_locked() or not self._apply_action_enabled()

    def _sync_action_buttons_state(self) -> None:
        locked = self._action_buttons_locked()
        for button_id in (
            "#ai-full-fix-bulk-regenerate",
            "#ai-full-fix-bulk-show-diff",
            "#ai-full-fix-bulk-raw-llm",
        ):
            with contextlib.suppress(Exception):
                self.query_one(button_id, CustomButton).disabled = locked
        self._sync_apply_button_state()

    @classmethod
    def _normalize_loading_message(cls, message: str) -> str:
        raw = str(message or "").strip()
        if not raw:
            return cls._DEFAULT_LOADING_LABEL
        lowered = raw.lower()
        if any(
            token in lowered
            for token in (
                "trying direct-edit mode",
                "direct-edit:",
                "trying json contract mode",
                "running codex (attempt",
                "running claude (attempt",
            )
        ):
            return cls._DEFAULT_LOADING_LABEL
        return raw

    def _set_loading_message(self, message: str) -> None:
        label = self._normalize_loading_message(message)
        for label_id in (
            "#ai-full-fix-bulk-values-loading-label",
            "#ai-full-fix-bulk-diff-loading-label",
        ):
            with contextlib.suppress(Exception):
                self.query_one(label_id, CustomStatic).update(label)

    def set_loading_message(self, message: str) -> None:
        """Update overlay loading message text while operation is in-flight."""
        self._set_loading_message(message)

    def _configure_editor_highlighting(self) -> None:
        editor_theme = self._active_preview_theme()
        with contextlib.suppress(Exception):
            editor = self.query_one("#ai-full-fix-bulk-values-editor", TextArea)
            editor.language = "yaml"
            _apply_supported_theme(editor, editor_theme)
        with contextlib.suppress(Exception):
            for node in self.query(".ai-full-fix-template-file-editor"):
                if not isinstance(node, TextArea):
                    continue
                node.language = "yaml"
                _apply_supported_theme(node, editor_theme)

    async def _render_template_file_sections(self, template_preview_text: str) -> None:
        sections = await asyncio.to_thread(
            self._parse_template_preview_sections, template_preview_text
        )
        with contextlib.suppress(Exception):
            container = self.query_one("#ai-full-fix-bulk-template-files-list", CustomVertical)
            container.remove_children()
            if not sections:
                container.mount(
                    CustomStatic(
                        "No template content generated.",
                        id="ai-full-fix-bulk-template-empty",
                        markup=False,
                    )
                )
            else:
                for index, section in enumerate(sections):
                    editor = TextArea(
                        text=section.content,
                        language=section.language,
                        theme="monokai",
                        show_line_numbers=True,
                        highlight_cursor_line=False,
                        id=f"{self._TEMPLATE_EDITOR_ID_PREFIX}{index}",
                        classes="ai-full-fix-template-file-editor",
                    )
                    collapsible = CustomCollapsible(
                        editor,
                        title=section.file_path,
                        collapsed=index != 0,
                        classes="ai-full-fix-template-collapsible",
                    )
                    container.mount(collapsible)
        self._configure_editor_highlighting()

    def _active_preview_theme(self) -> str:
        settings_theme = getattr(getattr(self.app, "settings", None), "theme", "dark")
        return _preferred_text_area_theme(str(settings_theme))

    def _run_inline_action(self, payload: AIFullFixBulkModalResult) -> None:
        handler = self._inline_action_handler
        if handler is None:
            return
        if self._inline_action_task is not None and not self._inline_action_task.done():
            self.notify("Action already in progress for this dialog.", severity="warning")
            return

        action = str(payload.get("action", "")).strip()
        use_loading = action in {"regenerate"}
        if use_loading:
            self._set_action_buttons_disabled(True)
        loading_label = "Working..."
        if action == "regenerate":
            loading_label = self._DEFAULT_LOADING_LABEL
        if use_loading:
            self.begin_loading(message=loading_label)

        async def _runner() -> None:
            try:
                await handler(payload)
            except Exception as exc:
                self.notify(f"Action failed: {exc!s}", severity="error")
            finally:
                if use_loading:
                    self.end_loading()
                    self._set_action_buttons_disabled(False)

        self._inline_action_task = asyncio.create_task(_runner())

    def _set_action_buttons_disabled(self, disabled: bool) -> None:
        self._manual_action_lock = disabled
        self._sync_action_buttons_state()

    def _tick_pulse(self) -> None:
        self._pulse_index = (self._pulse_index + 1) % len(self._PULSE_FRAMES)
        has_active = any(
            bundle.is_processing or bundle.is_waiting for bundle in self._bundles.values()
        )
        if has_active:
            # Only update tree node labels instead of full rebuild to avoid
            # destroying and recreating the entire tree 4 times per second.
            self._update_tree_markers()
            self._sync_bulk_progress()

    def _update_tree_markers(self) -> None:
        """Update only the marker text of active tree nodes without rebuilding."""
        with contextlib.suppress(Exception):
            tree = self.query_one("#ai-full-fix-bulk-violations-tree", CustomTree)
            for chart_node in tree.root.children:
                chart_key = (chart_node.data or {}).get("chart_key")
                if chart_key is None:
                    continue
                bundle = self._bundles.get(chart_key)
                if bundle is None:
                    continue
                if not (bundle.is_processing or bundle.is_waiting):
                    continue
                marker = self._chart_marker(bundle)
                violation_count = len(bundle.violations)
                violation_label = "violation" if violation_count == 1 else "violations"
                elapsed_suffix = self._tree_elapsed_label(bundle)
                new_label = (
                    f"{marker} {bundle.chart_name} ({violation_count} {violation_label})"
                    f"{elapsed_suffix}"
                )
                chart_node.set_label(Text(new_label, style=self._chart_row_color(bundle)))

    def _chart_marker(self, bundle: ChartBundleEditorState) -> str:
        if bundle.is_processing or bundle.is_waiting:
            return self._PULSE_FRAMES[self._pulse_index]
        if self._is_completed_status(bundle.status_text):
            return "✓"
        return "○"

    @classmethod
    def _bundle_render_status(cls, status_text: str) -> str:
        render_status = cls._status_value(status_text, "Render Verification").strip().lower()
        if not render_status:
            render_status = cls._status_value(status_text, "Re-Verify").strip().lower()
        return render_status

    @classmethod
    def _is_error_status(cls, status_text: str) -> bool:
        render_status = cls._bundle_render_status(status_text)
        if render_status in {
            "unresolved",
            "wiring_issue",
            "wiring issue",
            "unverified",
            "failed",
            "error",
            "timeout",
            "timed out",
            "blocked",
        }:
            return True
        normalized = str(status_text or "").lower()
        return any(
            token in normalized
            for token in (
                "ai full-fix flow failed",
                "apply failed",
                "failed",
                "error",
                "timed out",
                "timeout",
                "blocked",
            )
        )

    @classmethod
    def _is_success_status(cls, status_text: str, *, can_apply: bool = False) -> bool:
        if can_apply:
            return True
        return cls._bundle_render_status(status_text) in {"verified", "ok", "success"}

    @classmethod
    def _chart_row_color(cls, bundle: ChartBundleEditorState) -> str:
        if bundle.is_processing:
            return "yellow"
        if bundle.is_waiting or (
            cls._is_waiting_status(bundle.status_text) and not bundle.can_apply
        ):
            return "blue"
        if cls._is_error_status(bundle.status_text):
            return "red"
        if cls._is_success_status(bundle.status_text, can_apply=bundle.can_apply):
            return "green"
        return "white"

    @staticmethod
    def _is_waiting_status(status_text: str) -> bool:
        normalized = str(status_text or "").lower()
        if not normalized.strip():
            return False
        return any(
            token in normalized
            for token in (
                "queued",
                "queue",
                "waiting for fix worker",
                "waiting to start",
                "pending start",
            )
        )

    @staticmethod
    def _is_processing_status(status_text: str) -> bool:
        normalized = str(status_text or "").lower()
        if not normalized.strip():
            return False
        return any(
            token in normalized
            for token in (
                "generating",
                "generating fix",
                "preparing",
                "preparing deterministic fix seed",
                "trying direct-edit mode",
                "direct-edit:",
                "trying json contract mode",
                "running codex (attempt",
                "running claude (attempt",
                "render verification in progress",
                "verifying fix",
                "re-verifying",
                "regenerating",
                "building preview",
                "building updated file previews",
                "finalizing response",
            )
        )

    @staticmethod
    def _is_completed_status(status_text: str) -> bool:
        normalized = str(status_text or "").lower()
        if not normalized.strip():
            return False
        return any(
            token in normalized
            for token in (
                "llm: completed",
                "bundle:",
                "render verification:",
                "re-verify:",
                "applied:",
                "apply skipped:",
                "apply failed:",
                "ai full-fix flow failed",
                "timed out",
                "chart is not a local helm chart path",
            )
        )

    @staticmethod
    def _status_value(status_text: str, key: str) -> str:
        prefix = f"{key.strip().lower()}:"
        for line in str(status_text or "").splitlines():
            normalized = line.strip()
            if normalized.lower().startswith(prefix):
                _, _, value = normalized.partition(":")
                return value.strip()
        return ""

    @classmethod
    def _chip_display_value(cls, key: str, value: str) -> str:
        normalized_key = str(key or "").strip().lower()
        text = str(value or "").strip()
        if not text:
            return ""
        if normalized_key == "verification details":
            match = _BUNDLE_VERIFICATION_COUNTS_PATTERN.search(text)
            if match is not None:
                verified_count = int(match.group(1))
                unresolved_count = int(match.group(2))
                unverified_count = int(match.group(3))
                return (
                    f"{verified_count} verified | "
                    f"{unresolved_count} unresolved | "
                    f"{unverified_count} unverified"
                )
        if len(text) > 72:
            return f"{text[:69].rstrip()}..."
        return text

    @staticmethod
    def _chip_tooltip(key: str, value: str) -> str | None:
        normalized_key = str(key or "").strip().lower()
        text = str(value or "").strip()
        if normalized_key == "verification details" and text:
            return text
        return None

    @classmethod
    def _status_allows_verified_subset_apply(cls, status_text: str) -> bool:
        render_status = cls._status_value(status_text, "Render Verification").strip().lower()
        if render_status in {"verified", "ok", "success"}:
            return True
        details = cls._status_value(status_text, "Verification Details")
        if not details:
            return False
        match = _BUNDLE_VERIFICATION_COUNTS_PATTERN.search(details)
        if match is None:
            return False
        verified_count = int(match.group(1))
        unverified_count = int(match.group(3))
        return verified_count > 0 and unverified_count == 0

    def _completion_time_label(self, bundle: ChartBundleEditorState) -> str:
        if bundle.is_waiting:
            return "Queued"
        if bundle.is_processing:
            started_at = bundle.fix_started_at_monotonic
            if started_at is not None:
                elapsed = max(0.0, time.monotonic() - started_at)
                return f"{elapsed:.1f}s"
            return "Queued"
        completion_value = self._status_value(bundle.status_text, "Completion Time")
        if completion_value.strip():
            return completion_value.strip()
        timing_value = self._status_value(bundle.status_text, "Timing")
        seconds = [
            float(match.group(1))
            for match in _SECONDS_TOKEN_PATTERN.finditer(timing_value)
            if match.group(1)
        ]
        if seconds:
            return f"{sum(seconds):.1f}s"
        if bundle.last_fix_elapsed_seconds is not None:
            return f"{max(0.0, bundle.last_fix_elapsed_seconds):.1f}s"
        return "N/A"

    def _tree_elapsed_label(self, bundle: ChartBundleEditorState) -> str:
        if bundle.is_waiting:
            return ""
        elapsed = self._completion_time_label(bundle).strip()
        if not elapsed or elapsed.upper() in {"N/A", "QUEUED", "PENDING"}:
            return ""
        return f" | {elapsed}"

    def _sync_bundle_elapsed_tracking(
        self,
        bundle: ChartBundleEditorState,
        *,
        was_processing: bool,
    ) -> None:
        now = time.monotonic()
        if bundle.is_processing:
            bundle.is_waiting = False
            if bundle.fix_started_at_monotonic is None:
                bundle.fix_started_at_monotonic = now
            self._record_bulk_fix_started(bundle.fix_started_at_monotonic)
            return
        bundle.is_waiting = self._is_waiting_status(bundle.status_text) and not bool(bundle.can_apply)
        started_at = bundle.fix_started_at_monotonic
        if started_at is None:
            if was_processing and bundle.last_fix_elapsed_seconds is None:
                bundle.last_fix_elapsed_seconds = 0.0
            return
        bundle.last_fix_elapsed_seconds = max(0.0, now - started_at)
        bundle.fix_started_at_monotonic = None
        self._record_bulk_fix_started(started_at)
        if self._bulk_fix_started_at_monotonic is not None:
            self._bulk_last_elapsed_seconds = max(0.0, now - self._bulk_fix_started_at_monotonic)

    def _record_bulk_fix_started(self, started_at: float | None) -> None:
        if started_at is None:
            return
        if (
            self._bulk_fix_started_at_monotonic is None
            or started_at < self._bulk_fix_started_at_monotonic
        ):
            self._bulk_fix_started_at_monotonic = started_at

    def _fix_status_label(self, bundle: ChartBundleEditorState) -> str:
        render_status = self._status_value(bundle.status_text, "Render Verification").strip().lower()
        if not render_status:
            render_status = self._status_value(bundle.status_text, "Re-Verify").strip().lower()
        if render_status in {"verified", "ok", "success"}:
            return "Complete Fix"
        if render_status in {"unresolved", "wiring_issue", "wiring issue"} and bundle.can_apply:
            return "Partial Fix"
        if bundle.can_apply:
            return "Complete Fix"
        return "Incomplete Fix"

    @staticmethod
    def _parse_template_preview_sections(template_preview_text: str) -> list[_TemplatePreviewSection]:
        content = str(template_preview_text or "")
        if not content.strip():
            return []
        lines = content.splitlines()
        sections: list[_TemplatePreviewSection] = []
        current_file = ""
        current_lines: list[str] = []
        for line in lines:
            if line.startswith("# FILE:"):
                if current_file:
                    section_content = "\n".join(current_lines).rstrip()
                    if section_content:
                        section_content = f"{section_content}\n"
                    sections.append(
                        _TemplatePreviewSection(
                            file_path=current_file,
                            content=section_content,
                            language=_template_language_for_preview(current_file, section_content),
                        )
                    )
                current_file = line.replace("# FILE:", "", 1).strip() or "templates/unknown.yaml"
                current_lines = []
                continue
            current_lines.append(line)
        if current_file:
            section_content = "\n".join(current_lines).rstrip()
            if section_content:
                section_content = f"{section_content}\n"
            sections.append(
                _TemplatePreviewSection(
                    file_path=current_file,
                    content=section_content,
                    language=_template_language_for_preview(current_file, section_content),
                )
            )
        if sections:
            return sections
        fallback = content.rstrip()
        if fallback:
            if _looks_like_unified_diff(fallback):
                return [
                    _TemplatePreviewSection(
                        file_path="templates/preview-unavailable",
                        content=(
                            "Unable to render updated template content from this payload.\n"
                            "Use 'Regenerate Chart' to refresh preview content.\n"
                        ),
                        language="markdown",
                    )
                ]
            return [
                _TemplatePreviewSection(
                    file_path="templates/preview.yaml",
                    content=f"{fallback}\n",
                    language=_template_language_for_preview("templates/preview.yaml", fallback),
                )
            ]
        return []


def _looks_like_unified_diff(content: str) -> bool:
    lines = [line for line in content.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    if not lines[0].startswith("--- ") or not lines[1].startswith("+++ "):
        return False
    return any(line.startswith("@@ ") for line in lines[2:12])


def _template_language_for_preview(file_path: str, content: str) -> str:
    lowered = file_path.lower()
    if lowered.endswith(".tpl"):
        return "markdown"
    if lowered.endswith((".yaml", ".yml")):
        return "yaml"
    if _looks_like_unified_diff(content):
        return "diff"
    if "{{" in content and "}}" in content:
        return "markdown"
    return "yaml"
