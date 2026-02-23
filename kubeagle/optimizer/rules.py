"""Optimization rules for Helm chart best practices enforcement."""

from __future__ import annotations

from kubeagle.constants.optimizer import (
    CPU_BUMP_MIN_MILLICORES as DEFAULT_CPU_BUMP_MIN_MILLICORES,
    LIMIT_REQUEST_RATIO_THRESHOLD as DEFAULT_LIMIT_REQUEST_RATIO_THRESHOLD,
    LOW_CPU_THRESHOLD_MILLICORES as DEFAULT_LOW_CPU_THRESHOLD_MILLICORES,
    LOW_MEMORY_THRESHOLD_MI as DEFAULT_LOW_MEMORY_THRESHOLD_MI,
    MEMORY_BUMP_MIN_MI as DEFAULT_MEMORY_BUMP_MIN_MI,
    PDB_BLOCKING_THRESHOLD as DEFAULT_PDB_BLOCKING_THRESHOLD,
)
from kubeagle.models.optimization.optimization_rule import OptimizationRule
from kubeagle.models.optimization.optimization_violation import (
    OptimizationViolation,
)

# Runtime thresholds (defaults align with shared constants and can be updated from settings).
LIMIT_REQUEST_RATIO_THRESHOLD = DEFAULT_LIMIT_REQUEST_RATIO_THRESHOLD
LOW_CPU_THRESHOLD_MILLICORES = DEFAULT_LOW_CPU_THRESHOLD_MILLICORES
LOW_MEMORY_THRESHOLD_MI = DEFAULT_LOW_MEMORY_THRESHOLD_MI
PDB_BLOCKING_THRESHOLD = DEFAULT_PDB_BLOCKING_THRESHOLD
CPU_BUMP_MIN_MILLICORES = DEFAULT_CPU_BUMP_MIN_MILLICORES
MEMORY_BUMP_MIN_MI = DEFAULT_MEMORY_BUMP_MIN_MI
BURSTABLE_TARGET_RATIO = 1.5

# Resource fields currently protected from optimizer modifications.
# Updated at runtime via configure_rule_thresholds().
FIXED_RESOURCE_FIELDS: set[str] = {"cpu_limit", "memory_limit"}


def configure_rule_thresholds(
    *,
    limit_request_ratio_threshold: float | None = None,
    low_cpu_threshold_millicores: int | None = None,
    low_memory_threshold_mi: int | None = None,
    pdb_blocking_threshold: int | None = None,
    fixed_resource_fields: set[str] | None = None,
) -> None:
    """Update rule thresholds at runtime."""
    global LIMIT_REQUEST_RATIO_THRESHOLD
    global LOW_CPU_THRESHOLD_MILLICORES
    global LOW_MEMORY_THRESHOLD_MI
    global PDB_BLOCKING_THRESHOLD
    global FIXED_RESOURCE_FIELDS

    if (
        limit_request_ratio_threshold is not None
        and limit_request_ratio_threshold > 0
    ):
        LIMIT_REQUEST_RATIO_THRESHOLD = limit_request_ratio_threshold
    if low_cpu_threshold_millicores is not None and low_cpu_threshold_millicores > 0:
        LOW_CPU_THRESHOLD_MILLICORES = low_cpu_threshold_millicores
    if low_memory_threshold_mi is not None and low_memory_threshold_mi > 0:
        LOW_MEMORY_THRESHOLD_MI = low_memory_threshold_mi
    if pdb_blocking_threshold is not None and pdb_blocking_threshold > 0:
        PDB_BLOCKING_THRESHOLD = pdb_blocking_threshold
    if fixed_resource_fields is not None:
        FIXED_RESOURCE_FIELDS = fixed_resource_fields


def _parse_cpu(cpu_str: str | None) -> float | None:
    """Parse CPU string to millicores (for internal rule checking)."""
    if not cpu_str:
        return None
    cpu_str = str(cpu_str).strip()

    # Handle millicores (e.g., "100m" -> 100.0)
    if cpu_str.endswith("m"):
        try:
            return float(cpu_str[:-1])
        except ValueError:
            return None

    # Handle plain numbers (cores)
    try:
        return float(cpu_str) * 1000  # Convert cores to millicores
    except ValueError:
        return None


