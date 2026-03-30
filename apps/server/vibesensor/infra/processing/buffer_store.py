from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from threading import RLock

from vibesensor.infra.processing.buffer_mutations import ClientBufferMutator
from vibesensor.infra.processing.buffer_registry import ClientBufferRegistry
from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.ingest_preparation import IngestChunkPreparer
from vibesensor.infra.processing.models import (
    CachedMetricsHit,
    ClientMetrics,
    FloatArray,
    MetricsComputationResult,
    MetricsSnapshot,
    ProcessorConfig,
    ProcessorStats,
)
from vibesensor.infra.processing.ring_buffer_ingest import apply_ring_buffer_ingest
from vibesensor.infra.processing.snapshot_builder import (
    check_cache_hit,
    compute_snapshot_window,
)
from vibesensor.shared.types.payload_types import (
    IntakeStatsPayload,
)

LOGGER = logging.getLogger(__name__)


class SignalBufferStore:
    """Coordinate shared processing buffers across registry, mutation, and snapshot seams."""

    def __init__(self, config: ProcessorConfig) -> None:
        self.config = config
        self._registry = ClientBufferRegistry(config)
        self._buffer_mutator = ClientBufferMutator(config)
        self._ingest_preparer = IngestChunkPreparer(config)
        self.stats = ProcessorStats()

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
        with self.locked_client_buffer(client_id) as buf:
            if buf is None:
                return
            self._buffer_mutator.reset(buf)
        LOGGER.info("Flushed signal buffer for client %s (%s)", client_id, reason)

    def ingest(
        self,
        client_id: str,
        samples: FloatArray,
        *,
        sample_rate_hz: int | None = None,
        t0_us: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        t_start = clock()
        if samples.size == 0:
            return
        chunk = self._ingest_preparer.normalize_chunk(client_id, samples)
        if chunk is None:
            return

        ingested_samples = 0
        dropped_samples = 0
        with self.locked_client_buffer(client_id, create=True) as buf:
            assert buf is not None
            if sample_rate_hz is not None and sample_rate_hz > 0:
                self._buffer_mutator.apply_sample_rate_override(
                    buf,
                    sample_rate_hz,
                    resize_buffer=True,
                )
            now_mono = clock()
            buf.last_ingest_mono_s = now_mono

            prepared = self._ingest_preparer.apply_overflow_policy(
                client_id,
                chunk,
                capacity=buf.capacity,
            )
            dropped_samples = prepared.overflow.drop_count
            ingested_samples = apply_ring_buffer_ingest(buf, prepared.chunk, t0_us=t0_us)
            self._buffer_mutator.invalidate_cached_payloads(buf)
        with self.lock:
            self.stats.total_ingested_samples += ingested_samples
            self.stats.buffer_overflow_drops += dropped_samples
            self.stats.last_ingest_duration_s = clock() - t_start

    def snapshot_for_compute(
        self,
        client_id: str,
        *,
        sample_rate_hz: int | None = None,
    ) -> CachedMetricsHit | MetricsSnapshot | None:
        """Return a cached hit or an immutable compute snapshot for *client_id*."""
        with self.locked_client_buffer(client_id) as buf:
            if buf is None or buf.count == 0:
                return None
            if sample_rate_hz is not None and sample_rate_hz > 0:
                self._buffer_mutator.apply_sample_rate_override(
                    buf,
                    sample_rate_hz,
                    resize_buffer=False,
                )
            sr = buf.sample_rate_hz or self.config.sample_rate_hz

            cache_hit = check_cache_hit(
                ingest_generation=buf.ingest_generation,
                compute_generation=buf.compute_generation,
                compute_sample_rate_hz=buf.compute_sample_rate_hz,
                effective_sample_rate_hz=sr,
                latest_metrics=buf.latest_metrics,
            )
            if cache_hit is not None:
                return cache_hit

            window = compute_snapshot_window(
                count=buf.count,
                capacity=buf.capacity,
                sample_rate_hz=sr,
                waveform_seconds=self.config.waveform_seconds,
                fft_n=self.config.fft_n,
            )

            fft_block: FloatArray | None = None
            if window.needs_separate_fft_block:
                fft_block = self._buffer_mutator.copy_latest(buf, self.config.fft_n)
                time_window = fft_block[:, -window.n_time :]
            else:
                time_window = self._buffer_mutator.copy_latest(buf, window.n_time)
                if buf.count >= self.config.fft_n:
                    fft_block = time_window[:, -self.config.fft_n :]
            return MetricsSnapshot(
                client_id=client_id,
                sample_rate_hz=sr,
                ingest_generation=buf.ingest_generation,
                buffer_epoch=buf.buffer_epoch,
                time_window=time_window,
                fft_block=fft_block,
            )

    def store_metrics_result(self, result: MetricsComputationResult) -> ClientMetrics:
        """Commit a compute result back into shared state and update stats."""
        with self.locked_client_buffer(result.client_id) as buf:
            if buf is not None:
                self._buffer_mutator.commit_metrics_result(buf, result)
        with self.lock:
            self.stats.last_compute_duration_s = result.duration_s
            self.stats.total_compute_calls += 1
        return result.metrics

    def record_compute_all_duration(self, duration_s: float) -> None:
        with self.lock:
            self.stats.last_compute_all_duration_s = duration_s

    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float] | None:
        with self.locked_client_buffer(client_id) as buf:
            if buf is None or buf.count == 0:
                return None
            idx = (buf.write_idx - 1) % buf.capacity
            return (
                float(buf.data[0, idx]),
                float(buf.data[1, idx]),
                float(buf.data[2, idx]),
            )

    def latest_sample_rate_hz(self, client_id: str) -> int | None:
        with self.locked_client_buffer(client_id) as buf:
            if buf is None:
                return None
            rate = int(buf.sample_rate_hz or 0)
            return rate if rate > 0 else None

    def latest_metrics(self, client_id: str) -> ClientMetrics:
        """Return the most recent computed metrics for *client_id*."""
        with self.locked_client_buffer(client_id) as buf:
            if buf is None:
                return {}
            return buf.latest_metrics

    def all_latest_metrics(self, client_ids: list[str]) -> dict[str, ClientMetrics]:
        """Return latest metrics for all requested clients."""
        with self.locked_client_buffers(client_ids) as buffers:
            result: dict[str, ClientMetrics] = {}
            for cid in client_ids:
                buf = buffers.get(cid)
                if buf is not None and buf.latest_metrics:
                    result[cid] = buf.latest_metrics
            return result

    def clients_with_recent_data(
        self,
        client_ids: list[str],
        *,
        max_age_s: float = 3.0,
    ) -> list[str]:
        """Return subset of *client_ids* that received data within *max_age_s*."""
        now = time.monotonic()
        with self.locked_client_buffers(client_ids) as buffers:
            result: list[str] = []
            for client_id in client_ids:
                buf = buffers.get(client_id)
                if buf is None or buf.last_ingest_mono_s <= 0:
                    continue
                if (now - buf.last_ingest_mono_s) <= max_age_s:
                    result.append(client_id)
            return result

    def evict_clients(self, keep_client_ids: set[str]) -> None:
        self._registry.evict_clients(keep_client_ids)

    def intake_stats(self) -> IntakeStatsPayload:
        with self.lock:
            return {
                "total_ingested_samples": self.stats.total_ingested_samples,
                "total_compute_calls": self.stats.total_compute_calls,
                "last_compute_duration_s": self.stats.last_compute_duration_s,
                "last_compute_all_duration_s": self.stats.last_compute_all_duration_s,
                "last_ingest_duration_s": self.stats.last_ingest_duration_s,
            }

    def buffer_overflow_drops(self) -> int:
        with self.lock:
            return self.stats.buffer_overflow_drops

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
