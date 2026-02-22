"""Fix generator for optimization violations."""

import copy
import logging
from typing import Any

import yaml

from kubeagle.optimizer.rules import (
    BURSTABLE_TARGET_RATIO,
    OptimizationViolation,
    _parse_cpu,
    _parse_memory,
)

logger = logging.getLogger(__name__)

# Threshold constants
CPU_UNIT_THRESHOLD = 1000  # Convert to whole cores when >= 1000m
MEMORY_GI_THRESHOLD = 1024  # Convert to Gi when >= 1024Mi
RATIO_STRATEGY_BURSTABLE_15 = "burstable_1_5"
RATIO_STRATEGY_BURSTABLE_20 = "burstable_2_0"
RATIO_STRATEGY_GUARANTEED = "guaranteed"
RATIO_TARGET_LIMIT = "limit"
RATIO_TARGET_REQUEST = "request"


class FixGenerator:
    """Generates fixes for optimization violations."""

    def generate_fix(
        self,
        violation: OptimizationViolation,
        chart_data: dict,
        ratio_strategy: str | None = None,
        ratio_target: str | None = None,
        probe_settings: dict[str, Any] | None = None,
        fixed_resource_fields: set[str] | None = None,
    ) -> dict[str, Any] | None:
        """Generate a fix dictionary for a violation.

        Args:
            violation: The violation to fix
            chart_data: Current chart data (to compute smart defaults)
            ratio_strategy: Optional ratio strategy for RES005/RES006 fixes.
            ratio_target: Optional ratio fix target (`limit` or `request`).
            probe_settings: Optional probe override settings for PRB rules.
            fixed_resource_fields: Optional set of fields to protect from modification.

        Returns:
            Dictionary with the fix to apply, or None if not fixable
        """
        rule_id = violation.rule_id

        if rule_id == "RES002":
            # No CPU Limits - use request if available, else default
            resources = self._get_resources(chart_data)
            requests = resources.get("requests", {})
            cpu_request = requests.get("cpu", "100m")
            return {"resources": {"limits": {"cpu": self._double_cpu(cpu_request)}}}

        elif rule_id == "RES003":
            # No Memory Limits - use request if available, else default
            resources = self._get_resources(chart_data)
            requests = resources.get("requests", {})
            mem_request = requests.get("memory", "128Mi")
            return {
                "resources": {"limits": {"memory": self._double_memory(mem_request)}}
            }

        elif rule_id == "RES004":
            # No Resource Requests - add both CPU and memory
            return {
                "resources": {
                    "requests": {
                        "cpu": "100m",
                        "memory": "128Mi",
                    },
                    "limits": {
                        "cpu": "500m",
                        "memory": "512Mi",
                    },
                }
            }

        elif rule_id == "RES005":
            # High CPU Limit/Request Ratio — always increase request to bring
            # ratio in line.  Limits are never decreased.
            resources = self._get_resources(chart_data)
            limits = resources.get("limits", {})
            cpu_limit = _parse_cpu(limits.get("cpu"))
            multiplier = self._resolve_ratio_multiplier(ratio_strategy)

            if cpu_limit:
                if multiplier is None:
                    target_request = cpu_limit
                else:
                    target_request = cpu_limit / multiplier
                return {
                    "resources": {
                        "requests": {
                            "cpu": f"{self._safe_resource_int(target_request)}m"
                        }
                    }
                }

        elif rule_id == "RES006":
            # High Memory Limit/Request Ratio — always increase request to
            # bring ratio in line.  Limits are never decreased.
            resources = self._get_resources(chart_data)
            limits = resources.get("limits", {})
            mem_limit = _parse_memory(limits.get("memory"))
            multiplier = self._resolve_ratio_multiplier(ratio_strategy)

            if mem_limit:
                if multiplier is None:
                    target_request = mem_limit
                else:
                    target_request = mem_limit / multiplier
                return {
                    "resources": {
                        "requests": {
                            "memory": f"{self._safe_resource_int(target_request)}Mi"
                        }
                    }
                }

        elif rule_id == "RES007":
            # Very Low CPU Request - bump to 100m
            return {"resources": {"requests": {"cpu": "100m"}}}

        elif rule_id == "RES008":
            # No Memory Request - add default memory request
            return {"resources": {"requests": {"memory": "128Mi"}}}

        elif rule_id == "PRB001":
            # Missing Liveness Probe - add default
            return {
                "livenessProbe": self._build_http_probe_fix(
                    default_path="/health",
                    default_port="http",
                    default_initial_delay=15,
                    default_timeout=3,
                    default_period=10,
                    default_failure_threshold=3,
                    probe_settings=probe_settings,
                )
            }

        elif rule_id == "PRB002":
            # Missing Readiness Probe - add default
            return {
                "readinessProbe": self._build_http_probe_fix(
                    default_path="/ready",
                    default_port="http",
                    default_initial_delay=5,
                    default_timeout=3,
                    default_period=5,
                    default_failure_threshold=3,
                    probe_settings=probe_settings,
                )
            }

        elif rule_id == "PRB003":
            # Missing Startup Probe - add default
            return {
                "startupProbe": self._build_http_probe_fix(
                    default_path="/health",
                    default_port="http",
                    default_initial_delay=5,
                    default_timeout=3,
                    default_period=5,
                    default_failure_threshold=30,
                    probe_settings=probe_settings,
                )
            }

        elif rule_id == "AVL001":
            # No Pod Disruption Budget - add default PDB
            chart_name = chart_data.get("chart_name", "app")
            return {
                "podDisruptionBudget": {
                    "minAvailable": 1,
                    "labelSelector": {"matchLabels": {"app": chart_name}},
                }
            }

        elif rule_id == "AVL002":
            # No Pod Anti-Affinity - add preferred anti-affinity
            chart_name = chart_data.get("chart_name", "app")
            return {
                "affinity": {
                    "podAntiAffinity": {
                        "preferredDuringSchedulingIgnoredDuringExecution": [
                            {
                                "weight": 100,
                                "podAffinityTerm": {
                                    "labelSelector": {
                                        "matchLabels": {"app": chart_name}
                                    },
                                    "topologyKey": "kubernetes.io/hostname",
                                },
                            }
                        ]
                    }
                }
            }

        elif rule_id == "AVL004":
            # Missing Topology Spread - add default
            chart_name = chart_data.get("chart_name", "app")
            return {
                "topologySpreadConstraints": [
                    {
                        "maxSkew": 1,
                        "topologyKey": "kubernetes.io/hostname",
                        "whenUnsatisfiable": "ScheduleAnyway",
                        "labelSelector": {"matchLabels": {"app": chart_name}},
                    }
                ]
            }

        elif rule_id == "AVL005":
            # Single Replica - increase to 2
            return {"replicaCount": 2}

        elif rule_id == "SEC001":
            # Running As Root - fix to non-root
            return {
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 1000,
                    "fsGroup": 1000,
                }
            }

        elif rule_id == "RES009":
            # Very Low Memory Request - bump to 128Mi
            return {"resources": {"requests": {"memory": "128Mi"}}}

        elif rule_id == "AVL003":
            # Blocking PDB - set maxUnavailable to 1
            return {"podDisruptionBudget": {"maxUnavailable": 1}}

        return None

    @staticmethod
    def strip_fixed_fields(
        fix: dict[str, Any],
        fixed_fields: set[str] | None = None,
        *,
        exempt_rule_ids: frozenset[str] = frozenset({"RES007", "RES009"}),
        rule_id: str = "",
    ) -> dict[str, Any] | None:
        """Remove resource keys that correspond to fixed fields.

        Returns the (possibly trimmed) fix dict, or None if all resource
        keys were stripped and nothing else remains.
        """
        if not fixed_fields:
            return fix
        if rule_id in exempt_rule_ids:
            return fix

        resources = fix.get("resources")
        if not isinstance(resources, dict):
            return fix

        field_to_path: dict[str, tuple[str, str]] = {
            "cpu_request": ("requests", "cpu"),
            "cpu_limit": ("limits", "cpu"),
            "memory_request": ("requests", "memory"),
            "memory_limit": ("limits", "memory"),
        }

        for field, (section, key) in field_to_path.items():
            if field not in fixed_fields:
                continue
            sub = resources.get(section)
            if isinstance(sub, dict) and key in sub:
                del sub[key]
                if not sub:
                    del resources[section]

        if not resources:
            remaining = {k: v for k, v in fix.items() if k != "resources"}
            return remaining or None

        return fix

    def _get_resources(self, chart_data: dict) -> dict:
        """Get resources dict from chart data."""
        return chart_data.get("resources", {})

    @staticmethod
    def _resolve_ratio_multiplier(ratio_strategy: str | None) -> float | None:
        """Resolve ratio strategy to multiplier (or None for Guaranteed)."""
        if ratio_strategy == RATIO_STRATEGY_BURSTABLE_20:
            return 2.0
        if ratio_strategy == RATIO_STRATEGY_GUARANTEED:
            return None
        if ratio_strategy in (None, RATIO_STRATEGY_BURSTABLE_15):
            return BURSTABLE_TARGET_RATIO
        return BURSTABLE_TARGET_RATIO

    @staticmethod
    def _resolve_ratio_target(ratio_target: str | None) -> str:
        """Resolve ratio fix target to request/limit."""
        if ratio_target == RATIO_TARGET_REQUEST:
            return RATIO_TARGET_REQUEST
        return RATIO_TARGET_LIMIT

    @staticmethod
    def _safe_resource_int(value: float) -> int:
        """Convert computed resource values to positive integer units."""
        return max(1, int(value))

    @staticmethod
    def _double_cpu(cpu_str: str) -> str:
        """Double the CPU value."""
        value = _parse_cpu(cpu_str)
        if value:
            doubled = value * 2
            if doubled >= CPU_UNIT_THRESHOLD:
                return f"{int(doubled / CPU_UNIT_THRESHOLD)}"
            return f"{int(doubled)}m"
        return "500m"

    @staticmethod
    def _double_memory(mem_str: str) -> str:
        """Double the memory value."""
        value = _parse_memory(mem_str)
        if value:
            doubled = value * 2
            if doubled >= MEMORY_GI_THRESHOLD:
                return f"{int(doubled / MEMORY_GI_THRESHOLD)}Gi"
            return f"{int(doubled)}Mi"
        return "256Mi"

    @staticmethod
    def _build_http_probe_fix(
        *,
        default_path: str,
        default_port: str,
        default_initial_delay: int,
        default_timeout: int,
        default_period: int,
        default_failure_threshold: int,
        probe_settings: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build probe fix with optional per-violation overrides."""
        probe: dict[str, Any] = {
            "httpGet": {
                "path": default_path,
                "port": default_port,
            },
            "initialDelaySeconds": default_initial_delay,
            "timeoutSeconds": default_timeout,
            "periodSeconds": default_period,
            "failureThreshold": default_failure_threshold,
        }
        if not probe_settings:
            return probe

        http_get = probe["httpGet"]
        if not isinstance(http_get, dict):
            return probe

        path = probe_settings.get("path")
        if isinstance(path, str) and path.strip():
            http_get["path"] = path.strip()

        port = probe_settings.get("port")
        if isinstance(port, str) and port.strip():
            http_get["port"] = port.strip()
        elif isinstance(port, int):
            http_get["port"] = port

        scheme = probe_settings.get("scheme")
        if isinstance(scheme, str):
            scheme_value = scheme.strip().upper()
            if scheme_value in {"HTTP", "HTTPS"}:
                http_get["scheme"] = scheme_value

        host = probe_settings.get("host")
        if isinstance(host, str) and host.strip():
            http_get["host"] = host.strip()

        header_value = probe_settings.get("header")
        if isinstance(header_value, str):
            header_raw = header_value.strip()
            if ":" in header_raw:
                name, value = header_raw.split(":", 1)
                header_name = name.strip()
                header_payload = value.strip()
                if header_name and header_payload:
                    http_get["httpHeaders"] = [
                        {
                            "name": header_name,
                            "value": header_payload,
                        }
                    ]

        for field in (
            "initialDelaySeconds",
            "timeoutSeconds",
            "periodSeconds",
            "successThreshold",
            "failureThreshold",
            "terminationGracePeriodSeconds",
        ):
            value = probe_settings.get(field)
            if isinstance(value, int) and value > 0:
                probe[field] = value

        return probe


def apply_fix(values_path: str, fix: dict[str, Any]) -> bool:
    """Apply a fix to a values.yaml file.

    Args:
        values_path: Path to the values.yaml file
        fix: Dictionary with the fix to apply

    Returns:
        True if successful, False otherwise
    """
    # Read file content once for both backup and processing
    try:
        with open(values_path) as f:
            content = f.read()
    except OSError as e:
        logger.error("Failed to read values file %s: %s", values_path, e)
        return False

    try:
        current = yaml.safe_load(content) or {}
    except yaml.YAMLError as e:
        logger.error("Failed to parse values file %s: %s", values_path, e)
        return False

    # Deep merge the fix
    merged = _deep_merge(copy.deepcopy(current), fix)

    try:
        with open(values_path, "w") as f:
            yaml.dump(merged, f, default_flow_style=False, sort_keys=False)
    except OSError as e:
        logger.error("Failed to write values file %s: %s", values_path, e)
        # Best-effort in-memory rollback without leaving backup artifacts.
        try:
            with open(values_path, "w") as f:
                f.write(content)
        except OSError as rollback_error:
            logger.error(
                "Failed to rollback values file %s after write error: %s",
                values_path,
                rollback_error,
            )
        return False

    return True


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base
