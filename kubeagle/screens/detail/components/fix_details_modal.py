"""Shared fix/details modal used by violations and recommendations views."""

from __future__ import annotations

import contextlib
import re

from rich.text import Text
from textual.app import ComposeResult
from textual.events import Resize
from textual.screen import ModalScreen

from kubeagle.widgets import (
    CustomButton,
    CustomCollapsible,
    CustomContainer,
    CustomHorizontal,
    CustomMarkdownViewer as TextualMarkdownViewer,
    CustomRichLog,
    CustomStatic,
    CustomVertical,
)

FixDetailsAction = tuple[str, str, str | None]


class FixDetailsModal(ModalScreen[str | None]):
    """Generic modal for previewing markdown details with action buttons."""

    BINDINGS = [("escape", "cancel", "Close")]
    _DIALOG_MIN_WIDTH = 92
    _DIALOG_MAX_WIDTH = 168
    _DIALOG_MIN_HEIGHT = 24
    _DIALOG_MAX_HEIGHT = 46

    def __init__(
        self,
        *,
        title: str,
        markdown: str = "",
        actions: tuple[FixDetailsAction, ...],
        subtitle: str | None = None,
        diff_text: str | None = None,
        log_text: str | None = None,
    ) -> None:
        super().__init__(classes="fix-details-modal-screen selection-modal-screen")
        self._title = title
        self._subtitle = subtitle
        self._markdown = markdown
        self._diff_text = diff_text
        self._log_text = log_text
        self._actions = actions

    def compose(self) -> ComposeResult:
        with CustomContainer(classes="fix-details-modal-shell selection-modal-shell"):
            yield CustomStatic(
                self._title,
                classes="fix-details-modal-title selection-modal-title",
                markup=False,
            )
            if self._subtitle:
                yield CustomStatic(
                    self._subtitle,
                    classes="fix-details-modal-subtitle",
                    markup=False,
                )
            if self._diff_text is not None:
                yield CustomVertical(
                    CustomRichLog(
                        id="fix-details-modal-diff-log",
                        highlight=False,
                        markup=False,
                        wrap=False,
                    ),
                    id="fix-details-modal-markdown-wrap",
                )
            elif self._log_text is not None:
                yield CustomVertical(
                    CustomRichLog(
                        id="fix-details-modal-log",
                        highlight=False,
                        markup=False,
                        wrap=False,
                    ),
                    id="fix-details-modal-markdown-wrap",
                )
            else:
                yield CustomVertical(
                    TextualMarkdownViewer(
                        self._markdown,
                        id="fix-details-modal-markdown",
                        show_table_of_contents=False,
                    ),
                    id="fix-details-modal-markdown-wrap",
                )
            with CustomHorizontal(classes="fix-details-modal-actions selection-modal-actions"):
                for action_id, label, variant in self._actions:
                    if variant is None:
                        yield CustomButton(
                            label,
                            id=f"fix-details-modal-action-{action_id}",
                            compact=True,
                            classes="selection-modal-action-btn",
                        )
                    else:
                        yield CustomButton(
                            label,
                            id=f"fix-details-modal-action-{action_id}",
                            compact=True,
                            variant=variant,
                            classes="selection-modal-action-btn",
                        )

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        if self._actions:
            first_action_id = self._actions[0][0]
            with contextlib.suppress(Exception):
                self.query_one(
                    f"#fix-details-modal-action-{first_action_id}",
                    CustomButton,
                ).focus()
        if self._diff_text is not None:
            self._render_diff_content()
        elif self._log_text is not None:
            self._render_log_content()

    def on_resize(self, _: Resize) -> None:
        self._apply_dynamic_layout()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        prefix = "fix-details-modal-action-"
        if not button_id.startswith(prefix):
            return
        self.dismiss(button_id.removeprefix(prefix))

    def _apply_dynamic_layout(self) -> None:
        available_width = max(
            self._DIALOG_MIN_WIDTH,
            getattr(self.app.size, "width", self._DIALOG_MAX_WIDTH) - 8,
        )
        dialog_width = min(self._DIALOG_MAX_WIDTH, available_width)
        dialog_width = max(self._DIALOG_MIN_WIDTH, dialog_width)
        dialog_width_value = str(dialog_width)

        available_height = max(
            self._DIALOG_MIN_HEIGHT,
            getattr(self.app.size, "height", self._DIALOG_MAX_HEIGHT) - 2,
        )
        max_height = min(self._DIALOG_MAX_HEIGHT, available_height)
        dialog_min_height = min(self._DIALOG_MIN_HEIGHT, max_height)
        dialog_max_height = max(dialog_min_height, max_height)
        dialog_min_height_value = str(dialog_min_height)
        dialog_max_height_value = str(dialog_max_height)

        with contextlib.suppress(Exception):
            shell = self.query_one(".fix-details-modal-shell", CustomContainer)
            shell.styles.width = dialog_width_value
            shell.styles.min_width = dialog_width_value
            shell.styles.max_width = dialog_width_value
            shell.styles.height = dialog_max_height_value
            shell.styles.min_height = dialog_min_height_value
            shell.styles.max_height = dialog_max_height_value

        with contextlib.suppress(Exception):
            markdown_wrap = self.query_one(
                "#fix-details-modal-markdown-wrap",
                CustomVertical,
            )
            markdown_wrap.styles.height = "1fr"
            markdown_wrap.styles.min_height = "12"

    def _render_diff_content(self) -> None:
        with contextlib.suppress(Exception):
            diff_log = self.query_one("#fix-details-modal-diff-log", CustomRichLog)
            _write_diff_to_log(
                diff_log,
                str(self._diff_text or ""),
                empty_fallback="# No content changes",
            )

    def _render_log_content(self) -> None:
        with contextlib.suppress(Exception):
            log = self.query_one("#fix-details-modal-log", CustomRichLog)
            _write_plain_log_content(
                log,
                str(self._log_text or ""),
                empty_fallback="# No output captured.",
            )


