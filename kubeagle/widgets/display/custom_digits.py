"""CustomDigits widget for the TUI application.

Standard Wrapper Pattern:
- Wraps Textual's Digits with standardized styling
- Supports alignment: left, center, right
- Configurable value display

CSS Classes: widget-custom-digits
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from contextlib import suppress

from textual.timer import Timer
from textual.widgets import Digits as TextualDigits

# Pre-computed cosine ease-in-out values for counter animation.
# Index i maps to eased progress for step (i+1) out of 12 max steps.
_EASING_TABLE: tuple[float, ...] = tuple(
    0.5 - (0.5 * math.cos(math.pi * ((i + 1) / 12)))
    for i in range(12)
)


class CustomDigits(TextualDigits):
    """Custom digits display widget with standardized styling.

    Wraps Textual's Digits widget with consistent styling across the application.

    CSS Classes: widget-custom-digits

    Alignment:
        - left: Left-aligned digits (default)
        - center: Center-aligned digits
        - right: Right-aligned digits

    Supported Characters:
        - Textual Digits-supported character set

    Example:
        >>> digits = CustomDigits("3.14159")
        >>> yield digits
    """

    CSS_PATH = "../../css/widgets/custom_digits.tcss"
    _UPDATE_ANIMATION_CLASS = "value-updated"
    _DEFAULT_UPDATE_ANIMATION_SECONDS = 0.45
    _COUNTER_SMOOTH_EXTRA_SECONDS = 0.65
    _COUNTER_MAX_STEPS = 12
    _COUNTER_MIN_FRAME_SECONDS = 0.03
    _COUNTER_MAX_FRAME_SECONDS = 0.08
    _ANIMATABLE_VALUE_RE = re.compile(
        r"^\s*(?P<prefix>[^\d+\-]*?)"
        r"(?P<number>[-+]?\d+(?:\.\d+)?)"
        r"(?P<suffix>[^\d]*)\s*$"
    )
    # Reference to module-level pre-computed easing table for counter animation.
    _EASING_TABLE = _EASING_TABLE

    @staticmethod
    def _has_non_ascii(text: str) -> bool:
        """Return True when text contains non-ASCII glyphs (for example emoji)."""
        return any(ord(char) > 127 for char in text)

    @classmethod
    def _should_counter_animate(
        cls,
        *,
        prefix: str,
        suffix: str,
        decimals: int,
    ) -> bool:
        """Decide whether stepped counter animation is visually safe.

        High-precision values with emoji/non-ASCII decorations can appear to
        shift during frame-by-frame updates, so we fall back to pulse-only
        animation in that case.
        """
        return not (
            decimals >= 3
            and (cls._has_non_ascii(prefix) or cls._has_non_ascii(suffix))
        )

    def __init__(
        self,
        value: str = "",
        align: str = "left",
        emphasis: str | None = None,
        id: str | None = None,
        classes: str = "",
        disabled: bool = False,
    ) -> None:
        """Initialize the custom digits widget.

        Args:
            value: Numerical value to display.
            align: Text alignment (left, center, right).
            emphasis: Optional emphasis style (muted, accent, success, warning, error, highlight, inverse).
            id: Widget ID.
            classes: CSS classes.
            disabled: Whether the widget is disabled.
        """
        super().__init__(value, id=id, classes=classes, disabled=disabled)
        self._value: str = value
        self._update_animation_timer: Timer | None = None
        self._counter_animation_timer: Timer | None = None
        self._counter_animation_token = 0

        # Build alignment class
        align_class = f"align-{align}" if align != "left" else "align-left"

        # Apply alignment and emphasis classes as separate identifiers.
        self.add_class(align_class)
        if emphasis:
            self.add_class(emphasis)

    def on_unmount(self) -> None:
        """Stop animation timers to prevent leaked timers after widget removal."""
        self._stop_counter_animation()
        if self._update_animation_timer is not None:
            with suppress(Exception):
                self._update_animation_timer.stop()
            self._update_animation_timer = None

    @property
    def value(self) -> str:
        """Get the current displayed value.

        Returns:
            The displayed value.
        """
        return self._value

    @value.setter
    def value(self, val: str) -> None:
        """Set the displayed value.

        Args:
            val: New value to display.
        """
        self._value = val
        self.update(val)

    def update(self, value: str) -> None:
        """Update the digits with a new value.

        Args:
            value: New value to display.
        """
        self._stop_counter_animation()
        self._set_display_value(str(value))

    @staticmethod
    def _parse_animatable_value(
        value: str,
    ) -> tuple[str, float, int, str] | None:
        """Parse animatable numeric value with optional prefix/suffix."""
        match = CustomDigits._ANIMATABLE_VALUE_RE.match(value)
        if not match:
            return None
        number_text = match.group("number")
        with suppress(ValueError):
            numeric_value = float(number_text)
            decimals = len(number_text.split(".", 1)[1]) if "." in number_text else 0
            return (
                match.group("prefix"),
                numeric_value,
                decimals,
                match.group("suffix"),
            )
        return None

    @staticmethod
    def _format_animatable_value(
        prefix: str,
        numeric_value: float,
        decimals: int,
        suffix: str,
    ) -> str:
        """Format one animation frame while preserving prefix/suffix style."""
        if decimals <= 0:
            frame_value = str(round(numeric_value))
        else:
            frame_value = f"{numeric_value:.{decimals}f}"
        return f"{prefix}{frame_value}{suffix}"

    def _set_display_value(self, value: str) -> None:
        """Set displayed value without touching animation timers."""
        self._value = value
        super().update(value)

    def _stop_counter_animation(self) -> None:
        """Stop in-flight counter animation ticks."""
        self._counter_animation_token += 1
        if self._counter_animation_timer is not None:
            with suppress(Exception):
                self._counter_animation_timer.stop()
            self._counter_animation_timer = None

    def _schedule_update_animation_clear(self, duration: float | None) -> None:
        """Schedule clearing update animation CSS class."""
        if self._update_animation_timer is not None:
            with suppress(Exception):
                self._update_animation_timer.stop()
            self._update_animation_timer = None

        if not self.is_mounted:
            self._clear_update_animation()
            return

        animation_seconds = (
            self._DEFAULT_UPDATE_ANIMATION_SECONDS
            if duration is None
            else max(0.05, duration)
        )
        try:
            self._update_animation_timer = self.set_timer(
                animation_seconds,
                self._clear_update_animation,
            )
        except Exception:
            self._clear_update_animation()

    def _start_counter_animation(
        self,
        current_numeric: float,
        target_numeric: float,
        *,
        target_text: str,
        prefix: str,
        suffix: str,
        decimals: int,
        duration: float | None,
        on_complete: Callable[[], None] | None,
    ) -> None:
        """Animate numeric values with intermediate counter steps."""
        self._stop_counter_animation()
        self.remove_class(self._UPDATE_ANIMATION_CLASS)
        self.add_class(self._UPDATE_ANIMATION_CLASS)

        delta = target_numeric - current_numeric
        if decimals > 0:
            precision_scale = 10**decimals
            estimated_steps = round(abs(delta) * precision_scale)
            steps = max(1, min(estimated_steps, self._COUNTER_MAX_STEPS))
        else:
            steps = max(1, min(round(abs(delta)), self._COUNTER_MAX_STEPS))
        if duration is None:
            step_ratio = steps / self._COUNTER_MAX_STEPS
            total_seconds = self._DEFAULT_UPDATE_ANIMATION_SECONDS + (
                (step_ratio**1.15) * self._COUNTER_SMOOTH_EXTRA_SECONDS
            )
            total_seconds = min(1.2, total_seconds)
        else:
            total_seconds = max(0.05, duration)
        frame_seconds = max(
            self._COUNTER_MIN_FRAME_SECONDS,
            min(self._COUNTER_MAX_FRAME_SECONDS, total_seconds / steps),
        )
        token = self._counter_animation_token
        step_index = 0

        def _tick() -> None:
            nonlocal step_index
            if token != self._counter_animation_token:
                return
            if not self.is_mounted:
                self._counter_animation_timer = None
                self._clear_update_animation()
                return

            step_index += 1
            if step_index >= steps:
                self._counter_animation_timer = None
                self._set_display_value(target_text)
                if on_complete is not None:
                    with suppress(Exception):
                        on_complete()
                self._schedule_update_animation_clear(max(0.12, total_seconds * 0.25))
                return

            # Look up pre-computed easing value; scale index to match table size.
            table_index = round(step_index * (CustomDigits._COUNTER_MAX_STEPS - 1) / steps)
            table_index = min(table_index, CustomDigits._COUNTER_MAX_STEPS - 1)
            eased_progress = CustomDigits._EASING_TABLE[table_index]
            interpolated = current_numeric + (delta * eased_progress)
            self._set_display_value(
                self._format_animatable_value(
                    prefix,
                    interpolated,
                    decimals,
                    suffix,
                )
            )
            self._counter_animation_timer = self.set_timer(frame_seconds, _tick)

        self._counter_animation_timer = self.set_timer(frame_seconds, _tick)

    def update_with_animation(
        self,
        value: str,
        *,
        duration: float | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Update digits and trigger a short value-change animation.

        Args:
            value: New display value.
            duration: Optional pulse/counter animation duration in seconds.
            on_complete: Optional callback invoked after the final value is set.
        """
        current_animatable = self._parse_animatable_value(self._value)
        target_animatable = self._parse_animatable_value(value)

        if (
            current_animatable is not None
            and target_animatable is not None
            and self.is_mounted
        ):
            current_prefix, current_numeric, current_decimals, current_suffix = current_animatable
            target_prefix, target_numeric, target_decimals, target_suffix = target_animatable
            if (
                current_prefix == target_prefix
                and current_suffix == target_suffix
                and current_numeric != target_numeric
                and self._should_counter_animate(
                    prefix=target_prefix,
                    suffix=target_suffix,
                    decimals=max(current_decimals, target_decimals),
                )
            ):
                self._start_counter_animation(
                    current_numeric,
                    target_numeric,
                    target_text=value,
                    prefix=target_prefix,
                    suffix=target_suffix,
                    decimals=max(current_decimals, target_decimals),
                    duration=duration,
                    on_complete=on_complete,
                )
                return

        self.update(value)
        if on_complete is not None:
            with suppress(Exception):
                on_complete()
        self.animate_update(duration=duration)

    def _clear_update_animation(self) -> None:
        """Remove transient update animation state."""
        self._update_animation_timer = None
        self.remove_class(self._UPDATE_ANIMATION_CLASS)

    def animate_update(self, *, duration: float | None = None) -> None:
        """Animate a short pulse to indicate the value has changed."""
        self._stop_counter_animation()
        self.remove_class(self._UPDATE_ANIMATION_CLASS)
        self.add_class(self._UPDATE_ANIMATION_CLASS)
        self._schedule_update_animation_clear(duration)
