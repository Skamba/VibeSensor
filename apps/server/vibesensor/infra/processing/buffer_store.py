from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from threading import RLock

from vibesensor.infra.processing.buffer_mutations import ClientBufferMutator
from vibesensor.infra.processing.buffer_registry import ClientBufferRegistry
from vibesensor.infra.processing.buffer_store_ingest import BufferStoreIngestCoordinator
from vibesensor.infra.processing.buffer_store_snapshot import BufferStoreSnapshotReader
from vibesensor.infra.processing.buffer_store_stats import BufferStoreStats
from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.ingest_preparation import IngestChunkPreparer
from vibesensor.infra.processing.models import (
    CachedMetricsHit,
    ClientMetrics,
    FloatArray,
    MetricsComputationResult,
    MetricsSnapshot,
    ProcessorConfig,
)
from vibesensor.shared.types.analysis_time_range import AnalysisTimeRange
from vibesensor.shared.types.payload_types import (
    IntakeStatsPayload,
)


class SignalBufferStore:
    """Coordinate shared processing buffers across registry, mutation, and snapshot seams."""

    def __init__(self, config: ProcessorConfig) -> None:
        self.config = config
        self._registry = ClientBufferRegistry(config)
        self._buffer_mutator = ClientBufferMutator(config)
        self._ingest_preparer = IngestChunkPreparer(config)
        self._stats = BufferStoreStats(lock=self._registry.lock)
        self._ingest = BufferStoreIngestCoordinator(
            config=config,
            registry=self._registry,
            buffer_mutator=self._buffer_mutator,
            ingest_preparer=self._ingest_preparer,
            stats=self._stats,
        )
        self._snapshot = BufferStoreSnapshotReader(
            config=config,
            registry=self._registry,
            buffer_mutator=self._buffer_mutator,
        )

    @property
    def buffers(self) -> dict[str, ClientBuffer]:
        return self._registry.buffers

    @property
    def lock(self) -> RLock:
        return self._registry.lock

    def flush_client_buffer(
        self,
        client_id: str,
        *,
        reason: str = "sensor reset",
    ) -> None:
        """Reset the buffer for *client_id*, discarding all stored samples."""
        self._ingest.flush_client_buffer(client_id, reason=reason)

    def ingest(
        self,
        client_id: str,
        samples: FloatArray,
        *,
        sample_rate_hz: int | None = None,
        t0_us: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ingest.ingest(
            client_id,
            samples,
            sample_rate_hz=sample_rate_hz,
            t0_us=t0_us,
            clock=clock,
        )

    def snapshot_for_compute(
        self,
        client_id: str,
        *,
        sample_rate_hz: int | None = None,
    ) -> CachedMetricsHit | MetricsSnapshot | None:
        """Return a cached hit or an immutable compute snapshot for *client_id*."""
        return self._snapshot.snapshot_for_compute(client_id, sample_rate_hz=sample_rate_hz)

    def store_metrics_result(self, result: MetricsComputationResult) -> ClientMetrics:
        """Commit a compute result back into shared state and update stats."""
        with self.locked_client_buffer(result.client_id) as buf:
            if buf is not None:
                self._buffer_mutator.commit_metrics_result(buf, result)
        self._stats.record_compute_result(duration_s=result.duration_s)
        return result.metrics

    def record_compute_all_duration(self, duration_s: float) -> None:
        self._stats.record_compute_all_duration(duration_s)

    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float] | None:
        return self._snapshot.latest_sample_xyz(client_id)

    def latest_sample_rate_hz(self, client_id: str) -> int | None:
        return self._snapshot.latest_sample_rate_hz(client_id)

    def latest_analysis_time_range(self, client_id: str) -> AnalysisTimeRange | None:
        return self._snapshot.latest_analysis_time_range(client_id)

    def latest_metrics(self, client_id: str) -> ClientMetrics:
        """Return the most recent computed metrics for *client_id*."""
        return self._snapshot.latest_metrics(client_id)

    def all_latest_metrics(self, client_ids: list[str]) -> dict[str, ClientMetrics]:
        """Return latest metrics for all requested clients."""
        return self._snapshot.all_latest_metrics(client_ids)

    def clients_with_recent_data(
        self,
        client_ids: list[str],
        *,
        max_age_s: float = 3.0,
    ) -> list[str]:
        """Return subset of *client_ids* that received data within *max_age_s*."""
        return self._snapshot.clients_with_recent_data(client_ids, max_age_s=max_age_s)

    def evict_clients(self, keep_client_ids: set[str]) -> None:
        self._registry.evict_clients(keep_client_ids)

    def intake_stats(self) -> IntakeStatsPayload:
        return self._stats.intake_stats()

    def buffer_overflow_drops(self) -> int:
        return self._stats.buffer_overflow_drops()

    def locked_client_buffer(
        self,
        client_id: str,
        *,
        create: bool = False,
    ) -> AbstractContextManager[ClientBuffer | None]:
        return self._registry.locked_client_buffer(client_id, create=create)

    def locked_client_buffers(
        self,
        client_ids: Iterable[str],
    ) -> AbstractContextManager[dict[str, ClientBuffer]]:
        return self._registry.locked_client_buffers(client_ids)
