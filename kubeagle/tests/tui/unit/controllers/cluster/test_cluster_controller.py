"""Tests for cluster controller."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from kubeagle.constants.enums import FetchState, NodeStatus
from kubeagle.controllers.cluster.controller import (
    ClusterController,
    FetchStatus,
)
from kubeagle.models.charts.chart_info import HelmReleaseInfo
from kubeagle.models.core.node_info import NodeInfo
from kubeagle.models.core.workload_inventory_info import WorkloadInventoryInfo
from kubeagle.models.pdb.pdb_info import PDBInfo


class TestFetchStatus:
    """Tests for FetchStatus dataclass."""

    def test_fetch_status_init(self) -> None:
        """Test FetchStatus initialization."""
        status = FetchStatus(
            source_name="nodes",
            state=FetchState.SUCCESS,
            error_message=None,
            last_updated=datetime.now(timezone.utc),
        )
        assert status.source_name == "nodes"
        assert status.state == FetchState.SUCCESS

    def test_fetch_status_to_dict(self) -> None:
        """Test FetchStatus.to_dict method."""
        now = datetime.now(timezone.utc)
        status = FetchStatus(
            source_name="events",
            state=FetchState.ERROR,
            error_message="Connection failed",
            last_updated=now,
        )

        result = status.to_dict()

        assert result["source_name"] == "events"
        assert result["state"] == "error"
        assert result["error_message"] == "Connection failed"
        assert result["last_updated"] == now.isoformat()


class TestClusterController:
    """Tests for ClusterController class."""

    @pytest.fixture
    def controller(self) -> ClusterController:
        """Create ClusterController instance."""
        return ClusterController(context="my-cluster")

    def test_controller_init(self, controller: ClusterController) -> None:
        """Test ClusterController initialization."""
        assert controller.context == "my-cluster"
        assert controller._fetch_states is not None
        assert len(controller._fetch_states) > 0

    def test_controller_init_no_context(self) -> None:
        """Test ClusterController without context."""
        controller = ClusterController()
        assert controller.context is None

    def test_initialize_fetch_states(self, controller: ClusterController) -> None:
        """Test _initialize_fetch_states creates all sources."""
        sources = list(controller._fetch_states.keys())

        assert controller.SOURCE_NODES in sources
        assert controller.SOURCE_EVENTS in sources
        assert controller.SOURCE_PDBS in sources
        assert controller.SOURCE_HELM_RELEASES in sources
        assert controller.SOURCE_NODE_RESOURCES in sources
        assert controller.SOURCE_POD_DISTRIBUTION in sources
        assert controller.SOURCE_CLUSTER_CONNECTION in sources

    def test_update_fetch_state(self, controller: ClusterController) -> None:
        """Test _update_fetch_state updates state correctly."""
        controller._update_fetch_state(
            controller.SOURCE_NODES, FetchState.ERROR, "Test error"
        )

        status = controller._fetch_states[controller.SOURCE_NODES]
        assert status.state == FetchState.ERROR
        assert status.error_message == "Test error"

    def test_get_fetch_state(self, controller: ClusterController) -> None:
        """Test get_fetch_state returns correct status."""
        result = controller.get_fetch_state(controller.SOURCE_NODES)

        assert result is not None
        assert result.source_name == controller.SOURCE_NODES

    def test_get_fetch_state_nonexistent(self, controller: ClusterController) -> None:
        """Test get_fetch_state returns None for nonexistent source."""
        result = controller.get_fetch_state("nonexistent")
        assert result is None

    def test_get_all_fetch_states(self, controller: ClusterController) -> None:
        """Test get_all_fetch_states returns copy."""
        result = controller.get_all_fetch_states()

        assert isinstance(result, dict)
        assert len(result) > 0

    def test_get_loading_sources(self, controller: ClusterController) -> None:
        """Test get_loading_sources returns sources in loading state."""
        # Set one source to loading
        controller._fetch_states[controller.SOURCE_NODES].state = FetchState.LOADING

        result = controller.get_loading_sources()

        assert controller.SOURCE_NODES in result

    def test_get_error_sources(self, controller: ClusterController) -> None:
        """Test get_error_sources returns sources with errors."""
        # Set one source to error
        controller._update_fetch_state(controller.SOURCE_NODES, FetchState.ERROR, "Error")

        result = controller.get_error_sources()

        assert controller.SOURCE_NODES in result

    def test_reset_fetch_state(self, controller: ClusterController) -> None:
        """Test reset_fetch_state resets state to loading."""
        controller._update_fetch_state(
            controller.SOURCE_NODES, FetchState.SUCCESS, None
        )

        result = controller.reset_fetch_state(controller.SOURCE_NODES)

        assert result is True
        assert controller._fetch_states[controller.SOURCE_NODES].state == FetchState.LOADING
        assert controller._fetch_states[controller.SOURCE_NODES].error_message is None

    def test_reset_fetch_state_nonexistent(self, controller: ClusterController) -> None:
        """Test reset_fetch_state returns False for nonexistent source."""
        result = controller.reset_fetch_state("nonexistent")
        assert result is False

    def test_is_any_loading_true(self, controller: ClusterController) -> None:
        """Test is_any_loading returns True when any source is loading."""
        controller._fetch_states[controller.SOURCE_NODES].state = FetchState.LOADING

        result = controller.is_any_loading()

        assert result is True

    def test_is_any_loading_false(self, controller: ClusterController) -> None:
        """Test is_any_loading returns False when no source is loading."""
        result = controller.is_any_loading()

        assert result is False

    def test_is_all_success_true(self, controller: ClusterController) -> None:
        """Test is_all_success returns True when all sources succeeded."""
        result = controller.is_all_success()

        assert result is True

    def test_semaphore_class_methods(self) -> None:
        """Test class semaphore methods."""
        # Reset semaphore
        ClusterController.reset_semaphore()

        semaphore = ClusterController.get_semaphore()
        assert semaphore._value == 3  # Default value

        # Change max concurrent
        ClusterController.set_max_concurrent(5)
        semaphore = ClusterController.get_semaphore()
        assert semaphore._value == 5

        # Reset for other tests
        ClusterController.reset_semaphore()

    def test_kubectl_timeout_for_pods_query_balances_speed_and_reliability(
        self,
        controller: ClusterController,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pod inventory query should receive extended process timeout budget."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        timeout_seconds = controller._kubectl_timeout_for_args(
            (
                "get",
                "pods",
                "-A",
                "-o",
                "json",
                "--request-timeout=30s",
            )
        )

        assert timeout_seconds == 70

    def test_kubectl_timeout_for_warning_events_query_is_extended(
        self,
        controller: ClusterController,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Warning events query should use longer timeout budget than default."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        timeout_seconds = controller._kubectl_timeout_for_args(
            (
                "get",
                "events",
                "--all-namespaces",
                "--field-selector=type=Warning",
                "-o",
                "json",
                "--request-timeout=30s",
            )
        )

        assert timeout_seconds == 60

    def test_kubectl_timeout_for_warning_events_retry_budget(
        self,
        controller: ClusterController,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Warning events retry timeout should get the long-process budget."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        timeout_seconds = controller._kubectl_timeout_for_args(
            (
                "get",
                "events",
                "--all-namespaces",
                "--field-selector=type=Warning",
                "-o",
                "json",
                "--request-timeout=45s",
            )
        )

        assert timeout_seconds == 90

    @pytest.mark.asyncio
    async def test_acquire_slot(self, controller: ClusterController) -> None:
        """Test acquire_slot acquires semaphore."""
        # Reset for clean test
        ClusterController.reset_semaphore()

        result = await controller.acquire_slot("test")

        assert result is True

        # Cleanup
        ClusterController.release_slot()
        ClusterController.reset_semaphore()

    @pytest.mark.asyncio
    async def test_release_slot(self, controller: ClusterController) -> None:
        """Test release_slot releases semaphore."""
        # Reset for clean test
        ClusterController.reset_semaphore()

        await controller.acquire_slot("test")
        controller.release_slot()

        # Semaphore should be available again
        semaphore = ClusterController.get_semaphore()
        assert semaphore._value == 3  # Value should be 3 (was 2 after acquire)

        # Reset for other tests
        ClusterController.reset_semaphore()

    @pytest.mark.asyncio
    async def test_fetch_nodes_enriches_resources_from_pods(
        self,
        controller: ClusterController,
    ) -> None:
        """fetch_nodes should populate requests/limits/pod count from pods."""
        ClusterController.reset_semaphore()
        node = NodeInfo(
            name="node-a",
            status=NodeStatus.READY,
            node_group="workers",
            instance_type="m5.large",
            availability_zone="us-east-1a",
            cpu_allocatable=2000.0,
            memory_allocatable=8 * 1024 * 1024 * 1024,
            cpu_requests=0.0,
            memory_requests=0.0,
            cpu_limits=0.0,
            memory_limits=0.0,
            pod_count=0,
            pod_capacity=110,
        )
        controller._node_fetcher.fetch_nodes = AsyncMock(return_value=[node])  # type: ignore[method-assign]
        fetch_pods_mock = AsyncMock(
            return_value=[
                {
                    "status": {"phase": "Running"},
                    "spec": {
                        "nodeName": "node-a",
                        "containers": [
                            {
                                "resources": {
                                    "requests": {"cpu": "500m", "memory": "256Mi"},
                                    "limits": {"cpu": "1000m", "memory": "512Mi"},
                                }
                            }
                        ],
                        "initContainers": [
                            {
                                "resources": {
                                    "requests": {"cpu": "300m", "memory": "128Mi"},
                                    "limits": {"cpu": "600m", "memory": "256Mi"},
                                }
                            }
                        ],
                        "overhead": {"cpu": "50m", "memory": "64Mi"},
                    },
                },
                {
                    "status": {"phase": "Pending"},
                    "spec": {
                        "nodeName": "node-a",
                        "containers": [
                            {
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "128Mi"}
                                }
                            }
                        ],
                    },
                },
                {
                    "status": {"phase": "Succeeded"},
                    "spec": {
                        "nodeName": "node-a",
                        "containers": [
                            {
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "128Mi"}
                                }
                            }
                        ],
                    },
                },
            ]
        )
        controller._pod_fetcher.fetch_pods = fetch_pods_mock  # type: ignore[method-assign]

        nodes = await controller.fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0].cpu_requests == 650.0
        assert nodes[0].cpu_limits == 1050.0
        assert nodes[0].memory_requests == 448 * 1024 * 1024
        assert nodes[0].memory_limits == 576 * 1024 * 1024
        assert nodes[0].pod_count == 2
        fetch_pods_mock.assert_awaited_once_with(
            request_timeout=ClusterController._NODE_POD_ENRICH_REQUEST_TIMEOUT
        )
        ClusterController.reset_semaphore()

    @pytest.mark.asyncio
    async def test_fetch_nodes_returns_nodes_when_pod_enrichment_fails(
        self,
        controller: ClusterController,
    ) -> None:
        """fetch_nodes should still succeed when pod fetch errors."""
        ClusterController.reset_semaphore()
        node = NodeInfo(
            name="node-a",
            status=NodeStatus.READY,
            node_group="workers",
            instance_type="m5.large",
            availability_zone="us-east-1a",
            cpu_allocatable=2000.0,
            memory_allocatable=8 * 1024 * 1024 * 1024,
            cpu_requests=0.0,
            memory_requests=0.0,
            cpu_limits=0.0,
            memory_limits=0.0,
            pod_count=0,
            pod_capacity=110,
        )
        controller._node_fetcher.fetch_nodes = AsyncMock(return_value=[node])  # type: ignore[method-assign]
        controller._pod_fetcher.fetch_pods = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("timed out")
        )

        nodes = await controller.fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0].name == "node-a"
        assert nodes[0].cpu_requests == 0.0
        assert nodes[0].memory_requests == 0.0
        assert nodes[0].pod_count == 0
        ClusterController.reset_semaphore()

    @pytest.mark.asyncio
    async def test_fetch_nodes_inventory_only_skips_pod_enrichment(
        self,
        controller: ClusterController,
    ) -> None:
        """fetch_nodes(include_pod_resources=False) should avoid pod fetch."""
        ClusterController.reset_semaphore()
        node = NodeInfo(
            name="node-a",
            status=NodeStatus.READY,
            node_group="workers",
            instance_type="m5.large",
            availability_zone="us-east-1a",
            cpu_allocatable=2000.0,
            memory_allocatable=8 * 1024 * 1024 * 1024,
            cpu_requests=0.0,
            memory_requests=0.0,
            cpu_limits=0.0,
            memory_limits=0.0,
            pod_count=0,
            pod_capacity=110,
        )
        controller._node_fetcher.fetch_nodes = AsyncMock(return_value=[node])  # type: ignore[method-assign]
        fetch_pods_mock = AsyncMock(return_value=[])
        controller._pod_fetcher.fetch_pods = fetch_pods_mock  # type: ignore[method-assign]

        nodes = await controller.fetch_nodes(include_pod_resources=False)

        assert len(nodes) == 1
        assert nodes[0].name == "node-a"
        fetch_pods_mock.assert_not_awaited()
        ClusterController.reset_semaphore()

    @pytest.mark.asyncio
    async def test_fetch_node_resources_populates_limits_and_pod_count(
        self,
        controller: ClusterController,
    ) -> None:
        """fetch_node_resources should carry through limit and pod metrics."""
        ClusterController.reset_semaphore()
        controller._node_fetcher.fetch_nodes_raw = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "metadata": {
                        "name": "node-a",
                        "labels": {
                            "eks.amazonaws.com/nodegroup": "workers",
                            "node.kubernetes.io/instance-type": "m5.large",
                            "topology.kubernetes.io/zone": "us-east-1a",
                        },
                    },
                    "status": {
                        "allocatable": {"cpu": "2", "memory": "8Gi", "pods": "110"},
                        "conditions": [{"type": "Ready", "status": "True"}],
                        "nodeInfo": {"kubeletVersion": "v1.30.0"},
                    },
                    "spec": {},
                }
            ]
        )
        controller._pod_fetcher.fetch_pods = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "status": {"phase": "Running"},
                    "spec": {
                        "nodeName": "node-a",
                        "containers": [
                            {
                                "resources": {
                                    "requests": {"cpu": "500m", "memory": "256Mi"},
                                    "limits": {"cpu": "1000m", "memory": "512Mi"},
                                }
                            }
                        ],
                        "overhead": {"cpu": "50m", "memory": "64Mi"},
                    },
                }
            ]
        )

        resources = await controller.fetch_node_resources()

        assert len(resources) == 1
        assert resources[0].cpu_requests == 550.0
        assert resources[0].cpu_limits == 1050.0
        assert resources[0].memory_requests == 320 * 1024 * 1024
        assert resources[0].memory_limits == 576 * 1024 * 1024
        assert resources[0].pod_count == 1
        ClusterController.reset_semaphore()

    @pytest.mark.asyncio
    async def test_fetch_pods_incremental_streams_namespace_callbacks(
        self,
        controller: ClusterController,
    ) -> None:
        """Incremental pod fetch should emit callback per namespace."""
        controller._list_cluster_namespaces = AsyncMock(  # type: ignore[method-assign]
            return_value=["ns-a", "ns-b"]
        )

        async def _fetch_ns(namespace: str, request_timeout: str | None = None) -> list[dict]:
            _ = request_timeout
            return [{"metadata": {"name": f"{namespace}-pod"}}]

        controller._pod_fetcher.fetch_pods_for_namespace = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_ns
        )

        callbacks: list[tuple[str, int, int, int]] = []

        pods = await controller._fetch_pods_incremental(
            on_namespace_loaded=lambda ns, ns_pods, completed, total: callbacks.append(
                (ns, len(ns_pods), completed, total)
            )
        )

        assert len(pods) == 2
        assert len(callbacks) == 2
        assert {entry[0] for entry in callbacks} == {"ns-a", "ns-b"}
        assert {entry[2] for entry in callbacks} == {1, 2}
        assert all(entry[3] == 2 for entry in callbacks)
        assert len(controller._pods_cache) == 2

    @pytest.mark.asyncio
    async def test_fetch_pods_incremental_falls_back_to_all_namespaces_query(
        self,
        controller: ClusterController,
    ) -> None:
        """When namespace-scoped fetch returns nothing, fallback to -A pods query."""
        controller._list_cluster_namespaces = AsyncMock(  # type: ignore[method-assign]
            return_value=["ns-a", "ns-b"]
        )
        controller._pod_fetcher.fetch_pods_for_namespace = AsyncMock(  # type: ignore[method-assign]
            return_value=[]
        )
        fallback_pods = [
            {
                "metadata": {"name": "api-0", "namespace": "ns-a"},
                "spec": {"nodeName": "node-a"},
            }
        ]
        controller._pod_fetcher.fetch_pods = AsyncMock(  # type: ignore[method-assign]
            return_value=fallback_pods
        )

        pods = await controller._fetch_pods_incremental()

        assert pods == fallback_pods
        controller._pod_fetcher.fetch_pods.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_pod_request_stats_streams_partial_namespace_updates(
        self,
        controller: ClusterController,
    ) -> None:
        """Pod request stats should update after each namespace payload."""
        controller._list_cluster_namespaces = AsyncMock(  # type: ignore[method-assign]
            return_value=["ns-a", "ns-b"]
        )

        async def _fetch_ns(namespace: str, request_timeout: str | None = None) -> list[dict]:
            _ = request_timeout
            return [{"metadata": {"name": f"{namespace}-pod"}}]

        controller._pod_fetcher.fetch_pods_for_namespace = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_ns
        )
        controller._pod_parser.parse_pod_requests = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda pods: {
                "cpu_stats": {},
                "memory_stats": {},
                "count": len(pods),
            }
        )

        updates: list[tuple[int, int, int]] = []

        stats = await controller.get_pod_request_stats(
            on_namespace_update=lambda partial, completed, total: updates.append(
                (int(partial.get("count", 0)), completed, total)
            )
        )

        assert int(stats.get("count", 0)) == 2
        assert len(updates) == 2
        assert {item[1] for item in updates} == {1, 2}
        assert all(item[2] == 2 for item in updates)
        assert updates[-1][0] == 2

    @pytest.mark.asyncio
    async def test_fetch_warning_events_incremental_streams_namespace_callbacks(
        self,
        controller: ClusterController,
    ) -> None:
        """Incremental warning-event fetch should emit callback per namespace."""
        controller._list_cluster_namespaces = AsyncMock(  # type: ignore[method-assign]
            return_value=["ns-a", "ns-b"]
        )

        async def _fetch_events(
            namespace: str | None = None,
            request_timeout: str | None = None,
        ) -> list[dict]:
            _ = request_timeout
            assert namespace is not None
            return [{"metadata": {"name": f"{namespace}-event"}}]

        controller._event_fetcher.fetch_warning_events_raw = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_events
        )

        callbacks: list[tuple[str, int, int, int]] = []

        events = await controller._fetch_warning_events_incremental(
            on_namespace_loaded=lambda ns, ns_events, completed, total: callbacks.append(
                (ns, len(ns_events), completed, total)
            )
        )

        assert len(events) == 2
        assert len(callbacks) == 2
        assert {entry[0] for entry in callbacks} == {"ns-a", "ns-b"}
        assert {entry[2] for entry in callbacks} == {1, 2}
        assert all(entry[3] == 2 for entry in callbacks)

    @pytest.mark.asyncio
    async def test_get_event_summary_streams_partial_namespace_updates(
        self,
        controller: ClusterController,
    ) -> None:
        """Event summary should update after each namespace payload."""
        controller._list_cluster_namespaces = AsyncMock(  # type: ignore[method-assign]
            return_value=["ns-a", "ns-b"]
        )

        async def _fetch_events(
            namespace: str | None = None,
            request_timeout: str | None = None,
        ) -> list[dict]:
            _ = request_timeout
            return [
                {
                    "reason": "OOMKilling",
                    "message": "oom",
                    "type": "Warning",
                    "count": 1,
                    "lastTimestamp": datetime.now(timezone.utc).isoformat(),
                    "involvedObject": {
                        "name": f"{namespace}-pod",
                        "namespace": namespace,
                        "kind": "Pod",
                    },
                }
            ]

        controller._event_fetcher.fetch_warning_events_raw = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_events
        )

        updates: list[tuple[int, int, int]] = []
        summary = await controller.get_event_summary(
            on_namespace_update=lambda partial, completed, total: updates.append(
                (partial.total_count, completed, total)
            )
        )

        assert summary.total_count == 2
        assert summary.oom_count == 2
        assert len(updates) == 2
        assert updates[-1][0] == 2
        assert {item[1] for item in updates} == {1, 2}
        assert all(item[2] == 2 for item in updates)

    @pytest.mark.asyncio
    async def test_fetch_nodes_emits_partial_node_updates(
        self,
        controller: ClusterController,
    ) -> None:
        """fetch_nodes should emit progressive callbacks when requested."""
        ClusterController.reset_semaphore()
        node_a = NodeInfo(
            name="node-a",
            status=NodeStatus.READY,
            node_group="workers",
            instance_type="m5.large",
            availability_zone="us-east-1a",
            cpu_allocatable=2000.0,
            memory_allocatable=8 * 1024 * 1024 * 1024,
            cpu_requests=0.0,
            memory_requests=0.0,
            cpu_limits=0.0,
            memory_limits=0.0,
            pod_count=0,
            pod_capacity=110,
        )
        node_b = node_a.model_copy(update={"name": "node-b"})
        controller._node_fetcher.fetch_nodes = AsyncMock(return_value=[node_a, node_b])  # type: ignore[method-assign]

        async def _fetch_pods_incremental(
            on_namespace_loaded: Any = None,
            request_timeout: str | None = None,
        ) -> list[dict]:
            _ = request_timeout
            namespace_a = [
                {
                    "status": {"phase": "Running"},
                    "spec": {
                        "nodeName": "node-a",
                        "containers": [
                            {
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "128Mi"}
                                }
                            }
                        ],
                    },
                }
            ]
            namespace_b = [
                {
                    "status": {"phase": "Running"},
                    "spec": {
                        "nodeName": "node-b",
                        "containers": [
                            {
                                "resources": {
                                    "requests": {"cpu": "200m", "memory": "256Mi"}
                                }
                            }
                        ],
                    },
                }
            ]
            if on_namespace_loaded is not None:
                on_namespace_loaded("ns-a", namespace_a, 1, 2)
                on_namespace_loaded("ns-b", namespace_b, 2, 2)
            return namespace_a + namespace_b

        controller._fetch_pods_incremental = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_pods_incremental
        )

        updates: list[tuple[int, int, int, int]] = []
        nodes = await controller.fetch_nodes(
            include_pod_resources=True,
            on_node_update=lambda partial_nodes, completed, total: updates.append(
                (
                    len(partial_nodes),
                    completed,
                    total,
                    int(partial_nodes[0].pod_count if partial_nodes else 0),
                )
            ),
        )

        assert len(nodes) == 2
        assert updates[0][0:3] == (2, 1, 2)
        assert updates[1][0:3] == (2, 2, 2)
        assert updates[0][3] == 1
        assert nodes[0].pod_count == 1
        assert nodes[1].pod_count == 1
        ClusterController.reset_semaphore()

    @pytest.mark.asyncio
    async def test_fetch_pdbs_incremental_streams_namespace_callbacks(
        self,
        controller: ClusterController,
    ) -> None:
        """Incremental PDB fetch should emit callback per namespace."""
        controller._list_cluster_namespaces = AsyncMock(  # type: ignore[method-assign]
            return_value=["ns-a", "ns-b"]
        )

        async def _fetch_pdbs(namespace: str) -> list[dict]:
            return [
                {
                    "metadata": {"name": f"{namespace}-pdb", "namespace": namespace},
                    "spec": {},
                    "status": {},
                }
            ]

        controller._cluster_fetcher.fetch_pdbs_for_namespace = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_pdbs
        )

        callbacks: list[tuple[str, int, int, int]] = []
        result = await controller._fetch_pdbs_incremental(
            on_namespace_loaded=lambda ns, rows, completed, total: callbacks.append(
                (ns, len(rows), completed, total)
            )
        )

        assert len(result) == 2
        assert len(callbacks) == 2
        assert {entry[0] for entry in callbacks} == {"ns-a", "ns-b"}
        assert {entry[2] for entry in callbacks} == {1, 2}
        assert all(entry[3] == 2 for entry in callbacks)

    @pytest.mark.asyncio
    async def test_fetch_helm_releases_incremental_streams_namespace_callbacks(
        self,
        controller: ClusterController,
    ) -> None:
        """Incremental helm release fetch should emit callback per namespace."""
        controller._list_cluster_namespaces = AsyncMock(  # type: ignore[method-assign]
            return_value=["ns-a", "ns-b"]
        )

        async def _fetch_helm(namespace: str) -> list[HelmReleaseInfo]:
            return [
                HelmReleaseInfo(
                    name=f"{namespace}-rel",
                    namespace=namespace,
                    chart="app-1.0.0",
                    version="1",
                    app_version="1.0.0",
                    status="deployed",
                )
            ]

        controller._cluster_fetcher.fetch_helm_releases_for_namespace = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_helm
        )

        callbacks: list[tuple[str, int, int, int]] = []
        releases = await controller._fetch_helm_releases_incremental(
            on_namespace_loaded=lambda ns, rows, completed, total: callbacks.append(
                (ns, len(rows), completed, total)
            )
        )

        assert len(releases) == 2
        assert len(callbacks) == 2
        assert {entry[0] for entry in callbacks} == {"ns-a", "ns-b"}
        assert {entry[2] for entry in callbacks} == {1, 2}
        assert all(entry[3] == 2 for entry in callbacks)

    @pytest.mark.asyncio
    async def test_fetch_single_replica_incremental_streams_namespace_callbacks(
        self,
        controller: ClusterController,
    ) -> None:
        """Single-replica incremental fetch should emit callback per namespace."""
        controller._list_cluster_namespaces = AsyncMock(  # type: ignore[method-assign]
            return_value=["ns-a", "ns-b"]
        )
        controller._fetch_helm_releases_incremental = AsyncMock(  # type: ignore[method-assign]
            return_value=[]
        )

        async def _run_kubectl(args: tuple[str, ...]) -> str:
            namespace = args[args.index("-n") + 1]
            payload = {
                "items": [
                    {
                        "metadata": {
                            "name": f"{namespace}-app",
                            "namespace": namespace,
                            "labels": {},
                        },
                        "spec": {"replicas": 1},
                        "status": {"readyReplicas": 1},
                    }
                ]
            }
            return json.dumps(payload)

        controller._run_kubectl_cached = AsyncMock(side_effect=_run_kubectl)  # type: ignore[method-assign]

        callbacks: list[tuple[str, int, int, int]] = []
        rows = await controller._fetch_single_replica_incremental(
            on_namespace_loaded=lambda ns, ns_rows, completed, total: callbacks.append(
                (ns, len(ns_rows), completed, total)
            )
        )

        assert len(rows) == 2
        assert len(callbacks) == 2
        assert {entry[0] for entry in callbacks} == {"ns-a", "ns-b"}
        assert {entry[2] for entry in callbacks} == {1, 2}
        assert all(entry[3] == 2 for entry in callbacks)

    @pytest.mark.asyncio
    async def test_fetch_workload_inventory_incremental_includes_supported_kinds_and_filters_completed_jobs(
        self,
        controller: ClusterController,
    ) -> None:
        """Inventory fetch should include runtime kinds and skip completed jobs."""
        controller._list_cluster_namespaces = AsyncMock(  # type: ignore[method-assign]
            return_value=["team-a"]
        )
        controller._fetch_pdbs_incremental = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                PDBInfo(
                    name="team-a-pdb",
                    namespace="team-a",
                    kind="Workload",
                    min_available=1,
                    max_unavailable=None,
                    min_unavailable=None,
                    max_available=None,
                    current_healthy=1,
                    desired_healthy=1,
                    expected_pods=1,
                    disruptions_allowed=1,
                    unhealthy_pod_eviction_policy="IfHealthyBudget",
                    selector_match_labels={"app": "api"},
                )
            ]
        )

        controller._run_kubectl_cached = AsyncMock(  # type: ignore[method-assign]
            return_value=json.dumps(
                {
                    "items": [
                        {
                            "kind": "Deployment",
                            "metadata": {
                                "name": "api",
                                "namespace": "team-a",
                                "labels": {"app.kubernetes.io/instance": "rel-api"},
                            },
                            "spec": {
                                "replicas": 2,
                                "template": {
                                    "metadata": {"labels": {"app": "api"}},
                                    "spec": {
                                        "containers": [
                                            {
                                                "name": "api",
                                                "resources": {
                                                    "requests": {
                                                        "cpu": "200m",
                                                        "memory": "256Mi",
                                                    },
                                                    "limits": {
                                                        "cpu": "500m",
                                                        "memory": "512Mi",
                                                    },
                                                },
                                            }
                                        ]
                                    },
                                },
                            },
                            "status": {"readyReplicas": 2},
                        },
                        {
                            "kind": "StatefulSet",
                            "metadata": {"name": "db", "namespace": "team-a", "labels": {}},
                            "spec": {
                                "replicas": 1,
                                "template": {
                                    "metadata": {"labels": {"app": "db"}},
                                    "spec": {
                                        "containers": [
                                            {
                                                "name": "db",
                                                "resources": {
                                                    "requests": {
                                                        "cpu": "400m",
                                                        "memory": "1Gi",
                                                    },
                                                    "limits": {
                                                        "cpu": "800m",
                                                        "memory": "2Gi",
                                                    },
                                                },
                                            }
                                        ]
                                    },
                                },
                            },
                            "status": {"readyReplicas": 1},
                        },
                        {
                            "kind": "DaemonSet",
                            "metadata": {"name": "node-agent", "namespace": "team-a", "labels": {}},
                            "spec": {"template": {"metadata": {"labels": {"app": "agent"}}}},
                            "status": {"desiredNumberScheduled": 3, "numberReady": 3},
                        },
                        {
                            "kind": "Job",
                            "metadata": {"name": "batch-active", "namespace": "team-a", "labels": {}},
                            "spec": {
                                "parallelism": 1,
                                "template": {
                                    "metadata": {"labels": {"app": "batch"}},
                                    "spec": {
                                        "containers": [
                                            {
                                                "name": "batch",
                                                "resources": {
                                                    "requests": {"cpu": "50m"},
                                                    "limits": {"cpu": "100m"},
                                                },
                                            }
                                        ]
                                    },
                                },
                            },
                            "status": {"active": 1},
                        },
                        {
                            "kind": "Job",
                            "metadata": {"name": "batch-done", "namespace": "team-a", "labels": {}},
                            "spec": {
                                "parallelism": 1,
                                "template": {"metadata": {"labels": {"app": "batch-done"}}},
                            },
                            "status": {"succeeded": 1},
                        },
                        {
                            "kind": "CronJob",
                            "metadata": {"name": "nightly", "namespace": "team-a", "labels": {}},
                            "spec": {
                                "jobTemplate": {
                                    "spec": {
                                        "template": {
                                            "metadata": {"labels": {"app": "nightly"}},
                                            "spec": {
                                                "containers": [
                                                    {
                                                        "name": "nightly",
                                                        "resources": {
                                                            "requests": {
                                                                "cpu": "25m",
                                                                "memory": "128Mi",
                                                            },
                                                            "limits": {
                                                                "cpu": "100m",
                                                                "memory": "512Mi",
                                                            },
                                                        },
                                                    }
                                                ]
                                            },
                                        }
                                    }
                                }
                            },
                            "status": {"active": []},
                        },
                    ]
                }
            )
        )

        rows = await controller._fetch_workload_inventory_incremental()

        names = {row.name for row in rows}
        kinds = {row.kind for row in rows}
        assert names == {"api", "db", "node-agent", "batch-active", "nightly"}
        assert "batch-done" not in names
        assert kinds == {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}
        deployment = next(row for row in rows if row.name == "api")
        assert deployment.has_pdb is True
        assert deployment.helm_release == "rel-api"
        assert deployment.cpu_request == 200.0
        assert deployment.cpu_limit == 500.0
        assert deployment.memory_request == 256 * 1024 * 1024
        assert deployment.memory_limit == 512 * 1024 * 1024

        cronjob = next(row for row in rows if row.name == "nightly")
        assert cronjob.cpu_request == 25.0
        assert cronjob.cpu_limit == 100.0

    @pytest.mark.asyncio
    async def test_fetch_workload_inventory_incremental_streams_namespace_callbacks(
        self,
        controller: ClusterController,
    ) -> None:
        """Inventory fetch should emit namespace callback updates."""
        controller._list_cluster_namespaces = AsyncMock(  # type: ignore[method-assign]
            return_value=["ns-a", "ns-b"]
        )
        controller._fetch_pdbs_incremental = AsyncMock(return_value=[])  # type: ignore[method-assign]

        async def _run_kubectl(args: tuple[str, ...]) -> str:
            namespace = args[args.index("-n") + 1]
            return json.dumps(
                {
                    "items": [
                        {
                            "kind": "Deployment",
                            "metadata": {"name": f"{namespace}-app", "namespace": namespace, "labels": {}},
                            "spec": {
                                "replicas": 1,
                                "template": {"metadata": {"labels": {"app": "demo"}}},
                            },
                            "status": {"readyReplicas": 1},
                        }
                    ]
                }
            )

        controller._run_kubectl_cached = AsyncMock(side_effect=_run_kubectl)  # type: ignore[method-assign]

        callbacks: list[tuple[str, int, int, int]] = []
        rows = await controller._fetch_workload_inventory_incremental(
            on_namespace_loaded=lambda ns, ns_rows, completed, total: callbacks.append(
                (ns, len(ns_rows), completed, total)
            )
        )

        assert len(rows) == 2
        assert len(callbacks) == 2
        assert {entry[0] for entry in callbacks} == {"ns-a", "ns-b"}
        assert {entry[2] for entry in callbacks} == {1, 2}
        assert all(entry[3] == 2 for entry in callbacks)

    @pytest.mark.asyncio
    async def test_fetch_workload_inventory_emits_first_partial_update_immediately(
        self,
        controller: ClusterController,
    ) -> None:
        """Wrapper should emit first partial callback at completed=1."""
        first_row = SimpleNamespace(
            namespace="ns-a",
            kind="Deployment",
            name="api",
        )

        async def _fetch_incremental(
            on_namespace_loaded: Any = None,
        ) -> list[SimpleNamespace]:
            assert on_namespace_loaded is not None
            total = 12
            for completed in range(1, total + 1):
                rows = [first_row] if completed == 1 else []
                on_namespace_loaded(f"ns-{completed}", rows, completed, total)
            return [first_row]

        controller._fetch_workload_inventory_incremental = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_incremental
        )

        updates: list[tuple[int, int, int]] = []
        rows = await controller.fetch_workload_inventory(
            on_namespace_update=lambda partial, completed, total: updates.append(
                (len(partial), completed, total)
            )
        )

        assert rows == [first_row]
        assert updates
        assert updates[0] == (1, 1, 12)
        assert updates[-1][1:] == (12, 12)

    @pytest.mark.asyncio
    async def test_fetch_workload_inventory_emits_first_non_empty_partial_immediately(
        self,
        controller: ClusterController,
    ) -> None:
        """First non-empty namespace payload should be emitted without delay."""
        first_row = SimpleNamespace(
            namespace="ns-b",
            kind="Deployment",
            name="api",
        )

        async def _fetch_incremental(
            on_namespace_loaded: Any = None,
        ) -> list[SimpleNamespace]:
            assert on_namespace_loaded is not None
            total = 12
            on_namespace_loaded("ns-1", [], 1, total)
            on_namespace_loaded("ns-2", [first_row], 2, total)
            for completed in range(3, total + 1):
                on_namespace_loaded(f"ns-{completed}", [], completed, total)
            return [first_row]

        controller._fetch_workload_inventory_incremental = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_incremental
        )

        updates: list[tuple[int, int, int]] = []
        rows = await controller.fetch_workload_inventory(
            on_namespace_update=lambda partial, completed, total: updates.append(
                (len(partial), completed, total)
            )
        )

        assert rows == [first_row]
        assert updates
        assert updates[0] == (0, 1, 12)
        assert (1, 2, 12) in updates

    @pytest.mark.asyncio
    async def test_fetch_workload_inventory_streams_each_new_non_empty_batch(
        self,
        controller: ClusterController,
    ) -> None:
        """Wrapper should emit as soon as each namespace adds new rows."""
        row_a = SimpleNamespace(namespace="ns-a", kind="Deployment", name="a")
        row_b = SimpleNamespace(namespace="ns-b", kind="Deployment", name="b")

        async def _fetch_incremental(
            on_namespace_loaded: Any = None,
        ) -> list[SimpleNamespace]:
            assert on_namespace_loaded is not None
            total = 10
            on_namespace_loaded("ns-1", [], 1, total)
            on_namespace_loaded("ns-2", [row_a], 2, total)
            on_namespace_loaded("ns-3", [row_b], 3, total)
            for completed in range(4, total + 1):
                on_namespace_loaded(f"ns-{completed}", [], completed, total)
            return [row_a, row_b]

        controller._fetch_workload_inventory_incremental = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_incremental
        )

        updates: list[tuple[int, int, int]] = []
        rows = await controller.fetch_workload_inventory(
            on_namespace_update=lambda partial, completed, total: updates.append(
                (len(partial), completed, total)
            )
        )

        assert rows == [row_a, row_b]
        assert updates
        assert updates[0] == (0, 1, 10)
        assert (1, 2, 10) in updates
        assert (2, 3, 10) in updates

    @pytest.mark.asyncio
    async def test_fetch_workload_inventory_enrichment_does_not_block_initial_stream_update(
        self,
        controller: ClusterController,
    ) -> None:
        """Initial streamed rows should arrive before runtime enrichment finishes."""
        row = WorkloadInventoryInfo(
            name="api",
            namespace="ns-a",
            kind="Deployment",
            desired_replicas=1,
            ready_replicas=1,
            status="Ready",
        )
        enrichment_release = asyncio.Event()

        async def _fetch_incremental(
            on_namespace_loaded: Any = None,
        ) -> list[WorkloadInventoryInfo]:
            assert on_namespace_loaded is not None
            on_namespace_loaded("ns-a", [row], 1, 1)
            return [row]

        async def _slow_enrich(
            rows: list[WorkloadInventoryInfo],
            *,
            timeout_seconds: float = 45.0,
        ) -> list[WorkloadInventoryInfo]:
            _ = timeout_seconds
            await enrichment_release.wait()
            return rows

        controller._fetch_workload_inventory_incremental = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_incremental
        )
        enrich_mock = AsyncMock(
            side_effect=_slow_enrich
        )
        controller.enrich_workload_runtime_stats = enrich_mock  # type: ignore[method-assign]

        updates: list[tuple[int, int, int]] = []
        first_update_seen = asyncio.Event()

        def _on_update(
            partial: list[WorkloadInventoryInfo],
            completed: int,
            total: int,
        ) -> None:
            updates.append((len(partial), completed, total))
            first_update_seen.set()

        task = asyncio.create_task(
            controller.fetch_workload_inventory(
                on_namespace_update=_on_update,
                enrich_runtime_stats=True,
            )
        )

        await asyncio.wait_for(first_update_seen.wait(), timeout=0.2)
        assert updates[0] == (1, 1, 1)
        assert not task.done()

        enrichment_release.set()
        rows = await asyncio.wait_for(task, timeout=0.5)

        assert len(rows) == 1
        assert len(updates) >= 2
        enrich_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_workload_inventory_prefetches_runtime_inputs_before_enrichment(
        self,
        controller: ClusterController,
    ) -> None:
        """Runtime input fetch should start while workload inventory is still loading."""
        row = WorkloadInventoryInfo(
            name="api",
            namespace="ns-a",
            kind="Deployment",
            desired_replicas=1,
            ready_replicas=1,
            status="Ready",
        )
        prefetch_started = asyncio.Event()
        release_prefetch = asyncio.Event()

        async def _prefetch_inputs() -> tuple[Any, Any, Any, Any]:
            prefetch_started.set()
            await release_prefetch.wait()
            return ([], [], [], [])

        async def _fetch_incremental(
            on_namespace_loaded: Any = None,
        ) -> list[WorkloadInventoryInfo]:
            _ = on_namespace_loaded
            await asyncio.wait_for(prefetch_started.wait(), timeout=0.2)
            release_prefetch.set()
            return [row]

        prefetch_mock = AsyncMock(side_effect=_prefetch_inputs)
        controller._prefetch_workload_runtime_stats_inputs = prefetch_mock  # type: ignore[method-assign]
        controller._fetch_workload_inventory_incremental = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_incremental
        )

        rows = await controller.fetch_workload_inventory(enrich_runtime_stats=True)

        assert rows == [row]
        prefetch_mock.assert_awaited_once()
        assert controller._runtime_enrichment_prefetch_task is None

    @pytest.mark.asyncio
    async def test_fetch_workload_inventory_streams_runtime_metrics_before_completion(
        self,
        controller: ClusterController,
    ) -> None:
        """Runtime node/usage metrics should stream in before final completion callback."""
        row = WorkloadInventoryInfo(
            name="api",
            namespace="ns-a",
            kind="Deployment",
            desired_replicas=1,
            ready_replicas=1,
            status="Ready",
        )
        prefetch_release = asyncio.Event()

        async def _prefetch_inputs() -> tuple[Any, Any, Any, Any]:
            await prefetch_release.wait()
            return (
                [
                    {
                        "metadata": {"name": "api-abc", "namespace": "ns-a"},
                        "spec": {"nodeName": "node-a"},
                        "status": {"phase": "Running"},
                    }
                ],
                [],
                [],
                [],
            )

        async def _fetch_incremental(
            on_namespace_loaded: Any = None,
        ) -> list[WorkloadInventoryInfo]:
            assert on_namespace_loaded is not None
            on_namespace_loaded("ns-1", [row], 1, 12)
            prefetch_release.set()
            await asyncio.sleep(0)
            on_namespace_loaded("ns-2", [], 2, 12)
            for completed in range(3, 13):
                on_namespace_loaded(f"ns-{completed}", [], completed, 12)
            return [row]

        async def _final_enrich(
            rows: list[WorkloadInventoryInfo],
            *,
            timeout_seconds: float = 45.0,
        ) -> list[WorkloadInventoryInfo]:
            _ = timeout_seconds
            return rows

        apply_calls: list[int] = []

        def _apply_runtime(
            rows_to_update: list[WorkloadInventoryInfo],
            _workload_pods: Any,
            _node_utilization_by_name: Any,
            *,
            node_allocatable_by_name: Any = None,
            top_node_usage_by_name: Any = None,
            top_pod_usage_by_key: Any = None,
        ) -> None:
            _ = (
                node_allocatable_by_name,
                top_node_usage_by_name,
                top_pod_usage_by_key,
            )
            apply_calls.append(len(rows_to_update))
            for workload_row in rows_to_update:
                workload_row.assigned_nodes = "1"

        controller._prefetch_workload_runtime_stats_inputs = AsyncMock(  # type: ignore[method-assign]
            side_effect=_prefetch_inputs
        )
        controller._fetch_workload_inventory_incremental = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_incremental
        )
        controller._build_node_utilization_lookup_for_pods = AsyncMock(  # type: ignore[method-assign]
            return_value={}
        )
        controller._build_workload_pod_lookup = MagicMock(return_value={})  # type: ignore[method-assign]
        controller._build_node_allocatable_lookup = MagicMock(return_value={})  # type: ignore[method-assign]
        controller._build_top_node_usage_lookup = MagicMock(return_value={})  # type: ignore[method-assign]
        controller._build_top_pod_usage_lookup = MagicMock(return_value={})  # type: ignore[method-assign]
        controller._apply_workload_runtime_stats_with_lookup = MagicMock(  # type: ignore[method-assign]
            side_effect=_apply_runtime
        )
        controller.enrich_workload_runtime_stats = AsyncMock(  # type: ignore[method-assign]
            side_effect=_final_enrich
        )

        updates: list[tuple[int, str]] = []
        rows = await controller.fetch_workload_inventory(
            on_namespace_update=lambda partial, completed, total: updates.append(
                (completed, str(partial[0].assigned_nodes if partial else "-"))
            ),
            enrich_runtime_stats=True,
        )

        assert rows == [row]
        assert updates
        assert updates[0][0] == 1
        assert any(completed == 2 and assigned_nodes == "1" for completed, assigned_nodes in updates)
        assert apply_calls

    @pytest.mark.asyncio
    async def test_fetch_workload_inventory_streams_before_pdb_fetch_completes(
        self,
        controller: ClusterController,
    ) -> None:
        """Workload partial callbacks should not wait for full PDB fetch."""
        controller._list_cluster_namespaces = AsyncMock(  # type: ignore[method-assign]
            return_value=["ns-a"]
        )

        pdb_release = asyncio.Event()

        async def _fetch_pdbs() -> list[PDBInfo]:
            await pdb_release.wait()
            return []

        controller._fetch_pdbs_incremental = AsyncMock(  # type: ignore[method-assign]
            side_effect=_fetch_pdbs
        )
        controller._run_kubectl_cached = AsyncMock(  # type: ignore[method-assign]
            return_value=json.dumps(
                {
                    "items": [
                        {
                            "kind": "Deployment",
                            "metadata": {"name": "api", "namespace": "ns-a", "labels": {}},
                            "spec": {
                                "replicas": 1,
                                "template": {"metadata": {"labels": {"app": "api"}}},
                            },
                            "status": {"readyReplicas": 1},
                        }
                    ]
                }
            )
        )

        callback_seen = asyncio.Event()
        callbacks: list[tuple[int, int, int]] = []

        async def _run_fetch() -> list[Any]:
            return await controller._fetch_workload_inventory_incremental(
                on_namespace_loaded=lambda _ns, ns_rows, completed, total: (
                    callbacks.append((len(ns_rows), completed, total)),
                    callback_seen.set(),
                )
            )

        task = asyncio.create_task(_run_fetch())
        await asyncio.wait_for(callback_seen.wait(), timeout=0.4)
        assert callbacks
        assert callbacks[0] == (1, 1, 1)

        pdb_release.set()
        rows = await asyncio.wait_for(task, timeout=0.4)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_fetch_single_replica_incremental_includes_statefulsets(
        self,
        controller: ClusterController,
    ) -> None:
        """Single-replica fetch should include both Deployments and StatefulSets."""
        controller._list_cluster_namespaces = AsyncMock(  # type: ignore[method-assign]
            return_value=["ns-a"]
        )
        controller._fetch_helm_releases_incremental = AsyncMock(  # type: ignore[method-assign]
            return_value=[]
        )
        controller._run_kubectl_cached = AsyncMock(  # type: ignore[method-assign]
            return_value=json.dumps(
                {
                    "items": [
                        {
                            "kind": "Deployment",
                            "metadata": {"name": "api", "namespace": "ns-a", "labels": {}},
                            "spec": {"replicas": 1},
                            "status": {"readyReplicas": 1},
                        },
                        {
                            "kind": "StatefulSet",
                            "metadata": {"name": "db", "namespace": "ns-a", "labels": {}},
                            "spec": {"replicas": 1},
                            "status": {"readyReplicas": 0},
                        },
                        {
                            "kind": "Deployment",
                            "metadata": {"name": "scaled", "namespace": "ns-a", "labels": {}},
                            "spec": {"replicas": 2},
                            "status": {"readyReplicas": 2},
                        },
                    ]
                }
            )
        )

        rows = await controller._fetch_single_replica_incremental()

        assert len(rows) == 2
        assert {row.kind for row in rows} == {"Deployment", "StatefulSet"}
        assert {row.name for row in rows} == {"api", "db"}

    def test_format_util_stats_uses_max_avg_p95_order(
        self,
        controller: ClusterController,
    ) -> None:
        """Utilization stats should be formatted as max/avg/p95."""
        values = [float(value) for value in range(1, 21)]

        formatted = controller._format_util_stats(values)

        assert formatted == ("20%", "10%", "19%")

    def test_apply_workload_pod_runtime_stats_includes_pod_node_assignments_for_deployment(
        self,
        controller: ClusterController,
    ) -> None:
        """Deployment workload rows should include pod-to-node mapping and util stats."""
        row = WorkloadInventoryInfo(
            name="api",
            namespace="team-a",
            kind="Deployment",
            desired_replicas=2,
            ready_replicas=2,
            status="Ready",
        )

        pods = [
            {
                "metadata": {
                    "name": "api-5d4c8f9b6d-abcde",
                    "namespace": "team-a",
                    "labels": {"pod-template-hash": "5d4c8f9b6d"},
                    "ownerReferences": [
                        {
                            "kind": "ReplicaSet",
                            "name": "api-5d4c8f9b6d",
                            "controller": True,
                        }
                    ],
                },
                "spec": {
                    "nodeName": "node-a",
                    "containers": [
                        {
                            "name": "api",
                            "resources": {
                                "requests": {
                                    "cpu": "100m",
                                    "memory": "100Mi",
                                },
                                "limits": {
                                    "cpu": "200m",
                                    "memory": "200Mi",
                                },
                            },
                        }
                    ],
                },
            },
            {
                "metadata": {
                    "name": "api-5d4c8f9b6d-fghij",
                    "namespace": "team-a",
                    "labels": {"pod-template-hash": "5d4c8f9b6d"},
                    "ownerReferences": [
                        {
                            "kind": "ReplicaSet",
                            "name": "api-5d4c8f9b6d",
                            "controller": True,
                        }
                    ],
                },
                "spec": {
                    "nodeName": "node-b",
                    "containers": [
                        {
                            "name": "api",
                            "resources": {
                                "requests": {
                                    "cpu": "100m",
                                    "memory": "100Mi",
                                },
                                "limits": {
                                    "cpu": "200m",
                                    "memory": "200Mi",
                                },
                            },
                        }
                    ],
                },
            },
        ]

        node_utilization_by_name = {
            "node-a": {
                "cpu_req_pct": 60.0,
                "cpu_lim_pct": 30.0,
                "mem_req_pct": 50.0,
                "mem_lim_pct": 25.0,
            },
            "node-b": {
                "cpu_req_pct": 80.0,
                "cpu_lim_pct": 40.0,
                "mem_req_pct": 70.0,
                "mem_lim_pct": 35.0,
            },
        }

        controller._apply_workload_pod_runtime_stats(
            [row],
            pods,
            node_utilization_by_name,
        )

        assert row.assigned_nodes == "2"
        assert row.cpu_req_util_max == "80%"
        assert row.cpu_req_util_avg == "70%"
        assert row.cpu_req_util_p95 == "80%"
        assert row.cpu_lim_util_max == "40%"
        assert row.cpu_lim_util_avg == "35%"
        assert row.cpu_lim_util_p95 == "40%"
        assert row.mem_req_util_max == "70%"
        assert row.mem_req_util_avg == "60%"
        assert row.mem_req_util_p95 == "70%"
        assert row.mem_lim_util_max == "35%"
        assert row.mem_lim_util_avg == "30%"
        assert row.mem_lim_util_p95 == "35%"

    def test_apply_workload_pod_runtime_stats_maps_deployment_without_owner_references(
        self,
        controller: ClusterController,
    ) -> None:
        """Deployment pods should map via pod-name fallback when owner refs are absent."""
        row = WorkloadInventoryInfo(
            name="api",
            namespace="team-a",
            kind="Deployment",
            desired_replicas=1,
            ready_replicas=1,
            status="Ready",
        )

        pods = [
            {
                "metadata": {
                    "name": "api-5d4c8f9b6d-abcde",
                    "namespace": "team-a",
                    "labels": {},
                },
                "spec": {
                    "nodeName": "node-a",
                    "containers": [
                        {
                            "name": "api",
                            "resources": {
                                "requests": {
                                    "cpu": "100m",
                                    "memory": "100Mi",
                                },
                                "limits": {
                                    "cpu": "200m",
                                    "memory": "200Mi",
                                },
                            },
                        }
                    ],
                },
            }
        ]

        node_utilization_by_name = {
            "node-a": {
                "cpu_req_pct": 50.0,
                "cpu_lim_pct": 25.0,
                "mem_req_pct": 40.0,
                "mem_lim_pct": 20.0,
            },
        }

        controller._apply_workload_pod_runtime_stats(
            [row],
            pods,
            node_utilization_by_name,
        )

        assert row.assigned_nodes == "1"
        assert row.cpu_req_util_max == "50%"
        assert row.cpu_req_util_avg == "50%"
        assert row.cpu_req_util_p95 == "50%"
        assert row.cpu_lim_util_max == "25%"
        assert row.cpu_lim_util_avg == "25%"
        assert row.cpu_lim_util_p95 == "25%"

    def test_apply_workload_pod_runtime_stats_supports_statefulset_rows(
        self,
        controller: ClusterController,
    ) -> None:
        """Node-based utilization should be populated for non-Deployment workloads."""
        row = WorkloadInventoryInfo(
            name="db",
            namespace="team-a",
            kind="StatefulSet",
            desired_replicas=1,
            ready_replicas=1,
            status="Ready",
        )
        pods = [
            {
                "metadata": {
                    "name": "db-0",
                    "namespace": "team-a",
                    "labels": {},
                    "ownerReferences": [
                        {"kind": "StatefulSet", "name": "db", "controller": True}
                    ],
                },
                "spec": {"nodeName": "node-db"},
            }
        ]
        node_utilization_by_name = {
            "node-db": {
                "cpu_req_pct": 82.0,
                "cpu_lim_pct": 104.0,
                "mem_req_pct": 76.0,
                "mem_lim_pct": 97.0,
            }
        }

        controller._apply_workload_pod_runtime_stats(
            [row],
            pods,
            node_utilization_by_name,
        )

        assert row.assigned_nodes == "1"
        assert row.cpu_req_util_avg == "82%"
        assert row.cpu_lim_util_avg == "104%"
        assert row.mem_req_util_avg == "76%"
        assert row.mem_lim_util_avg == "97%"

    @pytest.mark.asyncio
    async def test_enrich_workload_runtime_stats_timeout_uses_cached_pods_fallback(
        self,
        controller: ClusterController,
    ) -> None:
        """Timeout path should still enrich rows by using cached pods."""
        row = WorkloadInventoryInfo(
            name="api",
            namespace="team-a",
            kind="Deployment",
            desired_replicas=1,
            ready_replicas=1,
            status="Ready",
        )
        cached_pod = {
            "metadata": {
                "name": "api-5d4c8f9b6d-abcde",
                "namespace": "team-a",
                "labels": {"pod-template-hash": "5d4c8f9b6d"},
                "ownerReferences": [
                    {
                        "kind": "ReplicaSet",
                        "name": "api-5d4c8f9b6d",
                        "controller": True,
                    }
                ],
            },
            "spec": {
                "nodeName": "node-a",
                "containers": [
                    {
                        "name": "api",
                        "resources": {
                            "requests": {"cpu": "100m", "memory": "100Mi"},
                            "limits": {"cpu": "200m", "memory": "200Mi"},
                        },
                    }
                ],
            },
            "status": {"phase": "Running"},
        }
        controller._pods_cache = [cached_pod]

        async def _slow_incremental(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            await asyncio.sleep(0.05)
            return []

        controller._pod_fetcher.fetch_pods = AsyncMock(  # type: ignore[method-assign]
            side_effect=_slow_incremental
        )
        controller._node_fetcher.fetch_nodes_raw = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "metadata": {
                        "name": "node-a",
                        "labels": {
                            "eks.amazonaws.com/nodegroup": "ng-a",
                            "node.kubernetes.io/instance-type": "m5.large",
                            "topology.kubernetes.io/zone": "us-east-1a",
                        },
                    },
                    "spec": {},
                    "status": {
                        "allocatable": {
                            "cpu": "200m",
                            "memory": "200Mi",
                            "pods": "110",
                        },
                        "conditions": [{"type": "Ready", "status": "True"}],
                        "nodeInfo": {"kubeletVersion": "v1.29.0"},
                    },
                }
            ]
        )

        rows = await controller.enrich_workload_runtime_stats(
            [row],
            timeout_seconds=0.01,
        )

        assert rows[0].assigned_nodes == "1"
        assert rows[0].cpu_req_util_max == "50%"
        assert rows[0].cpu_req_util_avg == "50%"
        assert rows[0].cpu_req_util_p95 == "50%"

    def test_apply_workload_runtime_stats_with_lookup_populates_aggregate_and_detail_payloads(
        self,
        controller: ClusterController,
    ) -> None:
        """Node-analysis enrichment should populate aggregate and drill-down fields."""
        row = WorkloadInventoryInfo(
            name="api",
            namespace="team-a",
            kind="Deployment",
            desired_replicas=2,
            ready_replicas=2,
            status="Ready",
        )
        pod_a = {
            "metadata": {"name": "api-a", "namespace": "team-a"},
            "status": {"phase": "Running"},
            "spec": {
                "nodeName": "node-a",
                "containers": [
                    {
                        "resources": {
                            "requests": {"cpu": "400m", "memory": "1Gi"},
                            "limits": {"cpu": "800m", "memory": "2Gi"},
                        }
                    }
                ],
            },
        }
        pod_b = {
            "metadata": {"name": "api-b", "namespace": "team-a"},
            "status": {"phase": "Running"},
            "spec": {
                "nodeName": "node-b",
                "containers": [
                    {
                        "resources": {
                            "requests": {"cpu": "200m", "memory": "512Mi"},
                            "limits": {"cpu": "400m", "memory": "1Gi"},
                        }
                    }
                ],
            },
        }
        workload_pods = {("team-a", "Deployment", "api"): [pod_a, pod_b]}

        controller._apply_workload_runtime_stats_with_lookup(
            [row],
            workload_pods,
            node_utilization_by_name={
                "node-a": {
                    "cpu_req_pct": 70.0,
                    "cpu_lim_pct": 40.0,
                    "mem_req_pct": 60.0,
                    "mem_lim_pct": 30.0,
                },
                "node-b": {
                    "cpu_req_pct": 50.0,
                    "cpu_lim_pct": 20.0,
                    "mem_req_pct": 40.0,
                    "mem_lim_pct": 15.0,
                },
            },
            node_allocatable_by_name={
                "node-a": {
                    "cpu_allocatable_mcores": 4000.0,
                    "memory_allocatable_bytes": 8 * 1024 * 1024 * 1024,
                    "node_group": "ng-a",
                },
                "node-b": {
                    "cpu_allocatable_mcores": 2000.0,
                    "memory_allocatable_bytes": 4 * 1024 * 1024 * 1024,
                    "node_group": "ng-b",
                },
            },
            top_node_usage_by_name={
                "node-a": {
                    "cpu_mcores": 1000.0,
                    "memory_bytes": 2 * 1024 * 1024 * 1024,
                },
                "node-b": {
                    "cpu_mcores": 500.0,
                    "memory_bytes": 1024 * 1024 * 1024,
                },
            },
            top_pod_usage_by_key={
                ("team-a", "api-a"): {
                    "cpu_mcores": 250.0,
                    "memory_bytes": 1024 * 1024 * 1024,
                },
                ("team-a", "api-b"): {
                    "cpu_mcores": 100.0,
                    "memory_bytes": 512 * 1024 * 1024,
                },
            },
        )

        assert row.assigned_nodes == "2"
        assert row.pod_count == 2
        assert row.cpu_req_util_avg == "60%"
        assert row.node_real_cpu_max == "1000m (25%)"
        assert row.node_real_cpu_avg == "750m (25%)"
        assert row.pod_real_cpu_max == "250m (6.2%)"
        assert row.pod_real_cpu_avg == "175m (5.6%)"
        assert row.pod_real_memory_avg == "768.0Mi (12%)"
        assert len(row.assigned_node_details) == 2
        node_a_detail = next(
            detail for detail in row.assigned_node_details if detail.node_name == "node-a"
        )
        assert node_a_detail.node_group == "ng-a"
        assert node_a_detail.workload_pod_count_on_node == 1
        assert node_a_detail.node_cpu_req_pct == pytest.approx(70.0)
        assert node_a_detail.node_real_cpu_pct_of_allocatable == pytest.approx(25.0)
        assert node_a_detail.node_real_memory_pct_of_allocatable == pytest.approx(25.0)
        assert (
            node_a_detail.workload_pod_real_cpu_pct_of_node_allocatable
            == pytest.approx(6.25)
        )
        assert (
            node_a_detail.workload_pod_real_memory_pct_of_node_allocatable
            == pytest.approx(12.5)
        )

        assert len(row.assigned_pod_details) == 2
        pod_a_detail = next(
            detail for detail in row.assigned_pod_details if detail.pod_name == "api-a"
        )
        assert pod_a_detail.pod_cpu_pct_of_node_allocatable == pytest.approx(6.25)
        assert pod_a_detail.pod_memory_pct_of_node_allocatable == pytest.approx(12.5)

    def test_apply_workload_runtime_stats_with_lookup_populates_restart_counts(
        self,
        controller: ClusterController,
    ) -> None:
        """Restart count should aggregate all container status restart counters."""
        row = WorkloadInventoryInfo(
            name="api",
            namespace="team-a",
            kind="Deployment",
            desired_replicas=1,
            ready_replicas=1,
            status="Ready",
        )
        workload_pods = {
            ("team-a", "Deployment", "api"): [
                {
                    "metadata": {"name": "api-a", "namespace": "team-a"},
                    "status": {
                        "phase": "Running",
                        "containerStatuses": [
                            {"restartCount": 2},
                            {
                                "restartCount": 1,
                                "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                                "lastState": {"terminated": {"exitCode": 137}},
                            },
                        ],
                        "initContainerStatuses": [{"restartCount": 3}],
                    },
                    "spec": {"nodeName": "node-a"},
                },
                {
                    "metadata": {"name": "api-b", "namespace": "team-a"},
                    "status": {
                        "phase": "Running",
                        "containerStatuses": [{"restartCount": 4}],
                        "ephemeralContainerStatuses": [{"restartCount": 1}],
                    },
                    "spec": {"nodeName": "node-b"},
                },
            ]
        }

        controller._apply_workload_runtime_stats_with_lookup(
            [row],
            workload_pods,
            node_utilization_by_name={},
            node_allocatable_by_name={},
            top_node_usage_by_name={},
            top_pod_usage_by_key={},
        )

        assert row.pod_count == 2
        assert row.restart_count == 11
        assert row.restart_reason_counts == {"CrashLoopBackOff": 1, "Unknown": 10}
        assert len(row.assigned_pod_details) == 2
        pod_a_detail = next(
            detail for detail in row.assigned_pod_details if detail.pod_name == "api-a"
        )
        assert pod_a_detail.restart_reason == "CrashLoopBackOff"
        assert pod_a_detail.last_exit_code == 137

    def test_apply_workload_runtime_stats_with_lookup_gracefully_handles_missing_metrics(
        self,
        controller: ClusterController,
    ) -> None:
        """Missing top metrics should not block row enrichment or detail rendering."""
        row = WorkloadInventoryInfo(
            name="api",
            namespace="team-a",
            kind="Deployment",
            desired_replicas=1,
            ready_replicas=1,
            status="Ready",
        )
        workload_pods = {
            ("team-a", "Deployment", "api"): [
                {
                    "metadata": {"name": "api-a", "namespace": "team-a"},
                    "status": {"phase": "Running"},
                    "spec": {"nodeName": "node-a"},
                }
            ]
        }

        controller._apply_workload_runtime_stats_with_lookup(
            [row],
            workload_pods,
            node_utilization_by_name={
                "node-a": {
                    "cpu_req_pct": 50.0,
                    "cpu_lim_pct": 20.0,
                    "mem_req_pct": 45.0,
                    "mem_lim_pct": 15.0,
                }
            },
            node_allocatable_by_name={},
            top_node_usage_by_name={},
            top_pod_usage_by_key={},
        )

        assert row.assigned_nodes == "1"
        assert row.node_real_cpu_avg == "-"
        assert row.node_real_memory_avg == "-"
        assert row.pod_real_cpu_avg == "-"
        assert row.pod_real_memory_avg == "-"
        assert len(row.assigned_node_details) == 1
        assert len(row.assigned_pod_details) == 1
        assert row.assigned_pod_details[0].pod_cpu_pct_of_node_allocatable is None
        assert row.assigned_pod_details[0].pod_memory_pct_of_node_allocatable is None

    @pytest.mark.asyncio
    async def test_enrich_workload_runtime_stats_records_nonfatal_top_metric_warnings(
        self,
        controller: ClusterController,
    ) -> None:
        """Top metrics fetch failures should be exposed as nonfatal warnings."""
        row = WorkloadInventoryInfo(
            name="api",
            namespace="team-a",
            kind="Deployment",
            desired_replicas=1,
            ready_replicas=1,
            status="Ready",
        )

        controller._pod_fetcher.fetch_pods = AsyncMock(return_value=[])  # type: ignore[method-assign]
        controller._node_fetcher.fetch_nodes_raw = AsyncMock(return_value=[])  # type: ignore[method-assign]
        controller._top_metrics_fetcher.fetch_top_nodes = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("top node unavailable")
        )
        controller._top_metrics_fetcher.fetch_top_pods_all_namespaces = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("top pod unavailable")
        )

        await controller.enrich_workload_runtime_stats([row], timeout_seconds=1.0)

        warnings = controller.get_last_nonfatal_warnings()
        assert "top_nodes" in warnings
        assert "top_pods" in warnings
        assert "unavailable" in warnings["top_nodes"]
        assert "unavailable" in warnings["top_pods"]
