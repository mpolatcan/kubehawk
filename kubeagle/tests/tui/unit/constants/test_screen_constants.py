"""Unit tests for screen-specific constants in constants/screens/*.py.

Tests cover:
- constants/screens/cluster.py: Tab IDs, tab names, status labels, loading/error messages
- constants/screens/cluster.py: Event-window options for summary/events scope
- constants/screens/settings.py: Section headers, validation messages, button labels
- constants/screens/detail.py: Optimizer categories/severities, button/filter labels
- constants/screens/common.py: Theme names (DARK_THEME, LIGHT_THEME)
- constants/screens/charts_explorer.py: Screen title, search/button labels
- constants/screens/__init__.py: Re-exports
"""

from __future__ import annotations

from kubeagle.constants.screens.cluster import (
    CLUSTER_ERROR_LOADING,
    CLUSTER_EVENT_WINDOW_DEFAULT,
    CLUSTER_EVENT_WINDOW_OPTIONS,
    LOADING_ANALYZING,
    LOADING_CHECKING_CONNECTION,
    LOADING_FETCHING_EVENTS,
    LOADING_FETCHING_NODE_RESOURCES,
    LOADING_FETCHING_NODES,
    LOADING_FETCHING_PDBS,
    LOADING_FETCHING_SINGLE_REPLICA,
    LOADING_INITIALIZING,
    STATUS_LABEL_CLUSTER,
    STATUS_LABEL_NODES,
    STATUS_LABEL_UPDATED,
    STATUS_NEVER,
    STATUS_UNKNOWN,
    TAB_EVENTS,
    TAB_GROUPS,
    TAB_HEALTH,
    TAB_IDS,
    TAB_NODE_DIST,
    TAB_NODES,
    TAB_OVERVIEW,
    TAB_PDBS,
    TAB_PODS,
    TAB_SINGLE_REPLICA,
    TAB_STATS,
)
from kubeagle.constants.screens.common import (
    DARK_THEME,
    LIGHT_THEME,
)
from kubeagle.constants.screens.detail import (
    BUTTON_APPLY_ALL,
    BUTTON_FIX,
    BUTTON_PREVIEW,
    FILTER_CATEGORY,
    FILTER_SEVERITY,
    OPTIMIZER_CATEGORIES,
    OPTIMIZER_SEVERITIES,
)
from kubeagle.constants.screens.settings import (
    BUTTON_CANCEL,
    BUTTON_SAVE,
    SETTINGS_SAVE_SUCCESS,
    SETTINGS_SCREEN_TITLE,
    SETTINGS_SECTION_AI_FIX,
    SETTINGS_SECTION_CLUSTER,
    SETTINGS_SECTION_GENERAL,
    SETTINGS_SECTION_THRESHOLDS,
    SETTINGS_VALIDATION_MESSAGES,
)

# =============================================================================
# Cluster screen constants
# =============================================================================


