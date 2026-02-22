"""CustomKPI widget for displaying key performance indicators.

Standard Reactive Pattern:
- Inherits from StatefulWidget
- Has is_loading, data, error reactives
- Implements watch_* methods

CSS Classes: widget-custom-kpi
"""

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

from kubeagle.widgets._base import StatefulWidget
import contextlib

# Spinner frames for the inline loading animation
_SPINNER_FRAMES = ("   ", ".  ", ".. ", "...")
_SPINNER_INTERVAL = 0.3


class CustomKPI(StatefulWidget):
    """Reusable KPI display widget with reactive state management.

    CSS Classes: widget-custom-kpi
    """

    DEFAULT_CSS = """
    CustomKPI {
        height: auto;
        width: 1fr;
        padding: 0 1;
        border: solid $surface-lighten-1;
        background: $surface;
        content-align: center middle;
    }
    CustomKPI:focus {
        border: solid $surface-lighten-1;
    }
    CustomKPI > .kpi-title {
        text-style: bold;
        color: $secondary;
        text-align: center;
        width: 100%;
    }
    CustomKPI > .kpi-value {
        text-style: bold;
        color: $text;
        text-align: center;
        width: 100%;
    }
    CustomKPI.success > .kpi-value { color: $success; }
    CustomKPI.warning > .kpi-value { color: $warning; }
    CustomKPI.error > .kpi-value { color: $error; }
    CustomKPI.info > .kpi-value { color: $text; }
    CustomKPI > .kpi-spinner {
        text-style: bold;
        color: $text;
        text-align: center;
        width: 100%;
        display: none;
    }
    CustomKPI.kpi-inline {
        padding: 0;
        margin: 0;
        border: none;
        height: auto;
        min-height: 0;
        layout: horizontal;
        content-align: left middle;
    }
    CustomKPI.kpi-inline > .kpi-title {
        color: $text-muted;
        text-style: italic;
        width: auto;
        margin-right: 1;
    }
    CustomKPI.kpi-inline > .kpi-value {
        width: auto;
        text-style: bold;
    }
    CustomKPI.kpi-inline > .kpi-spinner {
        width: auto;
    }
    CustomKPI .kpi-status {
        text-align: center;
        margin-top: 0;
    }
    CustomKPI .kpi-status.success { color: $success; }
    CustomKPI .kpi-status.warning { color: $warning; }
    CustomKPI .kpi-status.error { color: $error; }
    CustomKPI .kpi-status.info { color: $text; }
    """
    _id_pattern = "custom-kpi-{uuid}"
    _default_classes = "widget-custom-kpi"

    # Standard reactive attributes
    is_loading = reactive(False)
    data = reactive[list[dict]]([])
    error = reactive[str | None](None)

    # Widget-specific reactive
    value = reactive("", init=False)

    def __init__(
        self,
        title: str,
        value: str,
        status: str = "success",
        *,
        id: str | None = None,
        classes: str = "",
    ):
        """Initialize the custom KPI widget.

        Args:
            title: The KPI title.
            value: The value to display.
            status: Status indicator (success, warning, error, info).
            id: Optional widget ID.
            classes: Optional CSS classes.
        """
        super().__init__(id=id, classes=classes)
        self._title = title
        self._subtitle = ""
        self._value = value
        self._status = status
        self._spinner_timer = None
        self._spinner_frame = 0
        self._spinner_widget: Static | None = None
        self._value_widget: Static | None = None

    def on_mount(self) -> None:
        """Apply initial status class on mount and cache child widget refs."""
        if self._status:
            self.add_css_class(self._status)
        # Eagerly cache child widget references so hot paths avoid DOM traversal.
        try:
            self._value_widget = self.query_one(".kpi-value", Static)
        except Exception:
            self._value_widget = None
        try:
            self._spinner_widget = self.query_one(".kpi-spinner", Static)
        except Exception:
            self._spinner_widget = None

    def on_unmount(self) -> None:
        """Stop spinner timer and clear cached refs to prevent leaks after widget removal."""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self._spinner_widget = None
        self._value_widget = None

    def compose(self) -> ComposeResult:
        """Compose the KPI widget."""
        yield Static(self._format_title(), classes="kpi-title")
        yield Static(self._value, classes="kpi-value")
        yield Static("...", classes="kpi-spinner")

    def _format_title(self) -> str:
        """Build KPI title text with optional subtitle."""
        if not self._subtitle:
            return self._title
        return f"{self._title}\n[dim]{self._subtitle}[/dim]"

    def _get_value_widget(self) -> Static | None:
        """Return cached value widget reference."""
        if self._value_widget is None:
            try:
                self._value_widget = self.query_one(".kpi-value", Static)
            except Exception:
                return None
        return self._value_widget

    def _get_spinner_widget(self) -> Static | None:
        """Return cached spinner widget reference."""
        if self._spinner_widget is None:
            try:
                self._spinner_widget = self.query_one(".kpi-spinner", Static)
            except Exception:
                return None
        return self._spinner_widget

    def watch_is_loading(self, loading: bool) -> None:
        """Update UI based on loading state.

        Args:
            loading: The new loading state.
        """
        value_widget = self._get_value_widget()
        spinner_widget = self._get_spinner_widget()
        if value_widget is None or spinner_widget is None:
            return

        if loading:
            value_widget.display = False
            spinner_widget.display = True
            self._spinner_frame = 0
            self._spinner_timer = self.set_interval(
                _SPINNER_INTERVAL, self._advance_spinner
            )
        else:
            value_widget.display = True
            spinner_widget.display = False
            if self._spinner_timer is not None:
                self._spinner_timer.stop()
                self._spinner_timer = None

    def _advance_spinner(self) -> None:
        """Advance the spinner animation frame."""
        spinner_widget = self._get_spinner_widget()
        if spinner_widget is None:
            return
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_FRAMES)
        spinner_widget.update(_SPINNER_FRAMES[self._spinner_frame])

    def watch_data(self, data: list[dict]) -> None:
        """Update UI when data changes.

        Args:
            data: The new data value.
        """
        pass

    def watch_error(self, error: str | None) -> None:
        """Handle error state changes.

        Args:
            error: The error message or None if cleared.
        """
        pass

    def watch_value(self, value: str) -> None:
        """Update value when changed.

        Args:
            value: The new value.
        """
        widget = self._get_value_widget()
        if widget is not None:
            widget.update(value)

    def set_value(self, value: str) -> None:
        """Set the KPI value and stop any loading spinner.

        Args:
            value: The new value to display.
        """
        self._value = value
        self.is_loading = False
        self.value = value

    def set_subtitle(self, subtitle: str) -> None:
        """Set optional subtitle text rendered beneath the KPI title."""
        self._subtitle = subtitle
        with contextlib.suppress(Exception):
            self.query_one(".kpi-title", Static).update(self._format_title())

    def set_status(self, status: str) -> None:
        """Set the KPI status.

        Args:
            status: The new status (success, warning, error, info).
        """
        if self._status == status:
            return
        old_status = self._status
        self._status = status
        if old_status:
            self.remove_css_class(old_status)
        self.add_css_class(status)

    def start_loading(self) -> None:
        """Start the inline loading spinner."""
        self.is_loading = True

    @property
    def title(self) -> str:
        """Get the KPI title.

        Returns:
            The title text.
        """
        return self._title

    @property
    def status(self) -> str:
        """Get the current status.

        Returns:
            The status value.
        """
        return self._status
