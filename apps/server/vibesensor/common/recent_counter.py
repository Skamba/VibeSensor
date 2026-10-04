"""Event counts over a sliding window of monotonic time."""

from __future__ import annotations

from collections import deque

__all__ = ["RECENT_WINDOW_S", "RecentCounter"]

RECENT_WINDOW_S = 60.0
"""Health and live warnings look at this much recent history; totals stay for diagnostics."""


class RecentCounter:
    """Count events in the last ``window_s`` seconds, in one-second buckets.

    Memory is bounded by the window (one bucket per second with events). Not
    thread-safe: the owner serialises access.
    """

    __slots__ = ("_buckets", "_total", "_window_s")

    def __init__(self, window_s: float = RECENT_WINDOW_S) -> None:
        self._window_s = window_s
        self._buckets: deque[list[int]] = deque()
        self._total = 0

    def add(self, count: int, now_mono: float) -> None:
        if count <= 0:
            return
        second = int(now_mono)
        if self._buckets and self._buckets[-1][0] == second:
            self._buckets[-1][1] += count
        else:
            self._buckets.append([second, count])
        self._total += count
        self._expire(now_mono)

    def total(self, now_mono: float) -> int:
        self._expire(now_mono)
        return self._total

    def clear(self) -> None:
        self._buckets.clear()
        self._total = 0

    def _expire(self, now_mono: float) -> None:
        oldest_kept = now_mono - self._window_s
        while self._buckets and self._buckets[0][0] + 1 <= oldest_kept:
            self._total -= self._buckets.popleft()[1]
