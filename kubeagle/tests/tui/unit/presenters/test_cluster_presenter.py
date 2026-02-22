"""Unit tests for ClusterPresenter - data loading, state management, and UI logic.

This module tests:
- Initialization and properties
- Data accessor methods
- Health calculation methods (_calc_health, get_health_data)
- Row formatting methods (get_node_rows, get_node_group_rows, get_stats_rows, etc.)
- Percentage formatting (_format_pct)
- Dict-input event handling branches
- Message classes (ClusterDataLoaded, ClusterDataLoadFailed)
- Edge cases (empty data, null values, boundary conditions)

Tests use MagicMock to isolate the presenter from actual Kubernetes cluster operations.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from kubeagle.constants.timeouts import CLUSTER_CHECK_TIMEOUT
from kubeagle.screens.cluster.presenter import (
    ClusterDataLoaded,
    ClusterDataLoadFailed,
    ClusterPresenter,
)

# =============================================================================
# Test Fixtures
# =============================================================================


class MockClusterScreen:
    """Mock ClusterScreen for testing ClusterPresenter."""

    def __init__(self) -> None:
        """Initialize mock screen."""
        self.app = MagicMock()
        self.context = "test-cluster"
        self._messages: list = []
        self._loading_message = "Initializing..."

    def post_message(self, message: object) -> None:
        """Record posted messages."""
        self._messages.append(message)

    def call_later(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        """Execute callback immediately for testing."""
        if callable(callback):
            callback(*args, **kwargs)

    def _update_loading_message(self, message: str) -> None:
        """Update loading message."""
        self._loading_message = message

    def _refresh_all_tabs(self) -> None:
        """Mock tab refresh."""
        pass

    def run_worker(self, coro: Any, name: str = "", exclusive: bool = False) -> None:
        """Mock run_worker."""
        pass


def _make_mock_node(
    name: str = "node-1",
    status: str = "Ready",
    instance_type: str = "m5.large",
    cpu_requests: float | None = 1500.0,
    memory_requests: float | None = 4_000_000_000.0,
    pod_count: int | None = 50,
    pod_capacity: int | None = 110,
) -> MagicMock:
    """Create a mock node with configurable attributes."""
    node = MagicMock()
    node.name = name
    node.status.value = status
    node.instance_type = instance_type
    node.cpu_requests = cpu_requests
    node.memory_requests = memory_requests
    node.pod_count = pod_count
    node.pod_capacity = pod_capacity
    return node


def _make_mock_event(event_type: str = "Warning") -> MagicMock:
    """Create a mock event with configurable type."""
    event = MagicMock()
    event.type.value = event_type
    return event


def _make_mock_pdb(
    namespace: str = "default",
    name: str = "my-pdb",
    min_available: int | None = 1,
    max_unavailable: int | None = None,
    is_blocking: bool = False,
) -> MagicMock:
    """Create a mock PDB with configurable attributes."""
    pdb = MagicMock()
    pdb.namespace = namespace
    pdb.name = name
    pdb.min_available = min_available
    pdb.max_unavailable = max_unavailable
    pdb.is_blocking = is_blocking
    return pdb


def _make_mock_workload(
    name: str = "my-app",
    namespace: str = "default",
    chart: str = "my-chart",
    version: str = "1.0.0",
    status: str = "deployed",
) -> MagicMock:
    """Create a mock workload/release with configurable attributes."""
    wl = MagicMock()
    wl.name = name
    wl.namespace = namespace
    wl.chart = chart
    wl.version = version
    wl.status = status
    return wl


def _make_mock_single_replica(
    namespace: str = "default",
    name: str = "my-app",
    kind: str = "Deployment",
    status: str = "Ready",
    node_name: str | None = "node-1",
) -> MagicMock:
    """Create a mock single-replica workload."""
    wl = MagicMock()
    wl.namespace = namespace
    wl.name = name
    wl.kind = kind
    wl.status = status
    wl.node_name = node_name
    return wl


def _make_presenter_with_full_data() -> tuple[ClusterPresenter, MockClusterScreen]:
    """Create a presenter with realistic full data for text formatting tests."""
    screen = MockClusterScreen()
    presenter = ClusterPresenter(screen)

    presenter._data["cluster_name"] = "prod-cluster"
    presenter._data["nodes"] = [
        _make_mock_node("node-1", "Ready"),
        _make_mock_node("node-2", "Ready"),
        _make_mock_node("node-3", "NotReady"),
    ]
    presenter._data["events"] = [
        _make_mock_event("Warning"),
        _make_mock_event("Warning"),
        _make_mock_event("Error"),
        _make_mock_event("Normal"),
    ]
    presenter._data["pdbs"] = [
        _make_mock_pdb("ns-a", "pdb-1", is_blocking=False),
        _make_mock_pdb("ns-b", "pdb-2", is_blocking=True),
    ]
    presenter._data["single_replica"] = [
        _make_mock_single_replica("ns-a", "single-app"),
    ]
    presenter._data["all_workloads"] = [
        _make_mock_workload("app-1"),
        _make_mock_workload("app-2"),
    ]

    return presenter, screen


# =============================================================================
# ClusterPresenter Initialization Tests
# =============================================================================


class TestClusterPresenterInitialization:
    """Test ClusterPresenter initialization."""

    def test_init_sets_screen_reference(self) -> None:
        """Test that __init__ stores screen reference."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        assert presenter._screen is mock_screen

    def test_init_data_is_empty_dict(self) -> None:
        """Test that _data starts as empty dict."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        assert presenter._data == {}

    def test_init_loading_is_false(self) -> None:
        """Test that _is_loading starts as False."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        assert presenter._is_loading is False

    def test_init_error_is_empty_string(self) -> None:
        """Test that _error_message starts as empty string."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        assert presenter._error_message == ""

    def test_default_event_window_is_15_minutes(self) -> None:
        """Cluster presenter should use 15m default event lookback like Home."""
        assert ClusterPresenter._DEFAULT_EVENT_WINDOW_HOURS == 0.25

    def test_event_loaders_use_runtime_event_window(self) -> None:
        """Event-related loaders should use runtime-configurable lookback."""
        events_source = inspect.getsource(ClusterPresenter._load_streaming_events)
        summary_source = inspect.getsource(ClusterPresenter._load_streaming_event_summary)
        critical_source = inspect.getsource(ClusterPresenter._load_streaming_critical_events)
        assert "max_age_hours=self._event_window_hours" in events_source
        assert "max_age_hours=self._event_window_hours" in summary_source
        assert "max_age_hours=self._event_window_hours" in critical_source


# =============================================================================
# ClusterPresenter Property Tests
# =============================================================================


class TestClusterPresenterProperties:
    """Test ClusterPresenter property accessors."""

    def test_is_loading_property(self) -> None:
        """Test is_loading property returns _is_loading."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        assert presenter.is_loading is False

        presenter._is_loading = True
        assert presenter.is_loading is True

    def test_error_message_property(self) -> None:
        """Test error_message property returns _error_message."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        assert presenter.error_message == ""

        presenter._error_message = "Test error"
        assert presenter.error_message == "Test error"

    def test_is_connected_property(self) -> None:
        """Test is_connected property checks cluster_name."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        # Not connected initially
        assert presenter.is_connected is False

        # Connected when cluster_name is set
        presenter._data["cluster_name"] = "test-cluster"
        assert presenter.is_connected is True

    def test_event_window_setter_updates_value(self) -> None:
        """Test event window setter stores runtime lookback value."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter.set_event_window_hours(2.0)
        assert presenter.event_window_hours == 2.0

    def test_event_window_setter_resets_invalid_value(self) -> None:
        """Non-positive values should reset to default lookback."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter.set_event_window_hours(0.0)
        assert presenter.event_window_hours == ClusterPresenter._DEFAULT_EVENT_WINDOW_HOURS


