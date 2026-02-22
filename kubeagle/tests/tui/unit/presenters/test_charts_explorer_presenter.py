"""Unit tests for ChartsExplorerPresenter - filtering, formatting, sorting logic.

This module tests:
- Initialization and state management
- apply_filters() with all ViewFilter modes
- sort_charts() with all SortBy modes
- format_chart_row() column output
- build_summary_metrics() numeric summary
- Helper methods (_format_memory, _format_ratio, _build_probes_str, _is_extreme_ratio)

Tests use mock ChartInfo objects to isolate presenter from real data.
"""

from __future__ import annotations

from kubeagle.constants.enums import QoSClass
from kubeagle.models.charts.chart_info import ChartInfo
from kubeagle.screens.charts_explorer.config import (
    SortBy,
    ViewFilter,
)
from kubeagle.screens.charts_explorer.presenter import (
    ChartsExplorerPresenter,
)

# =============================================================================
# Test Helpers
# =============================================================================


def _make_chart(
    name: str = "test-chart",
    namespace: str | None = None,
    team: str = "team-alpha",
    values_file: str = "values.yaml",
    cpu_request: float = 100.0,
    cpu_limit: float = 200.0,
    memory_request: float = 128 * 1024 * 1024,
    memory_limit: float = 256 * 1024 * 1024,
    qos_class: QoSClass = QoSClass.BURSTABLE,
    has_liveness: bool = True,
    has_readiness: bool = True,
    has_startup: bool = False,
    has_anti_affinity: bool = False,
    has_topology_spread: bool = False,
    has_topology: bool = False,
    pdb_enabled: bool = True,
    pdb_template_exists: bool = False,
    pdb_min_available: int | None = None,
    pdb_max_unavailable: int | None = None,
    replicas: int | None = 2,
    priority_class: str | None = None,
) -> ChartInfo:
    """Create a ChartInfo for testing."""
    return ChartInfo(
        name=name,
        namespace=namespace,
        team=team,
        values_file=values_file,
        cpu_request=cpu_request,
        cpu_limit=cpu_limit,
        memory_request=memory_request,
        memory_limit=memory_limit,
        qos_class=qos_class,
        has_liveness=has_liveness,
        has_readiness=has_readiness,
        has_startup=has_startup,
        has_anti_affinity=has_anti_affinity,
        has_topology_spread=has_topology_spread,
        has_topology=has_topology,
        pdb_enabled=pdb_enabled,
        pdb_template_exists=pdb_template_exists,
        pdb_min_available=pdb_min_available,
        pdb_max_unavailable=pdb_max_unavailable,
        replicas=replicas,
        priority_class=priority_class,
    )


# =============================================================================
# Initialization Tests
# =============================================================================


class TestChartsExplorerPresenterInit:
    """Test ChartsExplorerPresenter initialization."""

    def test_init_creates_instance(self) -> None:
        """Test presenter can be created."""
        presenter = ChartsExplorerPresenter()
        assert presenter is not None

    def test_init_violations_empty(self) -> None:
        """Test violations dict starts empty."""
        presenter = ChartsExplorerPresenter()
        assert presenter._violations == {}

    def test_set_violations(self) -> None:
        """Test set_violations stores data."""
        presenter = ChartsExplorerPresenter()
        violations = {"chart-a": 3, "chart-b": 1}
        presenter.set_violations(violations)
        assert presenter._violations == {"chart-a": 3, "chart-b": 1}

    def test_set_violations_replaces_previous(self) -> None:
        """Test set_violations replaces previous data."""
        presenter = ChartsExplorerPresenter()
        presenter.set_violations({"chart-a": 1})
        presenter.set_violations({"chart-b": 2})
        assert presenter._violations == {"chart-b": 2}


# =============================================================================
# apply_filters Tests
# =============================================================================


