"""Tests for base widget classes (_base.py).

Covers BaseWidget and StatefulWidget class
attributes, methods, CSS utilities, reactive state, and ID generation.
"""

from __future__ import annotations

from kubeagle.widgets._base import (
    BaseWidget,
    StatefulWidget,
)

# ===========================================================================
# TestBaseWidget
# ===========================================================================


class TestBaseWidget:
    """Tests for BaseWidget class."""

    def test_base_widget_instantiation(self) -> None:
        """BaseWidget should instantiate without errors."""
        widget = BaseWidget()
        assert widget is not None

    def test_base_widget_with_id(self) -> None:
        """BaseWidget should accept explicit id."""
        widget = BaseWidget(id="test-widget")
        assert widget.id == "test-widget"

    def test_base_widget_with_classes(self) -> None:
        """BaseWidget should accept CSS classes."""
        widget = BaseWidget(classes="foo bar")
        assert "foo" in widget.classes
        assert "bar" in widget.classes

    def test_add_css_class_method_exists(self) -> None:
        """add_css_class method should exist on BaseWidget."""
        assert hasattr(BaseWidget, "add_css_class")
        assert callable(BaseWidget.add_css_class)

    def test_remove_css_class_method_exists(self) -> None:
        """remove_css_class method should exist on BaseWidget."""
        assert hasattr(BaseWidget, "remove_css_class")
        assert callable(BaseWidget.remove_css_class)

    def test_has_css_class_method_exists(self) -> None:
        """has_css_class method should exist on BaseWidget."""
        assert hasattr(BaseWidget, "has_css_class")
        assert callable(BaseWidget.has_css_class)

    def test_add_css_class_works(self) -> None:
        """add_css_class should add a CSS class to the widget."""
        widget = BaseWidget(classes="initial")
        widget.add_css_class("added")
        assert "added" in widget.classes
        assert "initial" in widget.classes

    def test_add_css_class_duplicate(self) -> None:
        """add_css_class with an already-present class should not error."""
        widget = BaseWidget(classes="existing")
        widget.add_css_class("existing")
        assert "existing" in widget.classes

    def test_remove_css_class_works(self) -> None:
        """remove_css_class should remove a CSS class from the widget."""
        widget = BaseWidget(classes="keep remove-me")
        widget.remove_css_class("remove-me")
        assert "remove-me" not in widget.classes
        assert "keep" in widget.classes

    def test_remove_css_class_nonexistent(self) -> None:
        """remove_css_class with a missing class should not error."""
        widget = BaseWidget(classes="keep")
        widget.remove_css_class("nonexistent")
        assert "keep" in widget.classes

    def test_has_css_class_works(self) -> None:
        """has_css_class should return True for present classes."""
        widget = BaseWidget(classes="present")
        assert widget.has_css_class("present") is True

    def test_has_css_class_returns_false_for_missing(self) -> None:
        """has_css_class should return False for absent classes."""
        widget = BaseWidget(classes="present")
        assert widget.has_css_class("absent") is False

    def test_compose_classes(self) -> None:
        """compose_classes should join non-empty class names."""
        widget = BaseWidget()
        result = widget.compose_classes("a", "b", "", "c")
        assert result == "a b c"

    def test_compose_classes_all_empty(self) -> None:
        """compose_classes with all empty strings should return empty."""
        widget = BaseWidget()
        result = widget.compose_classes("", "", "")
        assert result == ""

    def test_generate_id_returns_string(self) -> None:
        """_generate_id should return a string."""
        widget = BaseWidget()
        result = widget._generate_id("test-{uuid}")
        assert isinstance(result, str)
        assert result.startswith("test-")

    def test_generate_id_with_title(self) -> None:
        """_generate_id should substitute title placeholder."""
        widget = BaseWidget()
        result = widget._generate_id("card-{title}-{uuid}", title="Stats")
        assert "card-stats-" in result

    def test_generate_id_unique(self) -> None:
        """_generate_id should produce unique IDs on repeated calls."""
        widget = BaseWidget()
        id1 = widget._generate_id("w-{uuid}")
        id2 = widget._generate_id("w-{uuid}")
        assert id1 != id2

    def test_css_path_default_none(self) -> None:
        """CSS_PATH should default to None on BaseWidget."""
        assert BaseWidget.CSS_PATH is None

    def test_default_classes_empty(self) -> None:
        """_default_classes should default to empty string."""
        assert BaseWidget._default_classes == ""


