"""Unit tests for ClusterScreen configuration constants.

This module tests:
- Tab ID constants (uniqueness, values)
- Tab title mappings (completeness, types)
- Table column definitions (counts, types, widths)
- Event display limit constant

All constants are imported from screens.cluster.config.
"""

from __future__ import annotations

from kubeagle.screens.cluster.config import (
    CLUSTER_TABLE_HEADER_TOOLTIPS,
    EVENTS_DETAIL_TABLE_COLUMNS,
    MAX_EVENTS_DISPLAY,
    NODE_GROUPS_TABLE_COLUMNS,
    NODE_TABLE_COLUMNS,
    PDBS_TABLE_COLUMNS,
    TAB_EVENTS,
    TAB_GROUPS,
    TAB_HEALTH,
    TAB_NODE_DIST,
    TAB_NODES,
    TAB_OVERVIEW,
    TAB_PDBS,
    TAB_PODS,
    TAB_SINGLE_REPLICA,
    TAB_STATS,
    TAB_TITLES,
)

# =============================================================================
# Tab ID Tests
# =============================================================================


class TestClusterConfigTabIDs:
    """Test cluster config tab ID constants."""

    def test_tab_overview_value(self) -> None:
        """Test TAB_OVERVIEW alias points to events tab."""
        assert TAB_OVERVIEW == TAB_EVENTS == "tab-events"

    def test_tab_nodes_value(self) -> None:
        """Test TAB_NODES has correct value."""
        assert TAB_NODES == "tab-nodes"

    def test_tab_pods_value(self) -> None:
        """Test TAB_PODS has correct value."""
        assert TAB_PODS == "tab-pods"

    def test_tab_events_value(self) -> None:
        """Test TAB_EVENTS has correct value."""
        assert TAB_EVENTS == "tab-events"

    def test_tab_pdbs_value(self) -> None:
        """Test TAB_PDBS has correct value."""
        assert TAB_PDBS == "tab-pdbs"

    def test_tab_single_replica_value(self) -> None:
        """Test TAB_SINGLE_REPLICA has correct value."""
        assert TAB_SINGLE_REPLICA == "tab-single-replica"

    def test_tab_health_value(self) -> None:
        """Test TAB_HEALTH has correct value."""
        assert TAB_HEALTH == "tab-health"

    def test_tab_node_dist_value(self) -> None:
        """Test TAB_NODE_DIST has correct value."""
        assert TAB_NODE_DIST == "tab-node-dist"

    def test_tab_groups_value(self) -> None:
        """Test TAB_GROUPS has correct value."""
        assert TAB_GROUPS == "tab-groups"

    def test_tab_stats_value(self) -> None:
        """Test TAB_STATS has correct value."""
        assert TAB_STATS == "tab-stats"

    def test_all_active_tab_ids_unique(self) -> None:
        """Test active cluster tab IDs are unique."""
        all_tabs = [TAB_NODES, TAB_PODS, TAB_EVENTS]
        assert len(all_tabs) == 3
        assert len(set(all_tabs)) == 3, "Active tab IDs must be unique"

    def test_tab_titles_has_all_tabs(self) -> None:
        """Test TAB_TITLES has entries for all active cluster tabs."""
        all_tabs = [
            TAB_NODES,
            TAB_PODS,
            TAB_EVENTS,
        ]
        for tab_id in all_tabs:
            assert tab_id in TAB_TITLES, f"TAB_TITLES missing entry for {tab_id}"

    def test_tab_titles_all_strings(self) -> None:
        """Test all values in TAB_TITLES are non-empty strings."""
        for tab_id, title in TAB_TITLES.items():
            assert isinstance(title, str), f"Title for {tab_id} must be a string"
            assert len(title) > 0, f"Title for {tab_id} must not be empty"


# =============================================================================
# Column Definition Tests
# =============================================================================