def _parse_memory(mem_str: str | None) -> float | None:
    """Parse memory string to Mi."""
    if not mem_str:
        return None
    mem_str = str(mem_str).strip().lower()

    # Unit multipliers for conversion to Mi
    multipliers: dict[str, float] = {
        "ki": 1 / 1024,
        "mi": 1,
        "gi": 1024,
        "ti": 1024 * 1024,
    }

    for suffix, multiplier in multipliers.items():
        if mem_str.endswith(suffix):
            try:
                return float(mem_str[: -len(suffix)]) * multiplier
            except ValueError:
                return None

    # Plain number (no suffix) - treat as Mi
    try:
        return float(mem_str)
    except ValueError:
        return None


def _normalize_qos_class(raw_qos: object) -> str | None:
    """Normalize QoS input that may arrive as enum value or plain string."""
    if raw_qos is None:
        return None
    value = getattr(raw_qos, "value", raw_qos)
    text = str(value).strip()
    return text or None


def _is_best_effort_qos(chart: dict) -> bool:
    """Return True when chart is explicitly or effectively BestEffort."""
    qos_class = _normalize_qos_class(chart.get("qos_class"))
    if qos_class is not None:
        return qos_class.lower() == "besteffort"

    resources = chart.get("resources", {})
    resources_dict = resources if isinstance(resources, dict) else {}
    requests = resources_dict.get("requests")
    limits = resources_dict.get("limits")
    requests_dict = requests if isinstance(requests, dict) else {}
    limits_dict = limits if isinstance(limits, dict) else {}

    parsed_values = (
        _parse_cpu(requests_dict.get("cpu")),
        _parse_cpu(limits_dict.get("cpu")),
        _parse_memory(requests_dict.get("memory")),
        _parse_memory(limits_dict.get("memory")),
    )
    has_any_resources = any(value is not None and value > 0 for value in parsed_values)
    return not has_any_resources


def _check_no_cpu_limits(chart: dict) -> list[OptimizationViolation]:
    """RES002 - Detect charts without CPU limits defined."""
    if "cpu_limit" in FIXED_RESOURCE_FIELDS:
        return []
    resources = chart.get("resources", {})
    limits = resources.get("limits", {})

    if not limits.get("cpu"):
        return [
            OptimizationViolation(
                rule_id="RES002",
                name="No CPU Limits",
                description="Container has no CPU limits defined, which can lead to resource starvation",
                severity="warning",
                category="resources",
                fix_preview={"resources": {"limits": {"cpu": "500m"}}},
                auto_fixable=True,
            )
        ]
    return []


def _check_no_memory_limits(chart: dict) -> list[OptimizationViolation]:
    """RES003 - Detect charts without memory limits defined."""
    if "memory_limit" in FIXED_RESOURCE_FIELDS:
        return []
    resources = chart.get("resources", {})
    limits = resources.get("limits", {})

    if not limits.get("memory"):
        return [
            OptimizationViolation(
                rule_id="RES003",
                name="No Memory Limits",
                description="Container has no memory limits defined, which can lead to OOM kills",
                severity="warning",
                category="resources",
                fix_preview={"resources": {"limits": {"memory": "512Mi"}}},
                auto_fixable=True,
            )
        ]
    return []


def _check_no_resource_requests(chart: dict) -> list[OptimizationViolation]:
    """RES004 - Detect charts without any resource requests."""
    if "cpu_request" in FIXED_RESOURCE_FIELDS and "memory_request" in FIXED_RESOURCE_FIELDS:
        return []
    resources = chart.get("resources", {})
    requests = resources.get("requests", {})

    if not requests.get("cpu") and not requests.get("memory"):
        is_best_effort = _is_best_effort_qos(chart)
        return [
            OptimizationViolation(
                rule_id="RES004",
                name="No Resource Requests",
                description=(
                    "BestEffort workload has no resource requests, which increases eviction risk under node pressure"
                    if is_best_effort
                    else "Container has no resource requests, which prevents effective scheduling"
                ),
                severity="warning" if is_best_effort else "error",
                category="resources",
                fix_preview={
                    "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}}
                },
                auto_fixable=True,
            )
        ]
    return []


