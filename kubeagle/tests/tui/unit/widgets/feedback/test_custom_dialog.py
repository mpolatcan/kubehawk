"""Tests for CustomDialog widgets."""

from __future__ import annotations

from kubeagle.widgets.feedback.custom_dialog import (
    CustomConfirmDialog,
)


def test_custom_confirm_dialog_instantiation():
    """Test CustomConfirmDialog instantiation."""
    dialog = CustomConfirmDialog(message="Test message")
    assert dialog is not None
    assert dialog._message == "Test message"
    assert dialog._title == "Confirm"


def test_custom_confirm_dialog_with_callbacks():
    """Test CustomConfirmDialog with callbacks."""
    confirm_called = []
    cancel_called = []

    def on_confirm():
        confirm_called.append(True)

    def on_cancel():
        cancel_called.append(True)

    dialog = CustomConfirmDialog(
        message="Test",
        on_confirm=on_confirm,
        on_cancel=on_cancel,
    )
    assert dialog._on_confirm is on_confirm
    assert dialog._on_cancel is on_cancel


def test_custom_dialog_css_path():
    """Test CSS path is set correctly for dialogs."""
    assert CustomConfirmDialog.CSS_PATH.endswith("css/widgets/custom_dialog.tcss")
