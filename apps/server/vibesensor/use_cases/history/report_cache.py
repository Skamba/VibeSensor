"""In-memory PDF cache plus per-key build coordination for history reports."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable

from vibesensor.shared.types.report_cache import ReportPdfCacheKey

REPORT_PDF_CACHE_MAX_ENTRIES = 16


class HistoryReportPdfCache:
    """LRU PDF cache plus per-key build coordination."""

    __slots__ = ("_entries", "_locks")

    def __init__(self) -> None:
        self._entries: OrderedDict[ReportPdfCacheKey, bytes] = OrderedDict()
        self._locks: dict[ReportPdfCacheKey, asyncio.Lock] = {}

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
        async with build_lock:
            cached_pdf = self.get(cache_key)
            if cached_pdf is not None:
                return cached_pdf
            pdf = await asyncio.to_thread(build_pdf)
            self._put(cache_key, pdf)
            return pdf

    def _put(self, cache_key: ReportPdfCacheKey, pdf: bytes) -> None:
        """Insert a PDF into the LRU cache and prune related coordination state."""
        self._entries[cache_key] = pdf
        self._entries.move_to_end(cache_key)
        while len(self._entries) > REPORT_PDF_CACHE_MAX_ENTRIES:
            evicted_key, _ = self._entries.popitem(last=False)
            self._locks.pop(evicted_key, None)
        self._prune_stale_locks()

    def _prune_stale_locks(self) -> None:
        """Drop unlocked coordination locks whose cache entries were already evicted."""
        if len(self._locks) > REPORT_PDF_CACHE_MAX_ENTRIES * 2:
            stale_keys = [
                key
                for key, lock in self._locks.items()
                if key not in self._entries and not lock.locked()
            ]
            for key in stale_keys:
                self._locks.pop(key, None)