# =============================================================================
# ClusterPresenter Data Accessor Tests
# =============================================================================


class TestClusterPresenterDataAccessors:
    """Test ClusterPresenter data accessor methods."""

    def test_get_cluster_name(self) -> None:
        """Test get_cluster_name returns cluster name."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["cluster_name"] = "my-eks-cluster"

        assert presenter.get_cluster_name() == "my-eks-cluster"

    def test_get_cluster_name_default(self) -> None:
        """Test get_cluster_name returns 'Unknown' when not set."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        assert presenter.get_cluster_name() == "Unknown"

    def test_get_nodes(self) -> None:
        """Test get_nodes returns nodes list."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = [_make_mock_node(), _make_mock_node("node-2")]

        result = presenter.get_nodes()
        assert len(result) == 2

    def test_get_events(self) -> None:
        """Test get_events returns events list."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["events"] = [_make_mock_event()]

        result = presenter.get_events()
        assert len(result) == 1

    def test_get_single_replica(self) -> None:
        """Test get_single_replica returns single replica workloads."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["single_replica"] = [_make_mock_single_replica()]

        result = presenter.get_single_replica()
        assert len(result) == 1

    def test_get_pdbs(self) -> None:
        """Test get_pdbs returns PDBs list."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["pdbs"] = [_make_mock_pdb()]

        result = presenter.get_pdbs()
        assert len(result) == 1

    def test_get_node_groups(self) -> None:
        """Test get_node_groups returns node groups dict."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["node_groups"] = {"group1": {"nodes": []}}

        result = presenter.get_node_groups()
        assert "group1" in result

    def test_get_all_workloads(self) -> None:
        """Test get_all_workloads returns workloads list."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["all_workloads"] = [_make_mock_workload()]

        result = presenter.get_all_workloads()
        assert len(result) == 1

    def test_get_charts_overview_default(self) -> None:
        """Charts overview should return unavailable defaults when missing."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        result = presenter.get_charts_overview()
        assert result["available"] is False
        assert result["total_charts"] == 0
        assert result["charts_with_pdb_template"] == 0


# =============================================================================
# ClusterPresenter Health Methods Tests
# =============================================================================


class TestClusterPresenterHealthMethods:
    """Test ClusterPresenter health calculation methods."""

    def test_count_ready_nodes_all_ready(self) -> None:
        """Test counting ready nodes when all are ready."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = [
            _make_mock_node("n1", "Ready"),
            _make_mock_node("n2", "Ready"),
        ]

        ready, total = presenter.count_ready_nodes()
        assert ready == 2
        assert total == 2

    def test_count_ready_nodes_some_not_ready(self) -> None:
        """Test counting ready nodes when some are not ready."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = [
            _make_mock_node("n1", "Ready"),
            _make_mock_node("n2", "NotReady"),
        ]

        ready, total = presenter.count_ready_nodes()
        assert ready == 1
        assert total == 2

    def test_count_ready_nodes_empty(self) -> None:
        """Test counting ready nodes when no nodes."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = []

        ready, total = presenter.count_ready_nodes()
        assert ready == 0
        assert total == 0

    def test_count_events_by_type(self) -> None:
        """Test counting events by type."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["events"] = [
            _make_mock_event("Warning"),
            _make_mock_event("Warning"),
            _make_mock_event("Normal"),
        ]

        counts = presenter.count_events_by_type()
        assert counts["Warning"] == 2
        assert counts["Normal"] == 1

    def test_count_warning_events(self) -> None:
        """Test counting warning events."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["events"] = [
            _make_mock_event("Warning"),
            _make_mock_event("Normal"),
        ]

        count = presenter.count_warning_events()
        assert count == 1

    def test_count_error_events(self) -> None:
        """Test counting error events."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["events"] = [
            _make_mock_event("Error"),
            _make_mock_event("Warning"),
        ]

        count = presenter.count_error_events()
        assert count == 1

    def test_count_blocking_pdbs(self) -> None:
        """Test counting blocking PDBs."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["pdbs"] = [
            _make_mock_pdb(is_blocking=True),
            _make_mock_pdb(name="pdb-2", is_blocking=False),
        ]

        count = presenter.count_blocking_pdbs()
        assert count == 1


