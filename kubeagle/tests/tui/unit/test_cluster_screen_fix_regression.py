"""Regression tests for PRD-cluster-screen-fix.

These tests verify the 6 bug fixes implemented in the cluster screen fix PRD.
Each test targets a specific bug and is designed to:
- FAIL before the fix was applied
- PASS after the fix was applied

Bug 1: CustomTabbedContent wrapper breaks TabPane composition (CRITICAL)
Bug 2: Duplicate widget IDs between wrapper and inner widget (CRITICAL)
Bug 3: _update_table() adds duplicate columns on every refresh (HIGH)
Bug 4: CSS height constraints prevent content visibility (MEDIUM)
Bug 5: Message namespace may prevent message delivery (MEDIUM)
Bug 6: PodListComponent is unused dead code (LOW)
"""

from __future__ import annotations

import pytest
from textual.containers import Container
from textual.message import Message
from textual.widgets import TabbedContent as TextualTabbedContent
from textual.widgets._tabbed_content import TabPane as TextualTabPane

from kubeagle.screens.cluster.presenter import (
    ClusterDataLoaded,
    ClusterDataLoadFailed,
)
from kubeagle.widgets.data.tables.custom_data_table import CustomDataTable
from kubeagle.widgets.tabs.custom_tab_pane import CustomTabPane
from kubeagle.widgets.tabs.custom_tabbed_content import CustomTabbedContent

# =============================================================================
# Bug 1 Regression: CustomTabbedContent must directly inherit from TabbedContent
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestBug1CustomTabbedContentInheritance:
    """Bug 1: CustomTabbedContent must inherit from TextualTabbedContent, not Container.

    Before the fix, CustomTabbedContent extended Container and created an
    inner TextualTabbedContent in compose(). This meant TabPanes yielded
    inside the `with CustomTabbedContent(...)` context manager became
    children of the outer Container, not the inner TabbedContent.
    The inner TabbedContent was empty, so no tabs or content were visible.

    After the fix, CustomTabbedContent directly inherits from TextualTabbedContent.
    """

    def test_inherits_from_textual_tabbed_content(self) -> None:
        """CustomTabbedContent must be a subclass of TextualTabbedContent."""
        assert issubclass(CustomTabbedContent, TextualTabbedContent), (
            "CustomTabbedContent must directly inherit from TextualTabbedContent, "
            "not from Container. The Container wrapper pattern breaks TabPane "
            "context-manager composition."
        )

    def test_is_not_container_wrapper(self) -> None:
        """CustomTabbedContent must NOT be a subclass of Container (only).

        It IS a Container via TabbedContent's own MRO, but not directly.
        The key is that isinstance(tc, TabbedContent) must be True.
        """
        tc = CustomTabbedContent("A", "B")
        assert isinstance(tc, TextualTabbedContent)

    def test_active_property_works_natively(self) -> None:
        """The 'active' property must work natively from TabbedContent."""
        tc = CustomTabbedContent("A", "B", id="test-tabs")
        # active property is inherited from TextualTabbedContent
        assert hasattr(tc, "active")
        # It should be a string (tab ID or empty)
        assert isinstance(tc.active, str)

    def test_no_inner_widget_pattern(self) -> None:
        """CustomTabbedContent must NOT have an _inner_widget attribute.

        The old pattern created self._inner_widget in compose(), which
        was the root cause of Bug 1.
        """
        tc = CustomTabbedContent("A", "B")
        assert not hasattr(tc, "_inner_widget"), (
            "CustomTabbedContent should not have _inner_widget; "
            "it directly IS the TabbedContent."
        )


