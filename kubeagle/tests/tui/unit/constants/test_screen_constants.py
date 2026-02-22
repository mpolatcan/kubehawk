"""Unit tests for screen-specific constants in constants/screens/*.py.

Tests cover:
- constants/screens/cluster.py: Tab IDs, tab names, status labels, event-window options
- constants/screens/settings.py: Section headers, button labels
- constants/screens/common.py: Theme names (DARK_THEME, LIGHT_THEME)
- constants/screens/charts_explorer.py: Screen title, search/button labels
- constants/screens/__init__.py: Re-exports
"""

from __future__ import annotations

from kubeagle.constants.screens.cluster import (
    CLUSTER_EVENT_WINDOW_DEFAULT,
    CLUSTER_EVENT_WINDOW_OPTIONS,
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
from kubeagle.constants.screens.settings import (
    BUTTON_CANCEL,
    BUTTON_SAVE,
    SETTINGS_SECTION_AI_FIX,
    SETTINGS_SECTION_GENERAL,
    SETTINGS_SECTION_THRESHOLDS,
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

    def test_status_never_value(self) -> None:
        assert STATUS_NEVER == "Never"

    def test_status_unknown_value(self) -> None:
        assert STATUS_UNKNOWN == "Unknown"


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

    def test_button_save_type(self) -> None:
        assert isinstance(BUTTON_SAVE, str)

    def test_button_cancel_type(self) -> None:
        assert isinstance(BUTTON_CANCEL, str)


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