def _check_high_cpu_limit_request_ratio(chart: dict) -> list[OptimizationViolation]:
    """RES005 - CPU limit/request ratio >= threshold.

    The fix always increases the *request* to bring the ratio in line.
    Limits are never decreased — they are assumed intentional.
    """
    if "cpu_request" in FIXED_RESOURCE_FIELDS:
        return []
    if _is_best_effort_qos(chart):
        return []

    resources = chart.get("resources", {})
    limits = resources.get("limits", {})
    requests = resources.get("requests", {})

    cpu_limit = _parse_cpu(limits.get("cpu"))
    cpu_request = _parse_cpu(requests.get("cpu"))

    if cpu_limit and cpu_request and cpu_request > 0:
        ratio = cpu_limit / cpu_request
        if ratio >= LIMIT_REQUEST_RATIO_THRESHOLD:
            target_request = int(cpu_limit / BURSTABLE_TARGET_RATIO)
            return [
                OptimizationViolation(
                    rule_id="RES005",
                    name="High CPU Limit/Request Ratio",
                    description=(
                        f"CPU limit ({limits.get('cpu')}) is {ratio:.1f}x the request "
                        f"({requests.get('cpu')}), increasing request to bring "
                        f"ratio to {BURSTABLE_TARGET_RATIO:.1f}x"
                    ),
                    severity="warning",
                    category="resources",
                    fix_preview={
                        "resources": {
                            "requests": {"cpu": f"{target_request}m"}
                        }
                    },
                    auto_fixable=True,
                )
            ]
    return []


def _check_high_memory_limit_request_ratio(chart: dict) -> list[OptimizationViolation]:
    """RES006 - Memory limit/request ratio >= threshold.

    The fix always increases the *request* to bring the ratio in line.
    Limits are never decreased — they are assumed intentional.
    """
    if "memory_request" in FIXED_RESOURCE_FIELDS:
        return []
    if _is_best_effort_qos(chart):
        return []

    resources = chart.get("resources", {})
    limits = resources.get("limits", {})
    requests = resources.get("requests", {})

    mem_limit = _parse_memory(limits.get("memory"))
    mem_request = _parse_memory(requests.get("memory"))

    if mem_limit and mem_request and mem_request > 0:
        ratio = mem_limit / mem_request
        if ratio >= LIMIT_REQUEST_RATIO_THRESHOLD:
            target_request = int(mem_limit / BURSTABLE_TARGET_RATIO)
            return [
                OptimizationViolation(
                    rule_id="RES006",
                    name="High Memory Limit/Request Ratio",
                    description=(
                        f"Memory limit ({limits.get('memory')}) is {ratio:.1f}x the request "
                        f"({requests.get('memory')}), increasing request to bring "
                        f"ratio to {BURSTABLE_TARGET_RATIO:.1f}x"
                    ),
                    severity="warning",
                    category="resources",
                    fix_preview={
                        "resources": {
                            "requests": {
                                "memory": f"{target_request}Mi"
                            }
                        }
                    },
                    auto_fixable=True,
                )
            ]
    return []


def _check_very_low_cpu_request(chart: dict) -> list[OptimizationViolation]:
    """RES007 - CPU request < 10m may cause throttling.

    Only fires when the CPU *limit* is also low (or missing).  When the limit
    is reasonable but the request is low, RES005 handles it by increasing the
    request instead, so we avoid the bump-then-reduce-limit sequence.
    """
    resources = chart.get("resources", {})
    requests = resources.get("requests", {})
    limits = resources.get("limits", {})
    cpu_request = _parse_cpu(requests.get("cpu"))
    cpu_limit = _parse_cpu(limits.get("cpu"))

    if cpu_request and cpu_request < LOW_CPU_THRESHOLD_MILLICORES:
        # Only bump when the limit is also low (or absent).  If the limit is
        # already at or above the bump target the ratio rule (RES005) handles
        # it by increasing the request without touching the limit.
        limit_is_also_low = cpu_limit is None or cpu_limit < CPU_BUMP_MIN_MILLICORES
        if limit_is_also_low:
            return [
                OptimizationViolation(
                    rule_id="RES007",
                    name="Very Low CPU Request",
                    description=f"CPU request ({requests.get('cpu')}) is below {LOW_CPU_THRESHOLD_MILLICORES}m, which may cause CPU throttling",
                    severity="warning",
                    category="resources",
                    fix_preview={"resources": {"requests": {"cpu": "100m"}}},
                    auto_fixable=True,
                )
            ]
    return []


