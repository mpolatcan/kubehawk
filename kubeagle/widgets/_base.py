"""Base widget classes with configuration support for reusable components.

This module provides the foundation for all widgets in the TUI application,
with configurable ID patterns, CSS class composition utilities, common
lifecycle hooks, and standardized reactive state management.

Standard Reactive Pattern:
- All stateful widgets inherit from StatefulWidget
- Reactive attributes: is_loading, data, error
- Watch methods: watch_is_loading, watch_data, watch_error
- Worker pattern for async data loading

Example:
    >>> from kubeagle.widgets._base import StatefulWidget
    >>>
    >>> class CustomCard(StatefulWidget):
    ...     CSS_PATH = "css/widgets/custom_card.tcss"
    ...
    ...     def __init__(self, title: str, **kwargs):
    ...         super().__init__(title=title, **kwargs)
    ...
    ...     def watch_is_loading(self, loading: bool) -> None:
    ...         self.notify_loading_state(loading)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.reactive import reactive
from textual.widget import Widget

if TYPE_CHECKING:
    from textual.app import ComposeResult


class BaseWidget(Widget):
    """Base widget with configuration support for consistent widget patterns.

    This class provides:
    - Configurable ID pattern support with UUID generation
    - CSS class composition utilities
    - Common lifecycle hooks
    - Type-safe property definitions

    Attributes:
        CSS_PATH: Path to the widget's CSS file.
        _id_pattern: Pattern string for auto-generating widget IDs.
        _default_classes: Default CSS classes for the widget.

    Example:
        Creating a widget with ID pattern:
        >>> card = MyCard(title="Stats", id_pattern="stats-{title}-{uuid}")
        >>> # Generates ID like: "stats-stats-abc12345"
    """

    CSS_PATH: str | None = None
    _id_pattern: ClassVar[str | None] = None
    _default_classes: ClassVar[str] = ""

    def __init__(
        self,
        *,
        id: str | None = None,
        id_pattern: str | None = None,
        classes: str = "",
        **kwargs,
    ) -> None:
        """Initialize the base widget.

        Args:
            id: Explicit widget ID. Takes precedence over id_pattern.
            id_pattern: Pattern for auto-generating ID with UUID.
                Supports placeholders: {title}, {name}, {uuid}
                Example: "kpi-{title}-{uuid}" -> "kpi-stats-abc123"
            classes: CSS classes to apply to the widget.
            **kwargs: Additional keyword arguments passed to Widget.
        """
        # Generate ID from pattern if provided and no explicit ID
        if id_pattern and not id:
            id = self._generate_id(id_pattern, **kwargs)

        super().__init__(id=id, classes=classes, **kwargs)

        # Apply default classes after super().__init__ (which already applied `classes`)
        if self._default_classes:
            self.add_class(*self._default_classes.split())

    def _generate_id(self, pattern: str, **kwargs: str) -> str:
        """Generate widget ID from pattern.

        Args:
            pattern: ID pattern with placeholders.
            **kwargs: Values for placeholders (title, name, etc.).

        Returns:
            Generated ID string with UUID suffix.
        """
        import uuid

        # Extract title/name from kwargs if present
        title = kwargs.get("title", "") or kwargs.get("name", "") or "widget"
        name = kwargs.get("name", "") or title

        # Create a short UUID (first 8 characters)
        short_uuid = uuid.uuid4().hex[:8]

        # Replace placeholders
        result = pattern.format(title=title.lower().replace(" ", "-"), name=name, uuid=short_uuid)
        return result

    def add_css_class(self, class_name: str) -> None:
        """Add a CSS class to the widget.

        Args:
            class_name: The CSS class to add.
        """
        self.add_class(class_name)

    def remove_css_class(self, class_name: str) -> None:
        """Remove a CSS class from the widget.

        Args:
            class_name: The CSS class to remove.
        """
        self.remove_class(class_name)

    def has_css_class(self, class_name: str) -> bool:
        """Check if widget has a specific CSS class.

        Args:
            class_name: The CSS class to check.

        Returns:
            True if the class is present.
        """
        return self.has_class(class_name)

    def compose_classes(self, *class_names: str) -> str:
        """Compose a space-separated CSS class string.

        Args:
            *class_names: CSS class names to join.

        Returns:
            Space-separated class string.
        """
        return " ".join(c for c in class_names if c)


class StatefulWidget(BaseWidget):
    """Base class for widgets with standardized reactive state management.

    Provides the standard reactive pattern for all widgets:
    - is_loading: Tracks loading state for async operations
    - data: Holds data loaded from async operations
    - error: Holds error messages from failed operations

    All widgets inheriting from this class MUST implement:
    - watch_is_loading(loading: bool) -> None
    - watch_data(data: list[dict]) -> None
    - watch_error(error: str | None) -> None

    Worker Pattern for Async Data Loading:
        @worker
        async def _load_data(self) -> None:
            self.is_loading = True
            self.error = None
            try:
                result = await self._fetch_data()
                self.data = result
            except Exception as e:
                self.error = str(e)
            finally:
                self.is_loading = False

    Attributes:
        is_loading: Reactive attribute tracking loading state
        data: Reactive attribute holding loaded data
        error: Reactive attribute holding error messages
    """

    # Standard reactive attributes (ALL StatefulWidget subclasses MUST have these)
    is_loading = reactive(False)
    data = reactive[list[dict]]([])
    error = reactive[str | None](None)

    def __init__(self, **kwargs) -> None:
        """Initialize the stateful widget."""
        self._state: dict[str, object] = {}
        super().__init__(**kwargs)

    def watch_is_loading(self, loading: bool) -> None:
        """Update UI based on loading state.

        Override this method in subclasses to provide custom loading UI updates.

        Args:
            loading: The new loading state.
        """
        pass

    def watch_data(self, data: list[dict]) -> None:
        """Update UI when data changes.

        Override this method in subclasses to provide custom data display.

        Args:
            data: The new data value.
        """
        pass

    def watch_error(self, error: str | None) -> None:
        """Handle error state changes.

        Override this method in subclasses to provide custom error handling.

        Args:
            error: The error message or None if cleared.
        """
        pass

    def set_state(self, key: str, value: object) -> None:
        """Set a state value and trigger watchers.

        Args:
            key: State key.
            value: State value.
        """
        self._state[key] = value

    def get_state(self, key: str, default: object = None) -> object:
        """Get a state value.

        Args:
            key: State key.
            default: Default value if key not found.

        Returns:
            The state value or default.
        """
        return self._state.get(key, default)

    def notify_loading_state(self, loading: bool) -> None:
        """Notify loading state to parent or update UI.

        Override in subclasses for custom loading state notification.

        Args:
            loading: The new loading state.
        """
        pass

    def notify_error(self, error: str) -> None:
        """Notify error state to parent or update UI.

        Override in subclasses for custom error notification.

        Args:
            error: The error message.
        """
        pass

    def _fetch_data(self) -> list[dict]:
        """Fetch data for the widget.

        Override this method in subclasses to provide data fetching logic.

        Returns:
            List of dictionaries representing the data.
        """
        return []

    def compose(self) -> ComposeResult:
        """Compose the widget's child widgets.

        Override in subclasses to define widget composition.
        """
        yield from ()