# =============================================================================
# Bug 1 (supplementary): CustomTabPane must directly inherit from TabPane
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestBug1CustomTabPaneInheritance:
    """CustomTabPane must inherit from TextualTabPane.

    Required because TabbedContent.compose() checks
    isinstance(content, TabPane). Without direct inheritance, CustomTabPane
    (as a Container) fails the isinstance check and gets wrapped in an
    additional TabPane, breaking tab rendering.
    """

    def test_inherits_from_textual_tab_pane(self) -> None:
        """CustomTabPane must be a subclass of TextualTabPane."""
        assert issubclass(CustomTabPane, TextualTabPane), (
            "CustomTabPane must directly inherit from TextualTabPane so that "
            "isinstance(pane, TabPane) is True when TabbedContent processes children."
        )

    def test_isinstance_check_passes(self) -> None:
        """isinstance(pane, TextualTabPane) must be True."""
        pane = CustomTabPane("Tab Label", id="test-pane")
        assert isinstance(pane, TextualTabPane)

    def test_positional_string_becomes_title(self) -> None:
        """First positional string arg must become the tab title."""
        pane = CustomTabPane("My Tab Title", id="tab-1")
        assert pane._label == "My Tab Title"

    def test_keyword_label_becomes_title(self) -> None:
        """label keyword arg must become the tab title."""
        pane = CustomTabPane(label="Keyword Title", id="tab-2")
        assert pane._label == "Keyword Title"

    def test_dual_calling_convention(self) -> None:
        """Both calling conventions must work: positional and keyword."""
        p1 = CustomTabPane("Positional")
        p2 = CustomTabPane(label="Keyword")
        assert p1._label == "Positional"
        assert p2._label == "Keyword"


# =============================================================================
# Bug 2 Regression: No duplicate widget IDs
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestBug2NoDuplicateWidgetIDs:
    """Bug 2: CustomDataTable compose() must not create duplicate IDs.

    Before the fix, CustomDataTable.__init__() passed id=id to Container,
    then compose() created TextualDataTable(id=self.id) with the same ID.
    This caused duplicate IDs in the DOM.

    After the fix, the inner TextualDataTable no longer gets id=self.id.
    """

    def test_custom_data_table_compose_no_duplicate_id(self) -> None:
        """Inner DataTable must NOT have the same ID as the container."""
        table = CustomDataTable(id="my-table")
        assert table.id == "my-table"

        # Simulate compose - get the generated children
        children = list(table.compose())
        assert len(children) == 1, "compose() should yield exactly one child"

        inner_table = children[0]
        # The inner TextualDataTable must NOT have id="my-table"
        assert inner_table.id != "my-table", (
            "Inner TextualDataTable must not have the same ID as the Container wrapper. "
            "Duplicate IDs cause query_one() to match the wrong widget."
        )

    def test_custom_data_table_compose_inner_widget_set(self) -> None:
        """compose() must set _inner_widget to the TextualDataTable."""
        table = CustomDataTable(id="test-table")
        children = list(table.compose())
        assert table._inner_widget is not None
        assert table._inner_widget is children[0]

    def test_container_id_preserved(self) -> None:
        """The Container wrapper must keep its assigned ID."""
        table = CustomDataTable(id="charts-table")
        assert table.id == "charts-table"