def _check_very_low_memory_request(chart: dict) -> list[OptimizationViolation]:
    """RES009 - Memory request < 32Mi may cause OOM.

    Only fires when the memory *limit* is also low (or missing).  When the
    limit is reasonable but the request is low, RES006 handles it by
    increasing the request instead.
    """
    resources = chart.get("resources", {})
    requests = resources.get("requests", {})
    limits = resources.get("limits", {})
    mem_request = _parse_memory(requests.get("memory"))
    mem_limit = _parse_memory(limits.get("memory"))

    if mem_request and mem_request < LOW_MEMORY_THRESHOLD_MI:
        limit_is_also_low = mem_limit is None or mem_limit < MEMORY_BUMP_MIN_MI
        if limit_is_also_low:
            return [
                OptimizationViolation(
                    rule_id="RES009",
                    name="Very Low Memory Request",
                    description=f"Memory request ({requests.get('memory')}) is below {LOW_MEMORY_THRESHOLD_MI}Mi, which may cause OOM kills",
                    severity="warning",
                    category="resources",
                    fix_preview={"resources": {"requests": {"memory": "128Mi"}}},
                    auto_fixable=True,
                )
            ]
    return []


def _check_no_memory_request(chart: dict) -> list[OptimizationViolation]:
    """RES008 - Detect charts without memory requests defined."""
    if "memory_request" in FIXED_RESOURCE_FIELDS:
        return []
    resources = chart.get("resources", {})
    requests = resources.get("requests", {})
    # RES004 already covers the stronger case where both requests are missing.
    if not requests.get("cpu") and not requests.get("memory"):
        return []

    if not requests.get("memory"):
        return [
            OptimizationViolation(
                rule_id="RES008",
                name="No Memory Request",
                description="Container does not have a memory request defined",
                severity="warning",
                category="resources",
                fix_preview={"resources": {"requests": {"memory": "128Mi"}}},
                auto_fixable=True,
            )
        ]
    return []


def _check_missing_probe(
    chart: dict, probe_name: str, probe_key: str, rule_id: str, severity: str, fix_preview: dict
) -> list[OptimizationViolation]:
    """Helper to check for missing probe (reduces duplication)."""
    # Check if probe is defined at root level
    has_probe = probe_key in chart

    # Also check nested probes structure
    if not has_probe:
        probes = chart.get("probes", {})
        has_probe = bool(probes.get(probe_name))

    if not has_probe:
        return [
            OptimizationViolation(
                rule_id=rule_id,
                name=f"Missing {probe_name.title()} Probe",
                description=f"Container does not have a {probe_name} probe defined",
                severity=severity,
                category="probes",
                fix_preview=fix_preview,
                auto_fixable=True,
            )
        ]
    return []


def _check_missing_startup_probe(chart: dict) -> list[OptimizationViolation]:
    """PRB003 - Detect missing startupProbe in Helm values."""
    return _check_missing_probe(
        chart=chart,
        probe_name="startup",
        probe_key="startupProbe",
        rule_id="PRB003",
        severity="info",
        fix_preview={
            "startupProbe": {
                "httpGet": {"path": "/health", "port": "http"},
                "initialDelaySeconds": 10,
                "timeoutSeconds": 10,
                "periodSeconds": 30,
                "failureThreshold": 30,
            }
        },
    )


def _check_missing_liveness_probe(chart: dict) -> list[OptimizationViolation]:
    """PRB001 - Detect missing livenessProbe in Helm values."""
    return _check_missing_probe(
        chart=chart,
        probe_name="liveness",
        probe_key="livenessProbe",
        rule_id="PRB001",
        severity="warning",
        fix_preview={
            "livenessProbe": {
                "httpGet": {"path": "/health", "port": "http"},
                "initialDelaySeconds": 10,
                "timeoutSeconds": 10,
                "periodSeconds": 30,
                "failureThreshold": 3,
            }
        },
    )


