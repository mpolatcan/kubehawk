"""Custom dialog widgets for the TUI application.

Standard Reactive Pattern:
- Dialogs are modal screens, inherit from ModalScreen
- No reactive state needed (they manage their own lifecycle)

CSS Classes: widget-custom-dialog
"""

from collections.abc import Callable
from contextlib import suppress

from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widgets import Static

from kubeagle.widgets.feedback.custom_button import CustomButton

_DIALOG_MIN_WIDTH = 36
_DIALOG_SIDE_MARGIN = 6
_DIALOG_CONTENT_PADDING = 8
_DIALOG_MIN_HEIGHT = 8
_DIALOG_VERTICAL_MARGIN = 4


def _max_line_width(*values: str) -> int:
    width = 0
    for value in values:
        for line in value.splitlines() or [""]:
            width = max(width, len(line))
    return width


def _fit_dialog_width(dialog: ModalScreen, content_width: int) -> int:
    available_width = max(
        _DIALOG_MIN_WIDTH,
        getattr(dialog.app.size, "width", _DIALOG_MIN_WIDTH + _DIALOG_SIDE_MARGIN)
        - _DIALOG_SIDE_MARGIN,
    )
    return max(
        _DIALOG_MIN_WIDTH,
        min(content_width + _DIALOG_CONTENT_PADDING, available_width),
    )


def _apply_dialog_shell_size(dialog: ModalScreen, content_width: int) -> None:
    dialog_width = _fit_dialog_width(dialog, content_width)
    dialog_max_height = max(
        _DIALOG_MIN_HEIGHT,
        getattr(dialog.app.size, "height", _DIALOG_MIN_HEIGHT + _DIALOG_VERTICAL_MARGIN)
        - _DIALOG_VERTICAL_MARGIN,
    )
    with suppress(Exception):
        container = dialog.query_one(".dialog-container", Vertical)
        width_value = str(dialog_width)
        container.styles.width = width_value
        container.styles.min_width = width_value
        container.styles.max_width = width_value
        container.styles.height = "auto"
        container.styles.max_height = str(dialog_max_height)


class CustomConfirmDialog(ModalScreen[bool]):
    """Confirmation dialog with OK/Cancel buttons."""

    CSS_PATH = "../../css/widgets/custom_dialog.tcss"
    _default_classes = "widget-custom-dialog"

    def __init__(
        self,
        message: str,
        title: str = "Confirm",
        on_confirm: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the custom confirmation dialog.

        Args:
            message: Message to display.
            title: Dialog title.
            on_confirm: Callback when confirmed.
            on_cancel: Callback when cancelled.
        """
        super().__init__()
        self._message = message
        self._title = title
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel

    def compose(self):
        with Vertical(classes="dialog-container"):
            if self._title:
                with Vertical(classes="dialog-title-wrapper"):
                    yield Static(
                        self._title,
                        classes="dialog-title selection-modal-title",
                    )
            yield Static(self._message, classes="dialog-message")
            with Horizontal(classes="dialog-buttons"):
                yield CustomButton(
                    "OK",
                    id="confirm-btn",
                    classes="dialog-btn confirm",
                )
                yield CustomButton(
                    "Cancel",
                    id="cancel-btn",
                    classes="dialog-btn cancel dialog-cancel-btn",
                )

    def on_mount(self) -> None:
        self._apply_dynamic_layout()

    def on_resize(self, _: Resize) -> None:
        self._apply_dynamic_layout()

    def _apply_dynamic_layout(self) -> None:
        content_width = max(
            _max_line_width(self._title, self._message),
            len("OK") + len("Cancel") + 9,
        )
        _apply_dialog_shell_size(self, content_width)

    def on_button_pressed(self, event: CustomButton.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "confirm-btn":
            self.dismiss(True)
            if self._on_confirm:
                self._on_confirm()
        else:
            self.dismiss(False)
            if self._on_cancel:
                self._on_cancel()


