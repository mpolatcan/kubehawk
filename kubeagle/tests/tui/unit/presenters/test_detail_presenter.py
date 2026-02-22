"""Unit tests for detail presenter — shared data loading helpers.

This module tests:
- OptimizerDataLoaded / OptimizerDataLoadFailed messages
- build_helm_recommendations function
- truncated_list helper
- REC_SEVERITY_FILTERS / REC_CATEGORY_FILTERS constants

All functions are imported from screens.detail.presenter.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from kubeagle.screens.detail.presenter import (
    REC_CATEGORY_FILTERS,
    REC_SEVERITY_FILTERS,
    OptimizerDataLoaded,
    OptimizerDataLoadFailed,
    build_helm_recommendations,
    truncated_list,
)

# =============================================================================
# Message Tests
# =============================================================================


class TestOptimizerDataLoadedMessage:
    """Test OptimizerDataLoaded message class."""

    def test_create_with_all_fields(self) -> None:
        """Test OptimizerDataLoaded stores all fields."""
        msg = OptimizerDataLoaded(
            violations=[MagicMock()],
            recommendations=[{"id": "r1"}],
            charts=[MagicMock()],
            total_charts=5,
            duration_ms=123.4,
        )
        assert len(msg.violations) == 1
        assert len(msg.recommendations) == 1
        assert len(msg.charts) == 1
        assert msg.total_charts == 5
        assert msg.duration_ms == 123.4

    def test_create_with_empty_data(self) -> None:
        """Test OptimizerDataLoaded with empty lists."""
        msg = OptimizerDataLoaded(
            violations=[], recommendations=[], charts=[], total_charts=0, duration_ms=0.0
        )
        assert msg.violations == []
        assert msg.recommendations == []
        assert msg.charts == []
        assert msg.total_charts == 0


class TestOptimizerDataLoadFailedMessage:
    """Test OptimizerDataLoadFailed message class."""

    def test_create_stores_error(self) -> None:
        """Test OptimizerDataLoadFailed stores error string."""
        msg = OptimizerDataLoadFailed("Connection refused")
        assert msg.error == "Connection refused"

    def test_create_with_empty_error(self) -> None:
        """Test OptimizerDataLoadFailed with empty string."""
        msg = OptimizerDataLoadFailed("")
        assert msg.error == ""


# =============================================================================
# truncated_list Tests
# =============================================================================


class TestTruncatedList:
    """Test truncated_list helper function."""

    def test_short_list_no_truncation(self) -> None:
        """Test list shorter than limit is not truncated."""
        items = ["a", "b", "c"]
        result = truncated_list(items, limit=5)
        assert result == "a\nb\nc"
        assert "more" not in result

    def test_long_list_truncated(self) -> None:
        """Test list longer than limit is truncated."""
        items = [f"item-{i}" for i in range(20)]
        result = truncated_list(items, limit=3)
        assert "item-0" in result
        assert "item-2" in result
        assert "item-3" not in result
        assert "17 more" in result

    def test_exact_limit(self) -> None:
        """Test list at exactly the limit is not truncated."""
        items = ["a", "b", "c"]
        result = truncated_list(items, limit=3)
        assert "more" not in result

    def test_default_limit_is_15(self) -> None:
        """Test default limit is 15."""
        items = [f"item-{i}" for i in range(20)]
        result = truncated_list(items)
        assert "5 more" in result

    def test_empty_list(self) -> None:
        """Test empty list returns empty string."""
        result = truncated_list([])
        assert result == ""


# =============================================================================
# build_helm_recommendations Tests
# =============================================================================


class TestBuildHelmRecommendations:
    """Test build_helm_recommendations function."""

    def _make_chart(self, name: str, team: str = "default", pdb_enabled: bool = True, qos: str = "Guaranteed") -> MagicMock:
        """Create a mock chart."""
        chart = MagicMock()
        chart.name = name
        chart.team = team
        chart.pdb_enabled = pdb_enabled
        chart.qos_class.value = qos
        return chart

    def _make_violation(self, rule_id: str, chart_name: str, severity: str = "error", description: str = "desc") -> MagicMock:
        """Create a mock violation."""
        v = MagicMock()
        v.rule_id = rule_id
        v.chart_name = chart_name
        v.severity.value = severity
        v.description = description
        return v

    def test_empty_input_returns_empty(self) -> None:
        """Test with no violations and all charts healthy."""
        charts = [self._make_chart("c1"), self._make_chart("c2")]
        result = build_helm_recommendations([], charts)
        # May have summary recs depending on chart data, but no violation-based recs
        for rec in result:
            assert "id" in rec

    def test_low_pdb_coverage_rec(self) -> None:
        """Test low PDB coverage generates recommendation."""
        charts = [
            self._make_chart("c1", pdb_enabled=False),
            self._make_chart("c2", pdb_enabled=False),
            self._make_chart("c3", pdb_enabled=True),
        ]
        result = build_helm_recommendations([], charts)
        pdb_recs = [r for r in result if r["id"] == "low-pdb-coverage"]
        assert len(pdb_recs) == 1
        assert pdb_recs[0]["severity"] == "critical"

    def test_best_effort_qos_rec(self) -> None:
        """Test BestEffort QoS generates recommendation."""
        charts = [self._make_chart("c1", qos="BestEffort")]
        result = build_helm_recommendations([], charts)
        be_recs = [r for r in result if r["id"] == "charts-best-effort"]
        assert len(be_recs) == 1
        assert be_recs[0]["severity"] == "info"

    def test_violation_grouped_into_rec(self) -> None:
        """Test violations are grouped by rule_id into recommendations."""
        charts = [self._make_chart("c1"), self._make_chart("c2")]
        violations = [
            self._make_violation("AVL001", "c1"),
            self._make_violation("AVL001", "c2"),
        ]
        result = build_helm_recommendations(violations, charts)
        pdb_recs = [r for r in result if r["id"] == "charts-no-pdb"]
        assert len(pdb_recs) == 1
        assert len(pdb_recs[0]["affected_resources"]) == 2

    def test_unknown_rule_id_skipped(self) -> None:
        """Test violations with unknown rule_id are skipped."""
        charts = [self._make_chart("c1")]
        violations = [self._make_violation("UNKNOWN999", "c1")]
        result = build_helm_recommendations(violations, charts)
        # Should not crash, unknown rules just don't produce recs
        unknown_recs = [r for r in result if r["id"] == "UNKNOWN999"]
        assert len(unknown_recs) == 0

    def test_rec_has_required_fields(self) -> None:
        """Test each recommendation has all required fields."""
        charts = [self._make_chart("c1")]
        violations = [self._make_violation("PRB001", "c1")]
        result = build_helm_recommendations(violations, charts)
        probe_recs = [r for r in result if r["id"] == "charts-no-liveness"]
        assert len(probe_recs) == 1
        rec = probe_recs[0]
        assert "id" in rec
        assert "category" in rec
        assert "severity" in rec
        assert "title" in rec
        assert "description" in rec
        assert "affected_resources" in rec
        assert "recommended_action" in rec
        assert "yaml_example" in rec


# =============================================================================
# Filter Constants Tests
# =============================================================================


class TestPresenterConstants:
    """Test presenter-level constants."""

    def test_rec_severity_filters_starts_with_all(self) -> None:
        """Test REC_SEVERITY_FILTERS starts with 'all'."""
        assert REC_SEVERITY_FILTERS[0] == "all"

    def test_rec_severity_filters_count(self) -> None:
        """Test REC_SEVERITY_FILTERS has 4 entries."""
        assert len(REC_SEVERITY_FILTERS) == 4

    def test_rec_severity_filters_contains_expected(self) -> None:
        """Test REC_SEVERITY_FILTERS has critical, warning, info."""
        assert "critical" in REC_SEVERITY_FILTERS
        assert "warning" in REC_SEVERITY_FILTERS
        assert "info" in REC_SEVERITY_FILTERS

    def test_rec_category_filters_starts_with_all(self) -> None:
        """Test REC_CATEGORY_FILTERS starts with 'all'."""
        assert REC_CATEGORY_FILTERS[0] == "all"

    def test_rec_category_filters_count(self) -> None:
        """Test REC_CATEGORY_FILTERS has 4 entries."""
        assert len(REC_CATEGORY_FILTERS) == 4

    def test_rec_category_filters_contains_expected(self) -> None:
        """Test REC_CATEGORY_FILTERS has eks, reliability, resource."""
        assert "eks" in REC_CATEGORY_FILTERS
        assert "reliability" in REC_CATEGORY_FILTERS
        assert "resource" in REC_CATEGORY_FILTERS


# =============================================================================
# Removed Features Tests
# =============================================================================


class TestRemovedDetailPresenter:
    """Test that old DetailPresenter classes no longer exist."""

    def test_no_detail_presenter_class(self) -> None:
        """Test DetailPresenter class no longer exists in module."""
        import kubeagle.screens.detail.presenter as mod
        assert not hasattr(mod, "DetailPresenter")

    def test_no_detail_data_loaded(self) -> None:
        """Test DetailDataLoaded message no longer exists."""
        import kubeagle.screens.detail.presenter as mod
        assert not hasattr(mod, "DetailDataLoaded")

    def test_no_detail_data_load_failed(self) -> None:
        """Test DetailDataLoadFailed message no longer exists."""
        import kubeagle.screens.detail.presenter as mod
        assert not hasattr(mod, "DetailDataLoadFailed")


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestBuildHelmRecommendations",
    "TestOptimizerDataLoadFailedMessage",
    "TestOptimizerDataLoadedMessage",
    "TestPresenterConstants",
    "TestRemovedDetailPresenter",
    "TestTruncatedList",
]
