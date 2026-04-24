from __future__ import annotations

import logging
import time
from collections.abc import Callable

from vibesensor.infra.processing.buffer_mutations import ClientBufferMutator
from vibesensor.infra.processing.buffer_registry import ClientBufferRegistry
from vibesensor.infra.processing.buffer_store_stats import BufferStoreStats
from vibesensor.infra.processing.ingest_preparation import IngestChunkPreparer
from vibesensor.infra.processing.models import FloatArray, ProcessorConfig
from vibesensor.infra.processing.ring_buffer_ingest import apply_ring_buffer_ingest

LOGGER = logging.getLogger(__name__)


class BufferStoreIngestCoordinator:
    """Own buffer flush and ingest coordination apart from query/snapshot reads."""

    __slots__ = ("_buffer_mutator", "_config", "_ingest_preparer", "_registry", "_stats")

    def __init__(
        self,
        *,
        config: ProcessorConfig,
        registry: ClientBufferRegistry,
        buffer_mutator: ClientBufferMutator,
        ingest_preparer: IngestChunkPreparer,
        stats: BufferStoreStats,
    ) -> None:
        self._config = config
        self._registry = registry
        self._buffer_mutator = buffer_mutator
        self._ingest_preparer = ingest_preparer
        self._stats = stats

    def flush_client_buffer(
        self,
        client_id: str,
        *,
        reason: str = "sensor reset",
    ) -> None:
        with self._registry.locked_client_buffer(client_id) as buf:
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
        with self._registry.locked_client_buffer(client_id, create=True) as buf:
            assert buf is not None
            if sample_rate_hz is not None and sample_rate_hz > 0:
                self._buffer_mutator.apply_sample_rate_override(
                    buf,
                    sample_rate_hz,
                    resize_buffer=True,
                )
            buf.last_ingest_mono_s = clock()
            prepared = self._ingest_preparer.apply_overflow_policy(
                client_id,
                chunk,
                capacity=buf.capacity,
            )
            effective_sample_rate_hz = buf.sample_rate_hz or self._config.sample_rate_hz
            dropped_samples = prepared.overflow.drop_count
            adjusted_t0_us = prepared.adjusted_t0_us(
                t0_us=t0_us,
                sample_rate_hz=effective_sample_rate_hz,
            )
            ingested_samples = apply_ring_buffer_ingest(
                buf,
                prepared.chunk,
                t0_us=adjusted_t0_us,
            )
            self._buffer_mutator.invalidate_cached_payloads(buf)
        self._stats.record_ingest(
            ingested_samples=ingested_samples,
            dropped_samples=dropped_samples,
            duration_s=clock() - t_start,
        )
