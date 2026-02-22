"""Team parser for parsing team-related data."""

from __future__ import annotations

from typing import Any


class TeamParser:
    """Parses team-related data into structured formats."""

    def __init__(self) -> None:
        """Initialize team parser."""
        pass

    def group_charts_by_team(
        self, charts: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Group charts by team name.

        Args:
            charts: List of chart dictionaries

        Returns:
            Dictionary mapping team name to list of charts.
        """
        by_team: dict[str, list[dict[str, Any]]] = {}
        for chart in charts:
            team = chart.get("team", "Unknown")
            if team not in by_team:
                by_team[team] = []
            by_team[team].append(chart)
        return by_team
