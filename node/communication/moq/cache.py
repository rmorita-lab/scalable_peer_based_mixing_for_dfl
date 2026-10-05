"""
Media over QUIC (MoQ) Object Cache Implementation.

Provides in-memory caching and deduplication for MoQ objects based on their
hierarchical namespace prefixes, group IDs (rounds), and object IDs (chunks).

Key capabilities:
1. Object Caching: Store (MoQHeader, payload) indexed by header.cache_key().
2. Prefix & Namespace Filtering: Query or purge cache entries by TrackNamespace prefix.
3. Round-based Purging: Efficiently purge entries from older training rounds (group_id < current_round).
4. LRU & Memory Bounds: Automatically evict entries when max_entries or max_bytes is exceeded.
5. Deduplication & Metrics: Fast O(1) detection of duplicate objects, hit/miss tracking.
"""

from __future__ import annotations
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Tuple, Union, Dict, Any, List

from communication.moq.header import MoQHeader
from communication.moq.namespace import TrackNamespace


logger = logging.getLogger(__name__)


@dataclass
class MoQCacheEntry:
    """Represents a cached MoQ object with metadata."""

    header: MoQHeader
    payload: bytes
    cached_at: float
    last_accessed: float
    access_count: int = 1

    @property
    def key(self) -> str:
        return self.header.cache_key()

    @property
    def size(self) -> int:
        return len(self.payload) + self.header.payload_length