class TestApplyFilters:
    """Test ChartsExplorerPresenter.apply_filters()."""

    def test_all_view_returns_all(self) -> None:
        """Test ALL view returns all charts."""
        presenter = ChartsExplorerPresenter()
        charts = [_make_chart(name="a"), _make_chart(name="b")]
        result = presenter.apply_filters(charts, ViewFilter.ALL, None, "", False, None)
        assert len(result) == 2

    def test_extreme_ratios_filters_correctly(self) -> None:
        """Test EXTREME_RATIOS view filters charts with ratio >= 2.0."""
        presenter = ChartsExplorerPresenter()
        charts = [
            _make_chart(
                name="normal",
                cpu_request=100,
                cpu_limit=150,
                memory_limit=192 * 1024 * 1024,
            ),
            _make_chart(name="extreme", cpu_request=100, cpu_limit=300),
        ]
        result = presenter.apply_filters(
            charts, ViewFilter.EXTREME_RATIOS, None, "", False, None,
        )
        assert len(result) == 1
        assert result[0].name == "extreme"

    def test_single_replica_filters_correctly(self) -> None:
        """Test SINGLE_REPLICA view filters charts with replicas == 1."""
        presenter = ChartsExplorerPresenter()
        charts = [
            _make_chart(name="single", replicas=1),
            _make_chart(name="multi", replicas=3),
            _make_chart(name="none", replicas=None),
        ]
        result = presenter.apply_filters(
            charts, ViewFilter.SINGLE_REPLICA, None, "", False, None,
        )
        assert len(result) == 1
        assert result[0].name == "single"

    def test_no_pdb_filters_correctly(self) -> None:
        """Test NO_PDB view filters charts without PDB."""
        presenter = ChartsExplorerPresenter()
        charts = [
            _make_chart(name="has-pdb", pdb_enabled=True),
            _make_chart(name="no-pdb", pdb_enabled=False),
        ]
        result = presenter.apply_filters(
            charts, ViewFilter.NO_PDB, None, "", False, None,
        )
        assert len(result) == 1
        assert result[0].name == "no-pdb"

    def test_with_violations_filters_correctly(self) -> None:
        """Test WITH_VIOLATIONS view filters charts that have violations."""
        presenter = ChartsExplorerPresenter()
        presenter.set_violations({"chart-bad": 5})
        charts = [
            _make_chart(name="chart-bad"),
            _make_chart(name="chart-good"),
        ]
        result = presenter.apply_filters(
            charts, ViewFilter.WITH_VIOLATIONS, None, "", False, None,
        )
        assert len(result) == 1
        assert result[0].name == "chart-bad"

    def test_team_filter(self) -> None:
        """Test team filter narrows to specific team."""
        presenter = ChartsExplorerPresenter()
        charts = [
            _make_chart(name="a", team="alpha"),
            _make_chart(name="b", team="beta"),
        ]
        result = presenter.apply_filters(
            charts, ViewFilter.ALL, "alpha", "", False, None,
        )
        assert len(result) == 1
        assert result[0].team == "alpha"

    def test_team_filter_none_returns_all(self) -> None:
        """Test team=None returns all teams."""
        presenter = ChartsExplorerPresenter()
        charts = [
            _make_chart(name="a", team="alpha"),
            _make_chart(name="b", team="beta"),
        ]
        result = presenter.apply_filters(
            charts, ViewFilter.ALL, None, "", False, None,
        )
        assert len(result) == 2

    def test_active_only_filter(self) -> None:
        """Test active_only filter narrows to active charts."""
        presenter = ChartsExplorerPresenter()
        charts = [
            _make_chart(name="active-chart"),
            _make_chart(name="inactive-chart"),
        ]
        active = {"active-chart"}
        result = presenter.apply_filters(
            charts, ViewFilter.ALL, None, "", True, active,
        )
        assert len(result) == 1
        assert result[0].name == "active-chart"

    def test_active_only_false_returns_all(self) -> None:
        """Test active_only=False ignores active set."""
        presenter = ChartsExplorerPresenter()
        charts = [_make_chart(name="a"), _make_chart(name="b")]
        result = presenter.apply_filters(
            charts, ViewFilter.ALL, None, "", False, {"a"},
        )
        assert len(result) == 2

    def test_search_by_name(self) -> None:
        """Test search query matches chart name."""
        presenter = ChartsExplorerPresenter()
        charts = [
            _make_chart(name="my-api"),
            _make_chart(name="my-worker"),
        ]
        result = presenter.apply_filters(
            charts, ViewFilter.ALL, None, "api", False, None,
        )
        assert len(result) == 1
        assert result[0].name == "my-api"

    def test_search_by_team(self) -> None:
        """Test search query matches team name."""
        presenter = ChartsExplorerPresenter()
        charts = [
            _make_chart(name="a", team="frontend"),
            _make_chart(name="b", team="backend"),
        ]
        result = presenter.apply_filters(
            charts, ViewFilter.ALL, None, "front", False, None,
        )
        assert len(result) == 1
        assert result[0].team == "frontend"

    def test_search_case_insensitive(self) -> None:
        """Test search is case-insensitive."""
        presenter = ChartsExplorerPresenter()
        charts = [_make_chart(name="My-API")]
        result = presenter.apply_filters(
            charts, ViewFilter.ALL, None, "my-api", False, None,
        )
        assert len(result) == 1

    def test_combined_filters(self) -> None:
        """Test multiple filters applied together."""
        presenter = ChartsExplorerPresenter()
        charts = [
            _make_chart(name="app-a", team="alpha", replicas=1),
            _make_chart(name="app-b", team="alpha", replicas=3),
            _make_chart(name="app-c", team="beta", replicas=1),
        ]
        result = presenter.apply_filters(
            charts, ViewFilter.SINGLE_REPLICA, "alpha", "", False, None,
        )
        assert len(result) == 1
        assert result[0].name == "app-a"

    def test_empty_charts_returns_empty(self) -> None:
        """Test empty input returns empty output."""
        presenter = ChartsExplorerPresenter()
        result = presenter.apply_filters(
            [], ViewFilter.ALL, None, "", False, None,
        )
        assert result == []