class TestClusterScreenConstants:
    """Test cluster screen constants."""

    def test_tab_ids_is_list(self) -> None:
        assert isinstance(TAB_IDS, list)

    def test_tab_ids_count(self) -> None:
        assert len(TAB_IDS) == 10

    def test_tab_ids_all_strings(self) -> None:
        for tab_id in TAB_IDS:
            assert isinstance(tab_id, str)

    def test_tab_ids_all_prefixed(self) -> None:
        for tab_id in TAB_IDS:
            assert tab_id.startswith("tab-"), f"{tab_id} must start with 'tab-'"

    def test_tab_ids_unique(self) -> None:
        assert len(TAB_IDS) == len(set(TAB_IDS))

    def test_tab_overview_value(self) -> None:
        assert TAB_OVERVIEW == "1: Overview"

    def test_tab_nodes_value(self) -> None:
        assert TAB_NODES == "2: Nodes"

    def test_tab_pods_value(self) -> None:
        assert TAB_PODS == "3: Pods"

    def test_tab_events_value(self) -> None:
        assert TAB_EVENTS == "4: Events"

    def test_tab_pdbs_value(self) -> None:
        assert TAB_PDBS == "5: PDBs"

    def test_tab_single_replica_value(self) -> None:
        assert TAB_SINGLE_REPLICA == "6: Single Replica"

    def test_tab_health_value(self) -> None:
        assert TAB_HEALTH == "7: Health"

    def test_tab_node_dist_value(self) -> None:
        assert TAB_NODE_DIST == "8: Node Dist"

    def test_tab_groups_value(self) -> None:
        assert TAB_GROUPS == "9: Groups"

    def test_tab_stats_value(self) -> None:
        assert TAB_STATS == "0: Stats"

    def test_status_label_cluster_value(self) -> None:
        assert STATUS_LABEL_CLUSTER == "Cluster: "

    def test_status_label_updated_value(self) -> None:
        assert STATUS_LABEL_UPDATED == "Last Updated: "

    def test_status_never_value(self) -> None:
        assert STATUS_NEVER == "Never"

    def test_status_unknown_value(self) -> None:
        assert STATUS_UNKNOWN == "Unknown"

    def test_status_label_nodes_value(self) -> None:
        assert STATUS_LABEL_NODES == "Nodes: "

    def test_loading_initializing_type(self) -> None:
        assert isinstance(LOADING_INITIALIZING, str)

    def test_loading_checking_connection_type(self) -> None:
        assert isinstance(LOADING_CHECKING_CONNECTION, str)

    def test_loading_fetching_nodes_type(self) -> None:
        assert isinstance(LOADING_FETCHING_NODES, str)

    def test_loading_fetching_events_type(self) -> None:
        assert isinstance(LOADING_FETCHING_EVENTS, str)

    def test_loading_fetching_single_replica_type(self) -> None:
        assert isinstance(LOADING_FETCHING_SINGLE_REPLICA, str)

    def test_loading_fetching_pdbs_type(self) -> None:
        assert isinstance(LOADING_FETCHING_PDBS, str)

    def test_loading_fetching_node_resources_type(self) -> None:
        assert isinstance(LOADING_FETCHING_NODE_RESOURCES, str)

    def test_loading_analyzing_type(self) -> None:
        assert isinstance(LOADING_ANALYZING, str)

    def test_cluster_error_loading_type(self) -> None:
        assert isinstance(CLUSTER_ERROR_LOADING, str)

    def test_cluster_error_loading_has_placeholder(self) -> None:
        assert "{e}" in CLUSTER_ERROR_LOADING




# =============================================================================
# Cluster summary constants
# =============================================================================


class TestClusterSummaryConstants:
    """Test cluster summary/event-window constants."""

    def test_event_window_options_type(self) -> None:
        assert isinstance(CLUSTER_EVENT_WINDOW_OPTIONS, tuple)

    def test_event_window_options_non_empty(self) -> None:
        assert len(CLUSTER_EVENT_WINDOW_OPTIONS) > 0

    def test_event_window_options_have_label_and_value(self) -> None:
        for option in CLUSTER_EVENT_WINDOW_OPTIONS:
            assert isinstance(option, tuple)
            assert len(option) == 2
            assert isinstance(option[0], str)
            assert isinstance(option[1], str)

    def test_event_window_default_exists_in_options(self) -> None:
        option_values = {value for _, value in CLUSTER_EVENT_WINDOW_OPTIONS}
        assert CLUSTER_EVENT_WINDOW_DEFAULT in option_values


# =============================================================================
# Settings screen constants
# =============================================================================


class TestSettingsScreenConstants:
    """Test settings screen constants."""

    def test_section_general_value(self) -> None:
        assert SETTINGS_SECTION_GENERAL == "General Settings"

    def test_section_thresholds_type(self) -> None:
        assert isinstance(SETTINGS_SECTION_THRESHOLDS, str)

    def test_section_ai_fix_value(self) -> None:
        assert SETTINGS_SECTION_AI_FIX == "AI Fix Settings"

    def test_section_cluster_type(self) -> None:
        assert isinstance(SETTINGS_SECTION_CLUSTER, str)

    def test_validation_messages_type(self) -> None:
        assert isinstance(SETTINGS_VALIDATION_MESSAGES, dict)

    def test_validation_messages_non_empty(self) -> None:
        assert len(SETTINGS_VALIDATION_MESSAGES) > 0

    def test_validation_messages_values_are_tuples(self) -> None:
        for key, value in SETTINGS_VALIDATION_MESSAGES.items():
            assert isinstance(value, tuple), f"Validation entry {key} must be a tuple"
            assert len(value) == 2, f"Validation entry {key} must have 2 elements"
            assert isinstance(value[0], str), f"First element of {key} must be a string"

    def test_save_success_type(self) -> None:
        assert isinstance(SETTINGS_SAVE_SUCCESS, str)

    def test_button_save_type(self) -> None:
        assert isinstance(BUTTON_SAVE, str)

    def test_button_cancel_type(self) -> None:
        assert isinstance(BUTTON_CANCEL, str)

    def test_screen_title_type(self) -> None:
        assert isinstance(SETTINGS_SCREEN_TITLE, str)


