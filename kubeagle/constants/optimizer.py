"""Optimizer threshold constants."""

LIMIT_REQUEST_RATIO_THRESHOLD = 2.0
LOW_CPU_THRESHOLD_MILLICORES = 10
LOW_MEMORY_THRESHOLD_MI = 32
PDB_BLOCKING_THRESHOLD = 1

# Bump targets: the values we bump low requests/limits to.
# Bump rules (RES007/RES009) only fire when BOTH request AND limit are below
# these targets.  When only the request is low the ratio rules (RES005/RES006)
# handle it by increasing the request instead of decreasing the limit.
CPU_BUMP_MIN_MILLICORES = 100
MEMORY_BUMP_MIN_MI = 128

__all__ = [
    "CPU_BUMP_MIN_MILLICORES",
    "LIMIT_REQUEST_RATIO_THRESHOLD",
    "LOW_CPU_THRESHOLD_MILLICORES",
    "LOW_MEMORY_THRESHOLD_MI",
    "MEMORY_BUMP_MIN_MI",
    "PDB_BLOCKING_THRESHOLD",
]