# =============================================================================
# Sorting Tests
# =============================================================================


class TestSorting:
    """Test ChartsExplorerPresenter sorting behavior."""

    def test_sort_by_team_ascending(self) -> None:
        """SortBy.TEAM should order charts alphabetically by team."""
        presenter = ChartsExplorerPresenter()
        charts = [
            _make_chart(name="a", team="zeta"),
            _make_chart(name="b", team="alpha"),
        ]
        sorted_charts = presenter.sort_charts(
            charts, sort_by=SortBy.TEAM, descending=False
        )
        rows = [presenter.format_chart_row(c) for c in sorted_charts]
        assert rows[0][2] == "alpha"
        assert rows[1][2] == "zeta"

    def test_sort_by_violations_descending(self) -> None:
        """SortBy.VIOLATIONS should place higher violation counts first."""
        presenter = ChartsExplorerPresenter()
        presenter.set_violations({"chart-high": 5, "chart-low": 1})
        charts = [
            _make_chart(name="chart-low"),
            _make_chart(name="chart-high"),
        ]
        sorted_charts = presenter.sort_charts(
            charts, sort_by=SortBy.VIOLATIONS, descending=True
        )
        rows = [presenter.format_chart_row(c) for c in sorted_charts]
        assert "⎈" in rows[0][0]
        assert "chart-high" in rows[0][0]
        assert "⎈" in rows[1][0]
        assert "chart-low" in rows[1][0]

    def test_sort_by_cpu_ratio_missing_values_last(self) -> None:
        """SortBy.CPU_RATIO keeps charts without valid ratio at the end."""
        presenter = ChartsExplorerPresenter()
        charts = [
            _make_chart(name="has-ratio", cpu_request=100, cpu_limit=300),
            _make_chart(name="no-ratio", cpu_request=0, cpu_limit=0),
        ]
        sorted_charts = presenter.sort_charts(
            charts, sort_by=SortBy.CPU_RATIO, descending=True
        )
        rows = [presenter.format_chart_row(c) for c in sorted_charts]
        assert "⎈" in rows[0][0]
        assert "has-ratio" in rows[0][0]
        assert "⎈" in rows[1][0]
        assert "no-ratio" in rows[1][0]

    def test_sort_by_cpu_request_uses_left_value_of_compact_column(self) -> None:
        """SortBy.CPU_REQUEST should still order by cpu_request, not by limit."""
        presenter = ChartsExplorerPresenter()
        charts = [
            _make_chart(name="small-req", cpu_request=100, cpu_limit=900),
            _make_chart(name="big-req", cpu_request=400, cpu_limit=500),
        ]
        sorted_charts = presenter.sort_charts(
            charts, sort_by=SortBy.CPU_REQUEST, descending=True
        )
        rows = [presenter.format_chart_row(c) for c in sorted_charts]
        assert "⎈" in rows[0][0]
        assert "big-req" in rows[0][0]
        assert "400m / 500m" in rows[0][5]
        assert "⎈" in rows[1][0]
        assert "small-req" in rows[1][0]
        assert "100m / 900m" in rows[1][5]


