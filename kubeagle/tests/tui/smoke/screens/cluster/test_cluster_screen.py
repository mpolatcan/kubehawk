"""Smoke tests for ClusterScreen - widget composition, keybindings, initial state, and presenter integration.

This module tests:
- Screen class attributes and properties
- Widget composition verification
- Keybinding verification
- Tab navigation verification
- Initial state (all reactive/instance attributes)
- Method existence verification (new methods from refactor)
- Presenter integration (screen-presenter linkage)

Note: Tests using app.run_test() are kept minimal due to Textual testing overhead.
"""

from __future__ import annotations

import inspect

from kubeagle.screens.cluster import ClusterScreen
from kubeagle.screens.cluster.config import (
    CLUSTER_TABLE_HEADER_TOOLTIPS,
    NODE_TABLE_COLUMNS,
)
from kubeagle.widgets import CustomButton, CustomDataTable

# =============================================================================
# Widget Composition Tests
# =============================================================================


class TestClusterScreenWidgetComposition:
    """Test ClusterScreen widget composition."""

    def test_screen_has_correct_bindings(self) -> None:
        """Test that ClusterScreen has correct bindings."""
        assert hasattr(ClusterScreen, "BINDINGS")
        assert len(ClusterScreen.BINDINGS) > 0

    def test_screen_has_css_path(self) -> None:
        """Test that ClusterScreen has CSS_PATH."""
        assert hasattr(ClusterScreen, "CSS_PATH")
        assert "cluster" in ClusterScreen.CSS_PATH.lower()

    def test_screen_has_all_tabs(self) -> None:
        """Test that ClusterScreen exposes Nodes/Workloads/Events tabs."""
        expected_tabs = [
            "tab-nodes",
            "tab-pods",
            "tab-events",
        ]

        for tab in expected_tabs:
            assert tab in ClusterScreen.TAB_IDS, f"Tab {tab} should be in TAB_IDS"

    def test_screen_can_be_instantiated(self) -> None:
        """Test that ClusterScreen can be instantiated."""
        screen = ClusterScreen()
        assert screen is not None

    def test_workloads_tab_uses_kpi_surface_without_embedded_tables(self) -> None:
        """Workloads tab should render KPI cards only (no embedded data tables)."""
        source = inspect.getsource(ClusterScreen.compose)
        assert "pdbs-table" not in source
        assert "all-workloads-table" not in source
        assert "single-replica-table" not in source
        assert ClusterScreen._TAB_TABLE_IDS["tab-pods"] == ()

    def test_configure_cluster_table_header_tooltips_uses_config_mapping(self) -> None:
        """Cluster screen should apply configured header tooltip mapping."""
        from unittest.mock import MagicMock

        screen = ClusterScreen()
        table = MagicMock(spec=CustomDataTable)

        screen._configure_cluster_table_header_tooltips(
            table,
            "nodes-table",
            NODE_TABLE_COLUMNS,
        )

        table.set_header_tooltips.assert_called_once_with(
            CLUSTER_TABLE_HEADER_TOOLTIPS["nodes-table"]
        )

    def test_node_group_dynamic_az_column_gets_tooltip(self) -> None:
        """Grouped node-group AZ columns should receive generated tooltip text."""
        from unittest.mock import MagicMock

        screen = ClusterScreen()
        table = MagicMock(spec=CustomDataTable)
        columns = [
            ("Node Group", 28),
            ("us-east-1 (a/b/c)", 16),
        ]

        screen._configure_cluster_table_header_tooltips(
            table,
            "node-groups-table",
            columns,
        )

        called_with = table.set_header_tooltips.call_args.args[0]
        assert called_with["Node Group"] == (
            CLUSTER_TABLE_HEADER_TOOLTIPS["node-groups-table"]["Node Group"]
        )
        assert called_with["us-east-1 (a/b/c)"] == (
            "Number of nodes per availability zone in region us-east-1 (order: a/b/c)."
        )


# =============================================================================
# ClusterScreen Keybinding Tests
# =============================================================================