# =============================================================================
# Bug 3 Regression: _update_table clears columns before re-adding
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestBug3ColumnDuplicationFix:
    """Bug 3: ClusterScreen._update_table must use clear(columns=True).

    Before the fix, _update_table called table.clear() which only clears
    rows, not columns. On each refresh, columns were duplicated.

    After the fix, _update_table calls table.clear(columns=True).
    """

    def test_update_table_uses_clear_columns_true(self) -> None:
        """_update_table source must call clear(columns=True)."""
        import inspect

        from kubeagle.screens.cluster.cluster_screen import ClusterScreen

        source = inspect.getsource(ClusterScreen._update_table)
        assert "clear(columns=True)" in source, (
            "_update_table must call table.clear(columns=True) to clear columns "
            "before re-adding them on refresh. Without this, columns duplicate."
        )

    def test_custom_data_table_clear_accepts_columns_param(self) -> None:
        """CustomDataTable.clear() must accept a columns parameter."""
        table = CustomDataTable()
        # Must not raise
        table.clear(columns=True)
        table.clear(columns=False)

    def test_clear_safe_accepts_columns_param(self) -> None:
        """CustomDataTable.clear_safe() must accept a columns parameter."""
        table = CustomDataTable()
        # Must not raise
        table.clear_safe(columns=True)
        table.clear_safe(columns=False)

    def test_fixed_columns_lock_name_and_node_group_columns(self) -> None:
        """Nodes tables should lock leading identity columns for horizontal scroll."""
        from kubeagle.screens.cluster.cluster_screen import ClusterScreen
        from kubeagle.screens.cluster.config import (
            NODE_GROUPS_TABLE_COLUMNS,
            NODE_TABLE_COLUMNS,
        )

        screen = ClusterScreen()

        assert (
            screen._fixed_column_count_for_table(
                "nodes-table",
                NODE_TABLE_COLUMNS,
            )
            == 2
        )
        assert (
            screen._fixed_column_count_for_table(
                "node-groups-table",
                NODE_GROUPS_TABLE_COLUMNS,
            )
            == 2
        )
        assert screen._fixed_column_count_for_table("events-detail-table", []) == 0


