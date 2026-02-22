"""Base controller with async worker-friendly patterns for KubEagle TUI.

This module provides the foundation for background data loading using Textual Workers,
ensuring the UI remains responsive during kubectl/helm operations.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WorkerResult:
    """Result wrapper for worker operations."""

    success: bool
    data: Any | None = None
    error: str | None = None
    duration_ms: float = 0.0


class AsyncControllerMixin:
    """Mixin providing worker-friendly async patterns for controllers.

    This mixin enables controllers to be used with Textual Workers for
    background data loading without blocking the UI.
    """

    def __init__(self) -> None:
        """Initialize the async controller mixin."""
        self._load_start_time: float | None = None


class BaseController(AsyncControllerMixin, ABC):
    """Base controller class with worker-friendly patterns.

    Subclasses should implement the abstract methods to provide
    specific data fetching functionality.
    """

    @abstractmethod
    async def check_connection(self) -> bool:
        """Check if the data source is available.

        Returns:
            True if connection is available, False otherwise
        """
        ...

    @abstractmethod
    async def fetch_all(self) -> dict[str, Any]:
        """Fetch all data from the source.

        Returns:
            Dictionary containing all fetched data
        """
        ...