class TestClusterScreenKeybindings:
    """Test ClusterScreen-specific keybindings."""

    def test_has_pop_screen_binding(self) -> None:
        """Test that escape binding exists."""
        bindings = ClusterScreen.BINDINGS
        escape_bindings = [b for b in bindings if b[0] == "escape"]
        assert len(escape_bindings) > 0

    def test_has_refresh_binding(self) -> None:
        """Test that 'r' refresh binding exists."""
        bindings = ClusterScreen.BINDINGS
        refresh_bindings = [b for b in bindings if b[0] == "r"]
        assert len(refresh_bindings) > 0

    def test_has_search_binding(self) -> None:
        """Test that '/' search binding exists."""
        bindings = ClusterScreen.BINDINGS
        search_bindings = [b for b in bindings if b[0] == "slash"]
        assert len(search_bindings) > 0

    def test_has_tab_switch_bindings(self) -> None:
        """Test that tab switch bindings (1-3) exist."""
        bindings = ClusterScreen.BINDINGS
        tab_bindings = [b for b in bindings if b[0] in ["1", "2", "3"]]
        assert len(tab_bindings) == 3

    def test_has_navigation_bindings(self) -> None:
        """Test that navigation bindings exist."""
        bindings = ClusterScreen.BINDINGS
        nav_keys = ["h"]
        nav_bindings = [b for b in bindings if b[0] in nav_keys]
        assert len(nav_bindings) > 0


# =============================================================================
# Loading State Tests
# =============================================================================


class TestClusterScreenLoadingStates:
    """Test ClusterScreen loading state management."""

    def test_presenter_initial_state(self) -> None:
        """Test that presenter can be created."""
        screen = ClusterScreen()
        assert screen._presenter is not None
        assert hasattr(screen._presenter, "is_loading")
        assert hasattr(screen._presenter, "error_message")

    def test_show_loading_message_method_exists(self) -> None:
        """Test that _update_loading_message method exists."""
        screen = ClusterScreen()
        assert hasattr(screen, "_update_loading_message")


# =============================================================================
# Tab Navigation Tests
# =============================================================================


class TestClusterScreenTabNavigation:
    """Test ClusterScreen tab navigation."""

    def test_action_switch_tab_methods_exist(self) -> None:
        """Test that tab switch methods exist."""
        screen = ClusterScreen()

        assert hasattr(screen, "action_switch_tab_1")
        assert hasattr(screen, "action_switch_tab_2")
        assert hasattr(screen, "action_switch_tab_3")

    def test_tab_ids_count(self) -> None:
        """Test that TAB_IDS reflects merged tab set."""
        assert len(ClusterScreen.TAB_IDS) == 3


# =============================================================================
# Screen Properties Tests
# =============================================================================


class TestClusterScreenProperties:
    """Test ClusterScreen property accessors."""

    def test_screen_class_attributes(self) -> None:
        """Test that ClusterScreen has correct class attributes."""
        assert hasattr(ClusterScreen, "BINDINGS")
        assert len(ClusterScreen.BINDINGS) > 0

    def test_screen_has_css_path(self) -> None:
        """Test that ClusterScreen has CSS_PATH."""
        assert hasattr(ClusterScreen, "CSS_PATH")

    def test_presenter_property(self) -> None:
        """Test that presenter can be created."""
        screen = ClusterScreen()
        assert screen._presenter is not None

    def test_context_property(self) -> None:
        """Test that context can be set."""
        screen = ClusterScreen(context="test-context")
        assert screen.context == "test-context"


# =============================================================================
# Error State Tests
# =============================================================================


class TestClusterScreenErrorStates:
    """Test ClusterScreen error handling."""

    def test_show_error_state_method_exists(self) -> None:
        """Test that _show_error_state method exists."""
        screen = ClusterScreen()
        assert hasattr(screen, "_show_error_state")

    def test_update_status_bar_method_exists(self) -> None:
        """Test that _update_status_bar method exists."""
        screen = ClusterScreen()
        assert hasattr(screen, "_update_status_bar")


