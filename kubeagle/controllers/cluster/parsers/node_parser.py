"""Node parser for cluster controller - parses node data into structured formats."""

from __future__ import annotations

from kubeagle.constants.enums import NodeStatus
from kubeagle.models.core.node_info import NodeResourceInfo
from kubeagle.utils.resource_parser import memory_str_to_bytes, parse_cpu


class NodeParser:
    """Parses node data into structured formats."""

    # Label constants
    _NODE_GROUP_LABELS = (
        "eks.amazonaws.com/nodegroup",
        "alpha.eksctl.io/nodegroup-name",
        "karpenter.sh/nodepool",
        "karpenter.sh/provisioner-name",
        "kops.k8s.io/instancegroup",
    )
    _INSTANCE_TYPE_LABELS = (
        "node.kubernetes.io/instance-type",
        "beta.kubernetes.io/instance-type",
    )
    _AZ_LABELS = (
        "topology.kubernetes.io/zone",
        "failure-domain.beta.kubernetes.io/zone",
    )

    def __init__(self) -> None:
        """Initialize node parser."""
        pass

    def _get_label_value(
        self, labels: dict[str, str], label_tuples: tuple[str, ...], default: str = "Unknown"
    ) -> str:
        """Extract label value from labels dict using ordered label tuples."""
        for label in label_tuples:
            value = labels.get(label)
            if value:
                return value
        return default

    def parse_node_info(
        self,
        node: dict,
        cpu_requests: float = 0,
        memory_requests: float = 0,
        cpu_limits: float = 0,
        memory_limits: float = 0,
        pod_count: int = 0,
    ) -> NodeResourceInfo:
        """Parse a single node into NodeResourceInfo.

        Args:
            node: Raw node dictionary from API
            cpu_requests: CPU requests in millicores
            memory_requests: Memory requests in bytes
            cpu_limits: CPU limits in millicores
            memory_limits: Memory limits in bytes
            pod_count: Number of running/pending pods on this node

        Returns:
            NodeResourceInfo object.
        """
        metadata = node.get("metadata", {})
        status = node.get("status", {})
        spec = node.get("spec", {})
        labels = metadata.get("labels", {})

        node_name = metadata.get("name", "Unknown")

        # Node group
        node_group = self._get_label_value(labels, self._NODE_GROUP_LABELS)

        # Instance type
        instance_type = self._get_label_value(labels, self._INSTANCE_TYPE_LABELS)

        # Availability zone
        az = self._get_label_value(labels, self._AZ_LABELS)

        # Allocatable resources
        allocatable = status.get("allocatable", {})
        cpu_allocatable = parse_cpu(allocatable.get("cpu", "0")) * 1000  # millicores
        memory_allocatable = memory_str_to_bytes(allocatable.get("memory", "0Ki"))

        # Max pods
        max_pods_str = allocatable.get("pods", "110")
        try:
            max_pods = int(float(max_pods_str))
        except (ValueError, TypeError):
            max_pods = 110

        # Node conditions for health status
        conditions = {
            c["type"]: c["status"]
            for c in status.get("conditions", [])
            if "type" in c and "status" in c
        }
        is_ready = conditions.get("Ready") == "True"
        is_healthy = is_ready and not any(
            conditions.get(p) == "True"
            for p in ("MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable")
        )
        is_cordoned = spec.get("unschedulable", False)

        # Calculate percentages
        cpu_req_pct = (cpu_requests / cpu_allocatable * 100) if cpu_allocatable > 0 else 0.0
        cpu_lim_pct = (cpu_limits / cpu_allocatable * 100) if cpu_allocatable > 0 else 0.0
        mem_req_pct = (memory_requests / memory_allocatable * 100) if memory_allocatable > 0 else 0.0
        mem_lim_pct = (memory_limits / memory_allocatable * 100) if memory_allocatable > 0 else 0.0
        pod_pct = (pod_count / max_pods * 100) if max_pods > 0 else 0.0

        return NodeResourceInfo(
            name=node_name,
            status=NodeStatus.READY if is_ready else NodeStatus.NOT_READY,
            node_group=node_group,
            instance_type=instance_type,
            availability_zone=az,
            kubelet_version=status.get("nodeInfo", {}).get("kubeletVersion", "Unknown"),
            cpu_allocatable=cpu_allocatable,
            memory_allocatable=memory_allocatable,
            max_pods=max_pods,
            cpu_requests=cpu_requests,
            cpu_limits=cpu_limits,
            memory_requests=memory_requests,
            memory_limits=memory_limits,
            pod_count=pod_count,
            cpu_req_pct=cpu_req_pct,
            cpu_lim_pct=cpu_lim_pct,
            mem_req_pct=mem_req_pct,
            mem_lim_pct=mem_lim_pct,
            pod_pct=pod_pct,
            is_ready=is_ready,
            is_healthy=is_healthy,
            is_cordoned=is_cordoned,
            conditions=conditions,
            taints=spec.get("taints", []),
        )