class TestClusterConfigColumns:
    """Test cluster config table column definitions."""

    def test_node_table_columns_count(self) -> None:
        """Test NODE_TABLE_COLUMNS uses combined request/limit utilization columns."""
        assert len(NODE_TABLE_COLUMNS) == 7

    def test_events_detail_table_columns_count(self) -> None:
        """Test EVENTS_DETAIL_TABLE_COLUMNS has 5 columns."""
        assert len(EVENTS_DETAIL_TABLE_COLUMNS) == 5

    def test_pdbs_table_columns_count(self) -> None:
        """Test PDBS_TABLE_COLUMNS has 10 columns."""
        assert len(PDBS_TABLE_COLUMNS) == 10

    def test_node_groups_table_columns_count(self) -> None:
        """Test NODE_GROUPS_TABLE_COLUMNS has combined request/limit triplets."""
        assert len(NODE_GROUPS_TABLE_COLUMNS) == 6

    def test_all_columns_are_tuples(self) -> None:
        """Test each column is a (str, int) tuple."""
        all_column_defs = [
            NODE_TABLE_COLUMNS, EVENTS_DETAIL_TABLE_COLUMNS,
            PDBS_TABLE_COLUMNS, NODE_GROUPS_TABLE_COLUMNS,
        ]
        for columns in all_column_defs:
            for col in columns:
                assert isinstance(col, tuple), f"Column {col} must be a tuple"
                assert len(col) == 2, f"Column {col} must have exactly 2 elements"
                assert isinstance(col[0], str), f"Column name {col[0]} must be a string"
                assert isinstance(col[1], int), f"Column width {col[1]} must be an int"

    def test_all_widths_positive(self) -> None:
        """Test all width values are greater than 0."""
        all_column_defs = [
            NODE_TABLE_COLUMNS, EVENTS_DETAIL_TABLE_COLUMNS,
            PDBS_TABLE_COLUMNS, NODE_GROUPS_TABLE_COLUMNS,
        ]
        for columns in all_column_defs:
            for col_name, col_width in columns:
                assert col_width > 0, f"Width for '{col_name}' must be > 0, got {col_width}"

    def test_cluster_table_header_tooltips_table_keys(self) -> None:
        """Header tooltip mappings should exist for rendered cluster tab tables."""
        assert set(CLUSTER_TABLE_HEADER_TOOLTIPS.keys()) == {
            "all-workloads-table",
            "events-detail-table",
            "nodes-table",
            "node-groups-table",
            "pdbs-table",
            "single-replica-table",
        }

    def test_cluster_table_header_tooltips_cover_static_columns(self) -> None:
        """Each static table column should have a tooltip entry."""
        assert set(CLUSTER_TABLE_HEADER_TOOLTIPS["events-detail-table"].keys()) == {
            name for name, _ in EVENTS_DETAIL_TABLE_COLUMNS
        }
        assert set(CLUSTER_TABLE_HEADER_TOOLTIPS["nodes-table"].keys()) == {
            name for name, _ in NODE_TABLE_COLUMNS
        }
        assert {name for name, _ in NODE_GROUPS_TABLE_COLUMNS}.issubset(
            set(CLUSTER_TABLE_HEADER_TOOLTIPS["node-groups-table"].keys())
        )
        assert set(CLUSTER_TABLE_HEADER_TOOLTIPS["pdbs-table"].keys()) == {
            name for name, _ in PDBS_TABLE_COLUMNS
        }

    def test_cluster_table_header_tooltips_values_non_empty(self) -> None:
        """All header tooltip values should be non-empty strings."""
        for table_tooltips in CLUSTER_TABLE_HEADER_TOOLTIPS.values():
            for column_name, tooltip_text in table_tooltips.items():
                assert isinstance(column_name, str)
                assert isinstance(tooltip_text, str)
                assert tooltip_text.strip()


# =============================================================================
# Event Limit Tests
# =============================================================================


class TestClusterConfigEventLimit:
    """Test cluster config event limit constant."""

    def test_max_events_display_value(self) -> None:
        """Test MAX_EVENTS_DISPLAY has expected value."""
        assert MAX_EVENTS_DISPLAY == 100


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestClusterConfigColumns",
    "TestClusterConfigEventLimit",
    "TestClusterConfigTabIDs",
]