# =============================================================================
# Initial State Tests
# =============================================================================


class TestClusterScreenInitialState:
    """Test ClusterScreen initial attribute values after construction."""

    def test_default_context_is_none(self) -> None:
        """Test ClusterScreen() default context is None."""
        screen = ClusterScreen()
        assert screen.context is None

    def test_custom_context(self) -> None:
        """Test ClusterScreen(context='prod') stores context."""
        screen = ClusterScreen(context="prod")
        assert screen.context == "prod"

    def test_error_message_initial_none(self) -> None:
        """Test _error_message is None initially."""
        screen = ClusterScreen()
        assert screen._error_message is None

    def test_last_updated_initial_none(self) -> None:
        """Test _last_updated is None initially."""
        screen = ClusterScreen()
        assert screen._last_updated is None

    def test_loading_message_initial_empty(self) -> None:
        """Test _loading_message is empty string initially."""
        screen = ClusterScreen()
        assert screen._loading_message == ""

    def test_is_refreshing_initial_false(self) -> None:
        """Test _is_refreshing is False initially."""
        screen = ClusterScreen()
        assert screen._is_refreshing is False

    def test_tab_loading_states_initial_empty(self) -> None:
        """Test _tab_loading_states is empty dict initially."""
        screen = ClusterScreen()
        assert screen._tab_loading_states == {}

    def test_tab_last_updated_initial_empty(self) -> None:
        """Test _tab_last_updated is empty dict initially."""
        screen = ClusterScreen()
        assert screen._tab_last_updated == {}


# =============================================================================
# Method Existence Tests
# =============================================================================


class TestClusterScreenMethodsExist:
    """Test that all expected methods exist on ClusterScreen after refactor."""

    def test_has_refresh_all_tabs(self) -> None:
        """Test _refresh_all_tabs method exists."""
        screen = ClusterScreen()
        assert hasattr(screen, "_refresh_all_tabs")
        assert callable(screen._refresh_all_tabs)

    def test_has_update_table(self) -> None:
        """Test _update_table method exists."""
        screen = ClusterScreen()
        assert hasattr(screen, "_update_table")
        assert callable(screen._update_table)

    def test_has_update_static_tab(self) -> None:
        """Test _update_static_tab method exists."""
        screen = ClusterScreen()
        assert hasattr(screen, "_update_static_tab")
        assert callable(screen._update_static_tab)

    def test_has_action_refresh(self) -> None:
        """Test action_refresh method exists."""
        screen = ClusterScreen()
        assert hasattr(screen, "action_refresh")
        assert callable(screen.action_refresh)

    def test_has_action_focus_search(self) -> None:
        """Test action_focus_search method exists."""
        screen = ClusterScreen()
        assert hasattr(screen, "action_focus_search")
        assert callable(screen.action_focus_search)

    def test_has_action_show_help(self) -> None:
        """Test action_show_help method exists."""
        screen = ClusterScreen()
        assert hasattr(screen, "action_show_help")
        assert callable(screen.action_show_help)

    def test_has_on_cluster_data_loaded(self) -> None:
        """Test on_cluster_data_loaded method exists."""
        screen = ClusterScreen()
        assert hasattr(screen, "on_cluster_data_loaded")
        assert callable(screen.on_cluster_data_loaded)

    def test_has_on_cluster_data_load_failed(self) -> None:
        """Test on_cluster_data_load_failed method exists."""
        screen = ClusterScreen()
        assert hasattr(screen, "on_cluster_data_load_failed")
        assert callable(screen.on_cluster_data_load_failed)


# =============================================================================
# Presenter Integration Tests
# =============================================================================


