"""Tests for team parser."""

from __future__ import annotations

import pytest

from kubeagle.controllers.team.parsers.team_parser import TeamParser


class TestTeamParser:
    """Tests for TeamParser class."""

    @pytest.fixture
    def parser(self) -> TeamParser:
        """Create TeamParser instance."""
        return TeamParser()

    def test_parser_init(self, parser: TeamParser) -> None:
        """Test TeamParser initialization."""
        assert isinstance(parser, TeamParser)

    def test_group_charts_by_team_empty(self, parser: TeamParser) -> None:
        """Test group_charts_by_team with empty list."""
        result = parser.group_charts_by_team([])

        assert result == {}

    def test_group_charts_by_team_single_team(self, parser: TeamParser) -> None:
        """Test group_charts_by_team groups by team."""
        charts = [
            {"name": "chart1", "team": "team-a"},
            {"name": "chart2", "team": "team-a"},
            {"name": "chart3", "team": "team-b"},
        ]

        result = parser.group_charts_by_team(charts)

        assert "team-a" in result
        assert "team-b" in result
        assert len(result["team-a"]) == 2
        assert len(result["team-b"]) == 1

    def test_group_charts_by_team_unknown_team(self, parser: TeamParser) -> None:
        """Test group_charts_by_team handles unknown teams."""
        charts = [
            {"name": "chart1"},  # No team key
            {"name": "chart2", "team": "team-a"},
        ]

        result = parser.group_charts_by_team(charts)

        assert "Unknown" in result
        assert len(result["Unknown"]) == 1
        assert len(result["team-a"]) == 1