def _style_diff_line(line: str) -> Text:
    """Colorize a unified diff line by prefix for stable git-style readability."""
    if line.startswith(("--- ", "+++ ")):
        return Text(line, style="bold cyan")
    if line.startswith("@@ "):
        return Text(line, style="bold magenta")
    if line.startswith("+"):
        return Text(line, style="green")
    if line.startswith("-"):
        return Text(line, style="red")
    return Text(line)


def _write_diff_to_log(diff_log: CustomRichLog, content: str, *, empty_fallback: str) -> None:
    """Render unified diff content into a rich log with stable git-style colors."""
    log_widget = diff_log.rich_log
    if log_widget is None:
        return
    log_widget.clear()
    normalized = str(content or "").rstrip("\n")
    if not normalized:
        normalized = empty_fallback
    for line_number, line in enumerate(normalized.splitlines(), start=1):
        rendered = Text(f"{line_number:>4} ", style="dim")
        rendered.append_text(_style_diff_line(line))
        log_widget.write(rendered, scroll_end=False)


def _write_plain_log_content(log: CustomRichLog, content: str, *, empty_fallback: str) -> None:
    """Render plain text into a rich log, preserving line breaks."""
    log_widget = log.rich_log
    if log_widget is None:
        return
    log_widget.clear()
    normalized = str(content or "").rstrip("\n")
    if not normalized:
        normalized = empty_fallback
    for line in normalized.splitlines():
        log_widget.write(line, scroll_end=False)


