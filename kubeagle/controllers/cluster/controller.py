"""Cluster controller for EKS data operations.

This module serves as the main orchestrator for cluster data operations,
delegating to specialized controllers for node, pod, event, and PDB operations.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import os
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from kubeagle.constants.enums import FetchState
from kubeagle.constants.timeouts import (
    CLUSTER_REQUEST_TIMEOUT,
    HELM_COMMAND_TIMEOUT,
    KUBECTL_COMMAND_TIMEOUT,
)
from kubeagle.controllers.base import BaseController
from kubeagle.controllers.cluster.fetchers import (
    ClusterFetcher,
    EventFetcher,
    NodeFetcher,
    PodFetcher,
    TopMetricsFetcher,
)
from kubeagle.controllers.cluster.parsers import (
    EventParser,
    NodeParser,
    PodParser,
)
from kubeagle.models.charts.chart_info import HelmReleaseInfo
from kubeagle.models.core.node_info import NodeInfo, NodeResourceInfo
from kubeagle.models.core.workload_info import SingleReplicaWorkloadInfo
from kubeagle.models.core.workload_inventory_info import (
    WorkloadAssignedNodeDetailInfo,
    WorkloadAssignedPodDetailInfo,
    WorkloadInventoryInfo,
    WorkloadLiveUsageSampleInfo,
)
from kubeagle.models.events.event_info import EventDetail
from kubeagle.models.events.event_summary import EventSummary
from kubeagle.models.pdb.pdb_info import PDBInfo
from kubeagle.models.teams.distribution import PodDistributionInfo
from kubeagle.utils.resource_parser import memory_str_to_bytes, parse_cpu

logger = logging.getLogger(__name__)


@dataclass
class FetchStatus:
    """Status tracking for a single data source fetch operation."""

    source_name: str
    state: FetchState = FetchState.SUCCESS
    error_message: str | None = None
    last_updated: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_name": self.source_name,
            "state": self.state.value,
            "error_message": self.error_message,
            "last_updated": self.last_updated.isoformat()
            if self.last_updated
            else None,
        }


class ClusterController(BaseController):
    """EKS cluster data operations with parallel fetching.

    This class serves as an orchestrator that delegates to specialized controllers:
    - NodeFetcher: Node data fetching
    - PodFetcher: Pod distribution and workload operations
    - EventFetcher: Cluster event operations
    - ClusterFetcher: Cluster-level operations and Helm releases
    """

    SOURCE_NODES = "nodes"
    SOURCE_EVENTS = "events"
    SOURCE_PDBS = "pod_disruption_budgets"
    SOURCE_HELM_RELEASES = "helm_releases"
    SOURCE_NODE_RESOURCES = "node_resources"
    SOURCE_POD_DISTRIBUTION = "pod_distribution"
    SOURCE_CLUSTER_CONNECTION = "cluster_connection"
    _NODE_POD_ENRICH_REQUEST_TIMEOUT = "15s"
    _TOP_METRICS_REQUEST_TIMEOUT = "20s"
    _DEFAULT_EVENT_WINDOW_HOURS = 0.25  # 15 minutes
    _WARNING_EVENTS_REQUEST_TIMEOUT = CLUSTER_REQUEST_TIMEOUT
    _NAMESPACE_STREAM_MAX_CONCURRENT = 4
    _GLOBAL_COMMAND_CACHE_TTL_SECONDS = 20.0
    _PARTIAL_UPDATE_TARGET_EMITS = 4
    _PDB_NAMESPACE_RETRY_ATTEMPTS = 1
    _SEMAPHORE_ACQUIRE_TIMEOUT = 60.0  # Prevent indefinite blocking on hung fetches
    _SYSTEM_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease"}
    _HELM_RELEASE_LABEL_KEYS = (
        "app.kubernetes.io/instance",
        "helm.sh/release-name",
        "release",
    )
    _WORKLOAD_INVENTORY_RESOURCE_QUERY = "deployment,statefulset,daemonset,job,cronjob"
    _SINGLE_REPLICA_RESOURCE_QUERY = "deployment,statefulset"

    _fetch_semaphore: asyncio.Semaphore | None = None
    _semaphore_max_concurrent: int = 3
    _global_kubectl_cache: dict[tuple[str, tuple[str, ...]], tuple[float, str]] = {}
    _global_helm_cache: dict[tuple[str, tuple[str, ...]], tuple[float, str]] = {}
    _GLOBAL_COMMAND_CACHE_MAX_ENTRIES = 64  # Prevent unbounded memory growth

    @classmethod
    def get_semaphore(cls, max_concurrent: int | None = None) -> asyncio.Semaphore:
        """Get or create shared semaphore for concurrent fetch limiting."""
        effective_max = (
            max_concurrent
            if max_concurrent is not None
            else cls._semaphore_max_concurrent
        )

        # Compare against configured max, not runtime _value (which fluctuates
        # on acquire/release and must not trigger semaphore recreation).
        if (
            cls._fetch_semaphore is None
            or cls._semaphore_max_concurrent != effective_max
        ):
            cls._fetch_semaphore = asyncio.Semaphore(effective_max)
            cls._semaphore_max_concurrent = effective_max

        return cls._fetch_semaphore

    @classmethod
    def set_max_concurrent(cls, max_concurrent: int) -> None:
        """Set the maximum number of concurrent fetches."""
        if max_concurrent < 1:
            max_concurrent = 1
        cls._semaphore_max_concurrent = max_concurrent
        cls._fetch_semaphore = asyncio.Semaphore(max_concurrent)

    @classmethod
    async def acquire_slot(cls, operation_name: str = "fetch") -> bool:
        """Acquire a slot from the concurrency semaphore."""
        semaphore = cls.get_semaphore()
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=30.0)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Semaphore acquire timed out for {operation_name}")
            return False
        except asyncio.CancelledError:
            logger.debug(f"Semaphore acquire cancelled for {operation_name}")
            return False

    @classmethod
    def release_slot(cls) -> None:
        """Release a slot back to the concurrency semaphore."""
        if cls._fetch_semaphore is not None:
            cls._fetch_semaphore.release()

    @classmethod
    def reset_semaphore(cls) -> None:
        """Reset the semaphore."""
        cls._fetch_semaphore = None
        cls._semaphore_max_concurrent = 3

    @classmethod
    def clear_global_command_cache(cls, context: str | None = None) -> None:
        """Clear shared kubectl/helm command caches.

        Args:
            context: Optional context name. When provided, only cache entries
                for that context are cleared.
        """
        if context is None:
            cls._global_kubectl_cache.clear()
            cls._global_helm_cache.clear()
            return

        context_key = context or ""
        cls._global_kubectl_cache = {
            key: value
            for key, value in cls._global_kubectl_cache.items()
            if key[0] != context_key
        }
        cls._global_helm_cache = {
            key: value
            for key, value in cls._global_helm_cache.items()
            if key[0] != context_key
        }

    @staticmethod
    def resolve_current_context(timeout_seconds: int = 8) -> str | None:
        """Resolve active kubectl context name from local kubeconfig."""
        try:
            result = subprocess.run(
                ["kubectl", "config", "current-context"],
                capture_output=True,
                text=True,
                timeout=max(1, timeout_seconds),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

        if result.returncode != 0:
            return None
        resolved = (result.stdout or "").strip()
        return resolved or None

    @classmethod
    def _should_emit_partial_update(cls, completed: int, total: int) -> bool:
        """Throttle partial callbacks to avoid UI/event-loop update storms."""
        if total <= 0 or completed >= total:
            return True
        interval = max(1, math.ceil(total / cls._PARTIAL_UPDATE_TARGET_EMITS))
        return completed % interval == 0

    @staticmethod
    def _is_transient_pdb_namespace_error(error: Exception) -> bool:
        """Detect transient per-namespace PDB failures worth one retry."""
        text = str(error).lower()
        return (
            "malformed header" in text
            or "missing http content-type" in text
            or "connection reset by peer" in text
            or "transport is closing" in text
        )

    def __init__(self, context: str | None = None):
        """Initialize the cluster controller.

        Args:
            context: Optional Kubernetes context name.
        """
        super().__init__()
        self.context = context

        # Cache and in-flight dedup avoid repeated expensive kubectl/helm calls
        # when multiple tabs request the same sources concurrently.
        self._kubectl_cache: dict[tuple[str, ...], str] = {}
        self._kubectl_tasks: dict[tuple[str, ...], asyncio.Task[str]] = {}
        self._helm_cache: dict[tuple[str, ...], str] = {}
        self._helm_tasks: dict[tuple[str, ...], asyncio.Task[str]] = {}
        self._pods_cache: list[dict[str, Any]] = []
        self._nodes_cache: list[NodeInfo] = []
        self._helm_releases_cache: list[HelmReleaseInfo] = []
        self._warning_events_cache: list[dict[str, Any]] = []
        self._warning_events_cache_ready: bool = False
        self._nonfatal_warnings: dict[str, str] = {}
        self._runtime_enrichment_prefetch_task: (
            asyncio.Task[tuple[Any, Any, Any, Any]] | None
        ) = None

        # Initialize fetchers
        self._node_fetcher = NodeFetcher(self._run_kubectl_cached)
        self._pod_fetcher = PodFetcher(self._run_kubectl_cached)
        self._event_fetcher = EventFetcher(self._run_kubectl_cached)
        self._cluster_fetcher = ClusterFetcher(
            self._run_kubectl_cached,
            self._run_helm_cached,
        )
        self._top_metrics_fetcher = TopMetricsFetcher(self._run_kubectl_cached)

        # Initialize parsers
        self._node_parser = NodeParser()
        self._pod_parser = PodParser()
        self._event_parser = EventParser()

        # Fetch state tracking
        self._fetch_states: dict[str, FetchStatus] = {}
        self._initialize_fetch_states()

    @staticmethod
    def _is_full_events_query(args: tuple[str, ...]) -> bool:
        """Return True when args represent full all-namespaces event fetch."""
        return (
            len(args) >= 5
            and args[0] == "get"
            and args[1] == "events"
            and "--all-namespaces" in args
            and "-o" in args
            and "json" in args
            and not any(part.startswith("--field-selector=") for part in args)
        )

    @staticmethod
    def _is_warning_events_query(args: tuple[str, ...]) -> bool:
        """Return True when args represent warning-only events fetch."""
        return (
            len(args) >= 5
            and args[0] == "get"
            and args[1] == "events"
            and "--all-namespaces" in args
            and any(part == "--field-selector=type=Warning" for part in args)
        )

    @staticmethod
    def _is_pods_query(args: tuple[str, ...]) -> bool:
        """Return True when args represent pod inventory fetch."""
        has_scope = "-A" in args
        if not has_scope and "-n" in args:
            ns_index = args.index("-n")
            has_scope = ns_index + 1 < len(args)
        return (
            len(args) >= 4
            and args[0] == "get"
            and args[1] == "pods"
            and has_scope
            and "-o" in args
            and "json" in args
        )

    @classmethod
    def _build_warning_events_args(cls, args: tuple[str, ...]) -> tuple[str, ...]:
        """Build a warning-only events query from a full events query."""
        normalized: list[str] = [
            part
            for part in args
            if not part.startswith("--request-timeout=")
        ]
        normalized.append("--field-selector=type=Warning")
        normalized.append("--chunk-size=200")
        normalized.append(f"--request-timeout={cls._WARNING_EVENTS_REQUEST_TIMEOUT}")
        return tuple(normalized)

    @staticmethod
    def _request_timeout_seconds(args: tuple[str, ...]) -> int | None:
        """Parse kubectl --request-timeout value (seconds) from args."""
        prefix = "--request-timeout="
        for part in args:
            if not part.startswith(prefix):
                continue
            value = part[len(prefix):].strip().lower()
            if value.endswith("s"):
                value = value[:-1]
            if not value:
                return None
            with suppress(ValueError):
                seconds = float(value)
                if seconds > 0:
                    return max(1, math.ceil(seconds))
        return None

    def _kubectl_timeout_for_args(self, args: tuple[str, ...]) -> int:
        """Choose a process timeout based on command shape."""
        # Full events queries can be massive on busy clusters; use a shorter
        # timeout to quickly fail over to a warning-only query.
        if self._is_full_events_query(args):
            timeout_seconds = 20
        else:
            # Keep default commands bounded so unreachable clusters fail fast
            # instead of tying up worker threads for too long.
            request_timeout_seconds = self._request_timeout_seconds(args)
            if request_timeout_seconds is not None:
                base_timeout = max(20, request_timeout_seconds + 10)
                if self._is_pods_query(args):
                    if request_timeout_seconds <= 20:
                        timeout_seconds = max(base_timeout, 25)
                    elif request_timeout_seconds <= 30:
                        timeout_seconds = max(base_timeout, 70)
                    else:
                        timeout_seconds = max(base_timeout, 90)
                elif self._is_warning_events_query(args):
                    if request_timeout_seconds <= 30:
                        timeout_seconds = max(base_timeout, 60)
                    else:
                        timeout_seconds = max(base_timeout, 90)
                else:
                    timeout_seconds = min(KUBECTL_COMMAND_TIMEOUT, base_timeout)
            else:
                timeout_seconds = min(KUBECTL_COMMAND_TIMEOUT, 25)

        # During pytest runs, keep subprocess timeouts tighter so background
        # worker threads don't exceed per-test timeout budgets at teardown.
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return min(timeout_seconds, 10)

        return timeout_seconds

    def _run_kubectl_sync(
        self,
        args: tuple[str, ...],
        timeout: int | None = None,
    ) -> str:
        """Run a kubectl command synchronously (thread-safe wrapper target)."""
        cmd = ["kubectl"]
        if self.context:
            cmd.extend(["--context", self.context])
        cmd.extend(args)
        effective_timeout = timeout if timeout is not None else self._kubectl_timeout_for_args(args)
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=effective_timeout
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(stderr or "kubectl command failed")
        return result.stdout

    def _run_helm_sync(
        self,
        args: tuple[str, ...],
        timeout: int = HELM_COMMAND_TIMEOUT,
    ) -> str:
        """Run a helm command synchronously (thread-safe wrapper target)."""
        cmd = ["helm"]
        if self.context:
            cmd.extend(["--kube-context", self.context])
        cmd.extend(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout if result.returncode == 0 else ""

    async def _run_kubectl_uncached(self, args: tuple[str, ...]) -> str:
        try:
            return await asyncio.to_thread(self._run_kubectl_sync, args)
        except subprocess.TimeoutExpired:
            if not self._is_full_events_query(args):
                raise
            warning_args = self._build_warning_events_args(args)
            logger.warning(
                "Full events fetch timed out; falling back to warning-only events query"
            )
            return await asyncio.to_thread(
                self._run_kubectl_sync,
                warning_args,
                self._kubectl_timeout_for_args(warning_args),
            )

    async def _run_helm_uncached(self, args: tuple[str, ...]) -> str:
        return await asyncio.to_thread(self._run_helm_sync, args)

    async def _run_kubectl_cached(self, args: tuple[str, ...]) -> str:
        """Run kubectl with in-flight dedup and per-load memoization."""
        context_key = self.context or ""
        global_key = (context_key, args)
        global_cached = self._global_kubectl_cache.get(global_key)
        if global_cached is not None:
            cached_at, cached_output = global_cached
            if time.monotonic() - cached_at <= self._GLOBAL_COMMAND_CACHE_TTL_SECONDS:
                return cached_output
            self._global_kubectl_cache.pop(global_key, None)

        if args in self._kubectl_cache:
            return self._kubectl_cache[args]

        existing = self._kubectl_tasks.get(args)
        if existing is not None:
            return await asyncio.shield(existing)

        task = asyncio.create_task(self._run_kubectl_uncached(args))
        self._kubectl_tasks[args] = task
        try:
            result = await task
            self._kubectl_cache[args] = result
            self._global_kubectl_cache[global_key] = (time.monotonic(), result)
            # Evict oldest entries when cache exceeds max size
            if len(self._global_kubectl_cache) > self._GLOBAL_COMMAND_CACHE_MAX_ENTRIES:
                oldest_key = min(
                    self._global_kubectl_cache,
                    key=lambda k: self._global_kubectl_cache[k][0],
                )
                self._global_kubectl_cache.pop(oldest_key, None)
            return result
        finally:
            if self._kubectl_tasks.get(args) is task:
                self._kubectl_tasks.pop(args, None)

    async def _run_helm_cached(self, args: tuple[str, ...]) -> str:
        """Run helm with in-flight dedup and per-load memoization."""
        context_key = self.context or ""
        global_key = (context_key, args)
        global_cached = self._global_helm_cache.get(global_key)
        if global_cached is not None:
            cached_at, cached_output = global_cached
            if time.monotonic() - cached_at <= self._GLOBAL_COMMAND_CACHE_TTL_SECONDS:
                return cached_output
            self._global_helm_cache.pop(global_key, None)

        if args in self._helm_cache:
            return self._helm_cache[args]

        existing = self._helm_tasks.get(args)
        if existing is not None:
            return await asyncio.shield(existing)

        task = asyncio.create_task(self._run_helm_uncached(args))
        self._helm_tasks[args] = task
        try:
            result = await task
            self._helm_cache[args] = result
            self._global_helm_cache[global_key] = (time.monotonic(), result)
            # Evict oldest entries when cache exceeds max size
            if len(self._global_helm_cache) > self._GLOBAL_COMMAND_CACHE_MAX_ENTRIES:
                oldest_key = min(
                    self._global_helm_cache,
                    key=lambda k: self._global_helm_cache[k][0],
                )
                self._global_helm_cache.pop(oldest_key, None)
            return result
        finally:
            if self._helm_tasks.get(args) is task:
                self._helm_tasks.pop(args, None)

    def _initialize_fetch_states(self) -> None:
        """Initialize fetch states for all data sources."""
        now = datetime.now(timezone.utc)
        for source in [
            self.SOURCE_NODES,
            self.SOURCE_EVENTS,
            self.SOURCE_PDBS,
            self.SOURCE_HELM_RELEASES,
            self.SOURCE_NODE_RESOURCES,
            self.SOURCE_POD_DISTRIBUTION,
            self.SOURCE_CLUSTER_CONNECTION,
        ]:
            self._fetch_states[source] = FetchStatus(
                source_name=source,
                state=FetchState.SUCCESS,
                last_updated=now,
            )

    def _update_fetch_state(
        self,
        source: str,
        state: FetchState,
        error_message: str | None = None,
    ) -> None:
        """Update the fetch state for a data source."""
        if source not in self._fetch_states:
            self._fetch_states[source] = FetchStatus(source_name=source)
        self._fetch_states[source].state = state
        self._fetch_states[source].error_message = error_message
        if state == FetchState.SUCCESS:
            self._fetch_states[source].last_updated = datetime.now(timezone.utc)

    def _notify_progress(
        self,
        progress_callback: Callable[[str, int, int], None] | None,
        source: str,
        current: int,
        total: int,
    ) -> None:
        """Notify progress callback if provided."""
        if progress_callback:
            with suppress(Exception):
                progress_callback(source, current, total)

    @staticmethod
    def _summarize_connection_error(error: BaseException) -> str:
        """Extract a concise, user-facing connection error from kubectl output."""
        raw_message = str(error).strip()
        if not raw_message:
            return "Cluster connection check failed"

        lines = [line.strip() for line in raw_message.splitlines() if line.strip()]
        if not lines:
            return "Cluster connection check failed"

        preferred_tokens = (
            "unable to connect to the server",
            "you must be logged in",
            "context deadline exceeded",
            "timed out",
            "certificate",
            "no such host",
            "forbidden",
            "unauthorized",
        )

        selected_line = lines[-1]
        for line in reversed(lines):
            lower_line = line.lower()
            if line.startswith("error:") or any(
                token in lower_line for token in preferred_tokens
            ):
                selected_line = line
                break

        cleaned = selected_line.removeprefix("error:").strip()
        if len(cleaned) > 160:
            return f"{cleaned[:157].rstrip()}..."
        return cleaned or "Cluster connection check failed"

    def get_fetch_state(self, source: str) -> FetchStatus | None:
        """Get the fetch state for a specific data source."""
        return self._fetch_states.get(source)

    def get_all_fetch_states(self) -> dict[str, FetchStatus]:
        """Get all fetch states."""
        return self._fetch_states.copy()

    def get_loading_sources(self) -> list[str]:
        """Get list of data sources currently loading."""
        return [
            source
            for source, status in self._fetch_states.items()
            if status.state == FetchState.LOADING
        ]

    def get_error_sources(self) -> list[str]:
        """Get list of data sources with errors."""
        return [
            source
            for source, status in self._fetch_states.items()
            if status.state == FetchState.ERROR
        ]

    def get_last_nonfatal_warnings(self) -> dict[str, str]:
        """Return best-effort warnings from optional data sources."""
        return dict(self._nonfatal_warnings)

    def _record_nonfatal_warning(self, key: str, error: Exception | str) -> None:
        """Store a warning that should not fail screen loading."""
        message = str(error).strip() or "Unknown warning"
        self._nonfatal_warnings[str(key)] = message

    def reset_fetch_state(self, source: str) -> bool:
        """Reset the fetch state for a data source to initial loading state."""
        if source not in self._fetch_states:
            return False
        self._fetch_states[source].state = FetchState.LOADING
        self._fetch_states[source].error_message = None
        return True

    def is_any_loading(self) -> bool:
        """Check if any data source is currently loading."""
        return any(
            status.state == FetchState.LOADING for status in self._fetch_states.values()
        )

    def is_all_success(self) -> bool:
        """Check if all data sources have been fetched successfully."""
        return all(
            status.state == FetchState.SUCCESS for status in self._fetch_states.values()
        )

    async def check_connection(self) -> bool:
        """Check if the data source is available."""
        return await self._cluster_fetcher.check_cluster_connection()

    async def fetch_all(self) -> dict[str, Any]:
        """Fetch all cluster data.

        Runs independent fetches in parallel via asyncio.gather() to reduce
        total latency from sum-of-all to max-of-all.  The shared semaphore
        still throttles actual subprocess calls.

        Returns:
            Dictionary containing all fetched data.
        """
        (
            nodes,
            events,
            pdbs,
            helm_releases,
            node_resources,
            pod_distribution,
        ) = await asyncio.gather(
            self.fetch_nodes(),
            self.fetch_events(),
            self.fetch_pdbs(),
            self.get_helm_releases(),
            self.fetch_node_resources(),
            self.fetch_pod_distribution(),
        )

        return {
            "nodes": nodes,
            "events": events,
            "pdbs": pdbs,
            "helm_releases": helm_releases,
            "node_resources": node_resources,
            "pod_distribution": pod_distribution,
        }

    @staticmethod
    def _extract_container_resources(
        resources: dict[str, Any],
    ) -> tuple[float, float, float, float]:
        """Extract container requests/limits in mCPU and bytes."""
        requests = resources.get("requests", {})
        limits = resources.get("limits", {})

        cpu_req = parse_cpu(requests.get("cpu", "0")) * 1000
        cpu_lim = parse_cpu(limits.get("cpu", "0")) * 1000
        mem_req = memory_str_to_bytes(requests.get("memory", "0Ki"))
        mem_lim = memory_str_to_bytes(limits.get("memory", "0Ki"))

        return cpu_req, cpu_lim, mem_req, mem_lim

    def _effective_pod_resources(
        self, pod: dict[str, Any]
    ) -> tuple[float, float, float, float]:
        """Compute effective pod requests/limits using Kubernetes scheduling rules."""
        pod_spec = pod.get("spec", {})

        pod_cpu_req = 0.0
        pod_cpu_lim = 0.0
        pod_mem_req = 0.0
        pod_mem_lim = 0.0
        for container in pod_spec.get("containers", []):
            cpu_req, cpu_lim, mem_req, mem_lim = self._extract_container_resources(
                container.get("resources", {})
            )
            pod_cpu_req += cpu_req
            pod_cpu_lim += cpu_lim
            pod_mem_req += mem_req
            pod_mem_lim += mem_lim

        init_cpu_req = 0.0
        init_cpu_lim = 0.0
        init_mem_req = 0.0
        init_mem_lim = 0.0
        sidecar_cpu_req = 0.0
        sidecar_cpu_lim = 0.0
        sidecar_mem_req = 0.0
        sidecar_mem_lim = 0.0

        for container in pod_spec.get("initContainers", []):
            cpu_req, cpu_lim, mem_req, mem_lim = self._extract_container_resources(
                container.get("resources", {})
            )
            if container.get("restartPolicy") == "Always":
                sidecar_cpu_req += cpu_req
                sidecar_cpu_lim += cpu_lim
                sidecar_mem_req += mem_req
                sidecar_mem_lim += mem_lim
                continue
            init_cpu_req = max(init_cpu_req, cpu_req)
            init_cpu_lim = max(init_cpu_lim, cpu_lim)
            init_mem_req = max(init_mem_req, mem_req)
            init_mem_lim = max(init_mem_lim, mem_lim)

        effective_cpu_req = max(init_cpu_req, pod_cpu_req + sidecar_cpu_req)
        effective_cpu_lim = max(init_cpu_lim, pod_cpu_lim + sidecar_cpu_lim)
        effective_mem_req = max(init_mem_req, pod_mem_req + sidecar_mem_req)
        effective_mem_lim = max(init_mem_lim, pod_mem_lim + sidecar_mem_lim)

        if overhead := pod_spec.get("overhead"):
            overhead_cpu = parse_cpu(overhead.get("cpu", "0")) * 1000
            overhead_mem = memory_str_to_bytes(overhead.get("memory", "0Ki"))
            effective_cpu_req += overhead_cpu
            effective_mem_req += overhead_mem
            if effective_cpu_lim > 0:
                effective_cpu_lim += overhead_cpu
            if effective_mem_lim > 0:
                effective_mem_lim += overhead_mem

        return effective_cpu_req, effective_cpu_lim, effective_mem_req, effective_mem_lim

    @classmethod
    def _iter_pod_container_statuses(cls, pod_status: Any) -> list[dict[str, Any]]:
        """Return normalized container status entries for a pod."""
        if not isinstance(pod_status, dict):
            return []

        status_entries: list[dict[str, Any]] = []
        for status_key in (
            "containerStatuses",
            "initContainerStatuses",
            "ephemeralContainerStatuses",
        ):
            raw_entries = pod_status.get(status_key, [])
            if not isinstance(raw_entries, list):
                continue
            status_entries.extend(
                entry for entry in raw_entries if isinstance(entry, dict)
            )
        return status_entries

    @classmethod
    def _extract_container_restart_reason(
        cls,
        status_entry: dict[str, Any],
    ) -> str | None:
        """Return best-effort restart reason from one container status entry."""
        state = status_entry.get("state", {})
        current_state = state if isinstance(state, dict) else {}
        last_state = status_entry.get("lastState", {})
        previous_state = last_state if isinstance(last_state, dict) else {}

        waiting_state = current_state.get("waiting", {})
        waiting = waiting_state if isinstance(waiting_state, dict) else {}
        terminated_state = current_state.get("terminated", {})
        terminated = terminated_state if isinstance(terminated_state, dict) else {}
        last_waiting_state = previous_state.get("waiting", {})
        last_waiting = last_waiting_state if isinstance(last_waiting_state, dict) else {}
        last_terminated_state = previous_state.get("terminated", {})
        last_terminated = (
            last_terminated_state if isinstance(last_terminated_state, dict) else {}
        )

        for candidate in (
            waiting.get("reason"),
            terminated.get("reason"),
            last_terminated.get("reason"),
            last_waiting.get("reason"),
        ):
            reason = str(candidate or "").strip()
            if reason:
                return reason
        return None

    @classmethod
    def _extract_container_last_exit_code(
        cls,
        status_entry: dict[str, Any],
    ) -> int | None:
        """Return best-effort last exit code from one container status entry."""
        state = status_entry.get("state", {})
        current_state = state if isinstance(state, dict) else {}
        last_state = status_entry.get("lastState", {})
        previous_state = last_state if isinstance(last_state, dict) else {}

        terminated_state = current_state.get("terminated", {})
        terminated = terminated_state if isinstance(terminated_state, dict) else {}
        last_terminated_state = previous_state.get("terminated", {})
        last_terminated = (
            last_terminated_state if isinstance(last_terminated_state, dict) else {}
        )

        for candidate in (
            terminated.get("exitCode"),
            last_terminated.get("exitCode"),
        ):
            if candidate is None:
                continue
            try:
                return int(candidate)
            except (TypeError, ValueError):
                continue
        return None

    @classmethod
    def _extract_pod_restart_count(cls, pod_status: Any) -> int:
        """Return total restart count from all pod container status groups."""
        total_restarts = 0
        for entry in cls._iter_pod_container_statuses(pod_status):
            total_restarts += cls._coerce_int(entry.get("restartCount"), 0)
        return total_restarts

    @classmethod
    def _extract_pod_restart_reason_counts(
        cls,
        pod_status: Any,
    ) -> dict[str, int]:
        """Return restart reason -> restart count mapping for one pod."""
        reason_counts: dict[str, int] = {}
        for entry in cls._iter_pod_container_statuses(pod_status):
            restart_count = cls._coerce_int(entry.get("restartCount"), 0)
            if restart_count <= 0:
                continue
            reason = cls._extract_container_restart_reason(entry) or "Unknown"
            reason_counts[reason] = int(reason_counts.get(reason, 0)) + restart_count
        return reason_counts

    @classmethod
    def _extract_pod_restart_diagnostics(
        cls,
        pod_status: Any,
    ) -> tuple[str | None, int | None]:
        """Return best-effort restart reason and last exit code for a pod."""
        status_entries = sorted(
            cls._iter_pod_container_statuses(pod_status),
            key=lambda entry: cls._coerce_int(entry.get("restartCount"), 0),
            reverse=True,
        )
        if not status_entries:
            return None, None

        reason: str | None = None
        exit_code: int | None = None

        for entry in status_entries:
            if reason is None:
                reason = cls._extract_container_restart_reason(entry)

            if exit_code is None:
                exit_code = cls._extract_container_last_exit_code(entry)

            if reason is not None and exit_code is not None:
                break

        return reason, exit_code

    def _build_node_resource_totals(
        self,
        pods: list[dict[str, Any]],
    ) -> dict[str, dict[str, float | int]]:
        """Aggregate pod resources per node (mCPU/bytes + pod counts)."""
        totals_by_node: dict[str, dict[str, float | int]] = {}
        for pod in pods:
            pod_status = pod.get("status", {})
            if pod_status.get("phase") not in ("Running", "Pending"):
                continue
            node_name = pod.get("spec", {}).get("nodeName")
            if not node_name:
                continue

            totals = totals_by_node.setdefault(
                node_name,
                {
                    "cpu_requests": 0.0,
                    "cpu_limits": 0.0,
                    "memory_requests": 0.0,
                    "memory_limits": 0.0,
                    "pod_count": 0,
                },
            )
            cpu_req, cpu_lim, mem_req, mem_lim = self._effective_pod_resources(pod)

            totals["cpu_requests"] = float(totals["cpu_requests"]) + cpu_req
            totals["cpu_limits"] = float(totals["cpu_limits"]) + cpu_lim
            totals["memory_requests"] = float(totals["memory_requests"]) + mem_req
            totals["memory_limits"] = float(totals["memory_limits"]) + mem_lim
            totals["pod_count"] = int(totals["pod_count"]) + 1

        return totals_by_node

    @staticmethod
    def _merge_node_resource_totals(
        base: dict[str, dict[str, float | int]],
        delta: dict[str, dict[str, float | int]],
    ) -> None:
        """Merge per-node resource totals in-place."""
        for node_name, values in delta.items():
            target = base.setdefault(
                node_name,
                {
                    "cpu_requests": 0.0,
                    "cpu_limits": 0.0,
                    "memory_requests": 0.0,
                    "memory_limits": 0.0,
                    "pod_count": 0,
                },
            )
            target["cpu_requests"] = float(target["cpu_requests"]) + float(
                values.get("cpu_requests", 0.0)
            )
            target["cpu_limits"] = float(target["cpu_limits"]) + float(
                values.get("cpu_limits", 0.0)
            )
            target["memory_requests"] = float(target["memory_requests"]) + float(
                values.get("memory_requests", 0.0)
            )
            target["memory_limits"] = float(target["memory_limits"]) + float(
                values.get("memory_limits", 0.0)
            )
            target["pod_count"] = int(target["pod_count"]) + int(values.get("pod_count", 0))

    @staticmethod
    def _apply_node_resource_totals(
        nodes: list[NodeInfo],
        totals_by_node: dict[str, dict[str, float | int]],
    ) -> None:
        """Apply per-node pod totals into node models."""
        for node in nodes:
            totals = totals_by_node.get(node.name)
            if totals is None:
                continue
            node.cpu_requests = float(totals["cpu_requests"])
            node.cpu_limits = float(totals["cpu_limits"])
            node.memory_requests = float(totals["memory_requests"])
            node.memory_limits = float(totals["memory_limits"])
            node.pod_count = int(totals["pod_count"])

    @staticmethod
    def _apply_node_resource_totals_delta(
        node_lookup: dict[str, NodeInfo],
        totals_by_node: dict[str, dict[str, float | int]],
        delta_node_names: set[str],
    ) -> None:
        """Apply updated totals only for touched nodes to reduce callback cost."""
        for node_name in delta_node_names:
            node = node_lookup.get(node_name)
            totals = totals_by_node.get(node_name)
            if node is None or totals is None:
                continue
            node.cpu_requests = float(totals["cpu_requests"])
            node.cpu_limits = float(totals["cpu_limits"])
            node.memory_requests = float(totals["memory_requests"])
            node.memory_limits = float(totals["memory_limits"])
            node.pod_count = int(totals["pod_count"])

    async def _list_cluster_namespaces(self) -> list[str]:
        """Fetch namespace names for incremental namespace-scoped queries."""
        try:
            output = await self._run_kubectl_cached(
                (
                    "get",
                    "namespaces",
                    "-o",
                    "json",
                    f"--request-timeout={CLUSTER_REQUEST_TIMEOUT}",
                )
            )
            if not output:
                return []
            data = json.loads(output)
        except Exception as exc:
            logger.warning("Failed to list namespaces for incremental fetch: %s", exc)
            return []

        names = [
            item.get("metadata", {}).get("name", "").strip()
            for item in data.get("items", [])
        ]
        return sorted(name for name in names if name)

    async def _fetch_pods_incremental(
        self,
        on_namespace_loaded: Callable[[str, list[dict[str, Any]], int, int], Any]
        | None = None,
        request_timeout: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch pods namespace-by-namespace and emit partial updates."""
        namespaces = await self._list_cluster_namespaces()
        if not namespaces:
            pods = await self._pod_fetcher.fetch_pods(request_timeout=request_timeout)
            if pods:
                self._pods_cache = list(pods)
            return pods

        semaphore = asyncio.Semaphore(self._NAMESPACE_STREAM_MAX_CONCURRENT)
        total = len(namespaces)
        completed = 0
        all_pods: list[dict[str, Any]] = []

        async def _fetch_namespace(
            namespace: str,
        ) -> tuple[str, list[dict[str, Any]], Exception | None]:
            async with semaphore:
                try:
                    pods = await self._pod_fetcher.fetch_pods_for_namespace(
                        namespace,
                        request_timeout=request_timeout,
                    )
                    return namespace, pods, None
                except Exception as exc:
                    return namespace, [], exc

        tasks = [asyncio.create_task(_fetch_namespace(namespace)) for namespace in namespaces]
        try:
            for future in asyncio.as_completed(tasks):
                namespace, namespace_pods, error = await future
                completed += 1
                if error is not None:
                    logger.warning(
                        "Namespace pod fetch failed for %s: %s",
                        namespace,
                        error,
                    )
                elif namespace_pods:
                    all_pods.extend(namespace_pods)

                if on_namespace_loaded is not None:
                    with suppress(Exception):
                        callback_result: Any = on_namespace_loaded(
                            namespace,
                            namespace_pods,
                            completed,
                            total,
                        )
                        if inspect.isawaitable(callback_result):
                            await callback_result
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        if not all_pods:
            # Namespace-scoped pod requests can fail or timeout on large clusters.
            # Fall back to an all-namespaces query to keep downstream features usable.
            with suppress(Exception):
                fallback_pods = await self._pod_fetcher.fetch_pods(
                    request_timeout=request_timeout
                )
                if fallback_pods:
                    self._pods_cache = list(fallback_pods)
                    return fallback_pods

        self._pods_cache = list(all_pods)
        return all_pods

    async def _fetch_warning_events_incremental(
        self,
        on_namespace_loaded: Callable[[str, list[dict[str, Any]], int, int], Any]
        | None = None,
        request_timeout: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch warning events namespace-by-namespace and emit partial updates."""
        if self._warning_events_cache_ready and on_namespace_loaded is None:
            return list(self._warning_events_cache)

        namespaces = await self._list_cluster_namespaces()
        if not namespaces:
            events = await self._event_fetcher.fetch_warning_events_raw(
                request_timeout=request_timeout
            )
            self._warning_events_cache = list(events)
            self._warning_events_cache_ready = True
            return events

        semaphore = asyncio.Semaphore(self._NAMESPACE_STREAM_MAX_CONCURRENT)
        total = len(namespaces)
        completed = 0
        all_events: list[dict[str, Any]] = []

        async def _fetch_namespace(
            namespace: str,
        ) -> tuple[str, list[dict[str, Any]], Exception | None]:
            async with semaphore:
                try:
                    events = await self._event_fetcher.fetch_warning_events_raw(
                        namespace=namespace,
                        request_timeout=request_timeout,
                    )
                    return namespace, events, None
                except Exception as exc:
                    return namespace, [], exc

        tasks = [asyncio.create_task(_fetch_namespace(namespace)) for namespace in namespaces]
        try:
            for future in asyncio.as_completed(tasks):
                namespace, namespace_events, error = await future
                completed += 1
                if error is not None:
                    logger.warning(
                        "Namespace event fetch failed for %s: %s",
                        namespace,
                        error,
                    )
                elif namespace_events:
                    all_events.extend(namespace_events)

                if on_namespace_loaded is not None:
                    with suppress(Exception):
                        callback_result: Any = on_namespace_loaded(
                            namespace,
                            namespace_events,
                            completed,
                            total,
                        )
                        if inspect.isawaitable(callback_result):
                            await callback_result
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        self._warning_events_cache = list(all_events)
        self._warning_events_cache_ready = True
        return all_events

    @staticmethod
    def _event_counts_from_summary(summary: EventSummary) -> dict[str, int]:
        """Convert EventSummary into legacy event count dictionary."""
        return {
            "oom": summary.oom_count,
            "node_not_ready": summary.node_not_ready_count,
            "failed_scheduling": summary.failed_scheduling_count,
            "backoff": summary.backoff_count,
            "unhealthy": summary.unhealthy_count,
            "failed_mount": summary.failed_mount_count,
            "evicted": summary.evicted_count,
        }

    @staticmethod
    def _parse_pdb_items(pdb_items: list[dict[str, Any]]) -> list[PDBInfo]:
        """Parse raw PDB dictionaries into PDBInfo models."""
        result: list[PDBInfo] = []
        for item in pdb_items:
            spec = item.get("spec", {})
            status = item.get("status", {})
            metadata = item.get("metadata", {})
            raw_selector = spec.get("selector", {})
            raw_match_labels = (
                raw_selector.get("matchLabels", {})
                if isinstance(raw_selector, dict)
                else {}
            )
            selector_match_labels = (
                {str(key): str(value) for key, value in raw_match_labels.items()}
                if isinstance(raw_match_labels, dict) and raw_match_labels
                else None
            )

            result.append(
                PDBInfo(
                    name=metadata.get("name", "Unknown"),
                    namespace=metadata.get("namespace", "default"),
                    kind="Workload",
                    min_available=spec.get("minAvailable"),
                    max_unavailable=spec.get("maxUnavailable"),
                    min_unavailable=spec.get("minUnavailable"),
                    max_available=spec.get("maxAvailable"),
                    current_healthy=status.get("currentHealthy", 0),
                    desired_healthy=status.get("desiredHealthy", 0),
                    expected_pods=status.get("expectedPods", 0),
                    disruptions_allowed=status.get("disruptionsAllowed", 0),
                    unhealthy_pod_eviction_policy=spec.get(
                        "unhealthyPodEvictionPolicy",
                        "IfHealthyBudget",
                    ),
                    selector_match_labels=selector_match_labels,
                )
            )
        return result

    @staticmethod
    def _build_helm_release_lookup(
        releases: list[HelmReleaseInfo],
    ) -> dict[tuple[str, str], str]:
        """Map (namespace, release) -> chart label."""
        lookup: dict[tuple[str, str], str] = {}
        for release in releases:
            key = (release.namespace, release.name)
            chart_name = release.chart.split("-")[0] if release.chart else None
            lookup[key] = chart_name or release.name
        return lookup

    @classmethod
    def _coerce_int(cls, value: Any, default: int = 0) -> int:
        """Convert arbitrary value to int safely."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _helm_release_from_labels(cls, labels: dict[str, Any]) -> str | None:
        """Extract Helm release name from known workload label keys."""
        for key in cls._HELM_RELEASE_LABEL_KEYS:
            raw_value = labels.get(key)
            if raw_value is None:
                continue
            value = str(raw_value).strip()
            if value:
                return value
        return None

    @classmethod
    def _replica_status_from_counts(
        cls,
        desired_replicas: int | None,
        ready_replicas: int | None,
    ) -> str:
        """Build workload status text from desired/ready replica counts."""
        if desired_replicas is None:
            return "Unknown"
        if desired_replicas <= 0:
            return "ScaledToZero"

        ready = max(0, ready_replicas or 0)
        if ready >= desired_replicas:
            return "Ready"
        if ready > 0:
            return "Progressing"
        return "NotReady"

    @classmethod
    def _extract_workload_template_labels(
        cls,
        item: dict[str, Any],
    ) -> dict[str, str]:
        """Extract pod template labels for workload/PDB selector matching."""
        kind = str(item.get("kind", ""))
        spec = item.get("spec", {})

        raw_labels: Any
        if kind == "CronJob":
            raw_labels = (
                spec.get("jobTemplate", {})
                .get("spec", {})
                .get("template", {})
                .get("metadata", {})
                .get("labels", {})
            )
        else:
            raw_labels = (
                spec.get("template", {})
                .get("metadata", {})
                .get("labels", {})
            )

        if not isinstance(raw_labels, dict):
            return {}
        return {str(key): str(value) for key, value in raw_labels.items()}

    @classmethod
    def _extract_workload_template_spec(
        cls,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract pod template spec block from workload objects."""
        kind = str(item.get("kind", ""))
        spec = item.get("spec", {})
        if not isinstance(spec, dict):
            return {}

        if kind == "CronJob":
            pod_spec = (
                spec.get("jobTemplate", {})
                .get("spec", {})
                .get("template", {})
                .get("spec", {})
            )
        else:
            pod_spec = spec.get("template", {}).get("spec", {})
        return pod_spec if isinstance(pod_spec, dict) else {}

    @classmethod
    def _extract_workload_resource_totals(
        cls,
        item: dict[str, Any],
    ) -> tuple[float, float, float, float]:
        """Return aggregate request/limit totals for workload containers.

        CPU values are returned in millicores and memory values in bytes.
        """
        pod_spec = cls._extract_workload_template_spec(item)
        raw_containers = pod_spec.get("containers", [])
        if not isinstance(raw_containers, list):
            return 0.0, 0.0, 0.0, 0.0

        cpu_request = 0.0
        cpu_limit = 0.0
        memory_request = 0.0
        memory_limit = 0.0

        for container in raw_containers:
            if not isinstance(container, dict):
                continue
            resources = container.get("resources", {})
            if not isinstance(resources, dict):
                continue

            requests = resources.get("requests", {})
            limits = resources.get("limits", {})

            requests_map = requests if isinstance(requests, dict) else {}
            limits_map = limits if isinstance(limits, dict) else {}

            cpu_request += parse_cpu(str(requests_map.get("cpu", "") or "")) * 1000
            cpu_limit += parse_cpu(str(limits_map.get("cpu", "") or "")) * 1000
            memory_request += memory_str_to_bytes(
                str(requests_map.get("memory", "") or "")
            )
            memory_limit += memory_str_to_bytes(str(limits_map.get("memory", "") or ""))

        return cpu_request, cpu_limit, memory_request, memory_limit

    @staticmethod
    def _build_pdb_selector_lookup(
        pdbs: list[PDBInfo],
    ) -> dict[str, list[dict[str, str]]]:
        """Build namespace -> list[selector.matchLabels] lookup."""
        selectors_by_namespace: dict[str, list[dict[str, str]]] = {}
        for pdb in pdbs:
            selector = pdb.selector_match_labels or {}
            if not selector:
                continue
            selectors_by_namespace.setdefault(pdb.namespace, []).append(selector)
        return selectors_by_namespace

    @staticmethod
    def _selector_matches_labels(
        selector_match_labels: dict[str, str],
        workload_labels: dict[str, str],
    ) -> bool:
        """Return True when selector labels are a subset of workload labels."""
        if not selector_match_labels or not workload_labels:
            return False
        for key, expected_value in selector_match_labels.items():
            if workload_labels.get(key) != expected_value:
                return False
        return True

    @classmethod
    def _is_active_job_item(cls, item: dict[str, Any]) -> bool:
        """Return True when a Job should be included in active inventory."""
        status = item.get("status", {})
        active = cls._coerce_int(status.get("active"), 0)
        succeeded = cls._coerce_int(status.get("succeeded"), 0)
        failed = cls._coerce_int(status.get("failed"), 0)
        completion_time = status.get("completionTime")
        return active > 0 or (succeeded == 0 and failed == 0 and not completion_time)

    @classmethod
    def _workload_inventory_from_item(
        cls,
        item: dict[str, Any],
        pdb_selectors_by_namespace: dict[str, list[dict[str, str]]],
        *,
        template_labels: dict[str, str] | None = None,
    ) -> WorkloadInventoryInfo | None:
        """Convert raw kubectl workload item into inventory row."""
        metadata = item.get("metadata", {})
        spec = item.get("spec", {})
        status = item.get("status", {})
        kind = str(item.get("kind", "Workload") or "Workload")
        namespace = str(metadata.get("namespace", "default"))
        name = str(metadata.get("name", "Unknown"))

        if kind == "Job" and not cls._is_active_job_item(item):
            return None

        raw_labels = metadata.get("labels", {})
        labels = (
            {str(key): str(value) for key, value in raw_labels.items()}
            if isinstance(raw_labels, dict)
            else {}
        )
        labels_for_pdb = (
            template_labels
            if template_labels is not None
            else cls._extract_workload_template_labels(item)
        )

        desired_replicas: int | None = None
        ready_replicas: int | None = None
        status_text = "Unknown"

        if kind in {"Deployment", "StatefulSet"}:
            desired_replicas = cls._coerce_int(spec.get("replicas"), 1)
            ready_replicas = cls._coerce_int(status.get("readyReplicas"), 0)
            status_text = cls._replica_status_from_counts(desired_replicas, ready_replicas)
        elif kind == "DaemonSet":
            desired_replicas = cls._coerce_int(status.get("desiredNumberScheduled"), 0)
            ready_replicas = cls._coerce_int(status.get("numberReady"), 0)
            status_text = cls._replica_status_from_counts(desired_replicas, ready_replicas)
        elif kind == "Job":
            desired_replicas = cls._coerce_int(spec.get("parallelism"), 1)
            active = cls._coerce_int(status.get("active"), 0)
            succeeded = cls._coerce_int(status.get("succeeded"), 0)
            failed = cls._coerce_int(status.get("failed"), 0)
            ready_replicas = active
            if active > 0:
                status_text = "Running"
            elif succeeded > 0:
                status_text = "Succeeded"
            elif failed > 0:
                status_text = "Failed"
            else:
                status_text = "Pending"
        elif kind == "CronJob":
            raw_active = status.get("active", [])
            active_jobs = len(raw_active) if isinstance(raw_active, list) else 0
            ready_replicas = active_jobs
            if spec.get("suspend") is True:
                status_text = "Suspended"
            elif active_jobs > 0:
                status_text = "Running"
            else:
                status_text = "Idle"

        helm_release = cls._helm_release_from_labels(labels)
        selectors = pdb_selectors_by_namespace.get(namespace, [])
        has_pdb = any(
            cls._selector_matches_labels(selector, labels_for_pdb)
            for selector in selectors
        )
        cpu_request, cpu_limit, memory_request, memory_limit = (
            cls._extract_workload_resource_totals(item)
        )

        return WorkloadInventoryInfo(
            name=name,
            namespace=namespace,
            kind=kind,
            desired_replicas=desired_replicas,
            ready_replicas=ready_replicas,
            status=status_text,
            helm_release=helm_release,
            managed_by_helm=helm_release is not None,
            has_pdb=has_pdb,
            is_system_workload=namespace in cls._SYSTEM_NAMESPACES,
            cpu_request=cpu_request,
            cpu_limit=cpu_limit,
            memory_request=memory_request,
            memory_limit=memory_limit,
        )

    @classmethod
    def _single_replica_from_workload(
        cls,
        item: dict[str, Any],
        helm_lookup: dict[tuple[str, str], str],
    ) -> SingleReplicaWorkloadInfo | None:
        """Convert one Deployment/StatefulSet into single-replica workload row."""
        spec = item.get("spec", {})
        status = item.get("status", {})
        metadata = item.get("metadata", {})

        replicas = cls._coerce_int(spec.get("replicas"), 1)
        if replicas != 1:
            return None

        name = metadata.get("name", "Unknown")
        namespace = metadata.get("namespace", "default")
        raw_labels = metadata.get("labels", {})
        labels = raw_labels if isinstance(raw_labels, dict) else {}

        helm_release = cls._helm_release_from_labels(labels)
        chart_name = None
        if helm_release and namespace not in cls._SYSTEM_NAMESPACES:
            chart_name = helm_lookup.get((namespace, helm_release))

        ready = cls._coerce_int(status.get("readyReplicas"), 0)
        status_str = (
            "Ready"
            if ready >= replicas
            else ("Progressing" if ready > 0 else "NotReady")
        )
        kind = str(item.get("kind", "Workload") or "Workload")

        return SingleReplicaWorkloadInfo(
            name=name,
            namespace=namespace,
            kind=kind,
            replicas=replicas,
            ready_replicas=ready,
            helm_release=helm_release,
            chart_name=chart_name,
            status=status_str,
        )

    async def _fetch_pdbs_incremental(
        self,
        on_namespace_loaded: Callable[[str, list[PDBInfo], int, int], Any] | None = None,
    ) -> list[PDBInfo]:
        """Fetch PDBs namespace-by-namespace and emit partial updates."""
        namespaces = await self._list_cluster_namespaces()
        if not namespaces:
            return self._parse_pdb_items(await self._cluster_fetcher.fetch_pdbs())

        semaphore = asyncio.Semaphore(self._NAMESPACE_STREAM_MAX_CONCURRENT)
        total = len(namespaces)
        completed = 0
        all_pdbs: list[PDBInfo] = []

        async def _fetch_namespace(
            namespace: str,
        ) -> tuple[str, list[PDBInfo], Exception | None]:
            async with semaphore:
                attempts = self._PDB_NAMESPACE_RETRY_ATTEMPTS + 1
                for attempt_index in range(attempts):
                    try:
                        raw = await self._cluster_fetcher.fetch_pdbs_for_namespace(namespace)
                        return namespace, self._parse_pdb_items(raw), None
                    except Exception as exc:
                        should_retry = (
                            attempt_index < self._PDB_NAMESPACE_RETRY_ATTEMPTS
                            and self._is_transient_pdb_namespace_error(exc)
                        )
                        if not should_retry:
                            return namespace, [], exc
                        await asyncio.sleep(0.15 * (attempt_index + 1))

                return namespace, [], RuntimeError("PDB namespace fetch retry exhausted")

        tasks = [asyncio.create_task(_fetch_namespace(namespace)) for namespace in namespaces]
        try:
            for future in asyncio.as_completed(tasks):
                namespace, namespace_pdbs, error = await future
                completed += 1
                if error is not None:
                    logger.warning("Namespace PDB fetch failed for %s: %s", namespace, error)
                elif namespace_pdbs:
                    all_pdbs.extend(namespace_pdbs)

                if on_namespace_loaded is not None:
                    with suppress(Exception):
                        callback_result: Any = on_namespace_loaded(
                            namespace,
                            namespace_pdbs,
                            completed,
                            total,
                        )
                        if inspect.isawaitable(callback_result):
                            await callback_result
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        return all_pdbs

    async def _fetch_helm_releases_incremental(
        self,
        on_namespace_loaded: Callable[
            [str, list[HelmReleaseInfo], int, int],
            Any,
        ]
        | None = None,
    ) -> list[HelmReleaseInfo]:
        """Fetch Helm releases namespace-by-namespace and emit partial updates."""
        if self._helm_releases_cache:
            cached = list(self._helm_releases_cache)
            if on_namespace_loaded is not None:
                grouped: dict[str, list[HelmReleaseInfo]] = {}
                for release in cached:
                    grouped.setdefault(release.namespace, []).append(release)
                total = max(1, len(grouped))
                for index, namespace in enumerate(sorted(grouped), start=1):
                    with suppress(Exception):
                        callback_result: Any = on_namespace_loaded(
                            namespace,
                            grouped[namespace],
                            index,
                            total,
                        )
                        if inspect.isawaitable(callback_result):
                            await callback_result
            return cached

        namespaces = await self._list_cluster_namespaces()
        if not namespaces:
            releases = await self._cluster_fetcher.fetch_helm_releases()
            self._helm_releases_cache = list(releases)
            return releases

        semaphore = asyncio.Semaphore(self._NAMESPACE_STREAM_MAX_CONCURRENT)
        total = len(namespaces)
        completed = 0
        all_releases: list[HelmReleaseInfo] = []

        async def _fetch_namespace(
            namespace: str,
        ) -> tuple[str, list[HelmReleaseInfo], Exception | None]:
            async with semaphore:
                try:
                    releases = await self._cluster_fetcher.fetch_helm_releases_for_namespace(
                        namespace
                    )
                    return namespace, releases, None
                except Exception as exc:
                    return namespace, [], exc

        tasks = [asyncio.create_task(_fetch_namespace(namespace)) for namespace in namespaces]
        try:
            for future in asyncio.as_completed(tasks):
                namespace, namespace_releases, error = await future
                completed += 1
                if error is not None:
                    logger.warning(
                        "Namespace Helm release fetch failed for %s: %s",
                        namespace,
                        error,
                    )
                elif namespace_releases:
                    all_releases.extend(namespace_releases)

                if on_namespace_loaded is not None:
                    with suppress(Exception):
                        callback_result: Any = on_namespace_loaded(
                            namespace,
                            namespace_releases,
                            completed,
                            total,
                        )
                        if inspect.isawaitable(callback_result):
                            await callback_result
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        self._helm_releases_cache = list(all_releases)
        return all_releases

    def _parse_workload_inventory_items(
        self,
        items: list[dict[str, Any]],
        pdb_selectors_by_namespace: dict[str, list[dict[str, str]]],
        template_labels_by_key: dict[tuple[str, str, str], dict[str, str]] | None = None,
    ) -> list[WorkloadInventoryInfo]:
        """Convert raw workload item list to inventory model list."""
        rows: list[WorkloadInventoryInfo] = []
        for item in items:
            labels_for_pdb = self._extract_workload_template_labels(item)
            row = self._workload_inventory_from_item(
                item,
                pdb_selectors_by_namespace,
                template_labels=labels_for_pdb,
            )
            if row is not None:
                if template_labels_by_key is not None:
                    template_labels_by_key[(row.namespace, row.kind, row.name)] = (
                        labels_for_pdb
                    )
                rows.append(row)
        return rows

    @classmethod
    def _apply_workload_pdb_coverage(
        cls,
        rows: list[WorkloadInventoryInfo],
        pdb_selectors_by_namespace: dict[str, list[dict[str, str]]],
        template_labels_by_key: dict[tuple[str, str, str], dict[str, str]],
    ) -> None:
        """Apply PDB coverage to parsed workload rows using cached labels."""
        for row in rows:
            selectors = pdb_selectors_by_namespace.get(row.namespace, [])
            if not selectors:
                row.has_pdb = False
                continue
            labels_for_pdb = template_labels_by_key.get(
                (row.namespace, row.kind, row.name),
                {},
            )
            row.has_pdb = any(
                cls._selector_matches_labels(selector, labels_for_pdb)
                for selector in selectors
            )

    @staticmethod
    def _p95_value(values: list[float]) -> float:
        """Return p95 from numeric values."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = max(
            0,
            min(
                len(sorted_values) - 1,
                math.ceil(len(sorted_values) * 0.95) - 1,
            ),
        )
        return sorted_values[index]

    @staticmethod
    def _format_util_percentage(value: float) -> str:
        """Format one utilization percentage preserving small non-zero values."""
        if value <= 0:
            return "0%"
        if value < 1:
            return f"{value:.2f}%"
        if value < 10:
            return f"{value:.1f}%"
        return f"{value:.0f}%"

    @classmethod
    def _format_util_stats(cls, values: list[float]) -> tuple[str, str, str]:
        """Format utilization values as (max, avg, p95) single percentage fields."""
        if not values:
            return "-", "-", "-"
        max_value = max(values)
        avg_value = sum(values) / len(values)
        p95_value = cls._p95_value(values)
        return (
            cls._format_util_percentage(max_value),
            cls._format_util_percentage(avg_value),
            cls._format_util_percentage(p95_value),
        )

    @staticmethod
    def _format_mcores(value: float) -> str:
        """Format CPU usage in millicores."""
        if value <= 0:
            return "0m"
        return f"{value:.0f}m"

    @staticmethod
    def _format_memory_bytes(value: float) -> str:
        """Format memory bytes to human-readable IEC units."""
        if value <= 0:
            return "0B"
        if value >= 1024 * 1024 * 1024:
            return f"{value / (1024 * 1024 * 1024):.1f}Gi"
        if value >= 1024 * 1024:
            return f"{value / (1024 * 1024):.1f}Mi"
        if value >= 1024:
            return f"{value / 1024:.1f}Ki"
        return f"{value:.0f}B"

    @classmethod
    def _format_value_stats(
        cls,
        values: list[float],
        formatter: Callable[[float], str],
    ) -> tuple[str, str, str]:
        """Format numeric values as (max, avg, p95) using provided formatter."""
        if not values:
            return "-", "-", "-"
        max_value = max(values)
        avg_value = sum(values) / len(values)
        p95_value = cls._p95_value(values)
        return (
            formatter(max_value),
            formatter(avg_value),
            formatter(p95_value),
        )

    @staticmethod
    def _combine_value_and_percentage(
        value_text: str,
        pct_text: str,
    ) -> str:
        """Combine raw value and percentage as `value (pct)` when both exist."""
        value = str(value_text or "-").strip()
        pct = str(pct_text or "-").strip()
        if value == "-" and pct == "-":
            return "-"
        if value == "-":
            return pct
        if pct == "-":
            return value
        return f"{value} ({pct})"

    @classmethod
    def _combine_stats_with_percentage(
        cls,
        value_stats: tuple[str, str, str],
        pct_stats: tuple[str, str, str],
    ) -> tuple[str, str, str]:
        """Combine (max, avg, p95) tuples into `value (pct)` tuples."""
        return (
            cls._combine_value_and_percentage(value_stats[0], pct_stats[0]),
            cls._combine_value_and_percentage(value_stats[1], pct_stats[1]),
            cls._combine_value_and_percentage(value_stats[2], pct_stats[2]),
        )

    @staticmethod
    def _neighbor_pressure_pct(
        node_total_pct: float | None,
        workload_pct: float | None,
    ) -> float | None:
        """Return node pressure attributable to other workloads on the same node."""
        if node_total_pct is None or workload_pct is None:
            return None
        return max(0.0, node_total_pct - workload_pct)

    @staticmethod
    def _format_assigned_nodes(node_names: set[str]) -> str:
        """Render assigned node count."""
        if not node_names:
            return "-"
        return str(len(node_names))

    @staticmethod
    def _infer_cronjob_name_from_job(job_name: str) -> str | None:
        """Infer CronJob name from generated Job name."""
        value = str(job_name or "").strip()
        if "-" not in value:
            return None
        base, suffix = value.rsplit("-", 1)
        if suffix.isdigit() and base:
            return base
        return None

    @staticmethod
    def _infer_deployment_name_from_replicaset(
        replicaset_name: str,
        labels: dict[str, str],
    ) -> str | None:
        """Infer Deployment name from ReplicaSet name and pod labels."""
        value = str(replicaset_name or "").strip()
        if not value:
            return None
        pod_template_hash = str(labels.get("pod-template-hash", "") or "").strip()
        if pod_template_hash and value.endswith(f"-{pod_template_hash}"):
            deployment = value[: -(len(pod_template_hash) + 1)]
            return deployment or None
        if "-" not in value:
            return None
        deployment, _suffix = value.rsplit("-", 1)
        return deployment or None

    @staticmethod
    def _infer_deployment_name_from_pod_name(pod_name: str) -> str | None:
        """Infer Deployment name from generated pod name as fallback."""
        value = str(pod_name or "").strip()
        parts = value.split("-")
        if len(parts) < 3:
            return None
        replica_set_hash = parts[-2]
        pod_suffix = parts[-1]
        if len(replica_set_hash) < 8 or len(pod_suffix) < 4:
            return None
        if not replica_set_hash.isalnum() or not pod_suffix.isalnum():
            return None
        deployment = "-".join(parts[:-2]).strip()
        return deployment or None

    @staticmethod
    def _infer_statefulset_name_from_pod_name(pod_name: str) -> str | None:
        """Infer StatefulSet name from ordinal pod name as fallback."""
        value = str(pod_name or "").strip()
        if "-" not in value:
            return None
        statefulset, ordinal = value.rsplit("-", 1)
        if not ordinal.isdigit():
            return None
        return statefulset or None

    @staticmethod
    def _canonical_workload_kind(kind: str) -> str:
        """Normalize workload kind values to stable canonical names."""
        normalized = str(kind or "").strip().lower()
        kind_map = {
            "deployment": "Deployment",
            "deployments": "Deployment",
            "deployment.apps": "Deployment",
            "deployments.apps": "Deployment",
            "statefulset": "StatefulSet",
            "statefulsets": "StatefulSet",
            "statefulset.apps": "StatefulSet",
            "statefulsets.apps": "StatefulSet",
            "daemonset": "DaemonSet",
            "daemonsets": "DaemonSet",
            "daemonset.apps": "DaemonSet",
            "daemonsets.apps": "DaemonSet",
            "job": "Job",
            "jobs": "Job",
            "job.batch": "Job",
            "jobs.batch": "Job",
            "cronjob": "CronJob",
            "cronjobs": "CronJob",
            "cronjob.batch": "CronJob",
            "cronjobs.batch": "CronJob",
            "replicaset": "ReplicaSet",
            "replicasets": "ReplicaSet",
            "replicaset.apps": "ReplicaSet",
            "replicasets.apps": "ReplicaSet",
        }
        return kind_map.get(normalized, str(kind or "").strip())

    @classmethod
    def _pod_workload_keys(
        cls,
        pod: dict[str, Any],
    ) -> set[tuple[str, str]]:
        """Derive candidate workload keys for a pod."""
        metadata = pod.get("metadata", {})
        raw_labels = metadata.get("labels", {})
        labels = raw_labels if isinstance(raw_labels, dict) else {}
        keys: set[tuple[str, str]] = set()

        owner_refs = metadata.get("ownerReferences", [])
        owner_list = owner_refs if isinstance(owner_refs, list) else []
        controller_owner: dict[str, Any] | None = None
        for owner in owner_list:
            if isinstance(owner, dict) and owner.get("controller") is True:
                controller_owner = owner
                break
        if controller_owner is None:
            for owner in owner_list:
                if isinstance(owner, dict):
                    controller_owner = owner
                    break

        if controller_owner is not None:
            owner_kind = cls._canonical_workload_kind(
                str(controller_owner.get("kind", "") or "").strip()
            )
            owner_name = str(controller_owner.get("name", "") or "").strip()
            if owner_kind and owner_name:
                if owner_kind in {
                    "Deployment",
                    "StatefulSet",
                    "DaemonSet",
                    "Job",
                    "CronJob",
                }:
                    keys.add((owner_kind, owner_name))
                if owner_kind == "ReplicaSet":
                    deployment_name = cls._infer_deployment_name_from_replicaset(
                        owner_name,
                        {str(k): str(v) for k, v in labels.items()},
                    )
                    if deployment_name:
                        keys.add(("Deployment", deployment_name))
                if owner_kind == "Job":
                    cronjob_name = cls._infer_cronjob_name_from_job(owner_name)
                    if cronjob_name:
                        keys.add(("CronJob", cronjob_name))

        pod_name = str(metadata.get("name", "") or "").strip()
        if pod_name:
            deployment_name = cls._infer_deployment_name_from_pod_name(pod_name)
            if deployment_name:
                keys.add(("Deployment", deployment_name))
            statefulset_name = cls._infer_statefulset_name_from_pod_name(pod_name)
            if statefulset_name:
                keys.add(("StatefulSet", statefulset_name))

        job_name = str(labels.get("job-name", "") or "").strip()
        if job_name:
            keys.add(("Job", job_name))
            cronjob_name = cls._infer_cronjob_name_from_job(job_name)
            if cronjob_name:
                keys.add(("CronJob", cronjob_name))

        return keys

    @staticmethod
    def _build_node_utilization_lookup(
        node_resources: list[NodeResourceInfo],
    ) -> dict[str, dict[str, float]]:
        """Return node name -> allocation percentage metrics."""
        return {
            node.name: {
                "cpu_req_pct": float(node.cpu_req_pct),
                "cpu_lim_pct": float(node.cpu_lim_pct),
                "mem_req_pct": float(node.mem_req_pct),
                "mem_lim_pct": float(node.mem_lim_pct),
            }
            for node in node_resources
        }

    def _build_node_allocatable_lookup(
        self,
        nodes_items: list[dict[str, Any]],
    ) -> dict[str, dict[str, float | str]]:
        """Return node name -> allocatable resources and node-group metadata."""
        lookup: dict[str, dict[str, float | str]] = {}
        for node in nodes_items:
            info = self._node_parser.parse_node_info(node)
            lookup[info.name] = {
                "cpu_allocatable_mcores": float(info.cpu_allocatable),
                "memory_allocatable_bytes": float(info.memory_allocatable),
                "node_group": str(info.node_group or "Unknown"),
            }
        return lookup

    @staticmethod
    def _build_top_node_usage_lookup(
        rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, float]]:
        """Return node name -> real CPU/memory usage from `kubectl top node`."""
        lookup: dict[str, dict[str, float]] = {}
        for row in rows:
            name = str(row.get("node_name", "") or "").strip()
            if not name:
                continue
            lookup[name] = {
                "cpu_mcores": float(row.get("cpu_mcores", 0.0) or 0.0),
                "memory_bytes": float(row.get("memory_bytes", 0.0) or 0.0),
            }
        return lookup

    @staticmethod
    def _build_top_pod_usage_lookup(
        rows: list[dict[str, Any]],
    ) -> dict[tuple[str, str], dict[str, float]]:
        """Return (namespace, pod_name) -> real CPU/memory usage from `kubectl top pod`."""
        lookup: dict[tuple[str, str], dict[str, float]] = {}
        for row in rows:
            namespace = str(row.get("namespace", "") or "").strip()
            pod_name = str(row.get("pod_name", "") or "").strip()
            if not namespace or not pod_name:
                continue
            lookup[(namespace, pod_name)] = {
                "cpu_mcores": float(row.get("cpu_mcores", 0.0) or 0.0),
                "memory_bytes": float(row.get("memory_bytes", 0.0) or 0.0),
            }
        return lookup

    async def fetch_workload_live_usage_sample(
        self,
        namespace: str,
        workload_kind: str,
        workload_name: str,
        request_timeout: str | None = None,
    ) -> WorkloadLiveUsageSampleInfo:
        """Fetch one targeted runtime usage sample for a workload."""
        effective_namespace = str(namespace or "").strip()
        effective_kind = self._canonical_workload_kind(str(workload_kind or "").strip())
        effective_name = str(workload_name or "").strip()
        timestamp_epoch = time.time()
        sample = WorkloadLiveUsageSampleInfo(
            timestamp_epoch=timestamp_epoch,
            namespace=effective_namespace,
            workload_kind=effective_kind,
            workload_name=effective_name,
        )
        if not effective_namespace or not effective_kind or not effective_name:
            return sample

        pods = await self._pod_fetcher.fetch_pods_for_namespace(
            effective_namespace,
            request_timeout=self._NODE_POD_ENRICH_REQUEST_TIMEOUT,
        )
        if not pods:
            return sample

        workload_pods_lookup = self._build_workload_pod_lookup(pods)
        workload_pods = list(
            workload_pods_lookup.get(
                (effective_namespace, effective_kind, effective_name),
                [],
            )
        )
        if not workload_pods:
            return sample

        pod_names = {
            str(pod.get("metadata", {}).get("name", "") or "").strip()
            for pod in workload_pods
        }
        pod_names.discard("")
        node_names = {
            str(pod.get("spec", {}).get("nodeName", "") or "").strip()
            for pod in workload_pods
        }
        node_names.discard("")

        sample.pod_count = len(workload_pods)
        sample.node_count = len(node_names)

        top_timeout = request_timeout or self._TOP_METRICS_REQUEST_TIMEOUT
        top_pod_rows: list[dict[str, Any]] = []
        top_node_rows: list[dict[str, Any]] = []
        if pod_names and node_names:
            top_pod_rows, top_node_rows = await asyncio.gather(
                self._top_metrics_fetcher.fetch_top_pods_for_namespace(
                    effective_namespace,
                    sorted(pod_names),
                    request_timeout=top_timeout,
                ),
                self._top_metrics_fetcher.fetch_top_nodes_for_names(
                    sorted(node_names),
                    request_timeout=top_timeout,
                ),
            )
        elif pod_names:
            top_pod_rows = await self._top_metrics_fetcher.fetch_top_pods_for_namespace(
                effective_namespace,
                sorted(pod_names),
                request_timeout=top_timeout,
            )
        elif node_names:
            top_node_rows = await self._top_metrics_fetcher.fetch_top_nodes_for_names(
                sorted(node_names),
                request_timeout=top_timeout,
            )

        top_pod_usage_by_key = self._build_top_pod_usage_lookup(top_pod_rows)
        top_node_usage_by_name = self._build_top_node_usage_lookup(top_node_rows)

        pod_cpu_values: list[float] = []
        pod_memory_values: list[float] = []
        matched_pod_count = 0
        for pod in workload_pods:
            metadata = pod.get("metadata", {})
            pod_namespace = str(metadata.get("namespace", effective_namespace) or effective_namespace)
            pod_name = str(metadata.get("name", "") or "").strip()
            if not pod_name:
                continue
            usage = top_pod_usage_by_key.get((pod_namespace, pod_name))
            if usage is None:
                continue
            matched_pod_count += 1
            pod_cpu_values.append(float(usage.get("cpu_mcores", 0.0) or 0.0))
            pod_memory_values.append(float(usage.get("memory_bytes", 0.0) or 0.0))

        sample.pods_with_metrics = matched_pod_count
        sample.nodes_with_metrics = sum(
            1 for node_name in node_names if node_name in top_node_usage_by_name
        )
        if pod_cpu_values:
            sample.workload_cpu_mcores = sum(pod_cpu_values)
        if pod_memory_values:
            sample.workload_memory_bytes = sum(pod_memory_values)
        return sample

    @classmethod
    def _apply_aggressive_pod_markers(
        cls,
        rows: list[WorkloadInventoryInfo],
    ) -> None:
        """Mark workloads whose pod count exceeds cluster workload pod-count p95."""
        pod_counts = [float(row.pod_count) for row in rows if int(row.pod_count) > 0]
        if not pod_counts:
            for row in rows:
                row.aggressive_pod_outlier = False
                row.aggressive_pod_ratio = None
            return

        threshold = cls._p95_value(pod_counts)
        if threshold <= 0:
            for row in rows:
                row.aggressive_pod_outlier = False
                row.aggressive_pod_ratio = None
            return

        for row in rows:
            row.aggressive_pod_ratio = float(row.pod_count) / threshold
            row.aggressive_pod_outlier = float(row.pod_count) > threshold

    async def _build_node_utilization_lookup_for_pods(
        self,
        pods: list[dict[str, Any]],
        *,
        nodes_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, float]]:
        """Build node allocation percentages from pod-derived totals and node allocatable."""
        if not pods:
            return {}
        try:
            effective_nodes = (
                nodes_items
                if nodes_items is not None
                else await self._node_fetcher.fetch_nodes_raw(
                    request_timeout=self._NODE_POD_ENRICH_REQUEST_TIMEOUT
                )
            )
        except Exception as exc:
            logger.warning(
                "Unable to fetch nodes for workload runtime enrichment: %s",
                exc,
            )
            return {}
        if not effective_nodes:
            return {}
        totals_by_node = await asyncio.to_thread(self._build_node_resource_totals, pods)
        node_resources = await asyncio.to_thread(
            self._build_node_resources,
            effective_nodes,
            totals_by_node,
        )
        return self._build_node_utilization_lookup(node_resources)

    def _apply_workload_pod_runtime_stats(
        self,
        rows: list[WorkloadInventoryInfo],
        pods: list[dict[str, Any]],
        node_utilization_by_name: dict[str, dict[str, float]],
        *,
        node_allocatable_by_name: dict[str, dict[str, float | str]] | None = None,
        top_node_usage_by_name: dict[str, dict[str, float]] | None = None,
        top_pod_usage_by_key: dict[tuple[str, str], dict[str, float]] | None = None,
    ) -> None:
        """Populate workload rows with pod-node and utilization statistics."""
        workload_pods = self._build_workload_pod_lookup(pods)
        self._apply_workload_runtime_stats_with_lookup(
            rows,
            workload_pods,
            node_utilization_by_name,
            node_allocatable_by_name=node_allocatable_by_name or {},
            top_node_usage_by_name=top_node_usage_by_name or {},
            top_pod_usage_by_key=top_pod_usage_by_key or {},
        )

    def _build_workload_pod_lookup(
        self,
        pods: list[dict[str, Any]],
    ) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
        """Build workload key -> pod list lookup."""
        workload_pods: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

        for pod in pods:
            metadata = pod.get("metadata", {})
            namespace = str(metadata.get("namespace", "") or "").strip()
            if not namespace:
                continue
            for kind, workload_name in self._pod_workload_keys(pod):
                canonical_kind = self._canonical_workload_kind(kind)
                workload_pods.setdefault((namespace, canonical_kind, workload_name), []).append(
                    pod
                )
        return workload_pods

    def _apply_workload_runtime_stats_with_lookup(
        self,
        rows: list[WorkloadInventoryInfo],
        workload_pods: dict[tuple[str, str, str], list[dict[str, Any]]],
        node_utilization_by_name: dict[str, dict[str, float]],
        *,
        node_allocatable_by_name: dict[str, dict[str, float | str]] | None = None,
        top_node_usage_by_name: dict[str, dict[str, float]] | None = None,
        top_pod_usage_by_key: dict[tuple[str, str], dict[str, float]] | None = None,
    ) -> None:
        """Populate workload rows with runtime stats using pre-built pod lookup."""
        effective_node_allocatable = node_allocatable_by_name or {}
        effective_top_node_usage = top_node_usage_by_name or {}
        effective_top_pod_usage = top_pod_usage_by_key or {}

        for row in rows:
            row.assigned_node_details = []
            row.assigned_pod_details = []
            row.pod_count = 0
            row.restart_count = 0
            row.restart_reason_counts = {}
            row.assigned_nodes = "-"

            row_kind = self._canonical_workload_kind(row.kind)
            row_pods = workload_pods.get((row.namespace, row_kind, row.name), [])
            if not row_pods:
                continue

            row.pod_count = len(row_pods)
            row.restart_count = sum(
                self._extract_pod_restart_count(pod.get("status", {}))
                for pod in row_pods
            )
            for pod in row_pods:
                for reason, count in self._extract_pod_restart_reason_counts(
                    pod.get("status", {})
                ).items():
                    row.restart_reason_counts[reason] = (
                        int(row.restart_reason_counts.get(reason, 0)) + int(count)
                    )
            assigned_node_names = {
                str(pod.get("spec", {}).get("nodeName", "") or "").strip()
                for pod in row_pods
                if str(pod.get("spec", {}).get("nodeName", "") or "").strip()
            }
            row.assigned_nodes = self._format_assigned_nodes(assigned_node_names)

            pod_details: list[WorkloadAssignedPodDetailInfo] = []
            for pod in row_pods:
                metadata = pod.get("metadata", {})
                status = pod.get("status", {})
                spec = pod.get("spec", {})
                pod_namespace = str(metadata.get("namespace", row.namespace) or row.namespace)
                pod_name = str(metadata.get("name", "") or "").strip()
                node_name = str(spec.get("nodeName", "") or "").strip() or "-"
                pod_phase = str(status.get("phase", "Unknown") or "Unknown")
                restart_reason, last_exit_code = self._extract_pod_restart_diagnostics(
                    status
                )

                pod_usage = effective_top_pod_usage.get((pod_namespace, pod_name))
                pod_cpu_mcores = (
                    float(pod_usage.get("cpu_mcores", 0.0))
                    if pod_usage is not None
                    else None
                )
                pod_memory_bytes = (
                    float(pod_usage.get("memory_bytes", 0.0))
                    if pod_usage is not None
                    else None
                )

                node_alloc = effective_node_allocatable.get(node_name, {})
                node_cpu_allocatable = float(
                    node_alloc.get("cpu_allocatable_mcores", 0.0) or 0.0
                )
                node_memory_allocatable = float(
                    node_alloc.get("memory_allocatable_bytes", 0.0) or 0.0
                )
                cpu_pct = (
                    (pod_cpu_mcores / node_cpu_allocatable * 100.0)
                    if (pod_cpu_mcores is not None and node_cpu_allocatable > 0)
                    else None
                )
                memory_pct = (
                    (pod_memory_bytes / node_memory_allocatable * 100.0)
                    if (pod_memory_bytes is not None and node_memory_allocatable > 0)
                    else None
                )

                pod_details.append(
                    WorkloadAssignedPodDetailInfo(
                        namespace=pod_namespace,
                        pod_name=pod_name,
                        node_name=node_name,
                        pod_phase=pod_phase,
                        pod_real_cpu_mcores=pod_cpu_mcores,
                        pod_real_memory_bytes=pod_memory_bytes,
                        node_cpu_allocatable_mcores=(
                            node_cpu_allocatable if node_cpu_allocatable > 0 else None
                        ),
                        node_memory_allocatable_bytes=(
                            node_memory_allocatable if node_memory_allocatable > 0 else None
                        ),
                        pod_cpu_pct_of_node_allocatable=cpu_pct,
                        pod_memory_pct_of_node_allocatable=memory_pct,
                        restart_reason=restart_reason,
                        last_exit_code=last_exit_code,
                    )
                )
            row.assigned_pod_details = pod_details

            cpu_req_values: list[float] = []
            cpu_lim_values: list[float] = []
            mem_req_values: list[float] = []
            mem_lim_values: list[float] = []
            node_real_cpu_values: list[float] = []
            node_real_memory_values: list[float] = []
            node_real_cpu_pct_values: list[float] = []
            node_real_memory_pct_values: list[float] = []
            neighbor_cpu_pressure_values: list[float] = []
            neighbor_memory_pressure_values: list[float] = []
            neighbor_cpu_req_pressure_values: list[float] = []
            neighbor_cpu_lim_pressure_values: list[float] = []
            neighbor_memory_req_pressure_values: list[float] = []
            neighbor_memory_lim_pressure_values: list[float] = []
            pod_real_cpu_values = [
                float(detail.pod_real_cpu_mcores)
                for detail in pod_details
                if detail.pod_real_cpu_mcores is not None
            ]
            pod_real_memory_values = [
                float(detail.pod_real_memory_bytes)
                for detail in pod_details
                if detail.pod_real_memory_bytes is not None
            ]
            pod_real_cpu_pct_values = [
                float(detail.pod_cpu_pct_of_node_allocatable)
                for detail in pod_details
                if detail.pod_cpu_pct_of_node_allocatable is not None
            ]
            pod_real_memory_pct_values = [
                float(detail.pod_memory_pct_of_node_allocatable)
                for detail in pod_details
                if detail.pod_memory_pct_of_node_allocatable is not None
            ]
            workload_resource_totals_by_node: dict[str, dict[str, float]] = {}
            for pod in row_pods:
                pod_status = pod.get("status", {})
                if pod_status.get("phase") not in ("Running", "Pending"):
                    continue
                pod_node_name = str(pod.get("spec", {}).get("nodeName", "") or "").strip()
                if not pod_node_name:
                    continue
                node_totals = workload_resource_totals_by_node.setdefault(
                    pod_node_name,
                    {
                        "cpu_req": 0.0,
                        "cpu_lim": 0.0,
                        "mem_req": 0.0,
                        "mem_lim": 0.0,
                    },
                )
                pod_cpu_req, pod_cpu_lim, pod_mem_req, pod_mem_lim = self._effective_pod_resources(
                    pod
                )
                node_totals["cpu_req"] = float(node_totals["cpu_req"]) + pod_cpu_req
                node_totals["cpu_lim"] = float(node_totals["cpu_lim"]) + pod_cpu_lim
                node_totals["mem_req"] = float(node_totals["mem_req"]) + pod_mem_req
                node_totals["mem_lim"] = float(node_totals["mem_lim"]) + pod_mem_lim

            node_details: list[WorkloadAssignedNodeDetailInfo] = []
            for node_name in assigned_node_names:
                node_utilization = node_utilization_by_name.get(node_name)
                node_alloc = effective_node_allocatable.get(node_name, {})
                node_top_usage = effective_top_node_usage.get(node_name, {})

                cpu_req_pct = (
                    float(node_utilization.get("cpu_req_pct", 0.0))
                    if node_utilization is not None
                    else None
                )
                cpu_lim_pct = (
                    float(node_utilization.get("cpu_lim_pct", 0.0))
                    if node_utilization is not None
                    else None
                )
                mem_req_pct = (
                    float(node_utilization.get("mem_req_pct", 0.0))
                    if node_utilization is not None
                    else None
                )
                mem_lim_pct = (
                    float(node_utilization.get("mem_lim_pct", 0.0))
                    if node_utilization is not None
                    else None
                )
                if cpu_req_pct is not None:
                    cpu_req_values.append(cpu_req_pct)
                if cpu_lim_pct is not None:
                    cpu_lim_values.append(cpu_lim_pct)
                if mem_req_pct is not None:
                    mem_req_values.append(mem_req_pct)
                if mem_lim_pct is not None:
                    mem_lim_values.append(mem_lim_pct)

                node_real_cpu = (
                    float(node_top_usage.get("cpu_mcores", 0.0))
                    if node_top_usage
                    else None
                )
                node_real_memory = (
                    float(node_top_usage.get("memory_bytes", 0.0))
                    if node_top_usage
                    else None
                )
                node_cpu_allocatable = float(
                    node_alloc.get("cpu_allocatable_mcores", 0.0) or 0.0
                )
                node_memory_allocatable = float(
                    node_alloc.get("memory_allocatable_bytes", 0.0) or 0.0
                )
                node_real_cpu_pct = (
                    (node_real_cpu / node_cpu_allocatable * 100.0)
                    if (node_real_cpu is not None and node_cpu_allocatable > 0)
                    else None
                )
                node_real_memory_pct = (
                    (node_real_memory / node_memory_allocatable * 100.0)
                    if (node_real_memory is not None and node_memory_allocatable > 0)
                    else None
                )
                if node_real_cpu is not None:
                    node_real_cpu_values.append(node_real_cpu)
                if node_real_memory is not None:
                    node_real_memory_values.append(node_real_memory)
                if node_real_cpu_pct is not None:
                    node_real_cpu_pct_values.append(node_real_cpu_pct)
                if node_real_memory_pct is not None:
                    node_real_memory_pct_values.append(node_real_memory_pct)

                node_pod_details = [
                    detail for detail in pod_details if detail.node_name == node_name
                ]
                node_pod_cpu_values = [
                    float(detail.pod_real_cpu_mcores)
                    for detail in node_pod_details
                    if detail.pod_real_cpu_mcores is not None
                ]
                node_pod_memory_values = [
                    float(detail.pod_real_memory_bytes)
                    for detail in node_pod_details
                    if detail.pod_real_memory_bytes is not None
                ]
                workload_pod_real_cpu_on_node = (
                    sum(node_pod_cpu_values) if node_pod_cpu_values else None
                )
                workload_pod_real_memory_on_node = (
                    sum(node_pod_memory_values) if node_pod_memory_values else None
                )
                workload_pod_real_cpu_pct = (
                    (workload_pod_real_cpu_on_node / node_cpu_allocatable * 100.0)
                    if (
                        workload_pod_real_cpu_on_node is not None
                        and node_cpu_allocatable > 0
                    )
                    else None
                )
                workload_pod_real_memory_pct = (
                    (workload_pod_real_memory_on_node / node_memory_allocatable * 100.0)
                    if (
                        workload_pod_real_memory_on_node is not None
                        and node_memory_allocatable > 0
                    )
                    else None
                )
                workload_node_totals = workload_resource_totals_by_node.get(node_name)
                workload_cpu_req_pct = (
                    (float(workload_node_totals["cpu_req"]) / node_cpu_allocatable * 100.0)
                    if (workload_node_totals is not None and node_cpu_allocatable > 0)
                    else None
                )
                workload_cpu_lim_pct = (
                    (float(workload_node_totals["cpu_lim"]) / node_cpu_allocatable * 100.0)
                    if (workload_node_totals is not None and node_cpu_allocatable > 0)
                    else None
                )
                workload_memory_req_pct = (
                    (float(workload_node_totals["mem_req"]) / node_memory_allocatable * 100.0)
                    if (workload_node_totals is not None and node_memory_allocatable > 0)
                    else None
                )
                workload_memory_lim_pct = (
                    (float(workload_node_totals["mem_lim"]) / node_memory_allocatable * 100.0)
                    if (workload_node_totals is not None and node_memory_allocatable > 0)
                    else None
                )
                neighbor_cpu_pressure = self._neighbor_pressure_pct(
                    node_real_cpu_pct,
                    workload_pod_real_cpu_pct,
                )
                neighbor_memory_pressure = self._neighbor_pressure_pct(
                    node_real_memory_pct,
                    workload_pod_real_memory_pct,
                )
                neighbor_cpu_req_pressure = self._neighbor_pressure_pct(
                    cpu_req_pct,
                    workload_cpu_req_pct,
                )
                neighbor_cpu_lim_pressure = self._neighbor_pressure_pct(
                    cpu_lim_pct,
                    workload_cpu_lim_pct,
                )
                neighbor_memory_req_pressure = self._neighbor_pressure_pct(
                    mem_req_pct,
                    workload_memory_req_pct,
                )
                neighbor_memory_lim_pressure = self._neighbor_pressure_pct(
                    mem_lim_pct,
                    workload_memory_lim_pct,
                )
                if neighbor_cpu_pressure is not None:
                    neighbor_cpu_pressure_values.append(neighbor_cpu_pressure)
                if neighbor_memory_pressure is not None:
                    neighbor_memory_pressure_values.append(neighbor_memory_pressure)
                if neighbor_cpu_req_pressure is not None:
                    neighbor_cpu_req_pressure_values.append(neighbor_cpu_req_pressure)
                if neighbor_cpu_lim_pressure is not None:
                    neighbor_cpu_lim_pressure_values.append(neighbor_cpu_lim_pressure)
                if neighbor_memory_req_pressure is not None:
                    neighbor_memory_req_pressure_values.append(neighbor_memory_req_pressure)
                if neighbor_memory_lim_pressure is not None:
                    neighbor_memory_lim_pressure_values.append(neighbor_memory_lim_pressure)

                node_details.append(
                    WorkloadAssignedNodeDetailInfo(
                        node_name=node_name,
                        node_group=str(node_alloc.get("node_group", "Unknown")),
                        workload_pod_count_on_node=len(node_pod_details),
                        node_cpu_req_pct=cpu_req_pct,
                        node_cpu_lim_pct=cpu_lim_pct,
                        node_mem_req_pct=mem_req_pct,
                        node_mem_lim_pct=mem_lim_pct,
                        node_real_cpu_mcores=node_real_cpu,
                        node_real_memory_bytes=node_real_memory,
                        node_real_cpu_pct_of_allocatable=node_real_cpu_pct,
                        node_real_memory_pct_of_allocatable=node_real_memory_pct,
                        workload_pod_real_cpu_mcores_on_node=workload_pod_real_cpu_on_node,
                        workload_pod_real_memory_bytes_on_node=workload_pod_real_memory_on_node,
                        workload_pod_real_cpu_pct_of_node_allocatable=workload_pod_real_cpu_pct,
                        workload_pod_real_memory_pct_of_node_allocatable=(
                            workload_pod_real_memory_pct
                        ),
                    )
                )

            row.assigned_node_details = sorted(
                node_details,
                key=lambda detail: detail.node_name,
            )

            (
                row.cpu_req_util_max,
                row.cpu_req_util_avg,
                row.cpu_req_util_p95,
            ) = self._format_util_stats(cpu_req_values)
            (
                row.cpu_lim_util_max,
                row.cpu_lim_util_avg,
                row.cpu_lim_util_p95,
            ) = self._format_util_stats(cpu_lim_values)
            (
                row.mem_req_util_max,
                row.mem_req_util_avg,
                row.mem_req_util_p95,
            ) = self._format_util_stats(mem_req_values)
            (
                row.mem_lim_util_max,
                row.mem_lim_util_avg,
                row.mem_lim_util_p95,
            ) = self._format_util_stats(mem_lim_values)

            (
                node_real_cpu_max_value,
                node_real_cpu_avg_value,
                node_real_cpu_p95_value,
            ) = self._format_value_stats(node_real_cpu_values, self._format_mcores)
            (
                node_real_cpu_max_pct,
                node_real_cpu_avg_pct,
                node_real_cpu_p95_pct,
            ) = self._format_util_stats(node_real_cpu_pct_values)
            (
                row.node_real_cpu_max,
                row.node_real_cpu_avg,
                row.node_real_cpu_p95,
            ) = self._combine_stats_with_percentage(
                (node_real_cpu_max_value, node_real_cpu_avg_value, node_real_cpu_p95_value),
                (node_real_cpu_max_pct, node_real_cpu_avg_pct, node_real_cpu_p95_pct),
            )

            (
                node_real_memory_max_value,
                node_real_memory_avg_value,
                node_real_memory_p95_value,
            ) = self._format_value_stats(
                node_real_memory_values,
                self._format_memory_bytes,
            )
            (
                node_real_memory_max_pct,
                node_real_memory_avg_pct,
                node_real_memory_p95_pct,
            ) = self._format_util_stats(node_real_memory_pct_values)
            (
                row.node_real_memory_max,
                row.node_real_memory_avg,
                row.node_real_memory_p95,
            ) = self._combine_stats_with_percentage(
                (
                    node_real_memory_max_value,
                    node_real_memory_avg_value,
                    node_real_memory_p95_value,
                ),
                (
                    node_real_memory_max_pct,
                    node_real_memory_avg_pct,
                    node_real_memory_p95_pct,
                ),
            )

            (
                pod_real_cpu_max_value,
                pod_real_cpu_avg_value,
                pod_real_cpu_p95_value,
            ) = self._format_value_stats(pod_real_cpu_values, self._format_mcores)
            (
                pod_real_cpu_max_pct,
                pod_real_cpu_avg_pct,
                pod_real_cpu_p95_pct,
            ) = self._format_util_stats(pod_real_cpu_pct_values)
            (
                row.pod_real_cpu_max,
                row.pod_real_cpu_avg,
                row.pod_real_cpu_p95,
            ) = self._combine_stats_with_percentage(
                (pod_real_cpu_max_value, pod_real_cpu_avg_value, pod_real_cpu_p95_value),
                (pod_real_cpu_max_pct, pod_real_cpu_avg_pct, pod_real_cpu_p95_pct),
            )

            (
                pod_real_memory_max_value,
                pod_real_memory_avg_value,
                pod_real_memory_p95_value,
            ) = self._format_value_stats(
                pod_real_memory_values,
                self._format_memory_bytes,
            )
            (
                pod_real_memory_max_pct,
                pod_real_memory_avg_pct,
                pod_real_memory_p95_pct,
            ) = self._format_util_stats(pod_real_memory_pct_values)
            (
                row.pod_real_memory_max,
                row.pod_real_memory_avg,
                row.pod_real_memory_p95,
            ) = self._combine_stats_with_percentage(
                (
                    pod_real_memory_max_value,
                    pod_real_memory_avg_value,
                    pod_real_memory_p95_value,
                ),
                (
                    pod_real_memory_max_pct,
                    pod_real_memory_avg_pct,
                    pod_real_memory_p95_pct,
                ),
            )

            (
                row.neighbor_cpu_pressure_max,
                row.neighbor_cpu_pressure_avg,
                _neighbor_cpu_p95,
            ) = self._format_util_stats(neighbor_cpu_pressure_values)
            (
                row.neighbor_mem_pressure_max,
                row.neighbor_mem_pressure_avg,
                _neighbor_mem_p95,
            ) = self._format_util_stats(neighbor_memory_pressure_values)
            (
                row.neighbor_cpu_req_pressure_max,
                row.neighbor_cpu_req_pressure_avg,
                _neighbor_cpu_req_p95,
            ) = self._format_util_stats(neighbor_cpu_req_pressure_values)
            (
                row.neighbor_cpu_lim_pressure_max,
                row.neighbor_cpu_lim_pressure_avg,
                _neighbor_cpu_lim_p95,
            ) = self._format_util_stats(neighbor_cpu_lim_pressure_values)
            (
                row.neighbor_mem_req_pressure_max,
                row.neighbor_mem_req_pressure_avg,
                _neighbor_mem_req_p95,
            ) = self._format_util_stats(neighbor_memory_req_pressure_values)
            (
                row.neighbor_mem_lim_pressure_max,
                row.neighbor_mem_lim_pressure_avg,
                _neighbor_mem_lim_p95,
            ) = self._format_util_stats(neighbor_memory_lim_pressure_values)

        self._apply_aggressive_pod_markers(rows)

    async def _prefetch_workload_runtime_stats_inputs(
        self,
    ) -> tuple[Any, Any, Any, Any]:
        """Fetch pod/node/top metrics concurrently for workload runtime enrichment."""
        results = await asyncio.gather(
            self._pod_fetcher.fetch_pods(request_timeout=CLUSTER_REQUEST_TIMEOUT),
            self._node_fetcher.fetch_nodes_raw(request_timeout=CLUSTER_REQUEST_TIMEOUT),
            self._top_metrics_fetcher.fetch_top_nodes(
                request_timeout=self._TOP_METRICS_REQUEST_TIMEOUT
            ),
            self._top_metrics_fetcher.fetch_top_pods_all_namespaces(
                request_timeout=self._TOP_METRICS_REQUEST_TIMEOUT
            ),
            return_exceptions=True,
        )
        return cast(tuple[Any, Any, Any, Any], tuple(results))

    async def _fallback_enrich_workload_runtime_stats(
        self,
        rows: list[WorkloadInventoryInfo],
    ) -> list[WorkloadInventoryInfo]:
        """Fallback enrichment using cached/fresh pod data when full metrics timeout."""
        pods = list(self._pods_cache)
        if not pods:
            with suppress(Exception):
                pods = await self._pod_fetcher.fetch_pods(
                    request_timeout=self._NODE_POD_ENRICH_REQUEST_TIMEOUT
                )
                if pods:
                    self._pods_cache = list(pods)
        if not pods:
            return rows

        node_utilization_by_name = await self._build_node_utilization_lookup_for_pods(
            pods
        )
        self._apply_workload_pod_runtime_stats(
            rows,
            pods,
            node_utilization_by_name,
        )
        return rows

    async def enrich_workload_runtime_stats(
        self,
        rows: list[WorkloadInventoryInfo],
        *,
        timeout_seconds: float = 45.0,
    ) -> list[WorkloadInventoryInfo]:
        """Best-effort enrichment for workload pod runtime utilization stats."""
        if not rows:
            return rows

        self._nonfatal_warnings = {}
        prefetch_task = self._runtime_enrichment_prefetch_task
        self._runtime_enrichment_prefetch_task = None
        if prefetch_task is None:
            prefetch_task = asyncio.create_task(
                self._prefetch_workload_runtime_stats_inputs()
            )
        try:
            (
                pods_result,
                nodes_result,
                top_nodes_result,
                top_pods_result,
            ) = await asyncio.wait_for(
                prefetch_task,
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("Timed out while enriching workload runtime stats")
            if not prefetch_task.done():
                prefetch_task.cancel()
                await asyncio.gather(prefetch_task, return_exceptions=True)
            return await self._fallback_enrich_workload_runtime_stats(rows)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Workload runtime enrichment prefetch failed; using fallback: %s",
                exc,
            )
            return await self._fallback_enrich_workload_runtime_stats(rows)

        pods: list[dict[str, Any]] = []
        nodes_items: list[dict[str, Any]] = []
        top_nodes_rows: list[dict[str, Any]] = []
        top_pods_rows: list[dict[str, Any]] = []

        if isinstance(pods_result, Exception):
            logger.warning("Unable to fetch pods for workload enrichment: %s", pods_result)
        elif isinstance(pods_result, list):
            pods = pods_result
            if pods:
                self._pods_cache = list(pods)

        if isinstance(nodes_result, Exception):
            logger.warning(
                "Unable to fetch nodes for workload enrichment: %s",
                nodes_result,
            )
        elif isinstance(nodes_result, list):
            nodes_items = nodes_result

        if isinstance(top_nodes_result, Exception):
            logger.warning(
                "Unable to fetch top node metrics for workload enrichment: %s",
                top_nodes_result,
            )
            self._record_nonfatal_warning("top_nodes", top_nodes_result)
        elif isinstance(top_nodes_result, list):
            top_nodes_rows = top_nodes_result

        if isinstance(top_pods_result, Exception):
            logger.warning(
                "Unable to fetch top pod metrics for workload enrichment: %s",
                top_pods_result,
            )
            self._record_nonfatal_warning("top_pods", top_pods_result)
        elif isinstance(top_pods_result, list):
            top_pods_rows = top_pods_result

        if not pods:
            return rows

        node_utilization_by_name = await self._build_node_utilization_lookup_for_pods(
            pods,
            nodes_items=nodes_items,
        )
        node_allocatable_by_name = (
            self._build_node_allocatable_lookup(nodes_items) if nodes_items else {}
        )
        top_node_usage_by_name = self._build_top_node_usage_lookup(top_nodes_rows)
        top_pod_usage_by_key = self._build_top_pod_usage_lookup(top_pods_rows)
        self._apply_workload_pod_runtime_stats(
            rows,
            pods,
            node_utilization_by_name,
            node_allocatable_by_name=node_allocatable_by_name,
            top_node_usage_by_name=top_node_usage_by_name,
            top_pod_usage_by_key=top_pod_usage_by_key,
        )
        return rows

    async def _fetch_workload_inventory_incremental(
        self,
        on_namespace_loaded: Callable[
            [str, list[WorkloadInventoryInfo], int, int],
            Any,
        ]
        | None = None,
    ) -> list[WorkloadInventoryInfo]:
        """Fetch runtime workload inventory namespace-by-namespace."""
        namespaces = await self._list_cluster_namespaces()
        template_labels_by_key: dict[tuple[str, str, str], dict[str, str]] = {}
        pdb_task: asyncio.Task[list[PDBInfo]] = asyncio.create_task(
            self._fetch_pdbs_incremental()
        )

        if not namespaces:
            output = await self._run_kubectl_cached(
                (
                    "get",
                    self._WORKLOAD_INVENTORY_RESOURCE_QUERY,
                    "-A",
                    "-o",
                    "json",
                    f"--request-timeout={CLUSTER_REQUEST_TIMEOUT}",
                )
            )
            if not output:
                if not pdb_task.done():
                    pdb_task.cancel()
                    await asyncio.gather(pdb_task, return_exceptions=True)
                return []
            data = json.loads(output)
            rows = self._parse_workload_inventory_items(
                data.get("items", []),
                {},
                template_labels_by_key=template_labels_by_key,
            )
            pdb_selectors_by_namespace: dict[str, list[dict[str, str]]] = {}
            try:
                pdbs = await pdb_task
                pdb_selectors_by_namespace = self._build_pdb_selector_lookup(pdbs)
            except Exception as exc:
                logger.warning("Workload PDB coverage fetch failed: %s", exc)
            self._apply_workload_pdb_coverage(
                rows,
                pdb_selectors_by_namespace,
                template_labels_by_key,
            )
            return sorted(
                rows,
                key=lambda row: (row.namespace, row.kind, row.name),
            )

        semaphore = asyncio.Semaphore(self._NAMESPACE_STREAM_MAX_CONCURRENT)
        total = len(namespaces)
        completed = 0
        all_rows: list[WorkloadInventoryInfo] = []

        async def _fetch_namespace(
            namespace: str,
        ) -> tuple[str, list[WorkloadInventoryInfo], Exception | None]:
            async with semaphore:
                try:
                    output = await self._run_kubectl_cached(
                        (
                            "get",
                            self._WORKLOAD_INVENTORY_RESOURCE_QUERY,
                            "-n",
                            namespace,
                            "-o",
                            "json",
                            f"--request-timeout={CLUSTER_REQUEST_TIMEOUT}",
                        )
                    )
                    if not output:
                        return namespace, [], None
                    data = json.loads(output)
                    rows = self._parse_workload_inventory_items(
                        data.get("items", []),
                        {},
                        template_labels_by_key=template_labels_by_key,
                    )
                    return namespace, rows, None
                except Exception as exc:
                    return namespace, [], exc

        tasks = [asyncio.create_task(_fetch_namespace(namespace)) for namespace in namespaces]
        try:
            for future in asyncio.as_completed(tasks):
                namespace, namespace_rows, error = await future
                completed += 1
                if error is not None:
                    logger.warning(
                        "Namespace workload inventory fetch failed for %s: %s",
                        namespace,
                        error,
                    )
                elif namespace_rows:
                    all_rows.extend(namespace_rows)

                if on_namespace_loaded is not None:
                    with suppress(Exception):
                        callback_result: Any = on_namespace_loaded(
                            namespace,
                            namespace_rows,
                            completed,
                            total,
                        )
                        if inspect.isawaitable(callback_result):
                            await callback_result
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        pdb_selectors_by_namespace: dict[str, list[dict[str, str]]] = {}
        try:
            pdbs = await pdb_task
            pdb_selectors_by_namespace = self._build_pdb_selector_lookup(pdbs)
        except Exception as exc:
            logger.warning("Workload PDB coverage fetch failed: %s", exc)
        self._apply_workload_pdb_coverage(
            all_rows,
            pdb_selectors_by_namespace,
            template_labels_by_key,
        )

        return sorted(
            all_rows,
            key=lambda row: (row.namespace, row.kind, row.name),
        )

    async def _fetch_single_replica_incremental(
        self,
        on_namespace_loaded: Callable[
            [str, list[SingleReplicaWorkloadInfo], int, int],
            None,
        ]
        | None = None,
    ) -> list[SingleReplicaWorkloadInfo]:
        """Fetch single-replica workloads namespace-by-namespace."""
        namespaces = await self._list_cluster_namespaces()
        releases = (
            list(self._helm_releases_cache)
            if self._helm_releases_cache
            else await self._fetch_helm_releases_incremental()
        )
        helm_lookup = self._build_helm_release_lookup(releases)

        if not namespaces:
            workloads_output = await self._run_kubectl_cached(
                (
                    "get",
                    self._SINGLE_REPLICA_RESOURCE_QUERY,
                    "-A",
                    "-o",
                    "json",
                    f"--request-timeout={CLUSTER_REQUEST_TIMEOUT}",
                )
            )
            if not workloads_output:
                return []
            data = json.loads(workloads_output)
            result: list[SingleReplicaWorkloadInfo] = []
            for item in data.get("items", []):
                row = self._single_replica_from_workload(item, helm_lookup)
                if row is not None:
                    result.append(row)
            return result

        semaphore = asyncio.Semaphore(self._NAMESPACE_STREAM_MAX_CONCURRENT)
        total = len(namespaces)
        completed = 0
        all_workloads: list[SingleReplicaWorkloadInfo] = []

        async def _fetch_namespace(
            namespace: str,
        ) -> tuple[str, list[SingleReplicaWorkloadInfo], Exception | None]:
            async with semaphore:
                try:
                    output = await self._run_kubectl_cached(
                        (
                            "get",
                            self._SINGLE_REPLICA_RESOURCE_QUERY,
                            "-n",
                            namespace,
                            "-o",
                            "json",
                            f"--request-timeout={CLUSTER_REQUEST_TIMEOUT}",
                        )
                    )
                    if not output:
                        return namespace, [], None
                    data = json.loads(output)
                    namespace_rows: list[SingleReplicaWorkloadInfo] = []
                    for item in data.get("items", []):
                        row = self._single_replica_from_workload(item, helm_lookup)
                        if row is not None:
                            namespace_rows.append(row)
                    return namespace, namespace_rows, None
                except Exception as exc:
                    return namespace, [], exc

        tasks = [asyncio.create_task(_fetch_namespace(namespace)) for namespace in namespaces]
        try:
            for future in asyncio.as_completed(tasks):
                namespace, namespace_rows, error = await future
                completed += 1
                if error is not None:
                    logger.warning(
                        "Namespace single-replica fetch failed for %s: %s",
                        namespace,
                        error,
                    )
                elif namespace_rows:
                    all_workloads.extend(namespace_rows)
                if on_namespace_loaded is not None:
                    with suppress(Exception):
                        callback_result: Any = on_namespace_loaded(
                            namespace,
                            namespace_rows,
                            completed,
                            total,
                        )
                        if inspect.isawaitable(callback_result):
                            await callback_result
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        return all_workloads

    async def fetch_nodes(
        self,
        progress_callback: Callable[[str, int, int], None] | None = None,
        include_pod_resources: bool = True,
        on_node_update: Callable[[list[NodeInfo], int, int], None] | None = None,
    ) -> list[NodeInfo]:
        """Fetch and parse kubectl get nodes.

        Args:
            progress_callback: Optional callback for fetch progress updates.
            include_pod_resources: When True, enrich node metrics with pod-derived
                requests/limits/pod-count. Set False for fast inventory-only fetches.
        """
        self._update_fetch_state(self.SOURCE_NODES, FetchState.LOADING)

        try:
            semaphore = self.get_semaphore()
            await asyncio.wait_for(semaphore.acquire(), timeout=self._SEMAPHORE_ACQUIRE_TIMEOUT)

            try:
                self._notify_progress(progress_callback, self.SOURCE_NODES, 0, 1)
                if not include_pod_resources and self._nodes_cache:
                    nodes = [node.model_copy(deep=False) for node in self._nodes_cache]
                else:
                    nodes = await self._node_fetcher.fetch_nodes()
                if include_pod_resources:
                    try:
                        if self._pods_cache:
                            totals_by_node = await asyncio.to_thread(
                                self._build_node_resource_totals,
                                self._pods_cache,
                            )
                            self._apply_node_resource_totals(nodes, totals_by_node)
                        elif on_node_update is None:
                            pods = await self._pod_fetcher.fetch_pods(
                                request_timeout=self._NODE_POD_ENRICH_REQUEST_TIMEOUT
                            )
                            if pods:
                                self._pods_cache = list(pods)
                            totals_by_node = await asyncio.to_thread(
                                self._build_node_resource_totals,
                                pods,
                            )
                            self._apply_node_resource_totals(nodes, totals_by_node)
                        else:
                            aggregate_totals: dict[str, dict[str, float | int]] = {}
                            node_lookup = {node.name: node for node in nodes}

                            def _on_namespace_loaded(
                                _namespace: str,
                                namespace_pods: list[dict[str, Any]],
                                completed: int,
                                total: int,
                            ) -> None:
                                if namespace_pods:
                                    delta_totals = self._build_node_resource_totals(
                                        namespace_pods
                                    )
                                    self._merge_node_resource_totals(
                                        aggregate_totals,
                                        delta_totals,
                                    )
                                    self._apply_node_resource_totals_delta(
                                        node_lookup,
                                        aggregate_totals,
                                        set(delta_totals.keys()),
                                    )
                                if not self._should_emit_partial_update(
                                    completed,
                                    total,
                                ):
                                    return
                                with suppress(Exception):
                                    on_node_update(
                                        [node.model_copy(deep=False) for node in nodes],
                                        completed,
                                        total,
                                    )

                            await self._fetch_pods_incremental(
                                on_namespace_loaded=_on_namespace_loaded,
                                request_timeout=self._NODE_POD_ENRICH_REQUEST_TIMEOUT,
                            )
                    except Exception as exc:
                        logger.warning(
                            "Pod-based node enrichment failed; returning node inventory only: %s",
                            exc,
                        )
                self._nodes_cache = [node.model_copy(deep=False) for node in nodes]
                if on_node_update is not None and not include_pod_resources:
                    partial_nodes: list[NodeInfo] = []
                    total = len(nodes)
                    for index, node in enumerate(nodes, start=1):
                        partial_nodes.append(node.model_copy(deep=False))
                        with suppress(Exception):
                            on_node_update(partial_nodes, index, total)
                self._update_fetch_state(self.SOURCE_NODES, FetchState.SUCCESS)
                self._notify_progress(progress_callback, self.SOURCE_NODES, 1, 1)
                return nodes
            finally:
                semaphore.release()
        except asyncio.CancelledError:
            self._update_fetch_state(
                self.SOURCE_NODES, FetchState.ERROR, "Fetch cancelled"
            )
            raise
        except Exception:
            logger.exception("Error fetching nodes")
            self._update_fetch_state(
                self.SOURCE_NODES, FetchState.ERROR, "Error fetching nodes"
            )
            raise

    async def fetch_node_resources(
        self,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> list[NodeResourceInfo]:
        """Fetch detailed node resource analysis with allocation percentages."""
        self._update_fetch_state(self.SOURCE_NODE_RESOURCES, FetchState.LOADING)

        try:
            semaphore = self.get_semaphore()
            await asyncio.wait_for(semaphore.acquire(), timeout=self._SEMAPHORE_ACQUIRE_TIMEOUT)

            try:
                self._notify_progress(progress_callback, self.SOURCE_NODE_RESOURCES, 0, 1)

                # Fetch nodes and pods in parallel when cache is cold
                if self._pods_cache:
                    nodes_items, pods_data = await self._node_fetcher.fetch_nodes_raw(), self._pods_cache
                else:
                    nodes_items, pods_data = await asyncio.gather(
                        self._node_fetcher.fetch_nodes_raw(),
                        self._pod_fetcher.fetch_pods(),
                    )
                try:
                    if not self._pods_cache and pods_data:
                        self._pods_cache = list(pods_data)
                    totals_by_node = await asyncio.to_thread(
                        self._build_node_resource_totals,
                        pods_data,
                    )
                except Exception as exc:
                    logger.warning(
                        "Pod resource fetch failed for node resources; using zeroed resource totals: %s",
                        exc,
                    )
                    totals_by_node = {}

                # Calculate resource allocation per node
                resources = await asyncio.to_thread(
                    self._build_node_resources,
                    nodes_items,
                    totals_by_node,
                )

                self._update_fetch_state(self.SOURCE_NODE_RESOURCES, FetchState.SUCCESS)
                self._notify_progress(
                    progress_callback, self.SOURCE_NODE_RESOURCES, 1, 1
                )
                return resources
            finally:
                semaphore.release()
        except asyncio.CancelledError:
            self._update_fetch_state(
                self.SOURCE_NODE_RESOURCES, FetchState.ERROR, "Fetch cancelled"
            )
            raise
        except Exception:
            logger.exception("Error fetching node resources")
            self._update_fetch_state(
                self.SOURCE_NODE_RESOURCES,
                FetchState.ERROR,
                "Error fetching node resources",
            )
            raise

    def _build_node_resources(
        self,
        nodes_items: list[dict[str, Any]],
        totals_by_node: dict[str, dict[str, float | int]],
    ) -> list[NodeResourceInfo]:
        """Build node resource models off the event loop."""
        resources: list[NodeResourceInfo] = []
        for node in nodes_items:
            node_name = node.get("metadata", {}).get("name", "Unknown")
            totals = totals_by_node.get(
                node_name,
                {
                    "cpu_requests": 0.0,
                    "cpu_limits": 0.0,
                    "memory_requests": 0.0,
                    "memory_limits": 0.0,
                    "pod_count": 0,
                },
            )
            info = self._node_parser.parse_node_info(
                node,
                cpu_requests=float(totals["cpu_requests"]),
                memory_requests=float(totals["memory_requests"]),
                cpu_limits=float(totals["cpu_limits"]),
                memory_limits=float(totals["memory_limits"]),
                pod_count=int(totals["pod_count"]),
            )
            resources.append(info)
        return resources

    async def get_node_conditions_summary(self) -> dict[str, dict[str, int]]:
        """Analyze node conditions across all nodes."""
        nodes = await self.fetch_nodes(include_pod_resources=False)
        condition_types = [
            "Ready",
            "MemoryPressure",
            "DiskPressure",
            "PIDPressure",
            "NetworkUnavailable",
        ]
        conditions: dict[str, dict[str, int]] = {
            cond: {"True": 0, "False": 0, "Unknown": 0} for cond in condition_types
        }
        for node in nodes:
            for cond_type, status in node.conditions.items():
                if cond_type in conditions:
                    if status in conditions[cond_type]:
                        conditions[cond_type][status] += 1
                    else:
                        conditions[cond_type]["Unknown"] += 1
        return conditions

    async def get_node_taints_analysis(self) -> dict[str, Any]:
        """Analyze taints distribution across nodes."""
        nodes = await self.fetch_nodes(include_pod_resources=False)
        nodes_with_taints = 0
        taint_distribution: dict[str, dict[str, Any]] = {}
        for node in nodes:
            if node.taints:
                nodes_with_taints += 1
            for taint in node.taints:
                key = taint.get("key", "")
                effect = taint.get("effect", "Unknown")
                taint_key = f"{key}={taint.get('value', '')}" if key else effect
                if taint_key not in taint_distribution:
                    taint_distribution[taint_key] = {"effect": effect, "count": 0}
                taint_distribution[taint_key]["count"] += 1
        return {
            "total_nodes_with_taints": nodes_with_taints,
            "taint_distribution": taint_distribution,
        }

    async def get_kubelet_version_distribution(self) -> dict[str, int]:
        """Count nodes by kubelet version."""
        nodes = await self.fetch_nodes(include_pod_resources=False)
        version_counts: dict[str, int] = {}
        for node in nodes:
            version = node.kubelet_version.lstrip("v")
            if version:
                version_counts[version] = version_counts.get(version, 0) + 1
        return version_counts

    async def get_instance_type_distribution(self) -> dict[str, int]:
        """Count nodes by instance type."""
        nodes = await self.fetch_nodes(include_pod_resources=False)
        type_counts: dict[str, int] = {}
        for node in nodes:
            if node.instance_type:
                type_counts[node.instance_type] = type_counts.get(node.instance_type, 0) + 1
        return type_counts

    async def get_az_distribution(self) -> dict[str, int]:
        """Count nodes by availability zone."""
        nodes = await self.fetch_nodes(include_pod_resources=False)
        az_counts: dict[str, int] = {}
        for node in nodes:
            if node.availability_zone:
                az_counts[node.availability_zone] = az_counts.get(node.availability_zone, 0) + 1
        return az_counts

    async def get_node_groups_az_matrix(self) -> dict[str, dict[str, int]]:
        """Cross-tabulation of node groups by availability zone."""
        nodes = await self.fetch_nodes(include_pod_resources=False)
        matrix: dict[str, dict[str, int]] = {}
        for node in nodes:
            ng = node.node_group
            az = node.availability_zone
            if ng not in matrix:
                matrix[ng] = {}
            matrix[ng][az] = matrix[ng].get(az, 0) + 1
        return matrix

    async def get_allocated_analysis(
        self, include_pod_resources: bool = True
    ) -> dict[str, Any]:
        """Calculate CPU/Memory allocation percentages per node group.

        Args:
            include_pod_resources: When False, performs a fast inventory-only
                analysis (group counts and allocatable capacity without pod-derived
                request/limit enrichment).
        """
        nodes = await self.fetch_nodes(include_pod_resources=include_pod_resources)
        node_groups: dict[str, dict[str, Any]] = {}
        for node in nodes:
            ng = node.node_group
            if ng not in node_groups:
                node_groups[ng] = {
                    "cpu_allocatable": 0.0,
                    "memory_allocatable": 0.0,
                    "cpu_requests": 0.0,
                    "memory_requests": 0.0,
                    "node_count": 0,
                }
            node_groups[ng]["cpu_allocatable"] += node.cpu_allocatable
            node_groups[ng]["memory_allocatable"] += node.memory_allocatable
            node_groups[ng]["cpu_requests"] += node.cpu_requests
            node_groups[ng]["memory_requests"] += node.memory_requests
            node_groups[ng]["node_count"] += 1

        result: dict[str, dict[str, Any]] = {}
        for ng, totals in node_groups.items():
            cpu_pct = (
                (totals["cpu_requests"] / totals["cpu_allocatable"] * 100)
                if totals["cpu_allocatable"] > 0
                else 0.0
            )
            mem_pct = (
                (totals["memory_requests"] / totals["memory_allocatable"] * 100)
                if totals["memory_allocatable"] > 0
                else 0.0
            )
            result[ng] = {
                "cpu_allocatable": totals["cpu_allocatable"],
                "memory_allocatable": totals["memory_allocatable"],
                "cpu_requests": totals["cpu_requests"],
                "memory_requests": totals["memory_requests"],
                "cpu_pct": cpu_pct,
                "memory_pct": mem_pct,
                "node_count": totals["node_count"],
            }
        return result

    async def get_high_pod_count_nodes(
        self, threshold_pct: float = 80.0
    ) -> list[dict[str, Any]]:
        """Identify nodes approaching pod capacity."""
        nodes = await self.fetch_nodes()
        high_pod_nodes: list[dict[str, Any]] = []
        for node in nodes:
            pod_pct = (node.pod_count / node.pod_capacity * 100) if node.pod_capacity > 0 else 0.0
            if pod_pct >= threshold_pct:
                high_pod_nodes.append({
                    "name": node.name,
                    "node_group": node.node_group,
                    "pod_count": node.pod_count,
                    "max_pods": node.pod_capacity,
                    "pod_pct": pod_pct,
                })
        high_pod_nodes.sort(key=lambda x: x["pod_pct"], reverse=True)
        return high_pod_nodes

    async def fetch_pod_distribution(
        self,
        progress_callback: Callable[[str, int, int], None] | None = None,
        on_namespace_update: Callable[[PodDistributionInfo, int, int], None]
        | None = None,
        request_timeout: str | None = None,
    ) -> PodDistributionInfo:
        """Analyze pod distribution across nodes and node groups."""
        self._update_fetch_state(self.SOURCE_POD_DISTRIBUTION, FetchState.LOADING)

        try:
            semaphore = self.get_semaphore()
            await asyncio.wait_for(semaphore.acquire(), timeout=self._SEMAPHORE_ACQUIRE_TIMEOUT)

            try:
                self._notify_progress(
                    progress_callback, self.SOURCE_POD_DISTRIBUTION, 0, 1
                )

                nodes_items = await self._node_fetcher.fetch_nodes_raw()
                if self._pods_cache:
                    pods = list(self._pods_cache)
                    if on_namespace_update is not None:
                        with suppress(Exception):
                            partial_distribution = self._pod_parser.parse_distribution(
                                nodes_items,
                                pods,
                            )
                            on_namespace_update(partial_distribution, 1, 1)
                else:
                    partial_pods: list[dict[str, Any]] = []

                    async def _on_namespace_loaded(
                        _namespace: str,
                        namespace_pods: list[dict[str, Any]],
                        completed: int,
                        total: int,
                    ) -> None:
                        if namespace_pods:
                            partial_pods.extend(namespace_pods)
                        if on_namespace_update is None:
                            return
                        if not self._should_emit_partial_update(completed, total):
                            return
                        with suppress(Exception):
                            partial_distribution = await asyncio.to_thread(
                                self._pod_parser.parse_distribution,
                                nodes_items,
                                list(partial_pods),
                            )
                            on_namespace_update(partial_distribution, completed, total)

                    pods = await self._fetch_pods_incremental(
                        on_namespace_loaded=_on_namespace_loaded
                        if on_namespace_update is not None
                        else None,
                        request_timeout=request_timeout,
                    )
                distribution = await asyncio.to_thread(
                    self._pod_parser.parse_distribution,
                    nodes_items,
                    pods,
                )

                self._update_fetch_state(
                    self.SOURCE_POD_DISTRIBUTION, FetchState.SUCCESS
                )
                self._notify_progress(
                    progress_callback, self.SOURCE_POD_DISTRIBUTION, 1, 1
                )
                return distribution
            finally:
                semaphore.release()
        except asyncio.CancelledError:
            self._update_fetch_state(
                self.SOURCE_POD_DISTRIBUTION, FetchState.ERROR, "Fetch cancelled"
            )
            raise
        except Exception:
            logger.exception("Error fetching pod distribution")
            self._update_fetch_state(
                self.SOURCE_POD_DISTRIBUTION,
                FetchState.ERROR,
                "Error fetching pod distribution",
            )
            raise

    async def fetch_workload_inventory(
        self,
        on_namespace_update: Callable[
            [list[WorkloadInventoryInfo], int, int],
            None,
        ]
        | None = None,
        *,
        enrich_runtime_stats: bool = False,
    ) -> list[WorkloadInventoryInfo]:
        """Fetch runtime Kubernetes workload inventory."""
        self._nonfatal_warnings = {}
        semaphore = self.get_semaphore()
        await asyncio.wait_for(semaphore.acquire(), timeout=self._SEMAPHORE_ACQUIRE_TIMEOUT)
        prefetch_task: asyncio.Task[tuple[Any, Any, Any, Any]] | None = None
        runtime_lookups_task: asyncio.Task[Any] | None = None

        try:
            if enrich_runtime_stats:
                prefetch_task = asyncio.create_task(
                    self._prefetch_workload_runtime_stats_inputs()
                )

            if on_namespace_update is None:
                rows = await self._fetch_workload_inventory_incremental()
                if not enrich_runtime_stats:
                    return rows
                self._runtime_enrichment_prefetch_task = prefetch_task
                try:
                    return await self.enrich_workload_runtime_stats(rows)
                finally:
                    if self._runtime_enrichment_prefetch_task is prefetch_task:
                        self._runtime_enrichment_prefetch_task = None

            partial_rows: list[WorkloadInventoryInfo] = []
            emitted_first_callback = False
            partial_emit_step = 1
            last_completed = 0
            last_total = 0
            runtime_lookups: tuple[
                dict[tuple[str, str, str], list[dict[str, Any]]],
                dict[str, dict[str, float]],
                dict[str, dict[str, float | str]],
                dict[str, dict[str, float]],
                dict[tuple[str, str], dict[str, float]],
            ] | None = None
            runtime_rows_backfilled = False

            async def _build_stream_runtime_lookups() -> (
                tuple[
                    dict[tuple[str, str, str], list[dict[str, Any]]],
                    dict[str, dict[str, float]],
                    dict[str, dict[str, float | str]],
                    dict[str, dict[str, float]],
                    dict[tuple[str, str], dict[str, float]],
                ]
                | None
            ):
                if prefetch_task is None:
                    return None
                try:
                    (
                        pods_result,
                        nodes_result,
                        top_nodes_result,
                        top_pods_result,
                    ) = await prefetch_task
                except Exception as exc:
                    logger.warning(
                        "Unable to prepare runtime lookups for streamed workload enrichment: %s",
                        exc,
                    )
                    return None

                pods: list[dict[str, Any]] = []
                nodes_items: list[dict[str, Any]] = []
                top_nodes_rows: list[dict[str, Any]] = []
                top_pods_rows: list[dict[str, Any]] = []

                if isinstance(pods_result, Exception):
                    logger.warning(
                        "Unable to fetch pods for streamed workload enrichment: %s",
                        pods_result,
                    )
                elif isinstance(pods_result, list):
                    pods = pods_result
                    if pods:
                        self._pods_cache = list(pods)

                if isinstance(nodes_result, Exception):
                    logger.warning(
                        "Unable to fetch nodes for streamed workload enrichment: %s",
                        nodes_result,
                    )
                elif isinstance(nodes_result, list):
                    nodes_items = nodes_result

                if isinstance(top_nodes_result, Exception):
                    logger.warning(
                        "Unable to fetch top node metrics for streamed workload enrichment: %s",
                        top_nodes_result,
                    )
                    self._record_nonfatal_warning("top_nodes", top_nodes_result)
                elif isinstance(top_nodes_result, list):
                    top_nodes_rows = top_nodes_result

                if isinstance(top_pods_result, Exception):
                    logger.warning(
                        "Unable to fetch top pod metrics for streamed workload enrichment: %s",
                        top_pods_result,
                    )
                    self._record_nonfatal_warning("top_pods", top_pods_result)
                elif isinstance(top_pods_result, list):
                    top_pods_rows = top_pods_result

                if not pods:
                    return None

                node_utilization_by_name = await self._build_node_utilization_lookup_for_pods(
                    pods,
                    nodes_items=nodes_items,
                )
                return (
                    self._build_workload_pod_lookup(pods),
                    node_utilization_by_name,
                    self._build_node_allocatable_lookup(nodes_items)
                    if nodes_items
                    else {},
                    self._build_top_node_usage_lookup(top_nodes_rows),
                    self._build_top_pod_usage_lookup(top_pods_rows),
                )

            if enrich_runtime_stats:
                runtime_lookups_task = asyncio.create_task(_build_stream_runtime_lookups())

            def _on_namespace_loaded(
                _namespace: str,
                namespace_rows: list[WorkloadInventoryInfo],
                completed: int,
                total: int,
            ) -> None:
                nonlocal emitted_first_callback
                nonlocal partial_emit_step
                nonlocal last_completed
                nonlocal last_total
                nonlocal runtime_lookups
                nonlocal runtime_rows_backfilled
                last_completed = completed
                last_total = total
                if total > 0:
                    partial_emit_step = 1 if total <= 5 else 5
                row_count_before = len(partial_rows)
                if namespace_rows:
                    partial_rows.extend(namespace_rows)
                has_new_rows = len(partial_rows) > row_count_before
                runtime_metrics_updated = False
                if (
                    runtime_lookups is None
                    and runtime_lookups_task is not None
                    and runtime_lookups_task.done()
                ):
                    with suppress(Exception):
                        runtime_lookups = runtime_lookups_task.result()
                if runtime_lookups is not None:
                    (
                        workload_pods,
                        node_utilization_by_name,
                        node_allocatable_by_name,
                        top_node_usage_by_name,
                        top_pod_usage_by_key,
                    ) = runtime_lookups

                    if not runtime_rows_backfilled and partial_rows:
                        self._apply_workload_runtime_stats_with_lookup(
                            partial_rows,
                            workload_pods,
                            node_utilization_by_name,
                            node_allocatable_by_name=node_allocatable_by_name,
                            top_node_usage_by_name=top_node_usage_by_name,
                            top_pod_usage_by_key=top_pod_usage_by_key,
                        )
                        runtime_rows_backfilled = True
                        runtime_metrics_updated = True
                    elif namespace_rows:
                        self._apply_workload_runtime_stats_with_lookup(
                            namespace_rows,
                            workload_pods,
                            node_utilization_by_name,
                            node_allocatable_by_name=node_allocatable_by_name,
                            top_node_usage_by_name=top_node_usage_by_name,
                            top_pod_usage_by_key=top_pod_usage_by_key,
                        )
                        self._apply_aggressive_pod_markers(partial_rows)
                        runtime_metrics_updated = True

                # Emit first namespace callback immediately so UI tables can start
                # streaming rows, emit each time new rows are discovered, and emit
                # when runtime metrics arrive for already-streamed rows.
                should_emit = (
                    (not emitted_first_callback and completed == 1)
                    or has_new_rows
                    or completed >= total
                    or completed % partial_emit_step == 0
                    or runtime_metrics_updated
                )
                if not should_emit:
                    return
                with suppress(Exception):
                    sorted_rows = sorted(
                        partial_rows,
                        key=lambda row: (row.namespace, row.kind, row.name),
                    )
                    on_namespace_update(sorted_rows, completed, total)
                    if completed == 1:
                        emitted_first_callback = True

            rows = await self._fetch_workload_inventory_incremental(
                on_namespace_loaded=_on_namespace_loaded
            )
            if not enrich_runtime_stats:
                return rows

            self._runtime_enrichment_prefetch_task = prefetch_task
            try:
                enriched_rows = await self.enrich_workload_runtime_stats(rows)
            finally:
                if self._runtime_enrichment_prefetch_task is prefetch_task:
                    self._runtime_enrichment_prefetch_task = None
            with suppress(Exception):
                completed = last_completed if last_completed > 0 else 1
                total = last_total if last_total > 0 else completed
                on_namespace_update(
                    sorted(
                        enriched_rows,
                        key=lambda row: (row.namespace, row.kind, row.name),
                    ),
                    completed,
                    total,
                )
            return enriched_rows
        finally:
            if runtime_lookups_task is not None and not runtime_lookups_task.done():
                runtime_lookups_task.cancel()
                await asyncio.gather(runtime_lookups_task, return_exceptions=True)
            if prefetch_task is not None and not prefetch_task.done():
                prefetch_task.cancel()
                await asyncio.gather(prefetch_task, return_exceptions=True)
            semaphore.release()

    async def fetch_single_replica_workloads(
        self,
        on_namespace_update: Callable[
            [list[SingleReplicaWorkloadInfo], int, int],
            None,
        ]
        | None = None,
    ) -> list[SingleReplicaWorkloadInfo]:
        """Find workloads with only 1 replica (no HA)."""
        semaphore = self.get_semaphore()
        await asyncio.wait_for(semaphore.acquire(), timeout=self._SEMAPHORE_ACQUIRE_TIMEOUT)

        try:
            if on_namespace_update is None:
                return await self._fetch_single_replica_incremental()

            partial_rows: list[SingleReplicaWorkloadInfo] = []

            def _on_namespace_loaded(
                _namespace: str,
                namespace_rows: list[SingleReplicaWorkloadInfo],
                completed: int,
                total: int,
            ) -> None:
                if namespace_rows:
                    partial_rows.extend(namespace_rows)
                if not self._should_emit_partial_update(completed, total):
                    return
                with suppress(Exception):
                    on_namespace_update(partial_rows, completed, total)

            return await self._fetch_single_replica_incremental(
                on_namespace_loaded=_on_namespace_loaded
            )
        finally:
            semaphore.release()

    async def get_pod_request_stats(
        self,
        on_namespace_update: Callable[[dict[str, Any], int, int], None] | None = None,
        request_timeout: str | None = None,
    ) -> dict[str, Any]:
        """Calculate Min/Avg/Max/P95 CPU and Memory requests per node."""
        if self._pods_cache:
            stats = await asyncio.to_thread(
                self._pod_parser.parse_pod_requests,
                self._pods_cache,
            )
            if on_namespace_update is not None:
                with suppress(Exception):
                    on_namespace_update(stats, 1, 1)
            return stats

        partial_pods: list[dict[str, Any]] = []

        async def _on_namespace_loaded(
            _namespace: str,
            namespace_pods: list[dict[str, Any]],
            completed: int,
            total: int,
        ) -> None:
            if namespace_pods:
                partial_pods.extend(namespace_pods)
            if on_namespace_update is None:
                return
            if not self._should_emit_partial_update(completed, total):
                return
            with suppress(Exception):
                partial_stats = await asyncio.to_thread(
                    self._pod_parser.parse_pod_requests,
                    list(partial_pods),
                )
                on_namespace_update(partial_stats, completed, total)

        pods = await self._fetch_pods_incremental(
            on_namespace_loaded=_on_namespace_loaded
            if on_namespace_update is not None
            else None,
            request_timeout=request_timeout,
        )
        return await asyncio.to_thread(
            self._pod_parser.parse_pod_requests,
            pods,
        )

    async def fetch_events(
        self,
        max_age_hours: float = _DEFAULT_EVENT_WINDOW_HOURS,
        progress_callback: Callable[[str, int, int], None] | None = None,
        on_namespace_update: Callable[[dict[str, int], int, int], None] | None = None,
        request_timeout: str | None = None,
    ) -> dict[str, int]:
        """Fetch and analyze cluster events."""
        self._update_fetch_state(self.SOURCE_EVENTS, FetchState.LOADING)

        try:
            semaphore = self.get_semaphore()
            await asyncio.wait_for(semaphore.acquire(), timeout=self._SEMAPHORE_ACQUIRE_TIMEOUT)

            try:
                self._notify_progress(progress_callback, self.SOURCE_EVENTS, 0, 1)
                if self._warning_events_cache_ready:
                    events = list(self._warning_events_cache)
                    summary = await asyncio.to_thread(
                        self._event_parser.parse_events_summary,
                        events,
                        max_age_hours,
                    )
                    events_summary = self._event_counts_from_summary(summary)
                    if on_namespace_update is not None:
                        with suppress(Exception):
                            on_namespace_update(events_summary, 1, 1)
                else:
                    partial_events: list[dict[str, Any]] = []

                    async def _on_namespace_loaded(
                        _namespace: str,
                        namespace_events: list[dict[str, Any]],
                        completed: int,
                        total: int,
                    ) -> None:
                        if namespace_events:
                            partial_events.extend(namespace_events)
                        if on_namespace_update is None:
                            return
                        if not self._should_emit_partial_update(completed, total):
                            return
                        with suppress(Exception):
                            partial_summary = await asyncio.to_thread(
                                self._event_parser.parse_events_summary,
                                list(partial_events),
                                max_age_hours,
                            )
                            on_namespace_update(
                                self._event_counts_from_summary(partial_summary),
                                completed,
                                total,
                            )

                    events = await self._fetch_warning_events_incremental(
                        on_namespace_loaded=_on_namespace_loaded
                        if on_namespace_update is not None
                        else None,
                        request_timeout=request_timeout,
                    )
                    summary = await asyncio.to_thread(
                        self._event_parser.parse_events_summary,
                        events,
                        max_age_hours,
                    )
                    events_summary = self._event_counts_from_summary(summary)
                self._update_fetch_state(self.SOURCE_EVENTS, FetchState.SUCCESS)
                self._notify_progress(progress_callback, self.SOURCE_EVENTS, 1, 1)
                return events_summary
            finally:
                semaphore.release()
        except asyncio.CancelledError:
            self._update_fetch_state(
                self.SOURCE_EVENTS, FetchState.ERROR, "Fetch cancelled"
            )
            raise
        except Exception:
            logger.exception("Error fetching events")
            self._update_fetch_state(
                self.SOURCE_EVENTS, FetchState.ERROR, "Error fetching events"
            )
            raise

    async def get_event_summary(
        self,
        max_age_hours: float = _DEFAULT_EVENT_WINDOW_HOURS,
        max_recent_events: int = 20,
        on_namespace_update: Callable[[EventSummary, int, int], None] | None = None,
        request_timeout: str | None = None,
    ) -> EventSummary:
        """Get comprehensive event analysis summary.

        Args:
            max_age_hours: Only include events newer than this.
            max_recent_events: Maximum number of recent events to include.
        """
        if self._warning_events_cache_ready:
            events = list(self._warning_events_cache)
            summary = await asyncio.to_thread(
                self._event_parser.parse_events_summary,
                events,
                max_age_hours,
                max_recent_events,
            )
            if on_namespace_update is not None:
                with suppress(Exception):
                    on_namespace_update(summary, 1, 1)
            return summary

        partial_events: list[dict[str, Any]] = []

        async def _on_namespace_loaded(
            _namespace: str,
            namespace_events: list[dict[str, Any]],
            completed: int,
            total: int,
        ) -> None:
            if namespace_events:
                partial_events.extend(namespace_events)
            if on_namespace_update is None:
                return
            if not self._should_emit_partial_update(completed, total):
                return
            with suppress(Exception):
                partial_summary = await asyncio.to_thread(
                    self._event_parser.parse_events_summary,
                    list(partial_events),
                    max_age_hours,
                    max_recent_events,
                )
                on_namespace_update(partial_summary, completed, total)

        events = await self._fetch_warning_events_incremental(
            on_namespace_loaded=_on_namespace_loaded
            if on_namespace_update is not None
            else None,
            request_timeout=request_timeout,
        )

        if not events:
            return EventSummary(
                total_count=0, oom_count=0, node_not_ready_count=0,
                failed_scheduling_count=0, backoff_count=0, unhealthy_count=0,
                failed_mount_count=0, evicted_count=0, completed_count=0,
                normal_count=0, recent_events=[], max_age_hours=max_age_hours,
                desired_healthy=0,
            )
        return await asyncio.to_thread(
            self._event_parser.parse_events_summary,
            events,
            max_age_hours,
            max_recent_events,
        )

    async def get_critical_events(
        self,
        max_age_hours: float = _DEFAULT_EVENT_WINDOW_HOURS,
        limit: int = 50,
        on_namespace_update: Callable[[list[EventDetail], int, int], None] | None = None,
        request_timeout: str | None = None,
    ) -> list[EventDetail]:
        """Get recent critical events with full details."""
        if self._warning_events_cache_ready:
            events = list(self._warning_events_cache)
            critical_events = await asyncio.to_thread(
                self._event_parser.parse_critical_events,
                events,
                max_age_hours,
                limit,
            )
            if on_namespace_update is not None:
                with suppress(Exception):
                    on_namespace_update(critical_events, 1, 1)
            return critical_events

        partial_events: list[dict[str, Any]] = []

        async def _on_namespace_loaded(
            _namespace: str,
            namespace_events: list[dict[str, Any]],
            completed: int,
            total: int,
        ) -> None:
            if namespace_events:
                partial_events.extend(namespace_events)
            if on_namespace_update is None:
                return
            if not self._should_emit_partial_update(completed, total):
                return
            with suppress(Exception):
                partial_critical = await asyncio.to_thread(
                    self._event_parser.parse_critical_events,
                    list(partial_events),
                    max_age_hours,
                    limit,
                )
                on_namespace_update(partial_critical, completed, total)

        events = await self._fetch_warning_events_incremental(
            on_namespace_loaded=_on_namespace_loaded
            if on_namespace_update is not None
            else None,
            request_timeout=request_timeout,
        )
        return await asyncio.to_thread(
            self._event_parser.parse_critical_events,
            events,
            max_age_hours,
            limit,
        )

    async def fetch_pdbs(
        self,
        progress_callback: Callable[[str, int, int], None] | None = None,
        on_namespace_update: Callable[[list[PDBInfo], int, int], None] | None = None,
    ) -> list[PDBInfo]:
        """Fetch PodDisruptionBudgets."""
        self._update_fetch_state(self.SOURCE_PDBS, FetchState.LOADING)

        try:
            semaphore = self.get_semaphore()
            await asyncio.wait_for(semaphore.acquire(), timeout=self._SEMAPHORE_ACQUIRE_TIMEOUT)

            try:
                self._notify_progress(
                    progress_callback, self.SOURCE_PDBS, 0, 1
                )

                if on_namespace_update is None:
                    result = await self._fetch_pdbs_incremental()
                else:
                    partial_rows: list[PDBInfo] = []

                    def _on_namespace_loaded(
                        _namespace: str,
                        namespace_rows: list[PDBInfo],
                        completed: int,
                        total: int,
                    ) -> None:
                        if namespace_rows:
                            partial_rows.extend(namespace_rows)
                        if not self._should_emit_partial_update(completed, total):
                            return
                        with suppress(Exception):
                            on_namespace_update(partial_rows, completed, total)

                    result = await self._fetch_pdbs_incremental(
                        on_namespace_loaded=_on_namespace_loaded
                    )

                self._update_fetch_state(self.SOURCE_PDBS, FetchState.SUCCESS)
                self._notify_progress(
                    progress_callback, self.SOURCE_PDBS, 1, 1
                )
                return result
            finally:
                semaphore.release()
        except asyncio.CancelledError:
            self._update_fetch_state(
                self.SOURCE_PDBS, FetchState.ERROR, "Fetch cancelled"
            )
            raise
        except Exception:
            logger.exception("Error fetching PDBs")
            self._update_fetch_state(
                self.SOURCE_PDBS, FetchState.ERROR, "Error fetching PDBs"
            )
            raise

    async def check_cluster_connection(
        self,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> bool:
        """Check if cluster connection is working."""
        try:
            self._update_fetch_state(self.SOURCE_CLUSTER_CONNECTION, FetchState.LOADING)
            self._notify_progress(
                progress_callback, self.SOURCE_CLUSTER_CONNECTION, 0, 1
            )

            try:
                is_connected = await self._cluster_fetcher.check_cluster_connection()
                if is_connected:
                    self._update_fetch_state(
                        self.SOURCE_CLUSTER_CONNECTION, FetchState.SUCCESS
                    )
                else:
                    self._update_fetch_state(
                        self.SOURCE_CLUSTER_CONNECTION,
                        FetchState.ERROR,
                        "Cluster connection failed",
                    )
                self._notify_progress(
                    progress_callback, self.SOURCE_CLUSTER_CONNECTION, 1, 1
                )
                return is_connected
            except (OSError, subprocess.TimeoutExpired) as e:
                self._update_fetch_state(
                    self.SOURCE_CLUSTER_CONNECTION,
                    FetchState.ERROR,
                    self._summarize_connection_error(e),
                )
                return False
            except Exception as e:
                self._update_fetch_state(
                    self.SOURCE_CLUSTER_CONNECTION,
                    FetchState.ERROR,
                    self._summarize_connection_error(e),
                )
                return False
        except asyncio.CancelledError:
            self._update_fetch_state(
                self.SOURCE_CLUSTER_CONNECTION, FetchState.ERROR, "Fetch cancelled"
            )
            raise

    async def get_helm_releases(
        self,
        progress_callback: Callable[[str, int, int], None] | None = None,
        on_namespace_update: Callable[[list[HelmReleaseInfo], int, int], None] | None = None,
    ) -> list[HelmReleaseInfo]:
        """Get list of Helm releases from the cluster."""
        semaphore = self.get_semaphore()
        await asyncio.wait_for(semaphore.acquire(), timeout=self._SEMAPHORE_ACQUIRE_TIMEOUT)

        try:
            self._update_fetch_state(self.SOURCE_HELM_RELEASES, FetchState.LOADING)
            self._notify_progress(progress_callback, self.SOURCE_HELM_RELEASES, 0, 1)

            try:
                if on_namespace_update is None:
                    releases = await self._fetch_helm_releases_incremental()
                else:
                    partial_releases: list[HelmReleaseInfo] = []

                    def _on_namespace_loaded(
                        _namespace: str,
                        namespace_releases: list[HelmReleaseInfo],
                        completed: int,
                        total: int,
                    ) -> None:
                        if namespace_releases:
                            partial_releases.extend(namespace_releases)
                        if not self._should_emit_partial_update(completed, total):
                            return
                        with suppress(Exception):
                            on_namespace_update(partial_releases, completed, total)

                    releases = await self._fetch_helm_releases_incremental(
                        on_namespace_loaded=_on_namespace_loaded
                    )
                self._update_fetch_state(self.SOURCE_HELM_RELEASES, FetchState.SUCCESS)
                self._notify_progress(progress_callback, self.SOURCE_HELM_RELEASES, 1, 1)
                return releases
            except Exception:
                logger.exception("Error fetching Helm releases")
                self._update_fetch_state(
                    self.SOURCE_HELM_RELEASES,
                    FetchState.ERROR,
                    "Error fetching Helm releases",
                )
                return []
        finally:
            semaphore.release()
