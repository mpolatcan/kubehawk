"""Data cache implementation."""

import asyncio
import time
from typing import Any


class DataCache:
    """TTL-based data caching with automatic invalidation and bounded size.

    Performance notes:
    - Read operations (get, get_if_fresh) are lock-free. Since asyncio is
      single-threaded and these methods perform only non-mutating dict reads,
      no lock is needed. Expired entries are left in place (soft-expired) and
      cleaned up lazily during set() eviction.
    - Write operations (set, clear) acquire the lock to prevent interleaving
      mutations from concurrent coroutines.
    """

    TTL_SECONDS = {
        "nodes": 300,
        "pods": 180,
        "events": 120,
        "charts": 600,
        "releases": 120,
    }

    MAX_ENTRIES = 256  # Generous limit to avoid premature eviction

    def __init__(self, max_entries: int | None = None) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._max_entries = max_entries or self.MAX_ENTRIES

    async def get(self, key: str) -> Any:
        """Get cached data or None if expired.

        Lock-free: reads the dict without mutation. Expired entries are
        soft-expired (left in place) and cleaned up during set().
        """
        entry = self._cache.get(key)
        if entry is None:
            return None

        ttl = self._get_ttl_info(key, entry)

        if ttl is not None and self._is_expired(entry, ttl):
            return None

        return entry["data"]

    def _get_ttl_info(self, key: str, entry: dict[str, Any]) -> int | None:
        """Get TTL value for a cache entry.

        Args:
            key: Cache key.
            entry: Cache entry containing timestamp and optional ttl.

        Returns:
            TTL in seconds or None.
        """
        return entry.get("ttl") or self.TTL_SECONDS.get(key, 300)

    def _is_expired(self, entry: dict[str, Any], ttl: int) -> bool:
        """Check if a cache entry is expired.

        Args:
            entry: Cache entry with timestamp.
            ttl: TTL in seconds.

        Returns:
            True if entry is expired.
        """
        age = time.monotonic() - entry["timestamp"]
        return age > ttl

    async def set(self, key: str, data: Any, ttl: int | None = None) -> None:
        """Cache data with current timestamp (thread-safe)."""
        async with self._lock:
            self._cache[key] = {"data": data, "timestamp": time.monotonic(), "ttl": ttl}
            if len(self._cache) > self._max_entries:
                self._evict_expired_then_oldest()

    def _evict_expired_then_oldest(self) -> None:
        """Evict expired entries first, then oldest by timestamp if still over limit.

        Must be called under lock.
        """
        if not self._cache:
            return

        # Phase 1: Remove all expired entries
        expired_keys = [
            k for k, entry in self._cache.items()
            if self._is_expired(entry, self._get_ttl_info(k, entry) or 300)
        ]
        for k in expired_keys:
            del self._cache[k]

        # Phase 2: If still over limit, evict oldest by timestamp
        while len(self._cache) > self._max_entries:
            oldest_key = min(self._cache, key=lambda k: self._cache[k]["timestamp"])
            del self._cache[oldest_key]

    async def get_if_fresh(self, key: str, max_age_seconds: float) -> Any:
        """Get cached data only if younger than max_age_seconds.

        Lock-free: performs a non-mutating dict read.

        Unlike ``get()``, this ignores the entry's own TTL and uses
        the caller-supplied *max_age_seconds* as the freshness threshold.

        Args:
            key: Cache key.
            max_age_seconds: Maximum acceptable age in seconds.

        Returns:
            Cached data if fresh enough, otherwise None.
        """
        entry = self._cache.get(key)
        if entry is None:
            return None
        age = time.monotonic() - entry["timestamp"]
        if age > max_age_seconds:
            return None
        return entry["data"]

    async def clear(self, key: str | None = None) -> None:
        """Clear cache for specific key or all (thread-safe)."""
        async with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()