class BundleDiffModal(ModalScreen[str | None]):
    """Side-by-side bundle diff modal (values diff + collapsible template diffs)."""

    BINDINGS = [("escape", "cancel", "Close")]
    _DIALOG_MIN_WIDTH = 124
    _DIALOG_MAX_WIDTH = 196
    _DIALOG_MIN_HEIGHT = 30
    _DIALOG_MAX_HEIGHT = 48
    _TEMPLATE_EDITOR_ID_PREFIX = "bundle-diff-template-editor-"

    def __init__(
        self,
        *,
        title: str,
        subtitle: str | None = None,
        values_diff_text: str = "",
        template_diff_text: str = "",
    ) -> None:
        super().__init__(classes="selection-modal-screen")
        self._title = str(title or "Bundle Diff")
        self._subtitle = str(subtitle or "").strip() or None
        self._values_diff_text = str(values_diff_text or "")
        self._template_diff_text = str(template_diff_text or "")
        self._template_section_content_by_id: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with CustomContainer(classes="bundle-diff-modal-shell selection-modal-shell"):
            yield CustomStatic(self._title, classes="selection-modal-title", markup=False)
            if self._subtitle:
                yield CustomStatic(
                    self._subtitle,
                    classes="fix-details-modal-subtitle",
                    markup=False,
                )
            with CustomHorizontal(id="bundle-diff-editors"):
                with CustomVertical(classes="ai-full-fix-editor-pane"):
                    yield CustomStatic(
                        "Values Diff",
                        classes="apply-fixes-modal-panel-title ui-section-title",
                        markup=False,
                    )
                    yield CustomRichLog(
                        id="bundle-diff-values-editor",
                        highlight=False,
                        markup=False,
                        wrap=False,
                    )
                with CustomVertical(classes="ai-full-fix-editor-pane"):
                    yield CustomStatic(
                        "Template Diffs",
                        classes="apply-fixes-modal-panel-title ui-section-title",
                        markup=False,
                    )
                    yield CustomVertical(id="bundle-diff-template-files-list")
            with CustomHorizontal(classes="selection-modal-actions"):
                yield CustomButton(
                    "Copy Diff",
                    id="bundle-diff-modal-action-copy",
                    classes="selection-modal-action-btn",
                )
                yield CustomButton(
                    "Close",
                    id="bundle-diff-modal-action-close",
                    classes="selection-modal-action-btn",
                )

    def on_mount(self) -> None:
        self._apply_dynamic_layout()
        self._render_values_diff_content()
        self._render_template_diff_sections()
        with contextlib.suppress(Exception):
            self.query_one("#bundle-diff-modal-action-copy", CustomButton).focus()

    def on_resize(self, _: Resize) -> None:
        self._apply_dynamic_layout()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "bundle-diff-modal-action-close":
            self.dismiss(None)
            return
        if button_id == "bundle-diff-modal-action-copy":
            content = self._combined_diff_text()
            self.app.copy_to_clipboard(content)
            self.notify("Diff copied to clipboard", severity="information")

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
            shell = self.query_one(".bundle-diff-modal-shell", CustomContainer)
            shell.styles.width = str(dialog_width)
            shell.styles.min_width = str(dialog_width)
            shell.styles.max_width = str(dialog_width)
            shell.styles.height = str(dialog_height)
            shell.styles.min_height = str(dialog_height)
            shell.styles.max_height = str(dialog_height)

    def _render_values_diff_content(self) -> None:
        with contextlib.suppress(Exception):
            values_log = self.query_one("#bundle-diff-values-editor", CustomRichLog)
            _write_diff_to_log(values_log, self._values_diff_text, empty_fallback="# No values diff available.")

    def _render_template_diff_sections(self) -> None:
        sections = self._parse_template_diff_sections(self._template_diff_text)
        self._template_section_content_by_id = {}
        with contextlib.suppress(Exception):
            container = self.query_one("#bundle-diff-template-files-list", CustomVertical)
            container.remove_children()
            if not sections:
                container.mount(
                    CustomStatic(
                        "No template diff available.",
                        id="bundle-diff-template-empty",
                        markup=False,
                    )
                )
                return

            for index, (file_path, content) in enumerate(sections):
                editor_id = f"{self._TEMPLATE_EDITOR_ID_PREFIX}{index}"
                self._template_section_content_by_id[editor_id] = content
                editor = CustomRichLog(
                    id=editor_id,
                    classes="bundle-diff-template-editor",
                    highlight=False,
                    markup=False,
                    wrap=False,
                )
                container.mount(
                    CustomCollapsible(
                        editor,
                        title=file_path,
                        collapsed=index != 0,
                        classes="bundle-diff-template-collapsible",
                    )
                )
        self.call_after_refresh(self._render_template_diff_logs)

    def _render_template_diff_logs(self) -> None:
        for editor_id, content in self._template_section_content_by_id.items():
            with contextlib.suppress(Exception):
                diff_log = self.query_one(f"#{editor_id}", CustomRichLog)
                _write_diff_to_log(diff_log, content, empty_fallback="# No template diff available.")

    @classmethod
    def _parse_template_diff_sections(cls, template_diff_text: str) -> list[tuple[str, str]]:
        content = str(template_diff_text or "").strip()
        if not content:
            return []

        file_marker_sections = cls._parse_file_marker_sections(content)
        if file_marker_sections:
            return file_marker_sections

        lines = content.splitlines()
        sections: list[tuple[str, str]] = []
        current_file = ""
        current_lines: list[str] = []

        def _flush() -> None:
            if not current_lines:
                return
            file_path = current_file or "templates/changes.diff"
            section_text = "\n".join(current_lines).rstrip()
            if section_text:
                sections.append((file_path, f"{section_text}\n"))

        for line in lines:
            if line.startswith("diff --git "):
                _flush()
                current_lines = [line]
                match = re.match(r"^diff --git a/(.+?) b/(.+)$", line.strip())
                current_file = match.group(2) if match else "templates/changes.diff"
                continue
            if line.startswith("+++ b/") and not current_file:
                current_file = line.removeprefix("+++ b/").strip() or "templates/changes.diff"
            current_lines.append(line)

        _flush()
        if sections:
            return sections
        return [("templates/changes.diff", f"{content}\n")]

    @staticmethod
    def _parse_file_marker_sections(content: str) -> list[tuple[str, str]]:
        lines = content.splitlines()
        sections: list[tuple[str, str]] = []
        current_file = ""
        current_lines: list[str] = []
        for line in lines:
            if line.startswith("# FILE:"):
                if current_file:
                    section_text = "\n".join(current_lines).rstrip()
                    sections.append((current_file, f"{section_text}\n" if section_text else ""))
                current_file = line.replace("# FILE:", "", 1).strip() or "templates/unknown.diff"
                current_lines = []
                continue
            current_lines.append(line)
        if current_file:
            section_text = "\n".join(current_lines).rstrip()
            sections.append((current_file, f"{section_text}\n" if section_text else ""))
        return sections

    def _combined_diff_text(self) -> str:
        values = self._values_diff_text.strip()
        templates = self._template_diff_text.strip()
        parts: list[str] = []
        if values:
            parts.append(f"### Values Diff\n{values}")
        if templates:
            parts.append(f"### Template Diff\n{templates}")
        combined = "\n\n".join(parts).strip()
        return combined or "# No diff content available."


__all__ = ["BundleDiffModal", "FixDetailsAction", "FixDetailsModal"]
