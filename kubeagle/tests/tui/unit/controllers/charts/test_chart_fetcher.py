"""Tests for chart fetcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from kubeagle.controllers.charts.fetchers.chart_fetcher import ChartFetcher


class TestChartFetcher:
    """Tests for ChartFetcher class."""

    @pytest.fixture
    def fetcher(self, tmp_path: Path) -> ChartFetcher:
        """Create ChartFetcher instance."""
        return ChartFetcher(repo_path=tmp_path, max_workers=4)

    def test_fetcher_init(self, fetcher: ChartFetcher, tmp_path: Path) -> None:
        """Test ChartFetcher initialization."""
        assert fetcher.repo_path == tmp_path
        assert fetcher.max_workers == 4

    def test_find_chart_directories_empty(self, fetcher: ChartFetcher) -> None:
        """Test find_chart_directories with empty repository."""
        result = fetcher.find_chart_directories()
        assert result == []

    def test_find_chart_directories_no_values_yaml(
        self, fetcher: ChartFetcher, tmp_path: Path
    ) -> None:
        """Test find_chart_directories skips directories without values files."""
        chart_dir = tmp_path / "my-chart"
        chart_dir.mkdir()
        (chart_dir / "Chart.yaml").write_text("name: my-chart")

        result = fetcher.find_chart_directories()
        assert result == []

    def test_find_chart_directories_finds_valid_charts(
        self, fetcher: ChartFetcher, tmp_path: Path
    ) -> None:
        """Test find_chart_directories finds valid chart directories."""
        chart1 = tmp_path / "chart1"
        chart1.mkdir()
        (chart1 / "Chart.yaml").write_text("name: chart1")
        (chart1 / "values.yaml").write_text("key: value")

        chart2 = tmp_path / "chart2"
        chart2.mkdir()
        (chart2 / "Chart.yaml").write_text("name: chart2")
        (chart2 / "values.yaml").write_text("key: value")

        result = fetcher.find_chart_directories()
        assert len(result) == 2
        assert chart1 in result
        assert chart2 in result

    def test_find_chart_directories_finds_nested_charts(
        self, fetcher: ChartFetcher, tmp_path: Path
    ) -> None:
        """Test nested chart directories (e.g. architect/journey-builder-*) are discovered."""
        architect = tmp_path / "architect"
        architect.mkdir()

        oauth_manager = architect / "journey-builder-oauth-manager"
        oauth_manager.mkdir()
        (oauth_manager / "Chart.yaml").write_text("name: journey-builder-oauth-manager")
        (oauth_manager / "values.yaml").write_text("key: value")

        result = fetcher.find_chart_directories()
        assert result == [oauth_manager]

    def test_find_chart_directories_skips_dependency_subcharts(
        self, fetcher: ChartFetcher, tmp_path: Path
    ) -> None:
        """Test nested dependency charts under `charts/` are excluded."""
        parent_chart = tmp_path / "infra" / "kubecost"
        parent_chart.mkdir(parents=True)
        (parent_chart / "Chart.yaml").write_text("name: kubecost")
        (parent_chart / "values.yaml").write_text("key: value")

        dependency_chart = parent_chart / "charts" / "cost-analyzer"
        dependency_chart.mkdir(parents=True)
        (dependency_chart / "Chart.yaml").write_text("name: cost-analyzer")
        (dependency_chart / "values.yaml").write_text("key: value")

        result = fetcher.find_chart_directories()
        assert result == [parent_chart]

    def test_find_values_files_includes_all_values_variants(
        self, fetcher: ChartFetcher, tmp_path: Path
    ) -> None:
        """Test find_values_files discovers every supported values*.yaml variant."""
        chart_path = tmp_path / "my-chart"
        chart_path.mkdir()
        (chart_path / "values.yaml").write_text("key: default")
        (chart_path / "values-automation.yaml").write_text("key: automation")
        (chart_path / "values-default-namespace.yaml").write_text("key: namespace")
        (chart_path / "values-preview.yaml").write_text("key: preview")

        result = fetcher.find_values_files(chart_path)

        assert result == [
            chart_path / "values-automation.yaml",
            chart_path / "values.yaml",
            chart_path / "values-default-namespace.yaml",
            chart_path / "values-preview.yaml",
        ]

    def test_parse_values_file_valid(self, fetcher: ChartFetcher, tmp_path: Path) -> None:
        """Test parse_values_file parses valid YAML."""
        values_file = tmp_path / "values.yaml"
        values_file.write_text("key: value\nlist:\n  - item1\n  - item2")

        result = fetcher.parse_values_file(values_file)
        assert result is not None
        assert result["key"] == "value"
        assert result["list"] == ["item1", "item2"]

    def test_parse_values_file_invalid(self, fetcher: ChartFetcher, tmp_path: Path) -> None:
        """Test parse_values_file returns None for invalid YAML."""
        values_file = tmp_path / "values.yaml"
        values_file.write_text("invalid: yaml: content: [[[")

        result = fetcher.parse_values_file(values_file)
        assert result is None

    def test_parse_values_file_not_found(self, fetcher: ChartFetcher) -> None:
        """Test parse_values_file returns None for non-existent file."""
        result = fetcher.parse_values_file(Path("/nonexistent/values.yaml"))
        assert result is None
