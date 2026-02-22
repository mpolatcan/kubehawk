"""Chart fetcher for charts controller - fetches Helm chart data from repository."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from kubeagle.constants.limits import MAX_WORKERS

logger = logging.getLogger(__name__)


class ChartFetcher:
    """Fetches Helm chart data from repository."""
    _VALUES_FILE_PRIORITY = (
        "values-automation.yaml",
        "values.yaml",
        "values-default-namespace.yaml",
    )

    def __init__(self, repo_path: Path, max_workers: int = MAX_WORKERS) -> None:
        """Initialize chart fetcher.

        Args:
            repo_path: Path to Helm charts repository
            max_workers: Maximum number of parallel workers
        """
        self.repo_path = repo_path
        self.max_workers = max_workers

    def find_chart_directories(self) -> list[Path]:
        """Find all chart directories in the repository.

        Uses a lightweight values-file existence check instead of the full
        ``find_values_files`` scan to avoid redundant glob + sort work that
        will be repeated by ``_analyze_single_chart`` anyway.

        Returns:
            List of chart directory paths.
        """
        if not self.repo_path.exists():
            return []

        chart_dirs: list[Path] = []

        for chart_file in self.repo_path.rglob("Chart.yaml"):
            chart_dir = chart_file.parent
            if not self._is_valid_chart_dir(chart_dir):
                continue
            if not self._has_any_values_file(chart_dir):
                continue
            chart_dirs.append(chart_dir)

        return sorted(
            chart_dirs,
            key=lambda path: str(path.relative_to(self.repo_path)),
        )

    @staticmethod
    def _has_any_values_file(chart_dir: Path) -> bool:
        """Fast check for at least one values file without full glob + sort."""
        return any(
            f.is_file()
            and (f.name == "values.yaml" or f.name.startswith("values-"))
            for f in chart_dir.glob("values*.yaml")
        )

    def _is_valid_chart_dir(self, chart_dir: Path) -> bool:
        """Check whether chart directory should be included in analysis."""
        if not chart_dir.is_dir():
            return False

        try:
            rel_parts = chart_dir.relative_to(self.repo_path).parts
        except ValueError:
            return False

        if not rel_parts:
            return False

        # Skip hidden/special directories and Helm dependency sub-charts.
        if any(part[0] in (".", "_") for part in rel_parts):
            return False
        return "charts" not in rel_parts

    def find_values_files(self, chart_path: Path) -> list[Path]:
        """Find all values files for a chart in deterministic priority order."""
        if not chart_path.is_dir():
            return []

        values_files = [
            values_file
            for values_file in chart_path.glob("values*.yaml")
            if values_file.is_file()
            and (
                values_file.name == "values.yaml"
                or values_file.name.startswith("values-")
            )
        ]

        return sorted(values_files, key=self._values_file_sort_key)

    @classmethod
    def _values_file_sort_key(cls, values_file: Path) -> tuple[int, str]:
        """Sort key that preserves legacy priority and then name ordering."""
        file_name = values_file.name
        try:
            priority_index = cls._VALUES_FILE_PRIORITY.index(file_name)
        except ValueError:
            priority_index = len(cls._VALUES_FILE_PRIORITY)
        return priority_index, file_name

    _MAX_VALUES_FILE_BYTES = 5 * 1024 * 1024  # 5 MB

    def parse_values_file(self, values_file: Path) -> dict[str, Any] | None:
        """Parse a values YAML file.

        Args:
            values_file: Path to values file

        Returns:
            Parsed YAML content or None on error.
        """
        try:
            if values_file.stat().st_size > self._MAX_VALUES_FILE_BYTES:
                logger.warning("Values file too large, skipping: %s", values_file)
                return None
            with open(values_file) as f:
                return yaml.safe_load(f)
        except Exception:
            logger.exception(f"Error parsing values file: {values_file}")
            return None

