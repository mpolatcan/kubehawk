"""Team mapper for mapping chart directories to teams using CODEOWNERS file."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

from kubeagle.constants.patterns import (
    EMAIL_TEAM_PATTERN,
    GITHUB_TEAM_PATTERN,
    TEAM_PATTERN,
)
from kubeagle.models.teams.team_info import TeamInfo


class TeamMapper:
    """Map chart directories to teams using CODEOWNERS file."""

    __slots__ = ("_codeowners_path", "_load_lock", "_loaded", "team_mapping", "teams")
    _VALUES_FILE_CANDIDATES = (
        "values-automation.yaml",
        "values.yaml",
        "values-default-namespace.yaml",
    )
    _TEAM_VALUE_PATHS = (
        ("global", "labels", "project_team"),
        ("project_team",),
        ("global", "project_team"),
        ("helm", "global", "project_team"),
        ("team",),
        ("annotations", "team"),
        ("labels", "team"),
    )

    def __init__(self, codeowners_path: Path | None = None) -> None:
        """Initialize TeamMapper with optional CODEOWNERS path (lazy loading)."""
        self.teams: list[TeamInfo] = []
        self.team_mapping: dict[str, str] = {}
        self._codeowners_path = codeowners_path
        self._loaded = False
        self._load_lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        """Ensure data is loaded (sync fallback for non-async contexts).

        Called from both async and sync code paths and from worker threads.
        This must remain thread-safe and non-reentrant.
        """
        if self._loaded:
            return

        if self._codeowners_path is None:
            self._loaded = True
            return

        if not self._codeowners_path.exists():
            self._loaded = True
            return

        with self._load_lock:
            if self._loaded:
                return
            # Parse once; any I/O errors are handled in _parse_codeowners.
            self._parse_codeowners(self._codeowners_path)
            self._loaded = True

    def load_codeowners(self, codeowners_path: Path) -> None:
        """Load and parse a CODEOWNERS file."""
        self.teams = []
        self.team_mapping = {}
        self._parse_codeowners(codeowners_path)

    def _parse_codeowners(self, path: Path) -> None:
        """Parse CODEOWNERS file to extract team mappings."""
        if not path.exists():
            return

        try:
            with open(path, encoding="utf-8") as f:
                current_team = "Unknown"
                current_team_ref: str | None = None
                current_owners: list[str] = []

                for raw_line in f:
                    line = raw_line.strip()

                    if not line:
                        continue

                    if line.startswith("#"):
                        if "=======" in line:
                            continue

                        match = TEAM_PATTERN.search(line)
                        if match:
                            team_name = match.group(1)
                            current_team = self._normalize_team_name(team_name)
                            current_team_ref = team_name
                            current_owners = self._extract_owners_from_line(line)
                        else:
                            github_match = GITHUB_TEAM_PATTERN.search(line)
                            if github_match:
                                team_name = github_match.group(1)
                                if "/" in team_name:
                                    current_team = self._normalize_team_name(
                                        team_name.split("/")[-1]
                                    )
                                    current_team_ref = team_name
                                else:
                                    current_team = self._normalize_team_name(team_name)
                                    current_team_ref = team_name
                        continue

                    parts = line.split()

                    if not parts:
                        continue

                    path_pattern = parts[0]

                    if path_pattern.startswith("^"):
                        continue

                    line_owners = self._extract_owners_from_line(" ".join(parts[1:]))

                    if current_team == "Unknown" and line_owners:
                        current_team = self._extract_team_from_owner(line_owners[0])

                    normalized_pattern = path_pattern.lstrip("/")

                    if "**" in normalized_pattern:
                        normalized_pattern = normalized_pattern.split("**/")[-1]

                    team_info = TeamInfo(
                        name=current_team,
                        pattern=normalized_pattern,
                        owners=line_owners or current_owners,
                        team_ref=current_team_ref,
                    )
                    self.teams.append(team_info)

                    if normalized_pattern.endswith("/"):
                        dir_name = normalized_pattern.rstrip("/")
                        self.team_mapping[dir_name] = current_team
                    elif "*" in normalized_pattern:
                        prefix = normalized_pattern.rstrip("*")
                        if prefix:
                            self.team_mapping[prefix] = current_team
                    else:
                        self.team_mapping[normalized_pattern] = current_team

        except OSError:
            return

    def _extract_owners_from_line(self, line: str) -> list[str]:
        """Extract owner references from a line."""
        owners: list[str] = []

        for match in GITHUB_TEAM_PATTERN.finditer(line):
            owner = match.group(0)
            if owner not in owners:
                owners.append(owner)

        for match in EMAIL_TEAM_PATTERN.finditer(line):
            owner = match.group(1)
            if owner not in owners:
                owners.append(owner)

        return owners

    def _normalize_name(self, name: str) -> str:
        """Normalize a name for consistent display.

        Short all-uppercase acronyms (QA, AI, SRE) are preserved as-is.
        Longer segments get title-cased for readability.
        """
        name = name.lstrip("@").replace("_", "-")
        parts = name.split("-")
        normalized_parts = [
            part if (part.isupper() and len(part) <= 3) else part.title()
            for part in parts
        ]
        return "-".join(normalized_parts)

    def _normalize_team_name(self, name: str) -> str:
        """Normalize a team name for consistent display."""
        return self._normalize_name(name)

    def _extract_team_from_owner(self, owner: str) -> str:
        """Extract a team name from an owner reference."""
        owner = owner.strip()

        if owner.startswith("@"):
            team = owner.lstrip("@")
            if "/" in team:
                team = team.split("/")[-1]
            return self._normalize_name(team)

        if "@" in owner:
            team = owner.split("@")[0]
            return self._normalize_name(team)

        return self._normalize_name(owner)

    def get_team_for_path(self, chart_path: Path) -> str | None:
        """Get team name for a chart path.

        Checks chart name first, then parent directory names to support
        CODEOWNERS directory-level patterns like ``/mobile/`` covering all
        nested charts under that directory.
        """
        self._ensure_loaded()
        chart_name = chart_path.name

        if chart_name in self.team_mapping:
            return self.team_mapping[chart_name]

        best_match: str | None = None
        best_match_length = 0

        for pattern, team in self.team_mapping.items():
            if chart_name.startswith(pattern):
                match_length = len(pattern)
                if match_length > best_match_length:
                    best_match = team
                    best_match_length = match_length

        if best_match is not None:
            return best_match

        # Check parent directory names against directory-level CODEOWNERS
        # patterns.  This handles nested charts like ``mobile/aconsumer``
        # where ``/mobile/`` is mapped to "Mobile" in CODEOWNERS.
        for parent in chart_path.parents:
            parent_name = parent.name
            if not parent_name:
                break
            if parent_name in self.team_mapping:
                return self.team_mapping[parent_name]

        return None

    def get_team(self, chart_name: str) -> str:
        """Get team name for a chart by name."""
        self._ensure_loaded()
        return self.team_mapping.get(chart_name, "Unknown")

    def resolve_chart_team(
        self,
        chart_name: str,
        values: dict[str, Any] | None = None,
        chart_path: Path | None = None,
        values_file: Path | None = None,
    ) -> str:
        """Resolve chart team from values, CODEOWNERS, then sibling heuristics.

        Values-file teams take priority over CODEOWNERS because they represent
        the explicit team assignment chosen by the chart author.
        """
        self._ensure_loaded()

        team_from_values = self._extract_team_from_values_dict(values)
        if team_from_values is None and chart_path is not None:
            team_from_values = self._extract_team_from_values_files(
                chart_path,
                skip_file=values_file,
            )

        if team_from_values is not None:
            # Values-file team takes priority — force-update the mapping
            # so downstream code sees the correct team even if CODEOWNERS
            # had a different assignment.
            normalized_team = self._normalize_team_name(team_from_values)
            normalized_chart = chart_name.strip()
            if normalized_chart and normalized_team:
                with self._load_lock:
                    self.team_mapping[normalized_chart] = normalized_team
            return normalized_team

        codeowners_team: str | None = None
        if chart_path is not None:
            codeowners_team = self.get_team_for_path(chart_path)
        if codeowners_team in (None, "Unknown"):
            codeowners_team = self.get_team(chart_name)
        if codeowners_team not in (None, "Unknown"):
            return codeowners_team

        sibling_team = (
            self._infer_team_from_siblings(chart_path) if chart_path is not None else None
        )
        if sibling_team is not None:
            return self.register_chart_team(chart_name, sibling_team)

        return "Unknown"

    def _extract_team_from_values_dict(self, values: dict[str, Any] | None) -> str | None:
        """Extract team from parsed values dictionary using supported key paths."""
        if not isinstance(values, dict):
            return None

        for path in self._TEAM_VALUE_PATHS:
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

    def _extract_team_from_values_files(
        self,
        chart_path: Path,
        skip_file: Path | None = None,
    ) -> str | None:
        """Try to extract team from alternate values files for the same chart."""
        skip_target: Path | None = None
        if skip_file is not None:
            try:
                skip_target = skip_file.resolve()
            except OSError:
                skip_target = skip_file

        for filename in self._VALUES_FILE_CANDIDATES:
            candidate = chart_path / filename
            if not candidate.exists():
                continue

            try:
                candidate_resolved = candidate.resolve()
            except OSError:
                candidate_resolved = candidate

            if skip_target is not None and candidate_resolved == skip_target:
                continue

            try:
                with open(candidate, encoding="utf-8") as handle:
                    parsed = yaml.safe_load(handle)
            except (OSError, yaml.YAMLError):
                continue

            team = self._extract_team_from_values_dict(parsed)
            if team is not None:
                return team

        return None

    def _infer_team_from_siblings(self, chart_path: Path) -> str | None:
        """Infer team from same-level chart siblings when they are unanimous."""
        parent_dir = chart_path.parent
        if not parent_dir.exists() or not parent_dir.is_dir():
            return None

        inferred_teams: set[str] = set()

        for sibling in sorted(parent_dir.iterdir()):
            if sibling == chart_path or not sibling.is_dir():
                continue
            if not (sibling / "Chart.yaml").exists():
                continue

            sibling_team = self._resolve_sibling_team(sibling)
            if sibling_team is None or sibling_team == "Unknown":
                continue

            inferred_teams.add(self._normalize_team_name(sibling_team))
            if len(inferred_teams) > 1:
                return None

        if len(inferred_teams) == 1:
            return next(iter(inferred_teams))
        return None

    def _resolve_sibling_team(self, sibling_path: Path) -> str | None:
        """Resolve a sibling chart team from CODEOWNERS first, then values files."""
        sibling_mapped = self.get_team_for_path(sibling_path)
        if sibling_mapped not in (None, "Unknown"):
            return sibling_mapped

        sibling_chart_name = (
            sibling_path.parent.name
            if sibling_path.name == "main" and sibling_path.parent.name
            else sibling_path.name
        )
        sibling_mapped = self.get_team(sibling_chart_name)
        if sibling_mapped != "Unknown":
            return sibling_mapped

        return self._extract_team_from_values_files(sibling_path)

    def register_chart_team(self, chart_name: str, team_name: str) -> str:
        """Register or update team mapping discovered from values data."""
        self._ensure_loaded()

        normalized_chart = chart_name.strip()
        normalized_team_input = team_name.strip()
        if not normalized_chart or not normalized_team_input:
            return "Unknown"

        current_team = self.team_mapping.get(normalized_chart)
        if current_team and current_team != "Unknown":
            return current_team

        normalized_team = self._normalize_team_name(normalized_team_input)

        with self._load_lock:
            self.team_mapping[normalized_chart] = normalized_team

            for idx, info in enumerate(self.teams):
                if info.pattern == normalized_chart:
                    self.teams[idx] = TeamInfo(
                        name=normalized_team,
                        pattern=normalized_chart,
                        owners=info.owners,
                        team_ref=normalized_team_input,
                    )
                    break
            else:
                self.teams.append(
                    TeamInfo(
                        name=normalized_team,
                        pattern=normalized_chart,
                        owners=[],
                        team_ref=normalized_team_input,
                    )
                )

        return normalized_team

    def get_all_teams(self) -> list[str]:
        """Get list of all unique team names."""
        self._ensure_loaded()
        unique_teams = {team.name for team in self.teams}
        unique_teams.update(self.team_mapping.values())
        return sorted(unique_teams)

    def get_teams_with_charts(self) -> dict[str, list[str]]:
        """Get mapping of teams to their charts."""
        self._ensure_loaded()
        result: dict[str, list[str]] = {}

        for chart, team in self.team_mapping.items():
            if team not in result:
                result[team] = []
            result[team].append(chart)

        for team_info in self.teams:
            if team_info.name not in result:
                result[team_info.name] = []
            if team_info.pattern not in result[team_info.name]:
                result[team_info.name].append(team_info.pattern)

        return result

    def find_team_info(self, team_name: str) -> list[TeamInfo]:
        """Find all TeamInfo entries for a given team name."""
        self._ensure_loaded()
        normalized = team_name.lower().replace(" ", "-")
        return [t for t in self.teams if t.name.lower().replace(" ", "-") == normalized]

    def find_charts_for_team(self, team_name: str) -> list[str]:
        """Find all chart names/patterns owned by a team."""
        team_charts = self.find_team_info(team_name)
        return [t.pattern for t in team_charts]

    def get_team_owners(self, team_name: str) -> list[str]:
        """Get all owners for a team."""
        team_charts = self.find_team_info(team_name)
        owners_set: set[str] = set()
        for chart in team_charts:
            owners_set.update(chart.owners)
        return list(owners_set)

    def has_team(self, team_name: str) -> bool:
        """Check if a team exists in the mapping."""
        self._ensure_loaded()
        normalized = team_name.lower().replace(" ", "-")
        return any(t.name.lower().replace(" ", "-") == normalized for t in self.teams)

    def search_by_owner(self, owner_pattern: str) -> list[TeamInfo]:
        """Find all teams that have an owner matching the pattern."""
        self._ensure_loaded()
        results: list[TeamInfo] = []
        for team_info in self.teams:
            for owner in team_info.owners:
                if owner_pattern.lower() in owner.lower():
                    results.append(team_info)
                    break
        return results

    def to_dict(self) -> dict[str, Any]:
        """Export team mapping as a dictionary for serialization."""
        self._ensure_loaded()
        return {
            "teams": [
                {
                    "name": t.name,
                    "pattern": t.pattern,
                    "owners": t.owners,
                    "team_ref": t.team_ref,
                }
                for t in self.teams
            ],
            "team_mapping": dict(self.team_mapping),
        }