# =============================================================================
# ClusterPresenter Row Formatting Tests
# =============================================================================


class TestClusterPresenterRowFormatting:
    """Test ClusterPresenter get_*_rows() methods that produce table data."""

    # --- get_node_rows ---

    def test_get_node_rows(self) -> None:
        """Test get_node_rows returns correctly formatted tuples."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        node_a = _make_mock_node(
            name="ip-10-0-1-10.us-east-1.compute.internal",
            status="Ready",
            instance_type="m5.large",
            cpu_requests=1500.0,
            memory_requests=4_294_967_296.0,  # 4 Gi
            pod_count=50,
            pod_capacity=110,
        )
        node_a.cpu_allocatable = 2000.0
        node_a.memory_allocatable = 8_589_934_592.0  # 8 Gi
        node_a.cpu_limits = 3000.0
        node_a.memory_limits = 10_737_418_240.0  # 10 Gi

        node_b = _make_mock_node(
            name="ip-10-0-1-11.us-east-1.compute.internal",
            status="NotReady",
            instance_type="c5.xlarge",
            cpu_requests=3000.0,
            memory_requests=8_589_934_592.0,  # 8 Gi
            pod_count=20,
            pod_capacity=110,
        )
        node_b.cpu_allocatable = 4000.0
        node_b.memory_allocatable = 17_179_869_184.0  # 16 Gi
        node_b.cpu_limits = 5000.0
        node_b.memory_limits = 12_884_901_888.0  # 12 Gi

        presenter._data["nodes"] = [node_a, node_b]

        rows = presenter.get_node_rows()
        assert len(rows) == 2

        # First row — includes merged pod usage and req/alloc + lim/alloc fields.
        row0 = rows[0]
        assert len(row0) == 7
        assert len(row0[0]) <= 35  # name truncated
        assert row0[2] == "[#30d158]45%[/#30d158] (50/110)"
        assert row0[3] == "[#ff9f0a]75%[/#ff9f0a] (1500m/2000m)"
        assert row0[4] == "[#30d158]50%[/#30d158] (4.00Gi/8.00Gi)"
        assert row0[5] == "[bold #ff3b30]150%[/bold #ff3b30] (3000m/2000m)"
        assert row0[6] == "[bold #ff3b30]125%[/bold #ff3b30] (10.00Gi/8.00Gi)"

    def test_get_node_rows_empty(self) -> None:
        """Test get_node_rows with empty nodes list returns empty list."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)
        presenter._data["nodes"] = []

        rows = presenter.get_node_rows()
        assert rows == []

    def test_get_node_rows_null_values(self) -> None:
        """Test get_node_rows with None cpu/memory shows N/A."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        node = _make_mock_node(cpu_requests=None, memory_requests=None)
        node.cpu_allocatable = 0.0
        node.memory_allocatable = 0.0
        node.cpu_limits = 0.0
        node.memory_limits = 0.0
        presenter._data["nodes"] = [node]

        rows = presenter.get_node_rows()
        assert len(rows) == 1
        # With zero allocatable, percentage is unavailable and pair shows "-".
        assert rows[0][3] == "- (0m/-)"
        assert rows[0][4] == "- (0.00Gi/-)"
        assert rows[0][5] == "- (0m/-)"
        assert rows[0][6] == "- (0.00Gi/-)"

    def test_get_pdb_coverage_summary_rows_uses_charts_overview(self) -> None:
        """Chart coverage rows should come from chart overview payload."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)
        presenter._data["charts_overview"] = {
            "available": True,
            "total_charts": 10,
            "team_count": 2,
            "single_replica_charts": 1,
            "charts_with_pdb_template": 7,
            "charts_with_pdb": 3,
            "pdb_coverage_pct": 30.0,
        }
        presenter._data["all_workloads"] = []

        rows = presenter.get_pdb_coverage_summary_rows()
        values = dict(rows)
        assert values["Total Charts"] == "10"
        assert values["Charts with PDB Template"] == "7"
        assert values["Charts with PDB Enabled"] == "3"
        assert "30.0%" in values["PDB Coverage"]

    def test_get_runtime_pdb_coverage_summary_rows(self) -> None:
        """Runtime coverage rows should reflect all_workloads PDB matches."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)
        with_pdb = MagicMock(has_pdb=True)
        without_pdb = MagicMock(has_pdb=False)
        presenter._data["all_workloads"] = [with_pdb, without_pdb]

        rows = presenter.get_runtime_pdb_coverage_summary_rows()
        values = dict(rows)
        assert values["Total Runtime Workloads"] == "2"
        assert values["Runtime Workloads with PDB"] == "1"
        assert "50.0%" in values["Runtime PDB Coverage"]

    # --- get_node_group_rows ---

    def test_get_node_group_rows(self) -> None:
        """Test get_node_group_rows returns correctly formatted combined tuples."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["node_groups"] = {
            "worker-group-1": {
                "node_count": 3,
                "cpu_allocatable": 6000,
                "memory_allocatable": 24 * 1024 * 1024 * 1024,  # 24 Gi
                "cpu_requests": 4500,
                "memory_requests": 14 * 1024 * 1024 * 1024,
                "cpu_limits": 9000,
                "memory_limits": 30 * 1024 * 1024 * 1024,
            },
        }

        rows = presenter.get_node_group_rows()
        assert len(rows) == 1

        row = rows[0]
        assert len(row) == 6
        assert row[0] == "worker-group-1"
        assert row[1] == "3"
        assert "/" in row[2]
        assert "/" in row[3]
        assert "/" in row[4]
        assert "/" in row[5]

    def test_get_node_group_columns_with_az_matrix(self) -> None:
        """Test node group columns include merged AZ matrix columns."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)
        presenter._data["node_groups_az_matrix"] = {
            "worker-group-1": {"us-east-1a": 2, "us-east-1b": 1},
        }

        columns = presenter.get_node_group_columns()
        column_names = [name for name, _width in columns]
        assert "Node Group" in column_names
        assert "us-east-1 (a/b)" in column_names
        assert "Total" not in column_names

    def test_get_node_group_rows_with_az_matrix(self) -> None:
        """Test node group rows include merged AZ values without total."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)
        presenter._data["node_groups"] = {"worker-group-1": {"node_count": 3}}
        presenter._data["node_groups_az_matrix"] = {
            "worker-group-1": {"us-east-1a": 2, "us-east-1b": 1},
        }

        rows = presenter.get_node_group_rows()
        assert len(rows) == 1
        assert len(rows[0]) == 7
        assert rows[0][-1] == "2/1"

    # --- get_stats_rows ---

    def test_get_stats_rows(self) -> None:
        """Test get_stats_rows returns list of 3-tuples with all categories."""
        presenter, _ = _make_presenter_with_full_data()

        rows = presenter.get_stats_rows()
        assert len(rows) > 0
        for row in rows:
            assert len(row) == 3
            assert isinstance(row[0], str)
            assert isinstance(row[1], str)
            assert isinstance(row[2], str)

        categories = {r[0] for r in rows}
        assert "Nodes" in categories
        assert "PDBs" in categories
        assert "Workloads" in categories


