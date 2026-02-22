"""Charts controller for Helm chart analysis operations."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import Any

from kubeagle.controllers.base import BaseController
from kubeagle.controllers.charts.fetchers import (
    ChartFetcher,
    ReleaseFetcher,
)
from kubeagle.controllers.charts.parsers import ChartParser
from kubeagle.controllers.cluster.controller import ClusterController
from kubeagle.controllers.team.mappers import TeamMapper
from kubeagle.models.cache.data_cache import DataCache
from kubeagle.models.charts.chart_info import ChartInfo

logger = logging.getLogger(__name__)


class ChartsController(BaseController):
    """Helm chart analysis operations with parallel file parsing."""
    _GLOBAL_CACHE_TTL_SECONDS = 45.0
    _GLOBAL_CACHE_MAX_ENTRIES = 10  # Prevent unbounded memory growth
    _LIVE_VALUES_CACHE_MAX_ENTRIES = 128  # Prevent unbounded memory growth
    _CLUSTER_ANALYSIS_CONCURRENCY_CAP = 16
    _CLUSTER_ANALYSIS_CONCURRENCY_MULTIPLIER = 2
    _global_charts_cache: OrderedDict[
        tuple[str, str, frozenset[str] | None],
        tuple[float, list[ChartInfo]],
    ] = OrderedDict()

    def __init__(
        self,
        repo_path: Path,
        max_workers: int = 8,
        context: str | None = None,
        codeowners_path: Path | None = None,
        active_charts_path: Path | None = None,
        cache: DataCache | None = None,
    ):
        """Initialize the charts controller.

        Args:
            repo_path: Path to Helm charts repository
            max_workers: Maximum number of parallel workers
            context: Optional Kubernetes context name
            codeowners_path: Optional path to CODEOWNERS file
            active_charts_path: Optional path to active charts file
            cache: Optional external cache for coordinated invalidation
        """
        super().__init__()
        self._repo_path = repo_path
        self._codeowners_path = codeowners_path
        self._active_charts_path = active_charts_path
        self.max_workers = max_workers
        self.context = context
        self.is_cluster_mode = False

        # Initialize components
        self._chart_fetcher = ChartFetcher(repo_path, max_workers)
        self._release_fetcher: ReleaseFetcher | None = None
        resolved_codeowners = codeowners_path
        if resolved_codeowners is None:
            candidate = repo_path / "CODEOWNERS"
            if candidate.exists():
                resolved_codeowners = candidate
        self._team_mapper = (
            TeamMapper(resolved_codeowners) if resolved_codeowners is not None else None
        )
        self._chart_parser = ChartParser(self._team_mapper)

        # Caching
        self._active_charts: frozenset[str] | None = None
        self._state_lock = asyncio.Lock()  # Protects non-cache mutable state
        self._cache = cache
        self._charts_cache: list[ChartInfo] | None = None
        self._charts_cache_lock = asyncio.Lock()
        self._analysis_in_progress: asyncio.Event | None = None  # Prevents duplicate analyses
        self._live_values_output_cache: OrderedDict[tuple[str, str], str] = OrderedDict()

    @property
    def repo_path(self) -> Path:
        """Lazily resolve repo path on first access."""
        if not hasattr(self, "_repo_path_resolved"):
            self._repo_path_resolved = Path(self._repo_path).resolve()
        return self._repo_path_resolved

    @property
    def active_charts(self) -> frozenset[str] | None:
        """Get active charts set, loading from file if needed."""
        if self._active_charts is None and self._active_charts_path is not None:
            from kubeagle.models.charts.active_charts import (
                get_active_charts_set,
            )

            self._active_charts = get_active_charts_set(self._active_charts_path)
        return self._active_charts

    async def check_connection(self) -> bool:
        """Check if the repository is accessible.

        Returns:
            True if repository exists and is accessible.
        """
        try:
            return self.repo_path.exists() and self.repo_path.is_dir()
        except (OSError, ValueError):
            return False

    async def fetch_all(self) -> dict[str, Any]:
        """Fetch all chart data.

        Returns:
            Dictionary with chart data.
        """
        charts = await self.analyze_all_charts_async()
        return {"charts": charts}

    async def refresh(self) -> None:
        """Invalidate all caches and force re-analysis on next access."""
        async with self._charts_cache_lock:
            self._charts_cache = None

        async with self._state_lock:
            self._active_charts = None
            self._live_values_output_cache.clear()

        if hasattr(self, "_repo_path_resolved"):
            delattr(self, "_repo_path_resolved")

        if self._cache is not None:
            await self._cache.clear("charts")
            await self._cache.clear("charts_cluster")
            await self._cache.clear("releases")

        repo_key = str(self.repo_path)
        codeowners_key = (
            str(self._codeowners_path.resolve())
            if self._codeowners_path is not None
            else ""
        )
        self.__class__._global_charts_cache = OrderedDict(
            (key, value)
            for key, value in self._global_charts_cache.items()
            if key[0] != repo_key or key[1] != codeowners_key
        )

        logger.debug("ChartsController cache invalidated")

    def _global_cache_key(
        self,
        active_releases: set[str] | None,
    ) -> tuple[str, str, frozenset[str] | None]:
        """Build stable key for shared chart-analysis cache."""
        repo_key = str(self.repo_path)
        codeowners_key = (
            str(self._codeowners_path.resolve())
            if self._codeowners_path is not None
            else ""
        )
        release_key = (
            frozenset(active_releases) if active_releases is not None else None
        )
        return (repo_key, codeowners_key, release_key)

    def _get_global_cached_charts(
        self,
        active_releases: set[str] | None,
    ) -> list[ChartInfo] | None:
        """Return shared cached charts when still fresh."""
        key = self._global_cache_key(active_releases)
        cached = self._global_charts_cache.get(key)
        if cached is None:
            return None
        cached_at, charts = cached
        if time.monotonic() - cached_at > self._GLOBAL_CACHE_TTL_SECONDS:
            self._global_charts_cache.pop(key, None)
            return None
        self._global_charts_cache.move_to_end(key)
        return list(charts)

    def _set_global_cached_charts(
        self,
        active_releases: set[str] | None,
        charts: list[ChartInfo],
    ) -> None:
        """Store shared chart-analysis cache snapshot with LRU eviction."""
        key = self._global_cache_key(active_releases)
        # If key already exists, remove it first so re-insertion places it at the end
        self._global_charts_cache.pop(key, None)
        self._global_charts_cache[key] = (time.monotonic(), list(charts))
        # Evict least-recently-used entry when cache exceeds max size
        while len(self._global_charts_cache) > self._GLOBAL_CACHE_MAX_ENTRIES:
            self._global_charts_cache.popitem(last=False)

    async def analyze_all_charts_async(
        self,
        active_releases: set[str] | None = None,
        force_refresh: bool = False,
        on_analysis_progress: Callable[[int, int], None] | None = None,
        on_analysis_partial: Callable[[list[ChartInfo], int, int], None] | None = None,
    ) -> list[ChartInfo]:
        """Analyze all charts in repository with parallel processing.

        Args:
            active_releases: Optional set of release names to filter by.
            force_refresh: If True, invalidate cache and re-analyze.
            on_analysis_progress: Callback invoked as each chart analysis
                completes.
            on_analysis_partial: Callback invoked with accumulated chart analyses
                as each chart finishes.

        Returns:
            List of analyzed ChartInfo objects.
        """
        cache_key = "charts"

        if force_refresh:
            await self.refresh()

        if not force_refresh:
            shared_cached = self._get_global_cached_charts(active_releases)
            if shared_cached is not None:
                if active_releases is None:
                    self._charts_cache = list(shared_cached)
                    if self._cache is not None:
                        await self._cache.set(cache_key, list(shared_cached))
                return shared_cached

        if active_releases is None and not force_refresh:
            if self._cache is not None:
                cached = await self._cache.get(cache_key)
                if cached is not None:
                    return cached

            if self._charts_cache is not None:
                return self._charts_cache

        # Only hold the lock for the cache check, not the entire analysis.
        # Use an Event to prevent duplicate concurrent analyses.
        async with self._charts_cache_lock:
            if active_releases is None and not force_refresh:
                if self._cache is not None:
                    cached = await self._cache.get(cache_key)
                    if cached is not None:
                        return cached

                if self._charts_cache is not None:
                    return self._charts_cache

            # If another analysis is already running, wait for it.
            # Re-check inside the lock after waking to prevent stale reads.
            while self._analysis_in_progress is not None:
                event = self._analysis_in_progress
                # Release the lock while waiting so the running analysis can finish
                self._charts_cache_lock.release()
                try:
                    await event.wait()
                finally:
                    await self._charts_cache_lock.acquire()
                # After waking, re-check cache (analysis may have completed)
                shared_cached = self._get_global_cached_charts(active_releases)
                if shared_cached is not None:
                    return shared_cached

            # Mark analysis as in progress (still under lock)
            self._analysis_in_progress = asyncio.Event()

        try:
            try:
                if not self.repo_path.exists():
                    return []
            except (OSError, ValueError):
                return []

            chart_dirs = await asyncio.to_thread(self._chart_fetcher.find_chart_directories)

            if active_releases is not None:
                chart_dirs = [
                    d
                    for d in chart_dirs
                    if self._matches_active_release(d, active_releases)
                ]

            if on_analysis_progress is None and on_analysis_partial is None:
                charts = await asyncio.to_thread(
                    self._analyze_charts_parallel, chart_dirs
                )
            else:
                charts = await self._analyze_charts_parallel_async(
                    chart_dirs,
                    on_analysis_progress=on_analysis_progress,
                    on_analysis_partial=on_analysis_partial,
                )
            self._set_global_cached_charts(active_releases, charts)

            if active_releases is None:
                self._charts_cache = charts
                if self._cache is not None:
                    await self._cache.set(cache_key, charts)

            return charts
        finally:
            # Signal waiting callers and clear the event
            if self._analysis_in_progress is not None:
                self._analysis_in_progress.set()
            self._analysis_in_progress = None

    def _analyze_charts_parallel(self, chart_dirs: list[Path]) -> list[ChartInfo]:
        """Analyze charts in parallel using ThreadPoolExecutor."""
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            results = list(executor.map(self._analyze_single_chart, chart_dirs))

        charts: list[ChartInfo] = []
        for chart_results in results:
            charts.extend(chart_results)
        return charts

    async def _analyze_charts_parallel_async(
        self,
        chart_dirs: list[Path],
        *,
        on_analysis_progress: Callable[[int, int], None] | None = None,
        on_analysis_partial: Callable[[list[ChartInfo], int, int], None] | None = None,
    ) -> list[ChartInfo]:
        """Analyze charts in parallel and emit incremental progress callbacks."""
        if not chart_dirs:
            return []

        loop = asyncio.get_running_loop()
        total = len(chart_dirs)
        results_by_index: dict[int, list[ChartInfo]] = {}
        # Maintain a running snapshot to avoid O(n^2) rebuild on each callback.
        accumulated_snapshot: list[ChartInfo] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            async def _analyze_with_index(
                index: int,
                chart_dir: Path,
            ) -> tuple[int, list[ChartInfo]]:
                result = await loop.run_in_executor(
                    executor,
                    self._analyze_single_chart,
                    chart_dir,
                )
                return index, result

            tasks = [
                asyncio.create_task(_analyze_with_index(index, chart_dir))
                for index, chart_dir in enumerate(chart_dirs)
            ]
            try:
                for completed, future in enumerate(asyncio.as_completed(tasks), start=1):
                    index, result = await future
                    if result:
                        results_by_index[index] = result
                        if on_analysis_partial is not None:
                            try:
                                # Directly extend snapshot with the just-completed result.
                                accumulated_snapshot.extend(result)
                                on_analysis_partial(accumulated_snapshot, completed, total)
                            except Exception:
                                logger.debug(
                                    "Chart partial-analysis callback failed",
                                    exc_info=True,
                                )

                    if on_analysis_progress is not None:
                        try:
                            on_analysis_progress(completed, total)
                        except Exception:
                            logger.debug(
                                "Chart analysis progress callback failed",
                                exc_info=True,
                            )
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

        charts: list[ChartInfo] = []
        for index in sorted(results_by_index):
            charts.extend(results_by_index[index])
        return charts

    def _analyze_single_chart(self, chart_path: Path) -> list[ChartInfo]:
        """Analyze a single chart for every values file variant."""
        values_files = self._chart_fetcher.find_values_files(chart_path)
        if not values_files:
            return []

        chart_results: list[ChartInfo] = []
        for values_file in values_files:
            values = self._chart_fetcher.parse_values_file(values_file)
            if values is None:
                continue
            chart_results.append(
                self._chart_parser.parse(chart_path, values, values_file)
            )
        return chart_results

    def _run_helm(self, args: tuple[str, ...], timeout: int = 60) -> str:
        """Run helm command and return output."""
        cmd = ["helm"]
        if self.context:
            cmd.extend(["--kube-context", self.context])
        cmd.extend(args)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout if result.returncode == 0 else ""

    async def fetch_live_helm_releases(self) -> list[dict[str, str]]:
        """Fetch list of Helm releases from the cluster."""
        if self._release_fetcher is None:
            self._release_fetcher = ReleaseFetcher(
                lambda args: asyncio.to_thread(self._run_helm, args),
                self.context,
            )
        return await self._release_fetcher.fetch_releases()

    async def fetch_live_helm_releases_streaming(
        self,
        on_namespace_update: Callable[[list[dict[str, str]], int, int], None] | None = None,
    ) -> list[dict[str, str]]:
        """Fetch Helm releases progressively by namespace.

        Reuses ClusterController's namespace streaming path to match Cluster screen
        behavior and enables incremental progress updates in Charts Explorer.
        """
        cluster_controller = ClusterController(context=self.context)
        if on_namespace_update is None:
            releases = await cluster_controller.get_helm_releases()
            return [
                {"name": release.name, "namespace": release.namespace}
                for release in releases
                if release.name and release.namespace
            ]

        def _on_namespace_update(
            partial_releases: list[Any],
            completed: int,
            total: int,
        ) -> None:
            mapped = [
                {"name": str(release.name), "namespace": str(release.namespace)}
                for release in partial_releases
                if getattr(release, "name", None) and getattr(release, "namespace", None)
            ]
            on_namespace_update(mapped, completed, total)

        releases = await cluster_controller.get_helm_releases(
            on_namespace_update=_on_namespace_update
        )
        return [
            {"name": release.name, "namespace": release.namespace}
            for release in releases
            if release.name and release.namespace
        ]

    def _matches_active_release(
        self, chart_dir: Path, active_releases: set[str]
    ) -> bool:
        """Check whether chart directory maps to an active release name."""
        resolved_chart_name = self._chart_parser._resolve_chart_name(chart_dir)
        if resolved_chart_name in active_releases:
            return True
        if chart_dir.name in active_releases:
            return True
        return chart_dir.name == "main" and chart_dir.parent.name in active_releases

    def _resolve_cluster_analysis_concurrency(self, release_count: int) -> int:
        """Resolve bounded concurrency for live Helm values analysis."""
        if release_count <= 0:
            return 1
        base_workers = max(1, int(self.max_workers))
        boosted_workers = max(
            base_workers,
            base_workers * self._CLUSTER_ANALYSIS_CONCURRENCY_MULTIPLIER,
        )
        return max(
            1,
            min(
                release_count,
                boosted_workers,
                self._CLUSTER_ANALYSIS_CONCURRENCY_CAP,
            ),
        )

    def _consume_live_values_output(self, release: str, namespace: str) -> str | None:
        """Get and clear cached raw values output for a release/namespace pair."""
        return self._live_values_output_cache.pop((release, namespace), None)

    async def get_live_chart_values(
        self, release: str, namespace: str
    ) -> dict[str, Any]:
        """Fetch live values for a specific Helm release."""
        if self._release_fetcher is None:
            self._release_fetcher = ReleaseFetcher(
                lambda args: asyncio.to_thread(self._run_helm, args),
                self.context,
            )
        values, raw_output = await self._release_fetcher.fetch_release_values_with_output(
            release,
            namespace,
        )
        cache_key = (release, namespace)
        if raw_output:
            # Move to end if already present, then set value (LRU promotion)
            if cache_key in self._live_values_output_cache:
                self._live_values_output_cache.move_to_end(cache_key)
            self._live_values_output_cache[cache_key] = raw_output
            # Evict least-recently-used entries when cache exceeds max size
            while len(self._live_values_output_cache) > self._LIVE_VALUES_CACHE_MAX_ENTRIES:
                self._live_values_output_cache.popitem(last=False)
        else:
            self._live_values_output_cache.pop(cache_key, None)
        return values

    def analyze_live_chart(
        self, release: str, namespace: str, values: dict[str, Any]
    ) -> ChartInfo | None:
        """Analyze live chart values from cluster."""
        try:
            team = self._chart_parser._extract_team(values, chart_name=release)
            cpu_request = self._chart_parser._parse_cpu(values, "requests", "cpu")
            cpu_limit = self._chart_parser._parse_cpu(values, "limits", "cpu")
            memory_request = self._chart_parser._parse_memory(values, "requests", "memory")
            memory_limit = self._chart_parser._parse_memory(values, "limits", "memory")

            qos_class = self._chart_parser._determine_qos(
                cpu_request, cpu_limit, memory_request, memory_limit
            )

            has_liveness = self._chart_parser._has_probe(values, "livenessProbe")
            has_readiness = self._chart_parser._has_probe(values, "readinessProbe")
            has_startup = self._chart_parser._has_probe(values, "startupProbe")

            if not has_liveness or not has_readiness or not has_startup:
                probes = values.get("probes", {})
                if not has_liveness:
                    has_liveness = bool(probes.get("liveness"))
                if not has_readiness:
                    has_readiness = bool(probes.get("readiness"))
                if not has_startup:
                    has_startup = bool(probes.get("startup"))

            has_anti_affinity = self._chart_parser._has_anti_affinity(values)
            has_topology_spread = self._chart_parser._has_topology_spread(values)

            pdb_enabled = self._chart_parser._has_pdb(values)
            pdb_min_available, pdb_max_unavailable = self._chart_parser._get_pdb_values(values)

            replicas = self._chart_parser._get_replicas(values)
            priority_class = self._chart_parser._get_priority_class(values)

            return ChartInfo(
                name=release,
                team=team,
                values_file=f"cluster:{namespace}",
                namespace=namespace,
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
                has_topology=has_topology_spread,
                pdb_enabled=pdb_enabled,
                pdb_template_exists=False,
                pdb_min_available=pdb_min_available,
                pdb_max_unavailable=pdb_max_unavailable,
                replicas=replicas,
                priority_class=priority_class,
                deployed_values_content=None,
            )
        except (ValueError, KeyError, TypeError):
            logger.exception(f"Error analyzing live chart {release}")
            return None

    async def analyze_all_charts_cluster_async(
        self,
        releases: list[dict[str, str]] | None = None,
        force_refresh: bool = False,
        on_release_discovery_progress: Callable[
            [list[dict[str, str]], int, int], None
        ]
        | None = None,
        on_analysis_progress: Callable[[int, int], None] | None = None,
        on_analysis_partial: Callable[[list[ChartInfo], int, int], None] | None = None,
    ) -> list[ChartInfo]:
        """Analyze live Helm releases from cluster with parallel processing.

        Args:
            releases: Optional list of releases to analyze. If None, fetches from cluster.
            force_refresh: If True, invalidate cache and re-fetch from cluster.
            on_release_discovery_progress: Callback for namespace-by-namespace release
                discovery progress. Invoked only when releases is None.
            on_analysis_progress: Callback invoked as each release values analysis
                completes.
            on_analysis_partial: Callback invoked with accumulated chart analyses
                as each release finishes.

        Returns:
            List of analyzed ChartInfo objects.
        """
        self.is_cluster_mode = True
        cache_key = "charts_cluster"
        should_cache = releases is None

        if force_refresh:
            await self.refresh()

        if should_cache and not force_refresh:
            if self._cache is not None:
                cached = await self._cache.get(cache_key)
                if cached is not None:
                    return cached

            if self._charts_cache is not None:
                return self._charts_cache

        async with self._charts_cache_lock:
            if should_cache and not force_refresh:
                if self._cache is not None:
                    cached = await self._cache.get(cache_key)
                    if cached is not None:
                        return cached

                if self._charts_cache is not None:
                    return self._charts_cache

            async def fetch_and_analyze(
                release: dict[str, str],
            ) -> ChartInfo | None:
                name = release["name"]
                namespace = release["namespace"]
                values = await self.get_live_chart_values(name, namespace)
                raw_values_output = self._consume_live_values_output(name, namespace)
                chart = self.analyze_live_chart(name, namespace, values)
                if (
                    chart is not None
                    and raw_values_output is not None
                    and raw_values_output.strip()
                ):
                    chart.deployed_values_content = raw_values_output
                return chart

            charts: list[ChartInfo] = []
            analysis_started_at = time.perf_counter()

            if releases is None and on_release_discovery_progress is not None:
                # Stream analysis as namespace-scoped discovery reports releases.
                # This avoids waiting for full release discovery before first rows render.
                max_streaming_concurrency = max(
                    1,
                    min(
                        self.max_workers * self._CLUSTER_ANALYSIS_CONCURRENCY_MULTIPLIER,
                        self._CLUSTER_ANALYSIS_CONCURRENCY_CAP,
                    ),
                )
                semaphore = asyncio.Semaphore(max_streaming_concurrency)
                analysis_results: asyncio.Queue[ChartInfo | None] = asyncio.Queue()
                analysis_tasks: set[asyncio.Task[None]] = set()
                seen_releases: set[tuple[str, str]] = set()
                discovered_release_count = 0
                completed = 0
                discovery_releases: list[dict[str, str]] = []
                discovery_resolved = False

                async def _analyze_and_publish(release: dict[str, str]) -> None:
                    try:
                        async with semaphore:
                            chart = await fetch_and_analyze(release)
                        await analysis_results.put(chart)
                    except Exception:
                        logger.exception("Error analyzing live release")
                        await analysis_results.put(None)

                def _schedule_release(release: dict[str, str]) -> None:
                    nonlocal discovered_release_count
                    name = str(release.get("name", "")).strip()
                    namespace = str(release.get("namespace", "")).strip()
                    if not name or not namespace:
                        return
                    key = (namespace, name)
                    if key in seen_releases:
                        return
                    seen_releases.add(key)
                    discovered_release_count = len(seen_releases)
                    task = asyncio.create_task(
                        _analyze_and_publish({"name": name, "namespace": namespace})
                    )
                    analysis_tasks.add(task)
                    task.add_done_callback(analysis_tasks.discard)

                def _on_release_discovery_update(
                    partial_releases: list[dict[str, str]],
                    completed_namespaces: int,
                    total_namespaces: int,
                ) -> None:
                    with suppress(Exception):
                        on_release_discovery_progress(
                            partial_releases,
                            completed_namespaces,
                            total_namespaces,
                        )
                    for release in partial_releases:
                        _schedule_release(release)

                discovery_task = asyncio.create_task(
                    self.fetch_live_helm_releases_streaming(
                        on_namespace_update=_on_release_discovery_update
                    )
                )

                try:
                    while True:
                        if discovery_task.done() and not discovery_resolved:
                            with suppress(Exception):
                                discovery_releases = await discovery_task
                            for release in discovery_releases:
                                _schedule_release(release)
                            discovery_resolved = True

                        if (
                            discovery_resolved
                            and not analysis_tasks
                            and analysis_results.empty()
                        ):
                            break

                        try:
                            result = await asyncio.wait_for(analysis_results.get(), timeout=0.1)
                        except asyncio.TimeoutError:
                            continue

                        completed += 1
                        total = max(discovered_release_count, completed)
                        if isinstance(result, ChartInfo):
                            charts.append(result)
                            if on_analysis_partial is not None:
                                with suppress(Exception):
                                    on_analysis_partial(charts, completed, total)
                        if on_analysis_progress is not None:
                            with suppress(Exception):
                                on_analysis_progress(completed, total)
                finally:
                    if not discovery_task.done():
                        discovery_task.cancel()
                    with suppress(Exception):
                        await discovery_task
                    for task in list(analysis_tasks):
                        if not task.done():
                            task.cancel()
                    if analysis_tasks:
                        await asyncio.gather(*analysis_tasks, return_exceptions=True)

                duration_seconds = time.perf_counter() - analysis_started_at
                logger.debug(
                    "Stream-analyzed %d live Helm release(s) in %.2fs with concurrency=%d",
                    len(discovery_releases) or len(seen_releases),
                    duration_seconds,
                    max_streaming_concurrency,
                )
            else:
                if releases is None:
                    releases = await self.fetch_live_helm_releases()

                if not releases:
                    return []

                concurrency = self._resolve_cluster_analysis_concurrency(len(releases))
                semaphore = asyncio.Semaphore(concurrency)

                async def bounded_fetch(release: dict[str, str]) -> ChartInfo | None:
                    async with semaphore:
                        return await fetch_and_analyze(release)

                tasks = [asyncio.create_task(bounded_fetch(release)) for release in releases]
                total = len(tasks)

                for completed, future in enumerate(asyncio.as_completed(tasks), start=1):
                    try:
                        result = await future
                        if isinstance(result, ChartInfo):
                            charts.append(result)
                            if on_analysis_partial is not None:
                                try:
                                    on_analysis_partial(charts, completed, total)
                                except Exception:
                                    logger.debug(
                                        "Release partial-analysis callback failed",
                                        exc_info=True,
                                    )
                    except Exception:
                        logger.exception("Error analyzing live release")

                    if on_analysis_progress is not None:
                        try:
                            on_analysis_progress(completed, total)
                        except Exception:
                            logger.debug(
                                "Release analysis progress callback failed",
                                exc_info=True,
                            )

                duration_seconds = time.perf_counter() - analysis_started_at
                logger.debug(
                    "Analyzed %d live Helm release(s) in %.2fs with concurrency=%d",
                    total,
                    duration_seconds,
                    concurrency,
                )

            if should_cache:
                self._charts_cache = charts
                if self._cache is not None:
                    await self._cache.set(cache_key, charts)

            return charts

