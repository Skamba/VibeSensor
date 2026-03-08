"""Focused live-analysis snapshot state for dashboard diagnostics.

This module owns the rolling in-memory sample window that powers live
diagnostics and websocket findings previews. It is intentionally separate
from :mod:`vibesensor.metrics_log.logger` so runtime broadcast code can depend
on a narrow snapshot source instead of the full recording/persistence
orchestrator.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from itertools import islice
from threading import RLock

from ..constants import NUMERIC_TYPES
from ..runlog import utc_now_iso


class LiveAnalysisWindow:
    """Rolling live sample window with session-aware metadata snapshots."""

    def __init__(
        self,
        *,
        metadata_builder: Callable[[str, str], dict[str, object]],
        live_sample_window_s: float,
        max_samples: int = 20_000,
    ) -> None:
        self._metadata_builder = metadata_builder
        self._live_sample_window_s = float(live_sample_window_s)
        self._lock = RLock()
        self._samples: deque[dict[str, object]] = deque(maxlen=max_samples)
        self._current_run_id: str | None = None
        self._current_run_start_utc: str | None = None
        self._snapshot_start_utc = utc_now_iso()

    def start_session(self, *, run_id: str, start_time_utc: str) -> None:
        with self._lock:
            self._current_run_id = run_id
            self._current_run_start_utc = start_time_utc
            self._snapshot_start_utc = start_time_utc
            self._samples.clear()

    def stop_session(self) -> None:
        with self._lock:
            self._current_run_id = None
            self._current_run_start_utc = None

    def extend_rows(self, rows: Iterable[dict[str, object]], *, live_t_s: float) -> None:
        with self._lock:
            self._samples.extend(rows)
            self._prune_locked(live_t_s)

    def snapshot(self, max_rows: int = 4000) -> tuple[dict[str, object], list[dict[str, object]]]:
        with self._lock:
            run_id = self._current_run_id or "live"
            start_time_utc = self._current_run_start_utc or self._snapshot_start_utc
            metadata = self._metadata_builder(run_id, start_time_utc)
            metadata["end_time_utc"] = utc_now_iso()
            if max_rows <= 0:
                samples = list(self._samples)
            else:
                samples = list(islice(reversed(self._samples), max_rows))
                samples.reverse()
            return metadata, samples

    def _prune_locked(self, live_t_s: float) -> None:
        cutoff = float(live_t_s) - max(0.0, self._live_sample_window_s)
        while self._samples:
            ts = self._samples[0].get("t_s")
            if not isinstance(ts, NUMERIC_TYPES):
                self._samples.popleft()
                continue
            if float(ts) >= cutoff:
                break
            self._samples.popleft()