# =============================================================================
# ClusterPresenter _format_pct Tests
# =============================================================================


class TestClusterPresenterFormatPct:
    """Test ClusterPresenter _format_pct() color-coded percentage formatting."""

    def test_format_pct_normal(self) -> None:
        """Test format_pct with normal value (<=70) returns green status."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        result = presenter._format_pct(50.0)
        assert result == "[#30d158]50%[/#30d158]"

    def test_format_pct_warning(self) -> None:
        """Test format_pct with warning value (>70, <=90) returns warning color."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        result = presenter._format_pct(75.0)
        assert result == "[bold #ff9f0a]75%[/bold #ff9f0a]"

    def test_format_pct_critical(self) -> None:
        """Test format_pct with critical value (>90) returns critical color."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        result = presenter._format_pct(95.0)
        assert result == "[bold #ff3b30]95%[/bold #ff3b30]"

    def test_format_pct_boundary_70(self) -> None:
        """Test format_pct at 70.0 returns green status."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        result = presenter._format_pct(70.0)
        assert result == "[#30d158]70%[/#30d158]"

    def test_format_pct_boundary_90(self) -> None:
        """Test format_pct at 90.0 returns warning color (>70, <=90)."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        result = presenter._format_pct(90.0)
        assert result == "[bold #ff9f0a]90%[/bold #ff9f0a]"

    def test_format_pct_zero(self) -> None:
        """Test format_pct at 0.0 returns plain text."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        result = presenter._format_pct(0.0)
        assert result == "0%"

    def test_format_pct_100(self) -> None:
        """Test format_pct at 100.0 returns critical color."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        result = presenter._format_pct(100.0)
        assert result == "[bold #ff3b30]100%[/bold #ff3b30]"


# =============================================================================
# ClusterPresenter _calc_health Tests
# =============================================================================


class TestClusterPresenterCalcHealth:
    """Test ClusterPresenter _calc_health() internal method."""

    def test_calc_health_perfect(self) -> None:
        """Test perfect health: all ready, no errors, no blocking."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = [_make_mock_node(status="Ready")]
        presenter._data["events"] = []
        presenter._data["pdbs"] = []

        label, score, issues = presenter._calc_health()
        assert score == 100
        assert "HEALTHY" in label
        assert len(issues) == 0

    def test_calc_health_degraded(self) -> None:
        """Test degraded health: 80% nodes ready."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        nodes = [_make_mock_node(f"n{i}", "Ready") for i in range(8)]
        nodes += [_make_mock_node(f"nr{i}", "NotReady") for i in range(2)]
        presenter._data["nodes"] = nodes
        presenter._data["events"] = []
        presenter._data["pdbs"] = []

        label, score, issues = presenter._calc_health()
        # 80% nodes ready -> score = 100 * 0.8 = 80 -> DEGRADED
        assert score == 80
        assert "DEGRADED" in label
        assert any("ready" in i.lower() for i in issues)

    def test_calc_health_unhealthy(self) -> None:
        """Test unhealthy: no nodes -> score=0."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = []
        presenter._data["events"] = []
        presenter._data["pdbs"] = []

        label, score, issues = presenter._calc_health()
        assert score == 0
        assert "UNHEALTHY" in label
        assert any("No nodes" in i for i in issues)

    def test_calc_health_errors_reduce_score(self) -> None:
        """Test that 3 errors reduce score by 15."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = [_make_mock_node(status="Ready")]
        presenter._data["events"] = [_make_mock_event("Error")] * 3
        presenter._data["pdbs"] = []

        _label, score, issues = presenter._calc_health()
        # 100 - (3 errors * 5) = 85 -> DEGRADED
        assert score == 85
        assert any("error" in i.lower() for i in issues)

    def test_calc_health_warnings_reduce_score(self) -> None:
        """Test that 6 warnings reduce score by 6 and add issue."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = [_make_mock_node(status="Ready")]
        presenter._data["events"] = [_make_mock_event("Warning")] * 6
        presenter._data["pdbs"] = []

        _label, score, issues = presenter._calc_health()
        # 100 - (6 warnings * 1) = 94 -> still HEALTHY
        assert score == 94
        assert any("warning" in i.lower() for i in issues)

    def test_calc_health_blocking_pdbs_reduce_score(self) -> None:
        """Test that 1 blocking PDB reduces score by 10."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = [_make_mock_node(status="Ready")]
        presenter._data["events"] = []
        presenter._data["pdbs"] = [_make_mock_pdb(is_blocking=True)]

        _label, score, issues = presenter._calc_health()
        # 100 - (1 blocking * 10) = 90 -> HEALTHY (>= 90)
        assert score == 90
        assert any("blocking" in i.lower() for i in issues)

    def test_calc_health_score_clamped_to_0(self) -> None:
        """Test that score does not go below 0 even with many issues."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = [_make_mock_node(status="NotReady")]
        presenter._data["events"] = [_make_mock_event("Error")] * 30
        presenter._data["pdbs"] = [_make_mock_pdb(is_blocking=True)] * 5

        label, score, _issues = presenter._calc_health()
        assert score == 0
        assert "UNHEALTHY" in label