class TestClusterScreenPresenterIntegration:
    """Test ClusterScreen-ClusterPresenter integration."""

    def test_presenter_has_correct_screen_ref(self) -> None:
        """Test that presenter references the screen instance."""
        screen = ClusterScreen()
        assert screen._presenter._screen is screen

    def test_presenter_initial_not_loading(self) -> None:
        """Test that presenter is not loading initially."""
        screen = ClusterScreen()
        assert screen._presenter.is_loading is False

    def test_presenter_initial_no_error(self) -> None:
        """Test that presenter has no error initially."""
        screen = ClusterScreen()
        assert screen._presenter.error_message == ""

    def test_presenter_initial_not_connected(self) -> None:
        """Test that presenter is not connected initially."""
        screen = ClusterScreen()
        assert screen._presenter.is_connected is False


# =============================================================================
# Filter Option Tests
# =============================================================================


class TestClusterScreenFilterOptions:
    """Test tab filter option generation behavior."""

    def test_numeric_like_text_detection(self) -> None:
        """Numeric values with units and ratios must be treated as numeric-like."""
        screen = ClusterScreen()
        assert screen._is_numeric_like_text("500m") is True
        assert screen._is_numeric_like_text("2Gi") is True
        assert screen._is_numeric_like_text("85%") is True
        assert screen._is_numeric_like_text("3/10") is True
        assert screen._is_numeric_like_text("default") is False
        assert screen._is_numeric_like_text("nodegroup-a") is False

    def test_build_filter_options_only_from_string_data(self) -> None:
        """Filter options should include string columns and exclude numeric columns."""
        screen = ClusterScreen()
        long_name = "atlas-atlas-pdb-super-long-name-with-full-value-visible"
        columns = [
            ("Name", 30),
            ("Namespace", 20),
            ("CPU Req (m)", 12),
            ("Mem Alloc (GiB)", 14),
            ("Pod Count", 10),
        ]
        rows = [
            ("pod-a-1", "default", "500m", "2Gi", "8"),
            (long_name, "kube-system", "250m", "1Gi", "12"),
        ]

        options_by_column = screen._build_tab_string_filter_options([(columns, rows)])
        name_options = options_by_column["name"][1]
        name_values = {value for _, value in name_options}
        name_labels = {value: label for label, value in name_options}
        namespace_values = {value for _, value in options_by_column["namespace"][1]}

        assert "name" in options_by_column
        assert "namespace" in options_by_column
        assert "cpu_req_m" not in options_by_column
        assert "mem_alloc_gib" not in options_by_column
        assert "pod_count" not in options_by_column
        assert "all" in name_values
        assert "all" in namespace_values
        assert screen._encode_filter_value("Name", "pod-a-1") in name_values
        assert name_labels[screen._encode_filter_value("Name", "pod-a-1")] == "pod-a-1"
        assert (
            name_labels[screen._encode_filter_value("Name", long_name)]
            == long_name
        )
        assert screen._encode_filter_value("Namespace", "default") in namespace_values
        assert screen._filter_trigger_label("Namespace") == "Namespace"
        trigger_label = "Name"
        requested_width = max(10, len(trigger_label) + 4)
        responsive_available = max(
            screen._FILTER_SELECT_MIN_RESPONSIVE_WIDTH,
            screen._current_viewport_width() - screen._FILTER_ROW_FIXED_OVERHEAD,
        )
        expected_cap = min(
            screen._FILTER_SELECT_BASE_MAX_WIDTH,
            max(
                screen._FILTER_SELECT_MIN_RESPONSIVE_WIDTH,
                responsive_available,
            ),
        )
        assert screen._filter_select_width_from_options(
            name_options,
            control_label=trigger_label,
        ) == min(
            requested_width,
            expected_cap,
        )

    def test_build_filter_options_include_all_when_rows_empty(self) -> None:
        """Eligible string columns should still render an All option without row data."""
        screen = ClusterScreen()
        columns = [
            ("Name", 20),
            ("Namespace", 20),
            ("CPU Req %", 10),
        ]

        options_by_column = screen._build_tab_string_filter_options([(columns, [])])
        assert "name" in options_by_column
        assert "namespace" in options_by_column
        assert "cpu_req" not in options_by_column
        assert options_by_column["name"][1] == (("All", "all"),)
        assert options_by_column["namespace"][1] == (("All", "all"),)

    def test_build_filter_options_excludes_aws_az_columns(self) -> None:
        """Dynamic grouped AWS AZ columns should be hidden from filters."""
        screen = ClusterScreen()
        columns = [
            ("Node Group", 20),
            ("us-east-1 (a/b/c)", 16),
            ("us-west-2 (a/b)", 14),
        ]
        rows = [
            ("eks-qa-arm-16x", "2/1/0", "1/0"),
            ("eks-qa-arm-4x", "0/1/1", "0/1"),
        ]

        options_by_column = screen._build_tab_string_filter_options([(columns, rows)])
        assert "node_group" in options_by_column
        assert "us_east_1_a_b_c" not in options_by_column
        assert "us_west_2_a_b" not in options_by_column

    def test_filter_rows_by_dropdown_supports_multi_value_sets(self) -> None:
        """Multi-select filters should OR within one column and AND across columns."""
        screen = ClusterScreen()
        columns = [("Namespace", 20), ("Name", 20), ("Status", 12)]
        rows = [
            ("team-a", "svc-a", "Ready"),
            ("team-b", "svc-b", "Ready"),
            ("team-c", "svc-c", "NotReady"),
        ]
        selected_filters = {
            "namespace": {
                screen._encode_filter_value("Namespace", "team-a"),
                screen._encode_filter_value("Namespace", "team-b"),
            },
            "status": {screen._encode_filter_value("Status", "Ready")},
        }

        filtered_rows = screen._filter_rows_by_dropdown(rows, columns, selected_filters)
        assert filtered_rows == [
            ("team-a", "svc-a", "Ready"),
            ("team-b", "svc-b", "Ready"),
        ]

    def test_filter_rows_by_dropdown_treats_all_as_column_noop(self) -> None:
        """A column selection containing 'all' should not filter out any rows."""
        screen = ClusterScreen()
        columns = [("Namespace", 20), ("Name", 20)]
        rows = [
            ("team-a", "svc-a"),
            ("team-b", "svc-b"),
        ]
        selected_filters = {
            "namespace": {"all"},
        }

        assert screen._filter_rows_by_dropdown(rows, columns, selected_filters) == rows

    def test_rows_signature_is_bounded_to_fixed_width(self) -> None:
        """Row signatures should stay bounded to avoid big-int growth costs."""
        screen = ClusterScreen()
        rows = [(f"row-{i}", f"value-{i % 17}") for i in range(50_000)]

        signature = screen._rows_signature(rows)

        assert signature.bit_length() <= 64

    def test_sync_tab_filter_options_updates_filter_button_label(self) -> None:
        """Filter sync should update unified filter button with active count text."""
        screen = ClusterScreen()
        filter_btn = CustomButton(
            "Filters",
            id=screen._control_id("tab-nodes", "filters-btn"),
            classes="cluster-tab-filters-btn",
        )
        screen.query_one = lambda *_args, **_kwargs: filter_btn  # type: ignore[method-assign]

        table_data = [
            (
                [("Name", 20), ("Namespace", 20), ("CPU Req %", 10)],
                [("node-a", "default", "85%"), ("node-b", "kube-system", "72%")],
            )
        ]
        screen._sync_tab_filter_options("tab-nodes", table_data)
        assert filter_btn.label == "Filters"

        name_value = screen._encode_filter_value("Name", "node-a")
        screen._tab_column_filter_values["tab-nodes"] = {"name": {name_value}}
        screen._update_filter_dialog_button("tab-nodes")
        assert filter_btn.label == "Filters (1/1)"


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestClusterScreenErrorStates",
    "TestClusterScreenFilterOptions",
    "TestClusterScreenInitialState",
    "TestClusterScreenKeybindings",
    "TestClusterScreenLoadingStates",
    "TestClusterScreenMethodsExist",
    "TestClusterScreenPresenterIntegration",
    "TestClusterScreenProperties",
    "TestClusterScreenTabNavigation",
    "TestClusterScreenWidgetComposition",
]