# =============================================================================
# Bug 4 Regression: CSS height not collapsed
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestBug4CSSHeightFix:
    """Bug 4: CSS must not collapse content to zero height.

    Before the fix:
    - CustomTabbedContent CSS had height: auto on both wrapper and inner widget
    - cluster_screen.tcss had TabPane > * { height: 100%; width: 100%; }
      which forced all TabPane children to 100% height

    After the fix:
    - CustomTabbedContent CSS uses height: 1fr
    - The overly broad TabPane > * rule was removed
    """

    def test_custom_tabbed_content_css_has_1fr_height(self) -> None:
        """CustomTabbedContent CSS must use height: 1fr, not auto."""
        import pathlib

        css_path = pathlib.Path(__file__).parent.parent.parent.parent / "css" / "widgets" / "custom_tabbed_content.tcss"
        if css_path.exists():
            content = css_path.read_text()
            # The main CustomTabbedContent rule should have height: 1fr
            assert "height: 1fr" in content, (
                "CustomTabbedContent CSS must use 'height: 1fr' to ensure content "
                "fills available space instead of collapsing to zero."
            )
            # Should NOT have the old inner-widget pattern
            assert "CustomTabbedContent > TabbedContent" not in content, (
                "CSS should not target 'CustomTabbedContent > TabbedContent' since "
                "CustomTabbedContent IS the TabbedContent (direct inheritance)."
            )

    def test_cluster_screen_css_no_broad_tabpane_rule(self) -> None:
        """cluster_screen.tcss must not have overly broad TabPane > * rule."""
        import pathlib

        css_path = pathlib.Path(__file__).parent.parent.parent.parent / "css" / "screens" / "cluster_screen.tcss"
        if css_path.exists():
            content = css_path.read_text()
            assert "TabPane > *" not in content, (
                "cluster_screen.tcss must not have 'TabPane > *' rule which "
                "forces all TabPane children to 100% height, conflicting with "
                "auto-height tables."
            )

    def test_cluster_screen_css_avoids_height_tight_digit_clamping(self) -> None:
        """Tight-height mode must not clamp summary digits to clipping-prone heights."""
        import pathlib

        css_path = pathlib.Path(__file__).parent.parent.parent.parent / "css" / "screens" / "cluster_screen.tcss"
        if css_path.exists():
            content = css_path.read_text()
            assert "#tab-nodes.height-tight #nodes-main-grid .summary-digit-item" not in content
            assert "#tab-pods.height-tight #workloads-main-grid .summary-digit-item" not in content

    def test_cluster_screen_css_has_narrow_compact_digit_grid_overrides(self) -> None:
        """Narrow/compact modes must reflow summary digit grids for readability."""
        import pathlib

        css_path = pathlib.Path(__file__).parent.parent.parent.parent / "css" / "screens" / "cluster_screen.tcss"
        if css_path.exists():
            content = css_path.read_text()
            assert ".cluster-tab-pane.narrow .summary-digits-grid-4" in content
            assert ".cluster-tab-pane.compact .summary-digits-grid-4" in content
            assert "#tab-events.narrow #events-summary-digits-grid" in content
            assert "#tab-pods.compact #overview-pod-stats-grid" in content

    def test_nodes_grid_avoids_nested_scrollbar_and_height_clamp(self) -> None:
        """Nodes grid must avoid nested vertical scrolling and fixed-height clamps."""
        import pathlib
        import re

        css_path = pathlib.Path(__file__).parent.parent.parent.parent / "css" / "screens" / "cluster_screen.tcss"
        if css_path.exists():
            content = css_path.read_text()
            assert "#nodes-main-grid {" in content
            assert "overflow-y: hidden;" in content

            block_match = re.search(
                r"#nodes-main-grid > \.cluster-data-panel \{([^}]*)\}",
                content,
                re.MULTILINE | re.DOTALL,
            )
            assert block_match is not None, "Missing #nodes-main-grid > .cluster-data-panel CSS block."

            block = block_match.group(1)
            assert "height: auto;" in block
            assert "min-height:" in block
            assert "max-height:" not in block

    def test_nodes_table_panels_keep_horizontal_overflow_local_to_surface(self) -> None:
        """Nodes tables should never force horizontal page drift in narrow terminals."""
        import pathlib
        import re

        css_path = pathlib.Path(__file__).parent.parent.parent.parent / "css" / "screens" / "cluster_screen.tcss"
        if css_path.exists():
            content = css_path.read_text()
            surface_block_match = re.search(
                r"#nodes-table-panel > \.cluster-table-surface,\s*#node-groups-table-panel > \.cluster-table-surface \{([^}]*)\}",
                content,
                re.MULTILINE | re.DOTALL,
            )
            assert surface_block_match is not None, "Missing nodes table surface sizing CSS block."
            surface_block = surface_block_match.group(1)
            assert "width: 1fr;" in surface_block
            assert "min-width: 0;" in surface_block
            assert "max-width: 100%;" in surface_block
            assert "overflow-x: auto;" in surface_block

            data_table_block_match = re.search(
                r"#nodes-table-panel \.widget-custom-data-table > DataTable,\s*#node-groups-table-panel \.widget-custom-data-table > DataTable \{([^}]*)\}",
                content,
                re.MULTILINE | re.DOTALL,
            )
            assert data_table_block_match is not None, "Missing nodes DataTable overflow CSS block."
            data_table_block = data_table_block_match.group(1)
            assert "width: 1fr;" in data_table_block
            assert "min-width: 0;" in data_table_block
            assert "max-width: 100%;" in data_table_block
            assert "overflow-x: auto;" in data_table_block

    def test_top_bar_spacing_and_progress_alignment_rules_present(self) -> None:
        """Top bar should keep event controls padded and progress area on opposite side."""
        import pathlib
        import re

        css_path = pathlib.Path(__file__).parent.parent.parent.parent / "css" / "screens" / "cluster_screen.tcss"
        if css_path.exists():
            content = css_path.read_text()
            controls_block_match = re.search(
                r"#cluster-top-controls-left \{([^}]*)\}",
                content,
                re.MULTILINE | re.DOTALL,
            )
            assert controls_block_match is not None, "Missing #cluster-top-controls-left CSS block."
            controls_block = controls_block_match.group(1)
            assert "width: 3fr;" in controls_block
            assert "layout: grid;" in controls_block
            assert "grid-size: 2 1;" in controls_block
            assert "grid-columns: 4fr 2fr;" in controls_block

            select_block_match = re.search(
                r"\.cluster-event-window-select \{([^}]*)\}",
                content,
                re.MULTILINE | re.DOTALL,
            )
            assert select_block_match is not None, "Missing .cluster-event-window-select CSS block."
            select_block = select_block_match.group(1)
            assert "width: 1fr;" in select_block
            assert "min-width: 0;" in select_block
            assert "margin-top: 1;" in select_block
            assert "margin-bottom: 1;" in select_block

            refresh_block_match = re.search(
                r"#refresh-btn \{([^}]*)\}",
                content,
                re.MULTILINE | re.DOTALL,
            )
            assert refresh_block_match is not None, "Missing #refresh-btn CSS block."
            refresh_block = refresh_block_match.group(1)
            assert "width: 1fr;" in refresh_block
            assert "min-width: 0;" in refresh_block
            assert "margin-top: 1;" in refresh_block
            assert "margin-bottom: 1;" in refresh_block

            loading_bar_block_match = re.search(
                r"#cluster-loading-bar \{([^}]*)\}",
                content,
                re.MULTILINE | re.DOTALL,
            )
            assert loading_bar_block_match is not None, "Missing #cluster-loading-bar CSS block."
            loading_bar_block = loading_bar_block_match.group(1)
            assert "width: 4fr;" in loading_bar_block

            loading_spacer_match = re.search(
                r"#cluster-loading-spacer \{([^}]*)\}",
                content,
                re.MULTILINE | re.DOTALL,
            )
            assert loading_spacer_match is not None, "Missing #cluster-loading-spacer CSS block."
            loading_spacer_block = loading_spacer_match.group(1)
            assert "width: 2fr;" in loading_spacer_block

            progress_block_match = re.search(
                r"#cluster-progress-container \{([^}]*)\}",
                content,
                re.MULTILINE | re.DOTALL,
            )
            assert progress_block_match is not None, "Missing #cluster-progress-container CSS block."
            progress_block = progress_block_match.group(1)
            assert "width: 2fr;" in progress_block
            assert "layout: grid;" in progress_block
            assert "grid-size: 2 1;" in progress_block
            assert "grid-columns: 4fr 6fr;" in progress_block
            assert "align: right middle;" in progress_block
            assert "content-align: right middle;" in progress_block

            loading_text_block_match = re.search(
                r"#loading-text \{([^}]*)\}",
                content,
                re.MULTILINE | re.DOTALL,
            )
            assert loading_text_block_match is not None, "Missing #loading-text CSS block."
            loading_text_block = loading_text_block_match.group(1)
            assert "width: 1fr;" in loading_text_block
            assert "text-align: right;" in loading_text_block
            assert "content-align: right middle;" in loading_text_block


