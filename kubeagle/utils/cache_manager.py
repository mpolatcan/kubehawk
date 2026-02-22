"""CacheManager - Centralized cache coordination for data loading.

This module provides CacheManager, a singleton for coordinating cache
invalidation across all controllers.

Usage:
    from kubeagle.utils.cache_manager import cache_manager

    # Get a controller's cache
    cache = cache_manager.get_controller_cache("charts")

    # Invalidate all caches
    await cache_manager.invalidate_all()

    # Get cache statistics
    stats = cache_manager.get_cache_stats()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from kubeagle.models.cache.data_cache import DataCache

logger = logging.getLogger(__name__)


class CacheManager:
    """Singleton cache manager for coordinating cache invalidation.

    This manager:
    - Registers caches from different controllers
    - Provides coordinated invalidation
    - Tracks cache statistics
    - Supports TTL policies per cache type
    """

    _instance: CacheManager | None = None
    _lock = asyncio.Lock()

    def __new__(cls) -> CacheManager:
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize the CacheManager (singleton)."""
        if self._initialized:
            return

        self._entries: dict[str, _CacheEntry] = {}
        self._invalidation_order: list[str] = []
        self._initialized = True

        logger.info("CacheManager initialized")

    # =========================================================================
    # Invalidation
    # =========================================================================

    async def invalidate(self, name: str) -> None:
        """Invalidate a specific cache.

        Args:
            name: Name of the cache to invalidate
        """
        entry = self._entries.get(name)
        if entry:
            await entry.cache.clear()
            logger.debug(f"Invalidated cache: {name}")
        else:
            logger.warning(f"Cache not found for invalidation: {name}")


# Global cache manager instance
cache_manager = CacheManager()


@dataclass
class _CacheEntry:
    """Internal cache entry with metadata."""

    name: str
    cache: DataCache
    ttl_seconds: int = 300
    invalidator: Callable[[], Awaitable[None]] | None = None


__all__ = [
    "CacheManager",
    "cache_manager",
]
