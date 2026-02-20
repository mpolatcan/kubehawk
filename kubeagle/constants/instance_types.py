"""Default AWS EC2 instance type specifications for node estimation."""

from __future__ import annotations

# Fraction of instance resources allocatable by Kubernetes
# (after kubelet, system reservation, eviction thresholds)
ALLOCATABLE_RATIO: float = 0.92

# Default overhead percentage for system pods, daemonsets, kube-system workloads
DEFAULT_OVERHEAD_PCT: float = 0.15

# Hours per month for cost calculations (365 * 24 / 12)
HOURS_PER_MONTH: float = 730.0

# Default instance types for node estimation
# Format: (name, vcpus, memory_gib, on_demand_hourly_usd, spot_hourly_usd)
DEFAULT_INSTANCE_TYPES: list[tuple[str, int, float, float, float]] = [
    ("m5.large", 2, 8.0, 0.096, 0.035),
    ("m5.xlarge", 4, 16.0, 0.192, 0.067),
    ("m5.2xlarge", 8, 32.0, 0.384, 0.134),
    ("m5.4xlarge", 16, 64.0, 0.768, 0.268),
    ("m6i.large", 2, 8.0, 0.096, 0.034),
    ("m6i.xlarge", 4, 16.0, 0.192, 0.067),
]

# Spot price lookup for common instance types (us-east-1 approximate averages)
# Used to estimate costs for cluster nodes where only instance_type is known.
SPOT_PRICES: dict[str, float] = {
    # M5 family
    "m5.large": 0.035,
    "m5.xlarge": 0.067,
    "m5.2xlarge": 0.134,
    "m5.4xlarge": 0.268,
    "m5.8xlarge": 0.536,
    "m5.12xlarge": 0.804,
    "m5.16xlarge": 1.072,
    "m5.24xlarge": 1.608,
    # M6i family
    "m6i.large": 0.034,
    "m6i.xlarge": 0.067,
    "m6i.2xlarge": 0.134,
    "m6i.4xlarge": 0.268,
    "m6i.8xlarge": 0.536,
    "m6i.12xlarge": 0.804,
    "m6i.16xlarge": 1.072,
    "m6i.24xlarge": 1.608,
    # M7i family
    "m7i.large": 0.036,
    "m7i.xlarge": 0.071,
    "m7i.2xlarge": 0.142,
    "m7i.4xlarge": 0.284,
    "m7i.8xlarge": 0.568,
    "m7i.12xlarge": 0.852,
    "m7i.16xlarge": 1.136,
    "m7i.24xlarge": 1.704,
    # C5 family
    "c5.large": 0.031,
    "c5.xlarge": 0.062,
    "c5.2xlarge": 0.124,
    "c5.4xlarge": 0.248,
    "c5.9xlarge": 0.558,
    "c5.12xlarge": 0.744,
    "c5.18xlarge": 1.116,
    "c5.24xlarge": 1.488,
    # C6i family
    "c6i.large": 0.030,
    "c6i.xlarge": 0.061,
    "c6i.2xlarge": 0.122,
    "c6i.4xlarge": 0.243,
    "c6i.8xlarge": 0.486,
    "c6i.12xlarge": 0.729,
    "c6i.16xlarge": 0.972,
    "c6i.24xlarge": 1.458,
    # R5 family (memory-optimized)
    "r5.large": 0.038,
    "r5.xlarge": 0.076,
    "r5.2xlarge": 0.152,
    "r5.4xlarge": 0.304,
    "r5.8xlarge": 0.608,
    "r5.12xlarge": 0.912,
    "r5.16xlarge": 1.216,
    "r5.24xlarge": 1.824,
    # R6i family
    "r6i.large": 0.038,
    "r6i.xlarge": 0.075,
    "r6i.2xlarge": 0.150,
    "r6i.4xlarge": 0.300,
    "r6i.8xlarge": 0.600,
    "r6i.12xlarge": 0.900,
    "r6i.16xlarge": 1.200,
    "r6i.24xlarge": 1.800,
    # T3 family (burstable)
    "t3.medium": 0.013,
    "t3.large": 0.026,
    "t3.xlarge": 0.053,
    "t3.2xlarge": 0.106,
}