def _check_missing_readiness_probe(chart: dict) -> list[OptimizationViolation]:
    """PRB002 - Detect missing readinessProbe in Helm values."""
    return _check_missing_probe(
        chart=chart,
        probe_name="readiness",
        probe_key="readinessProbe",
        rule_id="PRB002",
        severity="warning",
        fix_preview={
            "readinessProbe": {
                "httpGet": {"path": "/health", "port": "http"},
                "initialDelaySeconds": 10,
                "timeoutSeconds": 10,
                "periodSeconds": 30,
                "failureThreshold": 3,
            }
        },
    )


def _check_missing_topology_spread(chart: dict) -> list[OptimizationViolation]:
    """AVL004 - Detect missing topology spread for multi-replica workloads."""
    replicas = chart.get("replicas", 1)
    if replicas <= 1:
        return []

    topology = chart.get("topologySpreadConstraints", [])

    if not topology:
        return [
            OptimizationViolation(
                rule_id="AVL004",
                name="Missing Topology Spread",
                description=(
                    "No topologySpreadConstraints defined for a multi-replica workload, "
                    "which may lead to uneven pod distribution"
                ),
                severity="info",
                category="availability",
                fix_preview={
                    "topologySpreadConstraints": [
                        {
                            "maxSkew": 1,
                            "topologyKey": "kubernetes.io/hostname",
                            "whenUnsatisfiable": "ScheduleAnyway",
                            "labelSelector": {"matchLabels": {"app": "CHART_NAME"}},
                        }
                    ]
                },
                auto_fixable=True,
            )
        ]
    return []


def _check_no_pdb(chart: dict) -> list[OptimizationViolation]:
    """AVL001 - Detect missing PodDisruptionBudget for multi-replica workloads."""
    replicas = chart.get("replicas", 1)
    if replicas <= 1:
        return []

    # Treat explicit enabled: false as disabled/missing.
    has_pdb = False
    for key in ("podDisruptionBudget", "pdb"):
        pdb = chart.get(key)
        if pdb is None:
            continue
        if isinstance(pdb, dict) and pdb.get("enabled") is False:
            continue
        has_pdb = True
        break

    if not has_pdb and replicas > 1:
        return [
            OptimizationViolation(
                rule_id="AVL001",
                name="No Pod Disruption Budget",
                description="Workload does not have a PodDisruptionBudget configured",
                severity="warning",
                category="availability",
                fix_preview={
                    "podDisruptionBudget": {
                        "enabled": True,
                        "maxUnavailable": 1,
                        "unhealthyPodEvictionPolicy": "AlwaysAllow",
                        "labelSelector": {"matchLabels": {"app": "CHART_NAME"}},
                    }
                },
                auto_fixable=True,
            )
        ]
    return []


def _check_no_pod_anti_affinity(chart: dict) -> list[OptimizationViolation]:
    """AVL002 - Detect missing podAntiAffinity (#10 - flag for all charts)."""
    affinity = chart.get("affinity", {})
    pod_anti_affinity = affinity.get("podAntiAffinity", {})

    has_anti_affinity = chart.get("has_anti_affinity", False) or bool(
        pod_anti_affinity.get("preferredDuringSchedulingIgnoredDuringExecution")
        or pod_anti_affinity.get("requiredDuringSchedulingIgnoredDuringExecution")
    )

    replicas = chart.get("replicas", 1)

    if not has_anti_affinity and replicas > 1:
        return [
            OptimizationViolation(
                rule_id="AVL002",
                name="No Pod Anti-Affinity",
                description="Workload does not have pod anti-affinity for high availability",
                severity="info",
                category="availability",
                fix_preview={
                    "affinity": {
                        "podAntiAffinity": {
                            "preferredDuringSchedulingIgnoredDuringExecution": [
                                {
                                    "weight": 100,
                                    "podAffinityTerm": {
                                        "labelSelector": {
                                            "matchLabels": {"app": "CHART_NAME"}
                                        },
                                        "topologyKey": "kubernetes.io/hostname",
                                    },
                                }
                            ]
                        }
                    }
                },
                auto_fixable=True,
            )
        ]
    return []