class MoQCache:
    """
    Thread-safe MoQ Object Cache supporting LRU eviction, memory bounding,
    and round-based/prefix-based invalidation.
    """

    def __init__(
        self,
        max_entries: int = 10_000,
        max_bytes: int = 50 * 1024 * 1024,  # 50 MB default
        default_ttl: Optional[float] = None,
    ):
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._default_ttl = default_ttl

        self._lock = threading.RLock()
        self._entries: OrderedDict[str, MoQCacheEntry] = OrderedDict()
        self._total_bytes: int = 0

        # Metrics & statistics
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    @property
    def max_entries(self) -> int:
        return self._max_entries

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def contains(self, key_or_header: Union[str, MoQHeader]) -> bool:
        """Check if an object exists in cache without updating LRU order."""
        key = key_or_header.cache_key() if isinstance(key_or_header, MoQHeader) else key_or_header
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            if self._is_expired(entry):
                self._delete_entry(key)
                return False
            return True

    def get(self, key_or_header: Union[str, MoQHeader]) -> Optional[MoQCacheEntry]:
        """
        Retrieve a cached object by key or MoQHeader.
        Updates LRU access order and hit statistics.
        """
        key = key_or_header.cache_key() if isinstance(key_or_header, MoQHeader) else key_or_header
        now = time.time()

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None

            if self._is_expired(entry, now):
                self._delete_entry(key)
                self._misses += 1
                return None

            # Mark as accessed & move to end (MRU)
            entry.last_accessed = now
            entry.access_count += 1
            self._entries.move_to_end(key)
            self._hits += 1
            return entry

    def put(self, header: MoQHeader, payload: bytes) -> bool:
        """
        Store an object into the cache.
        Returns True if newly inserted, False if updated an existing entry.
        """
        key = header.cache_key()
        now = time.time()
        entry_size = len(payload)

        with self._lock:
            if key in self._entries:
                old_entry = self._entries[key]
                self._total_bytes -= len(old_entry.payload)
                old_entry.header = header
                old_entry.payload = payload
                old_entry.last_accessed = now
                old_entry.access_count += 1
                self._total_bytes += entry_size
                self._entries.move_to_end(key)
                return False

            new_entry = MoQCacheEntry(
                header=header,
                payload=payload,
                cached_at=now,
                last_accessed=now,
                access_count=1,
            )
            self._entries[key] = new_entry
            self._total_bytes += entry_size

            # Evict if exceeding capacity
            self._enforce_limits()
            return True

    def check_and_put(
        self, header: MoQHeader, payload: bytes
    ) -> Tuple[bool, Optional[MoQCacheEntry]]:
        """
        Atomic deduplication and cache insert.

        Returns:
            (is_duplicate, entry)
            - If object was already in cache: returns (True, existing_entry)
            - If object is new: inserts into cache and returns (False, new_entry)
        """
        key = header.cache_key()
        now = time.time()

        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                if not self._is_expired(existing, now):
                    existing.last_accessed = now
                    existing.access_count += 1
                    self._entries.move_to_end(key)
                    self._hits += 1
                    return True, existing
                else:
                    self._delete_entry(key)

            # Not found or expired -> insert new
            self._misses += 1
            new_entry = MoQCacheEntry(
                header=header,
                payload=payload,
                cached_at=now,
                last_accessed=now,
                access_count=1,
            )
            self._entries[key] = new_entry
            self._total_bytes += len(payload)
            self._enforce_limits()
            return False, new_entry

    def purge_round(self, older_than_round: int) -> int:
        """
        Purge all cached objects belonging to training rounds older than older_than_round.
        (group_id < older_than_round).

        Returns number of deleted entries.
        """
        with self._lock:
            to_remove = [
                key
                for key, entry in self._entries.items()
                if entry.header.group_id < older_than_round
            ]
            for key in to_remove:
                self._delete_entry(key)
            if to_remove:
                logger.info(
                    f"MoQCache: Purged {len(to_remove)} entries older than round {older_than_round} "
                    f"(remaining: {len(self._entries)})"
                )
            return len(to_remove)

    def purge_prefix(
        self, prefix: Union[TrackNamespace, str, Tuple[str, ...]]
    ) -> int:
        """
        Purge all cached objects whose namespace matches the given prefix.

        Returns number of deleted entries.
        """
        if not isinstance(prefix, TrackNamespace):
            prefix = TrackNamespace(prefix)

        with self._lock:
            to_remove = [
                key
                for key, entry in self._entries.items()
                if entry.header.namespace.has_prefix(prefix)
            ]
            for key in to_remove:
                self._delete_entry(key)
            return len(to_remove)

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._entries.clear()
            self._total_bytes = 0

    def stats(self) -> Dict[str, Any]:
        """Return snapshot of cache performance metrics."""
        with self._lock:
            total_lookups = self._hits + self._misses
            hit_ratio = (self._hits / total_lookups) if total_lookups > 0 else 0.0
            return {
                "entries": len(self._entries),
                "total_bytes": self._total_bytes,
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": hit_ratio,
                "evictions": self._evictions,
                "max_entries": self._max_entries,
                "max_bytes": self._max_bytes,
            }

    def _delete_entry(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._total_bytes -= len(entry.payload)

    def _is_expired(self, entry: MoQCacheEntry, now: Optional[float] = None) -> bool:
        if self._default_ttl is None:
            return False
        if now is None:
            now = time.time()
        return (now - entry.cached_at) > self._default_ttl

    def _enforce_limits(self) -> None:
        """Evict oldest entries (LRU) until within max_entries and max_bytes."""
        while len(self._entries) > self._max_entries:
            key, entry = self._entries.popitem(last=False)
            self._total_bytes -= len(entry.payload)
            self._evictions += 1

        while self._total_bytes > self._max_bytes and self._entries:
            key, entry = self._entries.popitem(last=False)
            self._total_bytes -= len(entry.payload)
            self._evictions += 1


# Global singleton instance for node-level caching
_global_moq_cache: Optional[MoQCache] = None
_global_lock = threading.Lock()


def get_moq_cache(
    max_entries: int = 10_000,
    max_bytes: int = 50 * 1024 * 1024,
) -> MoQCache:
    """Get or initialize the global node-level MoQCache instance."""
    global _global_moq_cache
    if _global_moq_cache is None:
        with _global_lock:
            if _global_moq_cache is None:
                _global_moq_cache = MoQCache(
                    max_entries=max_entries,
                    max_bytes=max_bytes,
                )
    return _global_moq_cache


def reset_moq_cache() -> None:
    """Reset the global cache instance (useful for testing)."""
    global _global_moq_cache
    with _global_lock:
        if _global_moq_cache is not None:
            _global_moq_cache.clear()
        _global_moq_cache = None
