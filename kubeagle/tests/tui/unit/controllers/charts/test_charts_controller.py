"""Tests for charts controller."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from kubeagle.constants.enums import QoSClass
from kubeagle.controllers.charts.controller import ChartsController
from kubeagle.models.charts.chart_info import ChartInfo


class TestChartsController:
    """Tests for ChartsController class."""

    @pytest.fixture
    def controller(self, tmp_path: Path) -> ChartsController:
        """Create ChartsController instance with temp directory."""
        return ChartsController(repo_path=tmp_path, max_workers=2)

    def test_controller_init(self, controller: ChartsController, tmp_path: Path) -> None:
        """Test ChartsController initialization."""
        # repo_path property resolves path via Path.resolve()
        assert controller.repo_path == tmp_path.resolve()
        assert controller.max_workers == 2
        assert controller.context is None
        assert controller.is_cluster_mode is False

    def test_controller_with_context(self, tmp_path: Path) -> None:
        """Test ChartsController with Kubernetes context."""
        controller = ChartsController(repo_path=tmp_path, context="my-cluster")
        assert controller.context == "my-cluster"

    def test_active_charts_property_no_file(self, controller: ChartsController) -> None:
        """Test active_charts returns None when no file is set."""
        assert controller.active_charts is None

    @pytest.mark.asyncio
    async def test_check_connection_repo_exists(self, controller: ChartsController) -> None:
        """Test check_connection when repository exists."""
        result = await controller.check_connection()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_connection_repo_not_exists(self, tmp_path: Path) -> None:
        """Test check_connection when repository doesn't exist."""
        controller = ChartsController(repo_path=Path("/nonexistent/path"))
        result = await controller.check_connection()
        assert result is False

    @pytest.mark.asyncio
    async def test_fetch_all_returns_dict(self, controller: ChartsController) -> None:
        """Test fetch_all returns dictionary with charts key."""
        result = await controller.fetch_all()
        assert isinstance(result, dict)
        assert "charts" in result

    @pytest.mark.asyncio
    async def test_refresh_clears_cache(self, controller: ChartsController) -> None:
        """Test refresh clears caches."""
        # Set up a mock async cache
        mock_cache = AsyncMock()
        controller._cache = mock_cache

        await controller.refresh()

        # Verify cache clear was called
        mock_cache.clear.assert_called()

    def test_repo_path_property(self, tmp_path: Path) -> None:
        """Test repo_path property resolves path to absolute."""
        charts_dir = tmp_path / "charts"
        charts_dir.mkdir()
        controller = ChartsController(repo_path=charts_dir)
        resolved = controller.repo_path
        assert isinstance(resolved, Path)
        assert resolved.exists()