# =============================================================================
# format_chart_row Tests
# =============================================================================


class TestFormatChartRow:
    """Test ChartsExplorerPresenter.format_chart_row()."""

    def test_returns_12_columns(self) -> None:
        """Test row tuple has exactly 12 elements."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart()
        row = presenter.format_chart_row(chart)
        assert len(row) == 12

    def test_first_column_is_chart_with_helm_icon(self) -> None:
        """Chart column should include Helm icon and chart name."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(name="my-chart")
        row = presenter.format_chart_row(chart)
        assert "⎈" in row[0]
        assert "my-chart" in row[0]

    def test_first_column_has_helm_icon_for_cluster_backed_chart(self) -> None:
        """Cluster-backed rows should show Helm marker prefix in chart column."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(
            name="my-chart",
            namespace="team-a",
            values_file="cluster:team-a",
        )
        row = presenter.format_chart_row(chart)
        assert "⎈" in row[0]
        assert "my-chart" in row[0]

    def test_second_column_is_namespace(self) -> None:
        """Test second column is namespace."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(namespace="team-a")
        row = presenter.format_chart_row(chart)
        assert row[1] == "team-a"

    def test_third_column_is_team(self) -> None:
        """Test third column is team."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(team="team-x")
        row = presenter.format_chart_row(chart)
        assert row[2] == "team-x"

    def test_fourth_column_is_values_file_type(self) -> None:
        """Test fourth column is values file type."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(values_file="/repo/charts/my-chart/values-automation.yaml")
        row = presenter.format_chart_row(chart)
        assert row[3] == "Automation"

    def test_fourth_column_is_main_for_values_yaml(self) -> None:
        """Test values.yaml is classified as Main."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(values_file="/repo/charts/my-chart/values.yaml")
        row = presenter.format_chart_row(chart)
        assert row[3] == "Main"

    def test_fourth_column_is_default_for_default_namespace_values(self) -> None:
        """Test values-default-namespace.yaml is classified as Default."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(
            values_file="/repo/charts/my-chart/values-default-namespace.yaml"
        )
        row = presenter.format_chart_row(chart)
        assert row[3] == "Default"

    def test_fifth_column_is_qos(self) -> None:
        """Test fifth column is QoS class value."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(qos_class=QoSClass.GUARANTEED)
        row = presenter.format_chart_row(chart)
        assert row[4] == "Guaranteed"

    def test_last_column_is_chart_path(self) -> None:
        """Test last column shows relative chart path with grandparent."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(values_file="/repo/charts/my-chart/values.yaml")
        row = presenter.format_chart_row(chart)
        assert row[11] == "charts/my-chart/values.yaml"

    def test_cpu_req_lim_compact_formatted(self) -> None:
        """CPU request/limit should include inline ratio."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(cpu_request=100, cpu_limit=500)
        row = presenter.format_chart_row(chart)
        assert "100m / 500m" in row[5]
        assert "5.0" in row[5]

    def test_replicas_as_string(self) -> None:
        """Test replicas column is string."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(replicas=3)
        row = presenter.format_chart_row(chart)
        assert row[7] == "3"

    def test_replicas_none_shows_na(self) -> None:
        """Test replicas=None shows N/A."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(replicas=None)
        row = presenter.format_chart_row(chart)
        assert row[7] == "N/A"

    def test_probes_with_all(self) -> None:
        """Test probes column with all probes enabled."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(has_liveness=True, has_readiness=True, has_startup=True)
        row = presenter.format_chart_row(chart)
        assert row[8] == "L, R, S"

    def test_probes_with_none(self) -> None:
        """Test probes column with no probes."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(has_liveness=False, has_readiness=False, has_startup=False)
        row = presenter.format_chart_row(chart)
        assert row[8] == "None"

    def test_affinity_no(self) -> None:
        """Test affinity column without anti-affinity."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(has_anti_affinity=False, has_topology_spread=False)
        row = presenter.format_chart_row(chart)
        assert row[9] == "No"

    def test_affinity_anti(self) -> None:
        """Test affinity column with anti-affinity."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(has_anti_affinity=True, has_topology_spread=False)
        row = presenter.format_chart_row(chart)
        assert row[9] == "Anti"

    def test_affinity_anti_plus_topology(self) -> None:
        """Test affinity column with both anti-affinity and topology spread."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(has_anti_affinity=True, has_topology_spread=True)
        row = presenter.format_chart_row(chart)
        assert row[9] == "Anti+Topology"

    def test_pdb_yes(self) -> None:
        """Test PDB column with PDB enabled."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(pdb_enabled=True)
        row = presenter.format_chart_row(chart)
        assert row[10] == "Yes"

    def test_pdb_no(self) -> None:
        """Test PDB column with PDB disabled."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(pdb_enabled=False)
        row = presenter.format_chart_row(chart)
        assert row[10] == "No"

    def test_zero_cpu_shows_dash(self) -> None:
        """Test zero CPU request shows dash."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(cpu_request=0, cpu_limit=0)
        row = presenter.format_chart_row(chart)
        assert row[5] == "-"

    def test_zero_memory_shows_dash(self) -> None:
        """Test zero memory request shows dash."""
        presenter = ChartsExplorerPresenter()
        chart = _make_chart(memory_request=0, memory_limit=0)
        row = presenter.format_chart_row(chart)
        assert row[6] == "-"


# =============================================================================
# build_summary_metrics Tests
# =============================================================================


class TestBuildSummaryMetrics:
    """Test ChartsExplorerPresenter.build_summary_metrics()."""

    def test_shows_chart_counts(self) -> None:
        """Test summary metrics include shown/total chart counts."""
        presenter = ChartsExplorerPresenter()
        all_charts = [_make_chart(name="a"), _make_chart(name="b")]
        filtered = [_make_chart(name="a")]
        metrics = presenter.build_summary_metrics(all_charts, filtered)
        assert metrics["total"] == 2
        assert metrics["shown"] == 1

    def test_tracks_violation_count(self) -> None:
        """Test summary metrics include violation count when present."""
        presenter = ChartsExplorerPresenter()
        presenter.set_violations({"a": 3, "b": 2})
        charts = [_make_chart(name="a")]
        metrics = presenter.build_summary_metrics(charts, charts)
        assert metrics["violations"] == 5

    def test_no_violations_returns_zero(self) -> None:
        """Test summary metrics return zero violations when none exist."""
        presenter = ChartsExplorerPresenter()
        charts = [_make_chart(name="a")]
        metrics = presenter.build_summary_metrics(charts, charts)
        assert metrics["violations"] == 0

    def test_tracks_cpu_totals(self) -> None:
        """Test summary metrics include CPU totals."""
        presenter = ChartsExplorerPresenter()
        charts = [_make_chart(cpu_request=100, cpu_limit=200)]
        metrics = presenter.build_summary_metrics(charts, charts)
        assert metrics["cpu_req"] == 100
        assert metrics["cpu_lim"] == 200

    def test_tracks_memory_totals(self) -> None:
        """Test summary metrics include memory totals."""
        presenter = ChartsExplorerPresenter()
        charts = [_make_chart(memory_request=256 * 1024 * 1024)]
        metrics = presenter.build_summary_metrics(charts, charts)
        assert metrics["mem_req"] == 256 * 1024 * 1024

    def test_empty_filtered_charts(self) -> None:
        """Test summary metrics with empty filtered list."""
        presenter = ChartsExplorerPresenter()
        all_charts = [_make_chart()]
        metrics = presenter.build_summary_metrics(all_charts, [])
        assert metrics["total"] == 1
        assert metrics["shown"] == 0


# =============================================================================
# Helper Method Tests
# =============================================================================


class TestHelperMethods:
    """Test ChartsExplorerPresenter static helper methods."""

    def test_build_probes_str_all(self) -> None:
        """Test probes string with all probes."""
        chart = _make_chart(has_liveness=True, has_readiness=True, has_startup=True)
        result = ChartsExplorerPresenter._build_probes_str(chart)
        assert result == "L, R, S"

    def test_build_probes_str_partial(self) -> None:
        """Test probes string with some probes."""
        chart = _make_chart(has_liveness=True, has_readiness=False, has_startup=True)
        result = ChartsExplorerPresenter._build_probes_str(chart)
        assert result == "L, S"

    def test_build_probes_str_none(self) -> None:
        """Test probes string with no probes."""
        chart = _make_chart(has_liveness=False, has_readiness=False, has_startup=False)
        result = ChartsExplorerPresenter._build_probes_str(chart)
        assert result == "None"

    def test_format_memory_gi(self) -> None:
        """Test memory formatting in Gi."""
        result = ChartsExplorerPresenter._format_memory(2 * 1024 * 1024 * 1024)
        assert result == "2.0Gi"

    def test_format_memory_mi(self) -> None:
        """Test memory formatting in Mi."""
        result = ChartsExplorerPresenter._format_memory(256 * 1024 * 1024)
        assert result == "256.0Mi"

    def test_format_memory_ki(self) -> None:
        """Test memory formatting in Ki."""
        result = ChartsExplorerPresenter._format_memory(512 * 1024)
        assert result == "512.0Ki"

    def test_format_memory_bytes(self) -> None:
        """Test memory formatting in bytes."""
        result = ChartsExplorerPresenter._format_memory(500)
        assert result == "500B"

    def test_format_ratio_normal(self) -> None:
        """Test ratio formatting for normal values."""
        result = ChartsExplorerPresenter._format_ratio(100, 150)
        assert result == "1.5×"

    def test_format_ratio_warning(self) -> None:
        """Test ratio formatting for warning range (>= 2.0)."""
        result = ChartsExplorerPresenter._format_ratio(100, 250)
        assert "2.5×" in result
        assert "#ff9f0a" in result

    def test_format_ratio_critical(self) -> None:
        """Test ratio formatting for critical range (>= 4.0)."""
        result = ChartsExplorerPresenter._format_ratio(100, 500)
        assert "5.0×" in result
        assert "#ff3b30" in result

    def test_format_ratio_no_request(self) -> None:
        """Test ratio formatting with no request returns dash."""
        result = ChartsExplorerPresenter._format_ratio(0, 100)
        assert result == "-"

    def test_format_ratio_no_limit(self) -> None:
        """Test ratio formatting with no limit returns dash."""
        result = ChartsExplorerPresenter._format_ratio(100, 0)
        assert result == "-"

    def test_format_ratio_none_values(self) -> None:
        """Test ratio formatting with None values returns dash."""
        result = ChartsExplorerPresenter._format_ratio(None, None)
        assert result == "-"

    def test_is_extreme_ratio_true_cpu(self) -> None:
        """Test extreme ratio detection for CPU."""
        chart = _make_chart(cpu_request=100, cpu_limit=300, memory_request=100, memory_limit=100)
        assert ChartsExplorerPresenter._is_extreme_ratio(chart) is True

    def test_is_extreme_ratio_true_memory(self) -> None:
        """Test extreme ratio detection for memory."""
        chart = _make_chart(cpu_request=100, cpu_limit=100, memory_request=100, memory_limit=300)
        assert ChartsExplorerPresenter._is_extreme_ratio(chart) is True

    def test_is_extreme_ratio_false(self) -> None:
        """Test extreme ratio detection returns False for normal values."""
        chart = _make_chart(cpu_request=100, cpu_limit=150, memory_request=100, memory_limit=150)
        assert ChartsExplorerPresenter._is_extreme_ratio(chart) is False

    def test_is_extreme_ratio_zero_request(self) -> None:
        """Test extreme ratio with zero request returns False."""
        chart = _make_chart(cpu_request=0, cpu_limit=100, memory_request=0, memory_limit=100)
        assert ChartsExplorerPresenter._is_extreme_ratio(chart) is False

    def test_format_count_with_percentage(self) -> None:
        """Formatted KPI helper should append integer percentage in parenthesis."""
        result = ChartsExplorerPresenter.format_count_with_percentage(3, 8)
        assert result == "3 (38%)"

    def test_format_count_with_percentage_zero_total(self) -> None:
        """Zero total should avoid division by zero and show 0%."""
        result = ChartsExplorerPresenter.format_count_with_percentage(2, 0)
        assert result == "2 (0%)"

    def test_format_fraction_with_percentage(self) -> None:
        """Fraction KPI helper should append integer percentage in parenthesis."""
        result = ChartsExplorerPresenter.format_fraction_with_percentage(8, 10)
        assert result == "8/10 (80%)"

    def test_format_fraction_with_percentage_zero_total(self) -> None:
        """Zero total should avoid division by zero and show 0%."""
        result = ChartsExplorerPresenter.format_fraction_with_percentage(0, 0)
        assert result == "0/0 (0%)"


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestApplyFilters",
    "TestBuildSummaryMetrics",
    "TestChartsExplorerPresenterInit",
    "TestFormatChartRow",
    "TestHelperMethods",
    "TestSorting",
]