def _check_single_replica(chart: dict) -> list[OptimizationViolation]:
    """AVL005 - Detect single-replica charts with no redundancy (spec 3.2)."""
    replicas = chart.get("replicas")
    if replicas is not None and replicas == 1:
        return [
            OptimizationViolation(
                rule_id="AVL005",
                name="Single Replica (No Redundancy)",
                description="Chart runs with a single replica, providing no redundancy during failures or deployments",
                severity="warning",
                category="availability",
                fix_preview={"replicaCount": 2},
                auto_fixable=True,
            )
        ]
    return []


def _check_blocking_pdb(chart: dict) -> list[OptimizationViolation]:
    """AVL003 - Detect blocking PDB configurations (minAvailable >= replicas or maxUnavailable = 0)."""
    pdb = chart.get("podDisruptionBudget", chart.get("pdb", {}))
    if not pdb:
        return []

    replicas = chart.get("replicas", 1)
    min_available = pdb.get("minAvailable")
    max_unavailable = pdb.get("maxUnavailable")

    violations: list[OptimizationViolation] = []

    # Blocking means allowed evictions are below threshold.
    is_max_unavailable_blocking = False
    if isinstance(max_unavailable, int):
        is_max_unavailable_blocking = max_unavailable < PDB_BLOCKING_THRESHOLD
    elif isinstance(max_unavailable, str):
        if max_unavailable.endswith("%"):
            try:
                pct = int(max_unavailable.rstrip("%"))
                allowed_evictions = (replicas * pct) // 100
                is_max_unavailable_blocking = (
                    allowed_evictions < PDB_BLOCKING_THRESHOLD
                )
            except ValueError:
                pass
        elif max_unavailable.lstrip("-").isdigit():
            is_max_unavailable_blocking = (
                int(max_unavailable) < PDB_BLOCKING_THRESHOLD
            )

    if is_max_unavailable_blocking:
        violations.append(
            OptimizationViolation(
                rule_id="AVL003",
                name="Blocking PDB - maxUnavailable too low",
                description=(
                    f"PDB maxUnavailable={max_unavailable} allows fewer than "
                    f"{PDB_BLOCKING_THRESHOLD} disruption(s), which can block node drains"
                ),
                severity="error",
                category="availability",
                fix_preview={
                    "podDisruptionBudget": {
                        "maxUnavailable": PDB_BLOCKING_THRESHOLD,
                        "unhealthyPodEvictionPolicy": "AlwaysAllow",
                    }
                },
                auto_fixable=True,
            )
        )

    # Check for minAvailable threshold (blocking: too few/no pods can be evicted).
    if min_available is not None:
        is_blocking = False
        if isinstance(min_available, int):
            allowed_evictions = replicas - min_available
            is_blocking = allowed_evictions < PDB_BLOCKING_THRESHOLD
        elif isinstance(min_available, str):
            if min_available.endswith("%"):
                try:
                    pct = int(min_available.rstrip("%"))
                    # 100% minAvailable (or more) means 0 allowed evictions.
                    if pct >= 100:
                        is_blocking = True
                except ValueError:
                    pass
            elif (
                min_available.lstrip("-").isdigit()
            ):
                allowed_evictions = replicas - int(min_available)
                is_blocking = allowed_evictions < PDB_BLOCKING_THRESHOLD

        if is_blocking:
            violations.append(
                OptimizationViolation(
                    rule_id="AVL003",
                    name="Blocking PDB - minAvailable too high",
                    description=f"PDB minAvailable={min_available} blocks evictions for {replicas} replica workload",
                    severity="error",
                    category="availability",
                    fix_preview={
                        "podDisruptionBudget": {
                            "maxUnavailable": 1,
                            "unhealthyPodEvictionPolicy": "AlwaysAllow",
                        }
                    },
                    auto_fixable=True,
                )
            )

    return violations


