"""Resource impact analysis models for before/after optimization comparison."""

from __future__ import annotations

from pydantic import BaseModel


class ChartResourceSnapshot(BaseModel):
    """Per-chart resource snapshot (before or after optimization)."""

    name: str
    team: str
    replicas: int
    cpu_request_per_replica: float  # millicores
    cpu_limit_per_replica: float  # millicores
    memory_request_per_replica: float  # bytes
    memory_limit_per_replica: float  # bytes
    cpu_request_total: float  # millicores
    cpu_limit_total: float  # millicores
    memory_request_total: float  # bytes
    memory_limit_total: float  # bytes


class FleetResourceSummary(BaseModel):
    """Aggregated fleet resource totals."""

    cpu_request_total: float  # millicores
    cpu_limit_total: float  # millicores
    memory_request_total: float  # bytes
    memory_limit_total: float  # bytes
    chart_count: int
    total_replicas: int


class ResourceDelta(BaseModel):
    """Delta between before and after resource summaries."""

    cpu_request_diff: float  # millicores
    cpu_limit_diff: float  # millicores
    memory_request_diff: float  # bytes
    memory_limit_diff: float  # bytes
    cpu_request_pct: float  # percentage change
    cpu_limit_pct: float  # percentage change
    memory_request_pct: float  # percentage change
    memory_limit_pct: float  # percentage change
    replicas_diff: int
    replicas_pct: float


class InstanceTypeSpec(BaseModel):
    """AWS EC2 instance type specification."""

    name: str
    vcpus: int
    memory_gib: float
    cpu_millicores: int  # vcpus * 1000
    memory_bytes: int  # memory_gib * 1024^3
    hourly_price_usd: float  # on-demand price
    spot_price_usd: float  # spot price


class NodeEstimation(BaseModel):
    """Node estimation for a specific instance type."""

    instance_type: str
    vcpus: int
    memory_gib: float
    nodes_before: int
    nodes_after: int
    reduction: int
    reduction_pct: float
    spot_price_usd: float  # per-node hourly spot price
    cost_before_monthly: float  # nodes_before * spot_price * hours_per_month
    cost_after_monthly: float  # nodes_after * spot_price * hours_per_month
    cost_savings_monthly: float  # cost_before - cost_after


class ClusterNodeGroup(BaseModel):
    """Actual cluster node group aggregated by instance type."""

    instance_type: str
    node_count: int
    cpu_allocatable_per_node: float  # millicores
    memory_allocatable_per_node: float  # bytes
    cpu_allocatable_total: float  # millicores
    memory_allocatable_total: float  # bytes
    nodes_needed_after: int
    reduction: int
    reduction_pct: float
    spot_price_usd: float  # per-node hourly spot price (0.0 if unknown)
    cost_current_monthly: float  # node_count * spot_price * hours_per_month
    cost_after_monthly: float  # nodes_needed_after * spot_price * hours_per_month
    cost_savings_monthly: float  # cost_current - cost_after


class ResourceImpactResult(BaseModel):
    """Complete resource impact analysis result."""

    before: FleetResourceSummary
    after: FleetResourceSummary
    delta: ResourceDelta
    before_charts: list[ChartResourceSnapshot]
    after_charts: list[ChartResourceSnapshot]
    node_estimations: list[NodeEstimation]
    cluster_node_groups: list[ClusterNodeGroup] = []
    total_spot_savings_monthly: float = 0.0  # sum of all group/estimation savings