# =============================================================================
# Bug 5 Regression: Message namespace removed
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestBug5MessageNamespaceFix:
    """Bug 5: ClusterDataLoaded/ClusterDataLoadFailed must not have custom namespace.

    Before the fix, these messages had namespace attributes with hyphens
    which could interfere with Textual's message handler dispatch.

    After the fix, the namespace attributes are removed.
    """

    def test_cluster_data_loaded_no_namespace(self) -> None:
        """ClusterDataLoaded must not define a custom namespace attribute."""
        # Check that no custom namespace is defined on the class
        assert not hasattr(ClusterDataLoaded, "namespace") or ClusterDataLoaded.namespace is Message.namespace, (
            "ClusterDataLoaded must not define a custom 'namespace' attribute. "
            "Custom namespaces with hyphens interfere with handler dispatch."
        )

    def test_cluster_data_load_failed_no_namespace(self) -> None:
        """ClusterDataLoadFailed must not define a custom namespace attribute."""
        assert not hasattr(ClusterDataLoadFailed, "namespace") or ClusterDataLoadFailed.namespace is Message.namespace, (
            "ClusterDataLoadFailed must not define a custom 'namespace' attribute."
        )

    def test_cluster_data_loaded_handler_name(self) -> None:
        """The handler name must be on_cluster_data_loaded for proper dispatch."""
        from kubeagle.screens.cluster.cluster_screen import ClusterScreen

        assert hasattr(ClusterScreen, "on_cluster_data_loaded"), (
            "ClusterScreen must have on_cluster_data_loaded handler."
        )

    def test_cluster_data_load_failed_handler_name(self) -> None:
        """The handler name must be on_cluster_data_load_failed for proper dispatch."""
        from kubeagle.screens.cluster.cluster_screen import ClusterScreen

        assert hasattr(ClusterScreen, "on_cluster_data_load_failed"), (
            "ClusterScreen must have on_cluster_data_load_failed handler."
        )

    def test_cluster_data_load_failed_stores_error(self) -> None:
        """ClusterDataLoadFailed must store the error message."""
        error = "Connection refused"
        msg = ClusterDataLoadFailed(error)
        assert msg.error == error