# ===========================================================================
# TestStatefulWidget
# ===========================================================================


class TestStatefulWidget:
    """Tests for StatefulWidget class with reactive state."""

    def test_stateful_widget_instantiation(self) -> None:
        """StatefulWidget should instantiate without errors."""
        widget = StatefulWidget()
        assert widget is not None

    def test_stateful_widget_is_base_widget(self) -> None:
        """StatefulWidget should be a subclass of BaseWidget."""
        assert issubclass(StatefulWidget, BaseWidget)

    def test_stateful_widget_has_is_loading(self) -> None:
        """StatefulWidget should have is_loading reactive attribute."""
        assert hasattr(StatefulWidget, "is_loading")

    def test_stateful_widget_has_data(self) -> None:
        """StatefulWidget should have data reactive attribute."""
        assert hasattr(StatefulWidget, "data")

    def test_stateful_widget_has_error(self) -> None:
        """StatefulWidget should have error reactive attribute."""
        assert hasattr(StatefulWidget, "error")

    def test_set_state(self) -> None:
        """set_state should store a value retrievable with get_state."""
        widget = StatefulWidget()
        widget.set_state("key", "value")
        assert widget.get_state("key") == "value"

    def test_get_state_default(self) -> None:
        """get_state should return default when key is absent."""
        widget = StatefulWidget()
        assert widget.get_state("missing", "default_val") == "default_val"

    def test_get_state_none_default(self) -> None:
        """get_state should return None by default when key is absent."""
        widget = StatefulWidget()
        assert widget.get_state("missing") is None

    def test_set_state_overwrite(self) -> None:
        """set_state should overwrite existing values."""
        widget = StatefulWidget()
        widget.set_state("key", "old")
        widget.set_state("key", "new")
        assert widget.get_state("key") == "new"

    def test_has_watch_is_loading(self) -> None:
        """StatefulWidget should have watch_is_loading method."""
        assert hasattr(StatefulWidget, "watch_is_loading")
        assert callable(StatefulWidget.watch_is_loading)

    def test_has_watch_data(self) -> None:
        """StatefulWidget should have watch_data method."""
        assert hasattr(StatefulWidget, "watch_data")
        assert callable(StatefulWidget.watch_data)

    def test_has_watch_error(self) -> None:
        """StatefulWidget should have watch_error method."""
        assert hasattr(StatefulWidget, "watch_error")
        assert callable(StatefulWidget.watch_error)

    def test_has_notify_loading_state(self) -> None:
        """StatefulWidget should have notify_loading_state method."""
        assert hasattr(StatefulWidget, "notify_loading_state")
        assert callable(StatefulWidget.notify_loading_state)

    def test_has_notify_error(self) -> None:
        """StatefulWidget should have notify_error method."""
        assert hasattr(StatefulWidget, "notify_error")
        assert callable(StatefulWidget.notify_error)

    def test_has_fetch_data(self) -> None:
        """StatefulWidget should have _fetch_data method."""
        assert hasattr(StatefulWidget, "_fetch_data")
        assert callable(StatefulWidget._fetch_data)

    def test_fetch_data_returns_empty_list(self) -> None:
        """Default _fetch_data should return empty list."""
        widget = StatefulWidget()
        assert widget._fetch_data() == []

    def test_has_compose(self) -> None:
        """StatefulWidget should have compose method."""
        assert hasattr(StatefulWidget, "compose")
        assert callable(StatefulWidget.compose)

    def test_internal_state_dict_initialized(self) -> None:
        """StatefulWidget should initialize _state as empty dict."""
        widget = StatefulWidget()
        assert isinstance(widget._state, dict)
        assert len(widget._state) == 0