# =============================================================================
# Detail screen constants
# =============================================================================


class TestDetailScreenConstants:
    """Test detail screen constants."""

    def test_optimizer_categories_type(self) -> None:
        assert isinstance(OPTIMIZER_CATEGORIES, list)

    def test_optimizer_categories_values(self) -> None:
        assert OPTIMIZER_CATEGORIES == ["resources", "probes", "availability", "security"]

    def test_optimizer_severities_type(self) -> None:
        assert isinstance(OPTIMIZER_SEVERITIES, list)

    def test_optimizer_severities_values(self) -> None:
        assert OPTIMIZER_SEVERITIES == ["error", "warning", "info"]

    def test_button_apply_all_type(self) -> None:
        assert isinstance(BUTTON_APPLY_ALL, str)

    def test_button_fix_type(self) -> None:
        assert isinstance(BUTTON_FIX, str)

    def test_button_preview_type(self) -> None:
        assert isinstance(BUTTON_PREVIEW, str)

    def test_filter_category_type(self) -> None:
        assert isinstance(FILTER_CATEGORY, str)

    def test_filter_severity_type(self) -> None:
        assert isinstance(FILTER_SEVERITY, str)


# =============================================================================
# Common screen constants (theme names)
# =============================================================================


class TestCommonScreenConstants:
    """Test common screen constants."""

    def test_dark_theme_type(self) -> None:
        assert isinstance(DARK_THEME, str)

    def test_light_theme_type(self) -> None:
        assert isinstance(LIGHT_THEME, str)

    def test_dark_theme_name(self) -> None:
        assert DARK_THEME == "KubEagle-Dark"

    def test_light_theme_name(self) -> None:
        assert LIGHT_THEME == "KubEagle-Light"


# =============================================================================
# Charts Explorer Constants
# =============================================================================


class TestChartsExplorerConstants:
    """Test constants/screens/charts_explorer.py values."""

    def test_charts_explorer_title_import(self) -> None:
        from kubeagle.constants.screens.charts_explorer import (
            CHARTS_EXPLORER_TITLE,
        )

        assert CHARTS_EXPLORER_TITLE == "Charts Explorer"

    def test_search_placeholder_import(self) -> None:
        from kubeagle.constants.screens.charts_explorer import (
            SEARCH_PLACEHOLDER,
        )

        assert isinstance(SEARCH_PLACEHOLDER, str)
        assert len(SEARCH_PLACEHOLDER) > 0

    def test_button_labels_import(self) -> None:
        from kubeagle.constants.screens.charts_explorer import (
            BUTTON_CLEAR,
            BUTTON_FILTER,
            BUTTON_MODE_CLUSTER,
            BUTTON_MODE_LOCAL,
        )

        assert isinstance(BUTTON_FILTER, str)
        assert isinstance(BUTTON_CLEAR, str)
        assert isinstance(BUTTON_MODE_LOCAL, str)
        assert isinstance(BUTTON_MODE_CLUSTER, str)

    def test_charts_explorer_title_in_screens_init(self) -> None:
        from kubeagle.constants.screens import CHARTS_EXPLORER_TITLE

        assert CHARTS_EXPLORER_TITLE == "Charts Explorer"


# =============================================================================
# __init__.py re-exports
# =============================================================================


class TestScreensPackageReExports:
    """Test that constants/screens/__init__.py re-exports all expected names."""

    def test_all_exports_importable(self) -> None:
        import kubeagle.constants.screens as mod

        for name in mod.__all__:
            assert hasattr(mod, name), f"{name} listed in __all__ but not defined"