# =============================================================================
# Bug 6 Regression: PodListComponent retained with deprecation
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestBug6PodListComponentRetained:
    """Bug 6: PodListComponent file retained for import compatibility.

    Before the fix, the dead code was flagged for removal.
    The fix retained it with a deprecation docstring because existing
    tests import PodListComponent.
    """

    def test_pod_list_component_importable(self) -> None:
        """PodListComponent must still be importable (backward compatibility)."""
        try:
            from kubeagle.screens.cluster.components.pod_list import (
                PodListComponent,
            )
            assert PodListComponent is not None
        except ImportError:
            pytest.fail(
                "PodListComponent must remain importable for backward compatibility. "
                "Tests import it, so deleting the file would cause ImportError."
            )


# =============================================================================
# Cross-cutting: No regressions in shared widgets
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestNoRegressionSharedWidgets:
    """Verify that the fixes do not break shared widget functionality."""

    def test_custom_tabbed_content_with_titles(self) -> None:
        """CustomTabbedContent must accept title strings."""
        tc = CustomTabbedContent("Tab1", "Tab2", "Tab3")
        assert tc._titles == ("Tab1", "Tab2", "Tab3")

    def test_custom_tabbed_content_with_id(self) -> None:
        """CustomTabbedContent must accept id parameter."""
        tc = CustomTabbedContent("A", id="my-tabs")
        assert tc.id == "my-tabs"

    def test_custom_tabbed_content_with_classes(self) -> None:
        """CustomTabbedContent must auto-add widget-custom-tabbed-content class."""
        tc = CustomTabbedContent("A", classes="extra")
        assert "widget-custom-tabbed-content" in tc.classes
        assert "extra" in tc.classes

    def test_custom_tabbed_content_with_initial(self) -> None:
        """CustomTabbedContent must accept initial parameter."""
        tc = CustomTabbedContent("A", "B", initial="B")
        assert tc._initial == "B"

    def test_custom_tab_pane_with_id(self) -> None:
        """CustomTabPane must accept id parameter."""
        pane = CustomTabPane("Label", id="tab-1")
        assert pane.id == "tab-1"

    def test_custom_tab_pane_with_classes(self) -> None:
        """CustomTabPane must auto-add widget-custom-tab-pane class."""
        pane = CustomTabPane("Label", classes="extra")
        assert "widget-custom-tab-pane" in pane.classes
        assert "extra" in pane.classes

    def test_custom_tab_pane_disabled(self) -> None:
        """CustomTabPane must accept disabled parameter."""
        pane = CustomTabPane("Label", disabled=True)
        assert pane._disabled is True

    def test_custom_data_table_is_container(self) -> None:
        """CustomDataTable must still be a Container (test compatibility)."""
        table = CustomDataTable()
        assert isinstance(table, Container)

    def test_custom_data_table_with_columns(self) -> None:
        """CustomDataTable must accept columns parameter."""
        cols = [("Name", "name"), ("Version", "version")]
        table = CustomDataTable(columns=cols)
        assert table._columns == cols

    def test_custom_data_table_with_zebra_stripes(self) -> None:
        """CustomDataTable must accept zebra_stripes parameter."""
        table = CustomDataTable(zebra_stripes=True)
        assert table._zebra_stripes is True

    def test_custom_data_table_css_class(self) -> None:
        """CustomDataTable must auto-add widget-custom-data-table class."""
        table = CustomDataTable(classes="extra")
        assert "widget-custom-data-table" in table.classes
        assert "extra" in table.classes

    def test_custom_data_table_sort_state(self) -> None:
        """CustomDataTable must have proper initial sort state."""
        table = CustomDataTable()
        assert table._sort_column is None
        assert table._sort_reverse is False

    def test_custom_data_table_row_selected_event(self) -> None:
        """CustomDataTable.RowSelected event must be available."""
        assert hasattr(CustomDataTable, "RowSelected")


