from __future__ import annotations

from threading import RLock

from vibesensor.infra.processing.models import ProcessorStats
from vibesensor.shared.types.payload_types import IntakeStatsPayload


class BufferStoreStats:
    """Own mutable buffer-store observability counters."""

    __slots__ = ("_lock", "_stats")

    def __init__(self, *, lock: RLock) -> None:
        self._lock = lock
        self._stats = ProcessorStats()

    def record_ingest(
        self,
        *,
        ingested_samples: int,
        dropped_samples: int,
        duration_s: float,
    ) -> None:
        with self._lock:
            self._stats.total_ingested_samples += ingested_samples
            self._stats.buffer_overflow_drops += dropped_samples
            self._stats.last_ingest_duration_s = duration_s

    def record_compute_result(self, *, duration_s: float) -> None:
        with self._lock:
            self._stats.last_compute_duration_s = duration_s
            self._stats.total_compute_calls += 1

    def record_compute_all_duration(self, duration_s: float) -> None:
        with self._lock:
            self._stats.last_compute_all_duration_s = duration_s

    def intake_stats(self) -> IntakeStatsPayload:
        with self._lock:
            return {
                "total_ingested_samples": self._stats.total_ingested_samples,
                "total_compute_calls": self._stats.total_compute_calls,
                "last_compute_duration_s": self._stats.last_compute_duration_s,
                "last_compute_all_duration_s": self._stats.last_compute_all_duration_s,
                "last_ingest_duration_s": self._stats.last_ingest_duration_s,
            }

    def buffer_overflow_drops(self) -> int:
        with self._lock:
            return self._stats.buffer_overflow_drops