def _check_running_as_root(chart: dict) -> list[OptimizationViolation]:
    """SEC001 - Detect securityContext.runAsUser == 0 (running as root)."""
    sc = chart.get("securityContext", {})
    run_as_user = sc.get("runAsUser")

    if run_as_user == 0:
        return [
            OptimizationViolation(
                rule_id="SEC001",
                name="Running As Root",
                description="Container runs as root (runAsUser=0), which is a security risk",
                severity="error",
                category="security",
                fix_preview={
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "fsGroup": 1000,
                    }
                },
                auto_fixable=True,
            )
        ]
    return []


# All optimization rules
RULES: list[OptimizationRule] = [
    # Resources rules
    OptimizationRule(
        id="RES002",
        name="No CPU Limits",
        description="Container has no CPU limits defined",
        severity="warning",
        category="resources",
        check=_check_no_cpu_limits,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="RES003",
        name="No Memory Limits",
        description="Container has no memory limits defined",
        severity="warning",
        category="resources",
        check=_check_no_memory_limits,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="RES004",
        name="No Resource Requests",
        description="Container has no resource requests",
        severity="error",
        category="resources",
        check=_check_no_resource_requests,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="RES005",
        name="High CPU Limit/Request Ratio",
        description="CPU limit is too high compared to request",
        severity="warning",
        category="resources",
        check=_check_high_cpu_limit_request_ratio,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="RES006",
        name="High Memory Limit/Request Ratio",
        description="Memory limit is too high compared to request",
        severity="warning",
        category="resources",
        check=_check_high_memory_limit_request_ratio,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="RES007",
        name="Very Low CPU Request",
        description="CPU request is below recommended minimum",
        severity="warning",
        category="resources",
        check=_check_very_low_cpu_request,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="RES008",
        name="No Memory Request",
        description="Container does not have a memory request defined",
        severity="warning",
        category="resources",
        check=_check_no_memory_request,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="RES009",
        name="Very Low Memory Request",
        description="Memory request is below recommended minimum (32Mi)",
        severity="warning",
        category="resources",
        check=_check_very_low_memory_request,
        auto_fixable=True,
    ),
    # Probes rules
    OptimizationRule(
        id="PRB001",
        name="Missing Liveness Probe",
        description="Container does not have a liveness probe defined",
        severity="warning",
        category="probes",
        check=_check_missing_liveness_probe,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="PRB002",
        name="Missing Readiness Probe",
        description="Container does not have a readiness probe defined",
        severity="warning",
        category="probes",
        check=_check_missing_readiness_probe,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="PRB003",
        name="Missing Startup Probe",
        description="Container has no startupProbe defined",
        severity="info",
        category="probes",
        check=_check_missing_startup_probe,
        auto_fixable=True,
    ),
    # Availability rules
    OptimizationRule(
        id="AVL001",
        name="No Pod Disruption Budget",
        description="Multi-replica workload does not have a PodDisruptionBudget configured",
        severity="warning",
        category="availability",
        check=_check_no_pdb,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="AVL002",
        name="No Pod Anti-Affinity",
        description="Workload does not have pod anti-affinity for high availability",
        severity="info",
        category="availability",
        check=_check_no_pod_anti_affinity,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="AVL003",
        name="Blocking PDB Configuration",
        description="PDB configuration allows too few disruptions (minAvailable too high or maxUnavailable too low)",
        severity="error",
        category="availability",
        check=_check_blocking_pdb,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="AVL004",
        name="Missing Topology Spread",
        description="No topologySpreadConstraints defined for a multi-replica workload",
        severity="info",
        category="availability",
        check=_check_missing_topology_spread,
        auto_fixable=True,
    ),
    OptimizationRule(
        id="AVL005",
        name="Single Replica (No Redundancy)",
        description="Chart runs with a single replica, no redundancy",
        severity="warning",
        category="availability",
        check=_check_single_replica,
        auto_fixable=True,
    ),
    # Security rules
    OptimizationRule(
        id="SEC001",
        name="Running As Root",
        description="Container runs as root user",
        severity="error",
        category="security",
        check=_check_running_as_root,
        auto_fixable=True,
    ),
]


# Pre-built lookup dict for O(1) access
RULES_BY_ID: dict[str, OptimizationRule] = {rule.id: rule for rule in RULES}


def get_rule_by_id(rule_id: str) -> OptimizationRule | None:
    """Get a rule by its ID."""
    return RULES_BY_ID.get(rule_id)