# =============================================================================
# Acceptance Criteria Verification Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.fast
class TestAcceptanceCriteria:
    """Verify acceptance criteria from the PRD can be verified by these tests.

    AC-1: Cluster screen tabs visible and switchable
    AC-2: Data tables render with correct columns (no duplication)
    AC-4: No runtime errors on screen mount
    AC-5: No duplicate widget IDs
    AC-8: TUI application starts without errors
    AC-9: Other screens not regressed
    """

    def test_ac1_cluster_screen_has_3_tabs(self) -> None:
        """AC-1: ClusterScreen must expose merged 3-tab navigation."""
        from kubeagle.screens.cluster.cluster_screen import ClusterScreen

        assert len(ClusterScreen.TAB_IDS) == 3

    def test_ac1_tab_switch_actions_exist(self) -> None:
        """AC-1: Tab switch action methods for visible tabs must exist."""
        from kubeagle.screens.cluster.cluster_screen import ClusterScreen

        screen = ClusterScreen()
        for i in range(1, 4):
            method_name = f"action_switch_tab_{i}"
            assert hasattr(screen, method_name), f"Missing {method_name}"

    def test_ac2_update_table_clears_columns(self) -> None:
        """AC-2: _update_table must clear columns to prevent duplication."""
        import inspect

        from kubeagle.screens.cluster.cluster_screen import ClusterScreen

        source = inspect.getsource(ClusterScreen._update_table)
        assert "columns=True" in source

    def test_ac4_screen_instantiation_no_error(self) -> None:
        """AC-4: ClusterScreen must be instantiable without errors."""
        from kubeagle.screens.cluster.cluster_screen import ClusterScreen

        screen = ClusterScreen()
        assert screen is not None
        assert screen._presenter is not None

    def test_ac5_data_table_no_duplicate_ids(self) -> None:
        """AC-5: CustomDataTable compose must not create duplicate IDs."""
        table = CustomDataTable(id="test-id")
        children = list(table.compose())
        inner = children[0]
        assert inner.id != "test-id"

    def test_ac8_app_importable(self) -> None:
        """AC-8: The TUI app must be importable without errors."""
        from kubeagle.app import EKSHelmReporterApp

        app = EKSHelmReporterApp()
        assert app is not None

    def test_ac9_charts_explorer_screen_importable(self) -> None:
        """AC-9: ChartsExplorerScreen must still be importable (no regression)."""
        from kubeagle.screens.charts_explorer import ChartsExplorerScreen

        assert ChartsExplorerScreen is not None

    def test_ac9_optimizer_screen_importable(self) -> None:
        """AC-9: OptimizerScreen must still be importable (no regression)."""
        from kubeagle.screens.detail import OptimizerScreen

        assert OptimizerScreen is not None



# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestAcceptanceCriteria",
    "TestBug1CustomTabPaneInheritance",
    "TestBug1CustomTabbedContentInheritance",
    "TestBug2NoDuplicateWidgetIDs",
    "TestBug3ColumnDuplicationFix",
    "TestBug4CSSHeightFix",
    "TestBug5MessageNamespaceFix",
    "TestBug6PodListComponentRetained",
    "TestNoRegressionSharedWidgets",
]
