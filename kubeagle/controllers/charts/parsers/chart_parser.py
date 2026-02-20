"""Chart parser for parsing Helm chart data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from kubeagle.constants.enums import QoSClass
from kubeagle.models.charts.chart_info import ChartInfo
from kubeagle.utils.resource_parser import (
    parse_cpu_from_dict,
    parse_memory_from_dict,
)


class ChartParser:
    """Parses Helm chart values and extracts relevant information."""

    def __init__(self, team_mapper: Any | None = None) -> None:
        """Initialize chart parser.

        Args:
            team_mapper: Optional team mapper for CODEOWNERS-based team detection.
        """
        self.team_mapper = team_mapper

    def _parse_cpu(
        self, values: dict[str, Any], container_type: str, resource: str
    ) -> float:
        """Parse CPU value in millicores from values dict.

        Args:
            values: Parsed values dictionary
            container_type: Container type (e.g., "requests", "limits")
            resource: Resource name (e.g., "cpu")

        Returns:
            CPU value in millicores.
        """
        return parse_cpu_from_dict(values, container_type, resource)

    def _parse_memory(
        self, values: dict[str, Any], container_type: str, resource: str
    ) -> float:
        """Parse memory value in bytes from values dict.

        Args:
            values: Parsed values dictionary
            container_type: Container type (e.g., "requests", "limits")
            resource: Resource name (e.g., "memory")

        Returns:
            Memory value in bytes.
        """
        return parse_memory_from_dict(values, container_type, resource)

    def parse(
        self, chart_path: Path, values: dict[str, Any], values_file: Path
    ) -> ChartInfo:
        """Parse a chart's values file and extract chart information.

        Args:
            chart_path: Path to chart directory
            values: Parsed values dictionary
            values_file: Path to values file used

        Returns:
            ChartInfo object with parsed data.
        """
        chart_name = self._resolve_chart_name(chart_path)

        # Extract team - first try CODEOWNERS via TeamMapper, then values.yaml
        team = self._extract_team(
            values,
            chart_name=chart_name,
            chart_path=chart_path,
            values_file=values_file,
        )

        # Parse resources
        cpu_request = parse_cpu_from_dict(values, "requests", "cpu")
        cpu_limit = parse_cpu_from_dict(values, "limits", "cpu")
        memory_request = parse_memory_from_dict(values, "requests", "memory")
        memory_limit = parse_memory_from_dict(values, "limits", "memory")

        # Determine QoS class
        qos_class = self._determine_qos(
            cpu_request, cpu_limit, memory_request, memory_limit
        )

        # Check for probes
        has_liveness = self._has_probe(values, "livenessProbe")
        has_readiness = self._has_probe(values, "readinessProbe")
        has_startup = self._has_probe(values, "startupProbe")

        # Also check nested probes structure
        if not has_liveness or not has_readiness or not has_startup:
            probes = values.get("probes", {})
            if not has_liveness:
                has_liveness = bool(probes.get("liveness"))
            if not has_readiness:
                has_readiness = bool(probes.get("readiness"))
            if not has_startup:
                has_startup = bool(probes.get("startup"))

        # Check for anti-affinity
        has_anti_affinity = self._has_anti_affinity(values)
        has_topology_spread = self._has_topology_spread(values)

        # Check PDB
        pdb_enabled = self._has_pdb(values)
        pdb_template_exists = self._has_pdb_template(chart_path)
        pdb_min_available, pdb_max_unavailable = self._get_pdb_values(values)

        # Get replicas
        replicas = self._get_replicas(values)

        # Get priority class
        priority_class = self._get_priority_class(values)

        return ChartInfo(
            name=chart_name,
            team=team,
            values_file=str(values_file),
            cpu_request=cpu_request,
            cpu_limit=cpu_limit,
            memory_request=memory_request,
            memory_limit=memory_limit,
            qos_class=qos_class,
            has_liveness=has_liveness,
            has_readiness=has_readiness,
            has_startup=has_startup,
            has_anti_affinity=has_anti_affinity,
            has_topology_spread=has_topology_spread,
            has_topology=has_topology_spread,
            pdb_enabled=pdb_enabled,
            pdb_template_exists=pdb_template_exists,
            pdb_min_available=pdb_min_available,
            pdb_max_unavailable=pdb_max_unavailable,
            replicas=replicas,
            priority_class=priority_class,
        )

    def _resolve_chart_name(self, chart_path: Path) -> str:
        """Resolve chart display/release name from chart metadata or directory path."""
        chart_name_from_yaml = self._read_chart_name_from_yaml(chart_path)
        if chart_name_from_yaml is not None:
            return chart_name_from_yaml

        return self._resolve_chart_name_from_path(chart_path)

    @staticmethod
    def _read_chart_name_from_yaml(chart_path: Path) -> str | None:
        """Read chart name from Chart.yaml metadata."""
        chart_yaml_path = chart_path / "Chart.yaml"
        if not chart_yaml_path.is_file():
            return None

        try:
            with open(chart_yaml_path, encoding="utf-8") as handle:
                content = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError):
            return None

        if not isinstance(content, dict):
            return None

        raw_name = content.get("name")
        if raw_name is None:
            return None

        chart_name = str(raw_name).strip()
        return chart_name or None

    @staticmethod
    def _resolve_chart_name_from_path(chart_path: Path) -> str:
        """Legacy path-based chart name resolution fallback."""
        if chart_path.name == "main" and chart_path.parent.name:
            return chart_path.parent.name
        return chart_path.name

    def _extract_team(
        self,
        values: dict[str, Any],
        chart_name: str | None = None,
        chart_path: Path | None = None,
        values_file: Path | None = None,
    ) -> str:
        """Extract team name from values content first, then CODEOWNERS mapper."""
        if self.team_mapper is not None and chart_name:
            resolve_chart_team = getattr(self.team_mapper, "resolve_chart_team", None)
            if callable(resolve_chart_team):
                return str(
                    resolve_chart_team(
                        chart_name=chart_name,
                        values=values,
                        chart_path=chart_path,
                        values_file=values_file,
                    )
                )

        team = self._extract_team_from_values(values)
        if team is not None:
            if self.team_mapper is not None and chart_name:
                register_mapping = getattr(self.team_mapper, "register_chart_team", None)
                if callable(register_mapping):
                    return str(register_mapping(chart_name, team))

            return team

        if self.team_mapper is not None and chart_name:
            mapped_team = self.team_mapper.get_team(chart_name)
            if mapped_team != "Unknown":
                return mapped_team

        return "Unknown"

    def _extract_team_from_values(self, values: dict[str, Any]) -> str | None:
        """Extract team value from known values.yaml team fields."""
        team_paths: list[list[str]] = [
            ["global", "labels", "project_team"],
            ["project_team"],
            ["global", "project_team"],
            ["helm", "global", "project_team"],
            ["team"],
            ["annotations", "team"],
            ["labels", "team"],
        ]

        for path in team_paths:
            current: Any = values
            found = True
            for key in path:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    found = False
                    break
            if not found or current is None:
                continue

            team = str(current).strip()
            if team:
                return team

        return None

    def _determine_qos(
        self, cpu_req: float, cpu_lim: float, mem_req: float, mem_lim: float
    ) -> QoSClass:
        """Determine QoS class based on resource requests/limits."""
        if cpu_req > 0 and cpu_lim > 0 and mem_req > 0 and mem_lim > 0:
            if cpu_req == cpu_lim and mem_req == mem_lim:
                return QoSClass.GUARANTEED
            return QoSClass.BURSTABLE
        return QoSClass.BEST_EFFORT

    def _has_probe(self, values: dict[str, Any], probe_name: str) -> bool:
        """Check if container has a specific probe."""
        return probe_name in values

    def _has_anti_affinity(self, values: dict[str, Any]) -> bool:
        """Check if pod anti-affinity is configured."""
        affinity = values.get("affinity", {})
        if not affinity:
            return False
        return affinity.get("podAntiAffinity") is not None

    def _has_topology_spread(self, values: dict[str, Any]) -> bool:
        """Check if topology spread constraints are configured."""
        topology = values.get("topologySpreadConstraints", [])
        return len(topology) > 0

    def _has_pdb(self, values: dict[str, Any]) -> bool:
        """Check if PDB is enabled."""
        pdb = values.get("pdb", {})
        if not pdb:
            return False
        return pdb.get("enabled", False)

    def _has_pdb_template(self, chart_path: Path) -> bool:
        """Check if chart has a PDB template file."""
        pdb_template_path = chart_path / "templates" / "pdb.yaml"
        return pdb_template_path.exists()

    def _get_pdb_values(self, values: dict[str, Any]) -> tuple[int | None, int | None]:
        """Extract PDB minAvailable and maxUnavailable values from values."""
        pdb = values.get("pdb", {})
        min_available: int | None = pdb.get("minAvailable")
        max_unavailable: int | None = pdb.get("maxUnavailable")

        # Convert string to int if needed
        if isinstance(min_available, str):
            try:
                min_available = int(min_available)
            except ValueError:
                min_available = None
        if isinstance(max_unavailable, str):
            try:
                max_unavailable = int(max_unavailable)
            except ValueError:
                max_unavailable = None

        return min_available, max_unavailable

    def _get_replicas(self, values: dict[str, Any]) -> int | None:
        """Get replica count."""
        replica_count = values.get("replicaCount")
        if replica_count is None:
            replica_count = values.get("replicas")
        return replica_count if isinstance(replica_count, int) else None

    def _get_priority_class(self, values: dict[str, Any]) -> str | None:
        """Get priority class name."""
        return values.get("priorityClassName")