# =============================================================================
# ClusterPresenter Dict Event Handling Tests
# =============================================================================


class TestClusterPresenterDictEventHandling:
    """Test ClusterPresenter methods with dict-type event input."""

    def test_count_events_by_type_dict_input(self) -> None:
        """Test count_events_by_type with dict input returns same dict."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["events"] = {"Warning": 5, "Error": 2}

        counts = presenter.count_events_by_type()
        assert counts == {"Warning": 5, "Error": 2}

    def test_count_warning_events_dict_input(self) -> None:
        """Test count_warning_events with dict input uses dict.get."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["events"] = {"Warning": 5, "Error": 2}

        count = presenter.count_warning_events()
        assert count == 5

    def test_count_error_events_dict_input(self) -> None:
        """Test count_error_events with dict input uses dict.get."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["events"] = {"Warning": 5, "Error": 2}

        count = presenter.count_error_events()
        assert count == 2

    def test_count_warning_events_dict_no_warning(self) -> None:
        """Test count_warning_events with dict missing Warning key returns 0."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["events"] = {"Error": 3, "Normal": 10}

        count = presenter.count_warning_events()
        assert count == 0

    def test_count_error_events_dict_no_error(self) -> None:
        """Test count_error_events with dict missing Error key returns 0."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["events"] = {"Warning": 3, "Normal": 10}

        count = presenter.count_error_events()
        assert count == 0


# =============================================================================
# ClusterPresenter Tab Data Methods Tests
# =============================================================================


class TestClusterPresenterTabDataMethods:
    """Test ClusterPresenter tab data composite methods."""

    def test_get_overview_data(self) -> None:
        """Test getting overview data."""
        presenter, _ = _make_presenter_with_full_data()

        result = presenter.get_overview_data()
        assert result["cluster_name"] == "prod-cluster"
        assert result["ready_nodes"] == 2
        assert result["total_nodes"] == 3

    def test_get_health_data(self) -> None:
        """Test getting health data returns 3-tuple."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = [_make_mock_node(status="Ready")]
        presenter._data["events"] = []
        presenter._data["pdbs"] = []

        status, score, issues = presenter.get_health_data()
        assert isinstance(status, str)
        assert isinstance(score, int)
        assert isinstance(issues, list)

    def test_get_stats_data(self) -> None:
        """Test getting statistics data."""
        presenter, _ = _make_presenter_with_full_data()

        result = presenter.get_stats_data()
        assert "total_nodes" in result
        assert "ready_nodes" in result
        assert "event_counts" in result
        assert result["total_nodes"] == 3
        assert result["ready_nodes"] == 2


