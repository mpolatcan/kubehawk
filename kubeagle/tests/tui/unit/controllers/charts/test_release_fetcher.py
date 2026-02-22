"""Tests for release fetcher."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from kubeagle.controllers.charts.fetchers.release_fetcher import (
    ReleaseFetcher,
)


class TestReleaseFetcher:
    """Tests for ReleaseFetcher class."""

    @pytest.fixture
    def mock_run_helm(self) -> AsyncMock:
        """Create mock run_helm function."""
        return AsyncMock()

    def test_fetcher_init(self, mock_run_helm: AsyncMock) -> None:
        """Test ReleaseFetcher initialization."""
        fetcher = ReleaseFetcher(run_helm_func=mock_run_helm, context="my-cluster")
        assert fetcher._run_helm is mock_run_helm
        assert fetcher.context == "my-cluster"

    def test_fetcher_init_default_context(self, mock_run_helm: AsyncMock) -> None:
        """Test ReleaseFetcher with default context."""
        fetcher = ReleaseFetcher(run_helm_func=mock_run_helm)
        assert fetcher.context is None

    @pytest.mark.asyncio
    async def test_fetch_releases_success(self, mock_run_helm: AsyncMock) -> None:
        """Test fetch_releases returns releases."""
        fetcher = ReleaseFetcher(run_helm_func=mock_run_helm)

        releases_data = [
            {
                "name": "frontend",
                "namespace": "default",
                "chart": "frontend-1.0.0",
                "version": "1",
                "app_version": "1.0.0",
                "status": "deployed",
            },
            {
                "name": "backend",
                "namespace": "api",
                "chart": "backend-2.0.0",
                "version": "1",
                "app_version": "2.0.0",
                "status": "deployed",
            },
        ]
        mock_run_helm.return_value = json.dumps(releases_data)

        result = await fetcher.fetch_releases()

        assert len(result) == 2
        assert result[0]["name"] == "frontend"
        assert result[0]["namespace"] == "default"
        assert result[1]["name"] == "backend"
        assert result[1]["namespace"] == "api"

    @pytest.mark.asyncio
    async def test_fetch_releases_empty(self, mock_run_helm: AsyncMock) -> None:
        """Test fetch_releases returns empty list when no releases."""
        fetcher = ReleaseFetcher(run_helm_func=mock_run_helm)
        mock_run_helm.return_value = "[]"

        result = await fetcher.fetch_releases()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_releases_error(self, mock_run_helm: AsyncMock) -> None:
        """Test fetch_releases handles errors gracefully."""
        fetcher = ReleaseFetcher(run_helm_func=mock_run_helm)
        mock_run_helm.return_value = ""

        result = await fetcher.fetch_releases()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_releases_invalid_json(self, mock_run_helm: AsyncMock) -> None:
        """Test fetch_releases handles invalid JSON."""
        fetcher = ReleaseFetcher(run_helm_func=mock_run_helm)
        mock_run_helm.return_value = "invalid json"

        result = await fetcher.fetch_releases()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_release_values_with_output_success(
        self, mock_run_helm: AsyncMock
    ) -> None:
        """Test fetch_release_values_with_output returns values + raw output."""
        fetcher = ReleaseFetcher(run_helm_func=mock_run_helm)
        raw_output = "replicaCount: 2\nresources:\n  requests:\n    cpu: 100m\n"
        mock_run_helm.return_value = raw_output

        values, output = await fetcher.fetch_release_values_with_output(
            "my-release",
            "my-namespace",
        )

        assert values.get("replicaCount") == 2
        assert output == raw_output
        called_args = mock_run_helm.await_args_list[0].args[0]
        assert called_args[-2:] == ("-o", "yaml")

    @pytest.mark.asyncio
    async def test_fetch_release_values_with_output_empty(
        self, mock_run_helm: AsyncMock
    ) -> None:
        """Test fetch_release_values_with_output handles empty output."""
        fetcher = ReleaseFetcher(run_helm_func=mock_run_helm)
        mock_run_helm.return_value = ""

        values, output = await fetcher.fetch_release_values_with_output(
            "my-release",
            "my-namespace",
        )

        assert values == {}
        assert output is None
