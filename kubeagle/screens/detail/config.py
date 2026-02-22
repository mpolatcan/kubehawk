"""Detail module configuration - chart detail and optimizer screen constants."""

from __future__ import annotations

from typing import Any

# Tab IDs
TAB_VIOLATIONS: str = "tab-violations"
TAB_FIXES: str = "tab-fixes"

# Tab titles
TAB_TITLES: dict[str, str] = {
    TAB_VIOLATIONS: "Optimizer",
    TAB_FIXES: "Fixes",
}

# Violations table columns (5-column summary layout)
VIOLATIONS_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("Severity", 12),
    ("Category", 14),
    ("Chart", 22),
    ("Description", 45),
    ("Recommendation", 38),
]

# Full violations table columns (optimizer screen)
OPTIMIZER_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("Chart", 22),
    ("Team", 18),
    ("Values File Type", 18),
    ("Severity", 12),
    ("Category", 14),
    ("Rule", 32),
    ("Current", 28),
    ("Chart Path", 44),
]

OPTIMIZER_HEADER_TOOLTIPS: dict[str, str] = {
    "Chart": "Helm chart name where the violation was detected.",
    "Team": "Owning team mapped from CODEOWNERS/chart metadata.",
    "Values File Type": "Source kind for values (service/default/shared/other).",
    "Severity": "Violation impact level (Error, Warning, or Info).",
    "Category": "Rule category such as resources, probes, or scheduling.",
    "Rule": "Specific optimizer rule that raised this violation.",
    "Current": "Current chart value that triggered the rule.",
    "Chart Path": "Filesystem path of the affected chart.",
}

# Sort options for optimizer violations table
SORT_CATEGORY: str = "category"
SORT_SEVERITY: str = "severity"
SORT_CHART: str = "chart"
SORT_TEAM: str = "team"
SORT_RULE: str = "rule"

SORT_SELECT_OPTIONS: list[tuple[str, str]] = [
    (SORT_CATEGORY, "Category"),
    (SORT_SEVERITY, "Severity"),
    (SORT_CHART, "Chart"),
    (SORT_TEAM, "Team"),
    (SORT_RULE, "Rule"),
]

# Optimizer view switching
VIEW_VIOLATIONS: str = "violations"
VIEW_IMPACT: str = "impact"
VIEW_OPTIONS: list[tuple[str, str]] = [
    ("Optimizer", VIEW_VIOLATIONS),
    ("Impact Analysis", VIEW_IMPACT),
]

# Impact analysis table columns
IMPACT_NODE_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("Instance Type", 16),
    ("vCPUs", 8),
    ("Memory", 12),
    ("Spot $/hr", 10),
    ("Nodes Before", 14),
    ("Nodes After", 14),
    ("Reduction", 10),
    ("%", 8),
    ("Cost Before", 14),
    ("Cost After", 14),
    ("Cost Δ/mo", 14),
]

IMPACT_CHART_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("Chart", 22),
    ("Team", 16),
    ("CPU Req B->A", 20),
    ("CPU Lim B->A", 20),
    ("Mem Req B->A", 20),
    ("Mem Lim B->A", 20),
    ("Replicas", 14),
]

IMPACT_CLUSTER_NODE_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("Instance Type", 16),
    ("Nodes", 8),
    ("CPU/Node", 12),
    ("Mem/Node", 12),
    ("Spot $/hr", 10),
    ("Needed After", 12),
    ("Reduction", 10),
    ("%", 8),
    ("Cost Now/mo", 14),
    ("Cost After/mo", 14),
    ("Cost Δ/mo", 14),
]

# Fixes table columns
FIXES_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("Chart", 25),
    ("Violation", 30),
    ("Fix", 40),
]


# Max truncation lengths per field
_MAX_CATEGORY = 15
_MAX_CHART = 25
_MAX_DESCRIPTION = 50
_MAX_RECOMMENDATION = 40


def _truncate(value: str | None, max_len: int) -> str:
    """Truncate a string to max_len, returning 'N/A' for None."""
    if value is None:
        return "N/A"
    s = str(value)
    return s[:max_len] if len(s) > max_len else s


def format_violation_row(violation: Any) -> tuple[str, str, str, str, str]:
    """Format a violation object into a 5-element table row tuple.

    Args:
        violation: An object with severity.value, category, chart_name,
                   description, and recommended_value attributes.

    Returns:
        Tuple of (severity_markup, category, chart_name, description, recommendation).
    """
    severity_raw = violation.severity.value
    severity_upper = severity_raw.upper()
    if severity_upper == "ERROR":
        severity_str = f"[bold #ff3b30]{severity_upper}[/bold #ff3b30]"
    elif severity_upper == "WARNING":
        severity_str = f"[#ff9f0a]{severity_upper}[/#ff9f0a]"
    else:
        severity_str = severity_upper

    category = _truncate(violation.category, _MAX_CATEGORY)
    chart_name = _truncate(violation.chart_name, _MAX_CHART)
    description = _truncate(violation.description, _MAX_DESCRIPTION)
    recommendation = _truncate(violation.recommended_value, _MAX_RECOMMENDATION)

    return (severity_str, category, chart_name, description, recommendation)


# ============================================================================
# Chart Detail Screen Constants
# ============================================================================

# Section headers
SECTION_RESOURCES: str = "[bold]Resources[/bold]"
SECTION_PROBES: str = "[bold]Health Probes[/bold]"
SECTION_AVAILABILITY: str = "[bold]Availability[/bold]"
SECTION_CONFIGURATION: str = "[bold]Configuration[/bold]"

# Field labels (fixed-width for alignment)
LABEL_CPU_REQ: str = "CPU Request:"
LABEL_CPU_LIM: str = "CPU Limit:"
LABEL_CPU_RATIO: str = "CPU L/R Ratio:"
LABEL_MEM_REQ: str = "Memory Request:"
LABEL_MEM_LIM: str = "Memory Limit:"
LABEL_MEM_RATIO: str = "Mem L/R Ratio:"
LABEL_QOS: str = "QoS Class:"
LABEL_LIVENESS: str = "Liveness:"
LABEL_READINESS: str = "Readiness:"
LABEL_STARTUP: str = "Startup:"
LABEL_REPLICAS: str = "Replicas:"
LABEL_PDB: str = "PDB:"
LABEL_PDB_TEMPLATE: str = "PDB Template:"
LABEL_PDB_MIN: str = "PDB Min Avail:"
LABEL_PDB_MAX: str = "PDB Max Unavail:"
LABEL_ANTIAFFINITY: str = "Anti-Affinity:"
LABEL_TOPOLOGY: str = "Topology Spread:"
LABEL_HPA: str = "HPA:"
LABEL_TEAM: str = "Team:"
LABEL_PRIORITY: str = "Priority Class:"
LABEL_VALUES_FILE: str = "Values File:"

# QoS class color mapping (Rich markup colors)
QOS_COLORS: dict[str, str] = {
    "Guaranteed": "green",
    "Burstable": "yellow",
    "BestEffort": "red",
}

# Ratio thresholds for color coding
RATIO_GOOD_MAX: float = 2.0
RATIO_WARN_MAX: float = 4.0