class TestChartsControllerAnalysis:
    """Tests for chart analysis methods."""

    @pytest.fixture
    def controller(self, tmp_path: Path) -> ChartsController:
        """Create ChartsController for analysis tests."""
        return ChartsController(repo_path=tmp_path, max_workers=2)

    @pytest.mark.asyncio
    async def test_analyze_all_charts_async_reports_incremental_callbacks(
        self,
        controller: ChartsController,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Repository analysis should emit progress and partial callbacks."""
        chart_dirs = [tmp_path / "service-a", tmp_path / "service-b"]
        for chart_dir in chart_dirs:
            chart_dir.mkdir(parents=True)

        monkeypatch.setattr(
            controller._chart_fetcher,
            "find_chart_directories",
            lambda: chart_dirs,
        )

        def _analyze_single_chart(chart_path: Path) -> list[ChartInfo]:
            return [ChartInfo(
                name=chart_path.name,
                team="team-a",
                values_file=str(chart_path / "values.yaml"),
                cpu_request=0.0,
                cpu_limit=0.0,
                memory_request=0.0,
                memory_limit=0.0,
                qos_class=QoSClass.BEST_EFFORT,
                has_liveness=False,
                has_readiness=False,
                has_startup=False,
                has_anti_affinity=False,
                has_topology_spread=False,
                has_topology=False,
                pdb_enabled=False,
                pdb_template_exists=False,
                pdb_min_available=None,
                pdb_max_unavailable=None,
                replicas=None,
                priority_class=None,
            )]

        monkeypatch.setattr(controller, "_analyze_single_chart", _analyze_single_chart)

        progress_events: list[tuple[int, int]] = []
        partial_events: list[tuple[int, int, int]] = []

        def _on_progress(completed: int, total: int) -> None:
            progress_events.append((completed, total))

        def _on_partial(charts: list[ChartInfo], completed: int, total: int) -> None:
            partial_events.append((len(charts), completed, total))

        charts = await controller.analyze_all_charts_async(
            active_releases=None,
            force_refresh=True,
            on_analysis_progress=_on_progress,
            on_analysis_partial=_on_partial,
        )

        assert len(charts) == 2
        assert {chart.name for chart in charts} == {"service-a", "service-b"}
        assert progress_events == [(1, 2), (2, 2)]
        assert partial_events == [(1, 1, 2), (2, 2, 2)]


class TestChartsControllerClusterStreaming:
    """Tests for streaming cluster analysis workflows."""

    @pytest.fixture
    def controller(self, tmp_path: Path) -> ChartsController:
        """Create ChartsController for streaming tests."""
        return ChartsController(repo_path=tmp_path, max_workers=2)

    @staticmethod
    def _chart(name: str, namespace: str) -> ChartInfo:
        """Build minimal ChartInfo used by cluster analysis tests."""
        return ChartInfo(
            name=name,
            team="unknown",
            values_file=f"cluster:{namespace}",
            namespace=namespace,
            cpu_request=0.0,
            cpu_limit=0.0,
            memory_request=0.0,
            memory_limit=0.0,
            qos_class=QoSClass.BEST_EFFORT,
            has_liveness=False,
            has_readiness=False,
            has_startup=False,
            has_anti_affinity=False,
            has_topology_spread=False,
            has_topology=False,
            pdb_enabled=False,
            pdb_template_exists=False,
            pdb_min_available=None,
            pdb_max_unavailable=None,
            replicas=None,
            priority_class=None,
        )

    @pytest.mark.asyncio
    async def test_fetch_live_helm_releases_streaming_maps_updates(
        self,
        controller: ChartsController,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test streaming release fetch maps HelmReleaseInfo objects to dicts."""

        class _FakeClusterController:
            def __init__(self, context: str | None = None, **_kwargs: object) -> None:
                self.context = context

            async def get_helm_releases(self, on_namespace_update: object | None = None):
                first = SimpleNamespace(name="svc-a", namespace="team-a")
                second = SimpleNamespace(name="svc-b", namespace="team-b")
                if on_namespace_update is not None:
                    on_namespace_update([first], 1, 2)
                    on_namespace_update([first, second], 2, 2)
                return [first, second]

        monkeypatch.setattr(
            "kubeagle.controllers.charts.controller.ClusterController",
            _FakeClusterController,
        )

        updates: list[tuple[int, int, int]] = []

        def _on_namespace_update(
            partial_releases: list[dict[str, str]],
            completed: int,
            total: int,
        ) -> None:
            updates.append((len(partial_releases), completed, total))

        releases = await controller.fetch_live_helm_releases_streaming(
            on_namespace_update=_on_namespace_update
        )

        assert releases == [
            {"name": "svc-a", "namespace": "team-a"},
            {"name": "svc-b", "namespace": "team-b"},
        ]
        assert updates == [(1, 1, 2), (2, 2, 2)]

    @pytest.mark.asyncio
    async def test_analyze_all_charts_cluster_reports_analysis_progress(
        self, controller: ChartsController, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test cluster analysis emits progress callback for each processed release."""
        releases = [
            {"name": "svc-a", "namespace": "team-a"},
            {"name": "svc-b", "namespace": "team-b"},
            {"name": "svc-c", "namespace": "team-c"},
        ]

        controller.get_live_chart_values = AsyncMock(return_value={})  # type: ignore[method-assign]

        def _analyze_live_chart(
            release: str, namespace: str, _values: dict[str, object]
        ) -> ChartInfo:
            return self._chart(release, namespace)

        monkeypatch.setattr(controller, "analyze_live_chart", _analyze_live_chart)

        progress_events: list[tuple[int, int]] = []

        def _on_analysis_progress(completed: int, total: int) -> None:
            progress_events.append((completed, total))

        charts = await controller.analyze_all_charts_cluster_async(
            releases=releases,
            force_refresh=True,
            on_analysis_progress=_on_analysis_progress,
        )

        assert {chart.name for chart in charts} == {"svc-a", "svc-b", "svc-c"}
        assert progress_events == [(1, 3), (2, 3), (3, 3)]

    @pytest.mark.asyncio
    async def test_analyze_all_charts_cluster_reports_partial_results(
        self, controller: ChartsController, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test cluster analysis emits partial chart snapshots while processing."""
        releases = [
            {"name": "svc-a", "namespace": "team-a"},
            {"name": "svc-b", "namespace": "team-b"},
        ]

        controller.get_live_chart_values = AsyncMock(return_value={})  # type: ignore[method-assign]

        def _analyze_live_chart(
            release: str, namespace: str, _values: dict[str, object]
        ) -> ChartInfo:
            return self._chart(release, namespace)

        monkeypatch.setattr(controller, "analyze_live_chart", _analyze_live_chart)

        partial_events: list[tuple[int, int, int]] = []

        def _on_analysis_partial(
            charts: list[ChartInfo], completed: int, total: int
        ) -> None:
            partial_events.append((len(charts), completed, total))

        charts = await controller.analyze_all_charts_cluster_async(
            releases=releases,
            force_refresh=True,
            on_analysis_partial=_on_analysis_partial,
        )

        assert {chart.name for chart in charts} == {"svc-a", "svc-b"}
        assert partial_events == [(1, 1, 2), (2, 2, 2)]

    @pytest.mark.asyncio
    async def test_analyze_all_charts_cluster_uses_streaming_release_discovery(
        self, controller: ChartsController, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test discovery callback path uses streaming release fetch method."""
        fallback_fetch_mock = AsyncMock(return_value=[])
        streaming_fetch_mock = AsyncMock(
            return_value=[{"name": "svc-a", "namespace": "team-a"}]
        )
        controller.fetch_live_helm_releases = fallback_fetch_mock  # type: ignore[method-assign]
        controller.fetch_live_helm_releases_streaming = streaming_fetch_mock  # type: ignore[method-assign]
        controller.get_live_chart_values = AsyncMock(return_value={})  # type: ignore[method-assign]

        monkeypatch.setattr(
            controller,
            "analyze_live_chart",
            lambda release, namespace, values: self._chart(release, namespace),
        )

        discovery_events: list[tuple[int, int, int]] = []

        def _on_discovery_progress(
            partial_releases: list[dict[str, str]],
            completed: int,
            total: int,
        ) -> None:
            discovery_events.append((len(partial_releases), completed, total))

        charts = await controller.analyze_all_charts_cluster_async(
            releases=None,
            force_refresh=True,
            on_release_discovery_progress=_on_discovery_progress,
        )

        streaming_fetch_mock.assert_awaited_once()
        fallback_fetch_mock.assert_not_called()
        assert len(charts) == 1
        assert discovery_events == []

    @pytest.mark.asyncio
    async def test_analyze_all_charts_cluster_starts_analysis_before_discovery_finishes(
        self, controller: ChartsController, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Streamed namespace discovery should emit chart partials before final discovery."""
        release_a = {"name": "svc-a", "namespace": "team-a"}
        release_b = {"name": "svc-b", "namespace": "team-b"}
        second_namespace_emitted = False
        first_partial_before_second_namespace = False

        async def _streaming_fetch(
            on_namespace_update: Any | None = None,
        ) -> list[dict[str, str]]:
            nonlocal second_namespace_emitted
            if on_namespace_update is not None:
                on_namespace_update([release_a], 1, 2)
            await asyncio.sleep(0.02)
            second_namespace_emitted = True
            if on_namespace_update is not None:
                on_namespace_update([release_a, release_b], 2, 2)
            return [release_a, release_b]

        async def _values_for_release(
            release: str,
            namespace: str,
        ) -> dict[str, object]:
            if release == "svc-a":
                await asyncio.sleep(0.001)
            else:
                await asyncio.sleep(0.03)
            return {"release": release, "namespace": namespace}

        controller.fetch_live_helm_releases_streaming = _streaming_fetch  # type: ignore[method-assign]
        controller.fetch_live_helm_releases = AsyncMock(return_value=[])  # type: ignore[method-assign]
        controller.get_live_chart_values = AsyncMock(side_effect=_values_for_release)  # type: ignore[method-assign]

        monkeypatch.setattr(
            controller,
            "analyze_live_chart",
            lambda release, namespace, values: self._chart(release, namespace),
        )

        partial_events: list[tuple[int, int, int]] = []

        def _on_analysis_partial(
            charts: list[ChartInfo],
            completed: int,
            total: int,
        ) -> None:
            nonlocal first_partial_before_second_namespace
            partial_events.append((len(charts), completed, total))
            if len(charts) == 1 and not second_namespace_emitted:
                first_partial_before_second_namespace = True

        charts = await controller.analyze_all_charts_cluster_async(
            releases=None,
            force_refresh=True,
            on_release_discovery_progress=lambda *_args: None,
            on_analysis_partial=_on_analysis_partial,
        )

        assert len(charts) == 2
        assert first_partial_before_second_namespace is True
        assert partial_events
        assert partial_events[0][0] == 1

    @pytest.mark.asyncio
    async def test_analyze_all_charts_cluster_uses_raw_values_output_for_preview(
        self, controller: ChartsController, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test cluster analysis preserves raw Helm values output for chart preview."""
        releases = [{"name": "svc-a", "namespace": "team-a"}]
        raw_values = "replicaCount: 2\nresources:\n  requests:\n    cpu: 100m\n"
        controller._release_fetcher = cast(
            Any,
            SimpleNamespace(
                fetch_release_values_with_output=AsyncMock(return_value=({}, raw_values))
            ),
        )

        monkeypatch.setattr(
            controller,
            "analyze_live_chart",
            lambda release, namespace, values: self._chart(release, namespace),
        )

        charts = await controller.analyze_all_charts_cluster_async(
            releases=releases,
            force_refresh=True,
        )

        assert len(charts) == 1
        assert charts[0].deployed_values_content == raw_values
