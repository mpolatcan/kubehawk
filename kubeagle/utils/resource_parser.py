"""Resource parsing utilities for CPU and memory values.

Provides functions to parse Kubernetes resource strings into standardized formats:
- CPU: parsed to cores (float)
- Memory: parsed to Mi (mebibytes) or bytes
"""

from typing import Any

# Module-level constants to avoid re-creating on every function call.
# Suffix multipliers for memory_str_to_bytes() to convert to bytes.
_MEMORY_BYTES_MULTIPLIERS: tuple[tuple[str, int], ...] = (
    ("Ki", 1024),
    ("Mi", 1024**2),
    ("Gi", 1024**3),
    ("Ti", 1024**4),
)


def parse_cpu(cpu_str: str) -> float:
    """Parse CPU string to cores (float).

    Handles various CPU resource formats:
    - Nanocores: "500000000n" -> 0.5 cores
    - Microcores: "500000u" -> 0.5 cores
    - Millicores: "100m" -> 0.1 cores
    - Decimal: "1.5" -> 1.5 cores
    - Integer: "2" -> 2.0 cores

    Args:
        cpu_str: CPU value as string (e.g., "100m", "1.5", "500")

    Returns:
        CPU value in cores as float. Returns 0.0 on parse error or empty string.
    """
    if not cpu_str:
        return 0.0

    cpu_str = str(cpu_str).strip()

    # Handle nanocores (e.g., "500000000n" -> 0.5)
    if cpu_str.endswith("n"):
        try:
            return float(cpu_str[:-1]) / 1_000_000_000
        except ValueError:
            return 0.0

    # Handle microcores (e.g., "500000u" -> 0.5)
    if cpu_str.endswith("u"):
        try:
            return float(cpu_str[:-1]) / 1_000_000
        except ValueError:
            return 0.0

    # Handle millicores (e.g., "100m" -> 0.1)
    if cpu_str.endswith("m"):
        try:
            return float(cpu_str[:-1]) / 1000
        except ValueError:
            return 0.0

    # Handle plain numbers (cores)
    try:
        return float(cpu_str)
    except ValueError:
        return 0.0


def memory_str_to_bytes(memory_str: str) -> float:
    """Convert memory string to bytes.

    Handles various memory resource formats:
    - Ki: "1024Ki" -> 1048576 bytes
    - Mi: "512Mi" -> 536870912 bytes
    - Gi: "1Gi" -> 1073741824 bytes
    - Ti: "1Ti" -> 1099511627776 bytes

    Args:
        memory_str: Memory value as string (e.g., "512Mi", "1Gi")

    Returns:
        Memory value in bytes as float. Returns 0.0 on parse error or empty string.
    """
    if not memory_str:
        return 0.0

    memory_str = str(memory_str).strip()

    for suffix, mult in _MEMORY_BYTES_MULTIPLIERS:
        if memory_str.endswith(suffix):
            try:
                value = float(memory_str[:-2])
                return value * mult
            except ValueError:
                return 0.0

    # Handle plain bytes
    try:
        return float(memory_str)
    except ValueError:
        return 0.0


def parse_cpu_from_dict(
    values: dict[str, Any], container_type: str, resource: str
) -> float:
    """Parse CPU value from a nested dictionary.

    Utility function to extract and parse CPU from a structure like:
    {"resources": {"limits": {"cpu": "100m"}}}

    Args:
        values: Dictionary containing resource data
        container_type: Key for container resources (e.g., "limits", "requests")
        resource: Resource key (e.g., "cpu")

    Returns:
        Parsed CPU value in millicores. Returns 0.0 on error.
    """
    try:
        if not isinstance(values, dict):
            return 0.0
        resources = values.get("resources", {})
        if not isinstance(resources, dict):
            return 0.0
        container_resources = resources.get(container_type, {})
        if not isinstance(container_resources, dict):
            return 0.0
        if resource in container_resources:
            # Chart models/presenters use millicores for CPU display and aggregation.
            return parse_cpu(container_resources[resource]) * 1000
    except (ValueError, TypeError, AttributeError):
        return 0.0
    return 0.0


def parse_memory_from_dict(
    values: dict[str, Any], container_type: str, resource: str
) -> float:
    """Parse memory value from a nested dictionary.

    Utility function to extract and parse memory from a structure like:
    {"resources": {"limits": {"memory": "512Mi"}}}

    Args:
        values: Dictionary containing resource data
        container_type: Key for container resources (e.g., "limits", "requests")
        resource: Resource key (e.g., "memory")

    Returns:
        Parsed memory value in bytes. Returns 0.0 on error.
    """
    try:
        if not isinstance(values, dict):
            return 0.0
        resources = values.get("resources", {})
        if not isinstance(resources, dict):
            return 0.0
        container_resources = resources.get(container_type, {})
        if not isinstance(container_resources, dict):
            return 0.0
        if resource in container_resources:
            return memory_str_to_bytes(container_resources[resource])
    except (ValueError, TypeError, AttributeError):
        return 0.0
    return 0.0
