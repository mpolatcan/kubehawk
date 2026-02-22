"""Unit tests for scalar constants in constants/values.py.

Tests cover:
- Application constants
- Color constants (hex format)
- Health status markup
- Placeholder strings
"""

from __future__ import annotations

import re

from kubeagle.constants.values import (
    APP_TITLE,
    COLOR_ACCENT,
    COLOR_SECONDARY,
    DEGRADED,
    HEALTHY,
    PLACEHOLDER_ACTIVE_CHARTS,
    PLACEHOLDER_AI_FIX_BULK_PARALLELISM,
    PLACEHOLDER_CHARTS_PATH,
    PLACEHOLDER_CODEOWNERS,
    PLACEHOLDER_EVENT_AGE,
    PLACEHOLDER_EXPORT_PATH,
    PLACEHOLDER_LIMIT_REQUEST,
    PLACEHOLDER_REFRESH_INTERVAL,
    PLACEHOLDER_THRESHOLD,
    UNHEALTHY,
)

# =============================================================================
# Application
# =============================================================================


class TestApplicationConstants:
    """Test application-level constants."""

    def test_app_title_type(self) -> None:
        assert isinstance(APP_TITLE, str)

    def test_app_title_value(self) -> None:
        assert APP_TITLE == "KubEagle"

    def test_app_title_non_empty(self) -> None:
        assert len(APP_TITLE) > 0


# =============================================================================
# Colors
# =============================================================================


HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

ALL_COLORS = [
    ("COLOR_SECONDARY", COLOR_SECONDARY, "#6C757D"),
    ("COLOR_ACCENT", COLOR_ACCENT, "#17A2B8"),
]


class TestColorConstants:
    """Test color hex string constants."""

    def test_color_secondary_value(self) -> None:
        assert COLOR_SECONDARY == "#6C757D"

    def test_color_accent_value(self) -> None:
        assert COLOR_ACCENT == "#17A2B8"

    def test_all_colors_are_strings(self) -> None:
        for name, color, _ in ALL_COLORS:
            assert isinstance(color, str), f"{name} must be a string"

    def test_all_colors_are_valid_hex(self) -> None:
        for name, color, _ in ALL_COLORS:
            assert HEX_COLOR_PATTERN.match(color), f"{name} ({color}) must be valid hex #RRGGBB"


# =============================================================================
# Health status markup
# =============================================================================


class TestHealthStatusMarkup:
    """Test health status rich text markup constants."""

    def test_healthy_type(self) -> None:
        assert isinstance(HEALTHY, str)

    def test_healthy_contains_green(self) -> None:
        assert "[green]" in HEALTHY

    def test_healthy_contains_healthy(self) -> None:
        assert "HEALTHY" in HEALTHY

    def test_degraded_type(self) -> None:
        assert isinstance(DEGRADED, str)

    def test_degraded_contains_yellow(self) -> None:
        assert "[yellow]" in DEGRADED

    def test_degraded_contains_degraded(self) -> None:
        assert "DEGRADED" in DEGRADED

    def test_unhealthy_type(self) -> None:
        assert isinstance(UNHEALTHY, str)

    def test_unhealthy_contains_red(self) -> None:
        assert "[red]" in UNHEALTHY

    def test_unhealthy_contains_unhealthy(self) -> None:
        assert "UNHEALTHY" in UNHEALTHY


# =============================================================================
# Placeholders
# =============================================================================


class TestPlaceholderConstants:
    """Test settings screen placeholder constants."""

    def test_placeholder_charts_path_type(self) -> None:
        assert isinstance(PLACEHOLDER_CHARTS_PATH, str)

    def test_placeholder_charts_path_non_empty(self) -> None:
        assert len(PLACEHOLDER_CHARTS_PATH) > 0

    def test_placeholder_active_charts_type(self) -> None:
        assert isinstance(PLACEHOLDER_ACTIVE_CHARTS, str)

    def test_placeholder_codeowners_type(self) -> None:
        assert isinstance(PLACEHOLDER_CODEOWNERS, str)

    def test_placeholder_refresh_interval_type(self) -> None:
        assert isinstance(PLACEHOLDER_REFRESH_INTERVAL, str)

    def test_placeholder_export_path_type(self) -> None:
        assert isinstance(PLACEHOLDER_EXPORT_PATH, str)

    def test_placeholder_event_age_type(self) -> None:
        assert isinstance(PLACEHOLDER_EVENT_AGE, str)

    def test_placeholder_threshold_type(self) -> None:
        assert isinstance(PLACEHOLDER_THRESHOLD, str)

    def test_placeholder_limit_request_type(self) -> None:
        assert isinstance(PLACEHOLDER_LIMIT_REQUEST, str)

    def test_placeholder_ai_fix_bulk_parallelism_type(self) -> None:
        assert isinstance(PLACEHOLDER_AI_FIX_BULK_PARALLELISM, str)

    def test_all_placeholders_non_empty(self) -> None:
        placeholders = [
            PLACEHOLDER_CHARTS_PATH,
            PLACEHOLDER_ACTIVE_CHARTS,
            PLACEHOLDER_CODEOWNERS,
            PLACEHOLDER_REFRESH_INTERVAL,
            PLACEHOLDER_EXPORT_PATH,
            PLACEHOLDER_EVENT_AGE,
            PLACEHOLDER_THRESHOLD,
            PLACEHOLDER_LIMIT_REQUEST,
            PLACEHOLDER_AI_FIX_BULK_PARALLELISM,
        ]
        for p in placeholders:
            assert len(p) > 0, f"Placeholder must not be empty: {p!r}"


# =============================================================================
# __all__ exports
# =============================================================================


class TestValuesExports:
    """Test that __all__ exports are correct."""

    def test_all_exports_importable(self) -> None:
        import kubeagle.constants.values as mod

        for name in mod.__all__:
            assert hasattr(mod, name), f"{name} listed in __all__ but not defined"