# =============================================================================
# ClusterPresenter Message Tests
# =============================================================================


class TestClusterPresenterMessages:
    """Test ClusterPresenter message classes."""

    def test_cluster_data_loaded_message(self) -> None:
        """Test ClusterDataLoaded message can be created."""
        msg = ClusterDataLoaded()
        assert isinstance(msg, ClusterDataLoaded)

    def test_cluster_data_load_failed_message(self) -> None:
        """Test ClusterDataLoadFailed message contains error."""
        error_msg = "Connection refused"
        msg = ClusterDataLoadFailed(error_msg)
        assert msg.error == error_msg

    def test_cluster_data_load_failed_empty_error(self) -> None:
        """Test ClusterDataLoadFailed with empty error string."""
        msg = ClusterDataLoadFailed("")
        assert msg.error == ""


# =============================================================================
# ClusterPresenter Load Data Tests
# =============================================================================


class TestClusterPresenterLoadData:
    """Test ClusterPresenter data loading methods."""

    def test_load_data_exists(self) -> None:
        """Test load_data method exists."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        assert hasattr(presenter, "load_data")
        assert callable(presenter.load_data)

    def test_load_data_sets_loading_state(self) -> None:
        """Test load_data sets is_loading to True and clears error."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)
        presenter._error_message = "old error"

        presenter.load_data()

        assert presenter._is_loading is True
        assert presenter._error_message == ""

    def test_connection_check_timeout_uses_shared_constant(self) -> None:
        """Connection check timeout should align with global timeout config."""
        assert ClusterPresenter._CONNECTION_CHECK_TIMEOUT_SECONDS == CLUSTER_CHECK_TIMEOUT


