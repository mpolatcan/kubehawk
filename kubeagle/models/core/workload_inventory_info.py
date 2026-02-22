"""Runtime workload inventory models."""

from pydantic import BaseModel, Field


class WorkloadAssignedNodeDetailInfo(BaseModel):
    """Assigned-node detail for one workload row."""

    node_name: str
    node_group: str = "Unknown"
    workload_pod_count_on_node: int = 0
    node_cpu_req_pct: float | None = None
    node_cpu_lim_pct: float | None = None
    node_mem_req_pct: float | None = None
    node_mem_lim_pct: float | None = None
    node_real_cpu_mcores: float | None = None
    node_real_memory_bytes: float | None = None
    node_real_cpu_pct_of_allocatable: float | None = None
    node_real_memory_pct_of_allocatable: float | None = None
    workload_pod_real_cpu_mcores_on_node: float | None = None
    workload_pod_real_memory_bytes_on_node: float | None = None
    workload_pod_real_cpu_pct_of_node_allocatable: float | None = None
    workload_pod_real_memory_pct_of_node_allocatable: float | None = None


class WorkloadAssignedPodDetailInfo(BaseModel):
    """Assigned-pod detail for one workload row."""

    namespace: str
    pod_name: str
    node_name: str = "-"
    pod_phase: str = "Unknown"
    pod_real_cpu_mcores: float | None = None
    pod_real_memory_bytes: float | None = None
    node_cpu_allocatable_mcores: float | None = None
    node_memory_allocatable_bytes: float | None = None
    pod_cpu_pct_of_node_allocatable: float | None = None
    pod_memory_pct_of_node_allocatable: float | None = None
    restart_reason: str | None = None
    last_exit_code: int | None = None


class WorkloadLiveUsageSampleInfo(BaseModel):
    """Point-in-time workload usage sample for live chart polling."""

    timestamp_epoch: float
    namespace: str
    workload_kind: str
    workload_name: str
    pod_count: int = 0
    node_count: int = 0
    pods_with_metrics: int = 0
    nodes_with_metrics: int = 0
    workload_cpu_mcores: float | None = None
    workload_memory_bytes: float | None = None


class WorkloadInventoryInfo(BaseModel):
    """Live Kubernetes workload inventory row for the Workloads tab."""

    name: str
    namespace: str
    kind: str
    desired_replicas: int | None
    ready_replicas: int | None
    status: str
    helm_release: str | None = None
    has_pdb: bool = False
    cpu_request: float = 0.0
    cpu_limit: float = 0.0
    memory_request: float = 0.0
    memory_limit: float = 0.0
    assigned_nodes: str = "-"
    cpu_req_util_max: str = "-"
    cpu_req_util_avg: str = "-"
    cpu_req_util_p95: str = "-"
    cpu_lim_util_max: str = "-"
    cpu_lim_util_avg: str = "-"
    cpu_lim_util_p95: str = "-"
    mem_req_util_max: str = "-"
    mem_req_util_avg: str = "-"
    mem_req_util_p95: str = "-"
    mem_lim_util_max: str = "-"
    mem_lim_util_avg: str = "-"
    mem_lim_util_p95: str = "-"
    pod_count: int = 0
    restart_count: int = 0
    restart_reason_counts: dict[str, int] = Field(default_factory=dict)
    node_real_cpu_avg: str = "-"
    node_real_cpu_max: str = "-"
    node_real_cpu_p95: str = "-"
    node_real_memory_avg: str = "-"
    node_real_memory_max: str = "-"
    node_real_memory_p95: str = "-"
    pod_real_cpu_avg: str = "-"
    pod_real_cpu_max: str = "-"
    pod_real_cpu_p95: str = "-"
    pod_real_memory_avg: str = "-"
    pod_real_memory_max: str = "-"
    pod_real_memory_p95: str = "-"
    assigned_node_details: list[WorkloadAssignedNodeDetailInfo] = Field(default_factory=list)
    assigned_pod_details: list[WorkloadAssignedPodDetailInfo] = Field(default_factory=list)
