"""In-memory PDF cache plus per-key build coordination for history reports."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from vibesensor.shared.types.report_cache import ReportPdfCacheKey

REPORT_PDF_CACHE_MAX_ENTRIES = 16
REPORT_PDF_CACHE_MAX_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class HistoryReportPdfCacheStats:
    """Current PDF cache memory-budget state."""

    entry_count: int
    total_bytes: int
    max_entries: int
    max_bytes: int


class HistoryReportPdfCache:
    """LRU PDF cache plus per-key build coordination."""

    __slots__ = (
        "_entries",
        "_lock_users",
        "_locks",
        "_max_bytes",
        "_max_entries",
        "_total_bytes",
    )

    def __init__(
        self,
        *,
        max_entries: int = REPORT_PDF_CACHE_MAX_ENTRIES,
        max_bytes: int = REPORT_PDF_CACHE_MAX_BYTES,
    ) -> None:
        self._entries: OrderedDict[ReportPdfCacheKey, bytes] = OrderedDict()
        self._locks: dict[ReportPdfCacheKey, asyncio.Lock] = {}
        self._lock_users: dict[ReportPdfCacheKey, int] = {}
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._total_bytes = 0

    def stats(self) -> HistoryReportPdfCacheStats:
        """Return cache size statistics for telemetry and diagnostics."""
        return HistoryReportPdfCacheStats(
            entry_count=len(self._entries),
            total_bytes=self._total_bytes,
            max_entries=self._max_entries,
            max_bytes=self._max_bytes,
        )

    def get(self, cache_key: ReportPdfCacheKey) -> bytes | None:
        """Return a cached PDF and refresh its LRU position."""
        cached_pdf = self._entries.get(cache_key)
        if cached_pdf is None:
            return None
        self._entries.move_to_end(cache_key)
        return cached_pdf

    async def get_or_build(
        self,
        cache_key: ReportPdfCacheKey,
        build_pdf: Callable[[], bytes],
    ) -> bytes:
        """Reuse or build a cached PDF while serializing concurrent builds per key."""
        build_lock = self._locks.setdefault(cache_key, asyncio.Lock())
        self._lock_users[cache_key] = self._lock_users.get(cache_key, 0) + 1
        try:
            async with build_lock:
                cached_pdf = self.get(cache_key)
                if cached_pdf is not None:
                    return cached_pdf
                pdf = await asyncio.to_thread(build_pdf)
                self._put(cache_key, pdf)
                return pdf
        finally:
            remaining_users = self._lock_users[cache_key] - 1
            if remaining_users > 0:
                self._lock_users[cache_key] = remaining_users
            else:
                self._lock_users.pop(cache_key, None)
                self._prune_stale_lock(cache_key, build_lock)

    def _put(self, cache_key: ReportPdfCacheKey, pdf: bytes) -> None:
        """Insert a PDF into the LRU cache and prune related coordination state."""
        existing_pdf = self._entries.pop(cache_key, None)
        if existing_pdf is not None:
            self._total_bytes -= len(existing_pdf)
        if len(pdf) > self._max_bytes:
            self._prune_stale_locks()
            return
        self._entries[cache_key] = pdf
        self._total_bytes += len(pdf)
        self._entries.move_to_end(cache_key)
        while self._entries and (
            len(self._entries) > self._max_entries or self._total_bytes > self._max_bytes
        ):
            evicted_key, evicted_pdf = self._entries.popitem(last=False)
            self._total_bytes -= len(evicted_pdf)
            if self._lock_users.get(evicted_key, 0) == 0:
                self._locks.pop(evicted_key, None)
        self._prune_stale_locks()

    def _prune_stale_lock(
        self,
        cache_key: ReportPdfCacheKey,
        build_lock: asyncio.Lock,
    ) -> None:
        """Drop one idle coordination lock when no cache entry owns it."""
        if (
            self._locks.get(cache_key) is build_lock
            and cache_key not in self._entries
            and not build_lock.locked()
            and self._lock_users.get(cache_key, 0) == 0
        ):
            self._locks.pop(cache_key, None)

    def _prune_stale_locks(self) -> None:
        """Drop unlocked coordination locks whose cache entries were already evicted."""
        if len(self._locks) > self._max_entries * 2:
            stale_keys = [
                key
                for key, lock in self._locks.items()
                if (
                    key not in self._entries
                    and not lock.locked()
                    and self._lock_users.get(key, 0) == 0
                )
            ]
            for key in stale_keys:
                self._locks.pop(key, None)
