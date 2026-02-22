"""Tests for event fetcher."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from kubeagle.controllers.cluster.fetchers.event_fetcher import (
    EventFetcher,
)


class TestEventFetcher:
    """Tests for EventFetcher class."""

    @pytest.fixture
    def mock_run_kubectl(self) -> AsyncMock:
        """Create mock run_kubectl function."""
        return AsyncMock()

    def test_fetcher_init(self, mock_run_kubectl: AsyncMock) -> None:
        """Test EventFetcher initialization with run_kubectl_func."""
        fetcher = EventFetcher(run_kubectl_func=mock_run_kubectl)
        assert fetcher._run_kubectl is mock_run_kubectl

    def test_fetcher_init_default_context(self, mock_run_kubectl: AsyncMock) -> None:
        """Test EventFetcher initialization stores the callable."""
        fetcher = EventFetcher(mock_run_kubectl)
        assert fetcher._run_kubectl is mock_run_kubectl

    @pytest.mark.asyncio
    async def test_fetch_warning_events_raw_for_namespace_uses_namespace_scope(
        self,
        mock_run_kubectl: AsyncMock,
    ) -> None:
        """Namespace-scoped warning fetch should use -n namespace."""
        mock_run_kubectl.return_value = '{"items": []}'
        fetcher = EventFetcher(mock_run_kubectl)

        events = await fetcher.fetch_warning_events_raw(namespace="payments")

        assert events == []
        called_args = mock_run_kubectl.await_args_list[0].args[0]
        assert "--all-namespaces" not in called_args
        assert "-n" in called_args
        ns_index = called_args.index("-n")
        assert called_args[ns_index + 1] == "payments"

