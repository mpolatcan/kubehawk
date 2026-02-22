"""Unit tests for all enum definitions in constants/enums.py.

Tests cover:
- Each enum class and all its members
- Value correctness
- Membership tests
- String representation
"""

from __future__ import annotations

from enum import Enum

import pytest

from kubeagle.constants.enums import (
    AppState,
    FetchState,
    NodeStatus,
    QoSClass,
    Severity,
    SortBy,
    ThemeMode,
    ViewFilter,
    WidgetCategory,
)

# =============================================================================
# NodeStatus
# =============================================================================


class TestNodeStatus:
    """Test NodeStatus enum."""

    def test_is_enum(self) -> None:
        assert issubclass(NodeStatus, Enum)

    def test_members_count(self) -> None:
        assert len(NodeStatus) == 3

    def test_ready_value(self) -> None:
        assert NodeStatus.READY.value == "Ready"

    def test_not_ready_value(self) -> None:
        assert NodeStatus.NOT_READY.value == "NotReady"

    def test_unknown_value(self) -> None:
        assert NodeStatus.UNKNOWN.value == "Unknown"

    def test_membership(self) -> None:
        assert NodeStatus("Ready") is NodeStatus.READY

    def test_invalid_membership(self) -> None:
        with pytest.raises(ValueError):
            NodeStatus("invalid")

    def test_string_representation(self) -> None:
        assert "READY" in repr(NodeStatus.READY)


# =============================================================================
# QoSClass
# =============================================================================


class TestQoSClass:
    """Test QoSClass enum."""

    def test_is_enum(self) -> None:
        assert issubclass(QoSClass, Enum)

    def test_members_count(self) -> None:
        assert len(QoSClass) == 3

    def test_guaranteed_value(self) -> None:
        assert QoSClass.GUARANTEED.value == "Guaranteed"

    def test_burstable_value(self) -> None:
        assert QoSClass.BURSTABLE.value == "Burstable"

    def test_best_effort_value(self) -> None:
        assert QoSClass.BEST_EFFORT.value == "BestEffort"

    def test_membership(self) -> None:
        assert QoSClass("Burstable") is QoSClass.BURSTABLE


# =============================================================================
# Severity
# =============================================================================


class TestSeverity:
    """Test Severity enum."""

    def test_is_enum(self) -> None:
        assert issubclass(Severity, Enum)

    def test_members_count(self) -> None:
        assert len(Severity) == 3

    def test_error_value(self) -> None:
        assert Severity.ERROR.value == "error"

    def test_warning_value(self) -> None:
        assert Severity.WARNING.value == "warning"

    def test_info_value(self) -> None:
        assert Severity.INFO.value == "info"


# =============================================================================
# AppState
# =============================================================================


class TestAppState:
    """Test AppState enum."""

    def test_is_enum(self) -> None:
        assert issubclass(AppState, Enum)

    def test_members_count(self) -> None:
        assert len(AppState) == 4

    def test_idle_value(self) -> None:
        assert AppState.IDLE.value == "idle"

    def test_loading_value(self) -> None:
        assert AppState.LOADING.value == "loading"

    def test_error_value(self) -> None:
        assert AppState.ERROR.value == "error"

    def test_stale_value(self) -> None:
        assert AppState.STALE.value == "stale"


# =============================================================================
# FetchState
# =============================================================================


class TestFetchState:
    """Test FetchState enum."""

    def test_is_enum(self) -> None:
        assert issubclass(FetchState, Enum)

    def test_members_count(self) -> None:
        assert len(FetchState) == 3

    def test_loading_value(self) -> None:
        assert FetchState.LOADING.value == "loading"

    def test_success_value(self) -> None:
        assert FetchState.SUCCESS.value == "success"

    def test_error_value(self) -> None:
        assert FetchState.ERROR.value == "error"


# =============================================================================
# ThemeMode
# =============================================================================


class TestThemeMode:
    """Test ThemeMode enum."""

    def test_is_enum(self) -> None:
        assert issubclass(ThemeMode, Enum)

    def test_members_count(self) -> None:
        assert len(ThemeMode) == 2

    def test_dark_value(self) -> None:
        assert ThemeMode.DARK.value == "dark"

    def test_light_value(self) -> None:
        assert ThemeMode.LIGHT.value == "light"


# =============================================================================
# ViewFilter
# =============================================================================


class TestViewFilter:
    """Test ViewFilter enum."""

    def test_is_enum(self) -> None:
        assert issubclass(ViewFilter, Enum)

    def test_members_count(self) -> None:
        assert len(ViewFilter) == 5

    def test_all_value(self) -> None:
        assert ViewFilter.ALL.value == "all"

    def test_extreme_ratios_value(self) -> None:
        assert ViewFilter.EXTREME_RATIOS.value == "extreme_ratios"

    def test_single_replica_value(self) -> None:
        assert ViewFilter.SINGLE_REPLICA.value == "single_replica"

    def test_no_pdb_value(self) -> None:
        assert ViewFilter.NO_PDB.value == "no_pdb"

    def test_with_violations_value(self) -> None:
        assert ViewFilter.WITH_VIOLATIONS.value == "with_violations"


# =============================================================================
# SortBy
# =============================================================================


class TestSortBy:
    """Test SortBy enum."""

    def test_is_enum(self) -> None:
        assert issubclass(SortBy, Enum)

    def test_members_count(self) -> None:
        assert len(SortBy) == 12

    def test_chart_value(self) -> None:
        assert SortBy.CHART.value == "chart"

    def test_team_value(self) -> None:
        assert SortBy.TEAM.value == "team"


# =============================================================================
# WidgetCategory
# =============================================================================


class TestWidgetCategory:
    """Test WidgetCategory enum."""

    def test_is_enum(self) -> None:
        assert issubclass(WidgetCategory, Enum)

    def test_members_count(self) -> None:
        assert len(WidgetCategory) == 6


# =============================================================================
# __all__ exports
# =============================================================================


class TestEnumsExports:
    """Test that __all__ exports are correct."""

    def test_all_exports_importable(self) -> None:
        """All items in __all__ should be importable from the module."""
        import kubeagle.constants.enums as mod

        for name in mod.__all__:
            assert hasattr(mod, name), f"{name} listed in __all__ but not defined"