# =============================================================================
# ClusterPresenter Edge Cases Tests
# =============================================================================


class TestClusterPresenterEdgeCases:
    """Test ClusterPresenter edge cases."""

    def test_count_ready_nodes_with_different_statuses(self) -> None:
        """Test counting ready nodes with mixed status values."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = [
            _make_mock_node("n1", "Ready"),
            _make_mock_node("n2", "NotReady"),
        ]

        ready, total = presenter.count_ready_nodes()
        assert ready == 1
        assert total == 2

    def test_count_events_no_type_value_attr(self) -> None:
        """Test counting events when type has no value attr uses str()."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        mock_event = MagicMock()
        mock_event.type = MagicMock()
        del mock_event.type.value
        presenter._data["events"] = [mock_event]

        counts = presenter.count_events_by_type()
        assert isinstance(counts, dict)

    def test_get_overview_data_empty(self) -> None:
        """Test getting overview data when empty."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        presenter._data["nodes"] = []
        presenter._data["events"] = []
        presenter._data["pdbs"] = []
        presenter._data["single_replica"] = []

        result = presenter.get_overview_data()
        assert result["total_nodes"] == 0
        assert result["ready_nodes"] == 0

    def test_get_node_rows_long_name_truncated(self) -> None:
        """Test that node names longer than 35 chars are truncated."""
        mock_screen = MockClusterScreen()
        presenter = ClusterPresenter(mock_screen)

        long_name = "a" * 50
        presenter._data["nodes"] = [_make_mock_node(name=long_name)]

        rows = presenter.get_node_rows()
        assert len(rows[0][0]) == 35

    def test_streaming_nodes_updates_derived_sources_during_partial_callbacks(
        self,
    ) -> None:
        """Partial node callbacks should populate node-derived widget sources immediately."""

        class _TestPresenter(ClusterPresenter):
            def __init__(self, screen: MockClusterScreen) -> None:
                super().__init__(screen)
                self.partial_snapshots: list[tuple[str, bool, bool]] = []

            def _emit_partial_source_update(self, key: str, value: Any) -> None:
                self.partial_snapshots.append(
                    (
                        key,
                        bool(self._data.get("node_groups")),
                        bool(self._data.get("az_distribution")),
                    )
                )
                super()._emit_partial_source_update(key, value)

        class _Controller:
            @staticmethod
            async def fetch_nodes(
                *,
                include_pod_resources: bool,
                on_node_update: Any,
            ) -> list[SimpleNamespace]:
                _ = include_pod_resources
                nodes = [
                    SimpleNamespace(
                        name="node-a",
                        conditions={"Ready": "True"},
                        taints=[],
                        availability_zone="us-east-1a",
                        instance_type="m5.large",
                        kubelet_version="v1.29.0",
                        node_group="group-a",
                        cpu_allocatable=4.0,
                        memory_allocatable=16.0,
                        cpu_requests=2.0,
                        memory_requests=8.0,
                        cpu_limits=3.0,
                        memory_limits=12.0,
                        pod_count=40,
                        pod_capacity=110,
                    ),
                    SimpleNamespace(
                        name="node-b",
                        conditions={"Ready": "True"},
                        taints=[],
                        availability_zone="us-east-1b",
                        instance_type="m5.xlarge",
                        kubelet_version="v1.29.0",
                        node_group="group-a",
                        cpu_allocatable=4.0,
                        memory_allocatable=16.0,
                        cpu_requests=1.0,
                        memory_requests=4.0,
                        cpu_limits=2.0,
                        memory_limits=8.0,
                        pod_count=20,
                        pod_capacity=110,
                    ),
                ]
                on_node_update(nodes[:1], 1, 2)
                on_node_update(nodes, 2, 2)
                return nodes

        mock_screen = MockClusterScreen()
        presenter = _TestPresenter(mock_screen)
        controller = _Controller()

        nodes = asyncio.run(presenter._load_streaming_nodes(controller))  # type: ignore[arg-type]

        assert len(nodes) == 2
        assert presenter.partial_snapshots
        first_partial = presenter.partial_snapshots[0]
        assert first_partial[0] == "nodes"
        assert first_partial[1] is True
        assert first_partial[2] is True

    def test_streaming_nodes_throttles_expensive_partial_derived_rebuilds(
        self,
    ) -> None:
        """Derived node snapshots should be throttled during rapid partial callbacks."""

        class _ThrottlePresenter(ClusterPresenter):
            def __init__(self, screen: MockClusterScreen) -> None:
                super().__init__(screen)
                self.derived_rebuild_calls = 0

            def _build_derived_node_sources(self, nodes: list) -> dict[str, Any]:
                self.derived_rebuild_calls += 1
                return {
                    "node_groups": {"group-a": {"node_count": len(nodes)}},
                    "az_distribution": {"us-east-1a": len(nodes)},
                }

            async def _cache_derived_node_sources(self, nodes: list) -> None:
                _ = nodes
                return

            def _emit_partial_source_update(self, key: str, value: Any) -> None:
                _ = (key, value)
                return

        class _Controller:
            @staticmethod
            async def fetch_nodes(
                *,
                include_pod_resources: bool,
                on_node_update: Any,
            ) -> list[SimpleNamespace]:
                _ = include_pod_resources
                nodes = [
                    SimpleNamespace(name="node-a"),
                    SimpleNamespace(name="node-b"),
                    SimpleNamespace(name="node-c"),
                ]
                on_node_update(nodes[:1], 1, 3)
                on_node_update(nodes[:2], 2, 3)
                on_node_update(nodes, 3, 3)
                return nodes

        presenter = _ThrottlePresenter(MockClusterScreen())
        presenter._PARTIAL_NODE_DERIVED_EMIT_INTERVAL_SECONDS = 999.0
        controller = _Controller()
        nodes = asyncio.run(presenter._load_streaming_nodes(controller))  # type: ignore[arg-type]

        assert len(nodes) == 3
        # First partial + final completion callback should rebuild derived snapshots.
        assert presenter.derived_rebuild_calls == 2


class TestClusterPresenterPodStatsRows:
    """Test pod request/limit row formatting for workloads summary digits."""

    def test_get_overview_pod_stats_rows_with_request_and_limit_metrics(self) -> None:
        """Presenter should expose CPU/Memory request+limit rows."""
        presenter = ClusterPresenter(MockClusterScreen())
        presenter._data["pod_request_stats"] = {
            "cpu_request_stats": {"min": 100.0, "avg": 200.0, "max": 300.0, "p95": 280.0},
            "cpu_limit_stats": {"min": 500.0, "avg": 700.0, "max": 900.0, "p95": 850.0},
            "memory_request_stats": {
                "min": 128 * 1024 * 1024,
                "avg": 256 * 1024 * 1024,
                "max": 512 * 1024 * 1024,
                "p95": 480 * 1024 * 1024,
            },
            "memory_limit_stats": {
                "min": 512 * 1024 * 1024,
                "avg": 768 * 1024 * 1024,
                "max": 1024 * 1024 * 1024,
                "p95": 960 * 1024 * 1024,
            },
        }

        rows = presenter.get_overview_pod_stats_rows()

        assert rows == [
            ("CPU Request (m)", "100", "200", "300", "280"),
            ("CPU Limit (m)", "500", "700", "900", "850"),
            ("Memory Request (Mi)", "128", "256", "512", "480"),
            ("Memory Limit (Mi)", "512", "768", "1024", "960"),
        ]

    def test_get_overview_pod_stats_rows_supports_legacy_keys(self) -> None:
        """Presenter should keep legacy cpu_stats/memory_stats compatibility."""
        presenter = ClusterPresenter(MockClusterScreen())
        presenter._data["pod_request_stats"] = {
            "cpu_stats": {"min": 50.0, "avg": 120.0, "max": 200.0, "p95": 180.0},
            "memory_stats": {
                "min": 64 * 1024 * 1024,
                "avg": 128 * 1024 * 1024,
                "max": 256 * 1024 * 1024,
                "p95": 240 * 1024 * 1024,
            },
        }

        rows = presenter.get_overview_pod_stats_rows()

        assert rows == [
            ("CPU Request (m)", "50", "120", "200", "180"),
            ("Memory Request (Mi)", "64", "128", "256", "240"),
        ]


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestClusterPresenterCalcHealth",
    "TestClusterPresenterDataAccessors",
    "TestClusterPresenterDictEventHandling",
    "TestClusterPresenterEdgeCases",
    "TestClusterPresenterFormatPct",
    "TestClusterPresenterHealthMethods",
    "TestClusterPresenterInitialization",
    "TestClusterPresenterLoadData",
    "TestClusterPresenterMessages",
    "TestClusterPresenterPodStatsRows",
    "TestClusterPresenterProperties",
    "TestClusterPresenterRowFormatting",
    "TestClusterPresenterTabDataMethods",
]
