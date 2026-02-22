"""Tests for CacheManager - centralized cache coordination.

This module tests:
- CacheManager singleton pattern
- CacheManager invalidate operation
"""

from __future__ import annotations

import asyncio

import pytest

from kubeagle.models.cache.data_cache import DataCache
from kubeagle.utils.cache_manager import CacheManager

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def fresh_cache_manager() -> CacheManager:
    """Get a fresh CacheManager instance for testing."""
    # Reset singleton for each test
    CacheManager._instance = None
    CacheManager._lock = asyncio.Lock()
    manager = CacheManager()
    manager._initialized = False
    manager.__init__()
    return manager


# =============================================================================
# CacheManager Unit Tests
# =============================================================================


class TestCacheManagerImports:
    """Test that CacheManager can be imported correctly."""

    def test_cache_manager_import(self) -> None:
        """Test CacheManager class import."""
        from kubeagle.utils.cache_manager import CacheManager

        assert CacheManager is not None
        assert hasattr(CacheManager, "invalidate")

    def test_global_cache_manager_import(self) -> None:
        """Test global cache_manager instance import."""
        from kubeagle.utils import cache_manager

        assert cache_manager is not None


class TestCacheManagerSingleton:
    """Test CacheManager singleton pattern."""

    def test_singleton_returns_same_instance(self) -> None:
        """Test that singleton returns the same instance."""
        # Reset singleton
        CacheManager._instance = None

        manager1 = CacheManager()
        manager2 = CacheManager()

        assert manager1 is manager2

    def test_singleton_initialized_once(self) -> None:
        """Test that singleton is initialized only once."""
        # Reset singleton
        CacheManager._instance = None

        manager = CacheManager()
        manager._initialized = False

        # Create again
        manager2 = CacheManager()

        # Should be the same instance
        assert manager is manager2


class TestCacheManagerInvalidation:
    """Test CacheManager cache invalidation."""

    @pytest.mark.asyncio
    async def test_invalidate_cache(self, fresh_cache_manager: CacheManager) -> None:
        """Test invalidating a specific cache."""
        cache = DataCache()
        await cache.set("key1", {"data": "value1"}, ttl=300)
        fresh_cache_manager._entries["test_cache"] = type(
            "_CacheEntry", (), {"name": "test_cache", "cache": cache, "ttl_seconds": 300, "invalidator": None}
        )()

        await fresh_cache_manager.invalidate("test_cache")

        # Cache should be cleared (get returns None)
        assert await cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_invalidate_not_found_logs_warning(
        self, fresh_cache_manager: CacheManager
    ) -> None:
        """Test invalidating non-existent cache logs a warning."""
        from unittest.mock import patch

        with patch(
            "kubeagle.utils.cache_manager.logger"
        ) as mock_logger:
            await fresh_cache_manager.invalidate("nonexistent")

            mock_logger.warning.assert_called()


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    "TestCacheManagerImports",
    "TestCacheManagerInvalidation",
    "TestCacheManagerSingleton",
]
