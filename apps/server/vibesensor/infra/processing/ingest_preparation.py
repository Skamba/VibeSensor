from __future__ import annotations

import logging
from dataclasses import dataclass

from vibesensor.infra.processing.buffer_capacity import OverflowResult, evaluate_overflow
from vibesensor.infra.processing.models import FloatArray, ProcessorConfig
from vibesensor.infra.processing.sample_validation import normalize_sample_chunk

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PreparedIngestChunk:
    """Normalized ingest chunk plus overflow trimming metadata."""

    chunk: FloatArray
    overflow: OverflowResult

    def adjusted_t0_us(
        self,
        *,
        t0_us: int | None,
        sample_rate_hz: int,
    ) -> int | None:
        if t0_us is None or t0_us <= 0:
            return t0_us
        if self.overflow.start_offset <= 0 or sample_rate_hz <= 0:
            return int(t0_us)
        return int(t0_us) + (self.overflow.start_offset * 1_000_000) // sample_rate_hz


class IngestChunkPreparer:
    """Own input normalization and overflow trimming for incoming sample chunks."""

    def __init__(self, config: ProcessorConfig) -> None:
        self._accel_scale_g_per_lsb = config.accel_scale_g_per_lsb

    def normalize_chunk(
        self,
        client_id: str,
        samples: FloatArray,
    ) -> FloatArray | None:
        return normalize_sample_chunk(
            client_id=client_id,
            samples=samples,
            accel_scale_g_per_lsb=self._accel_scale_g_per_lsb,
            logger=LOGGER,
        )

    def apply_overflow_policy(
        self,
        client_id: str,
        chunk: FloatArray,
        *,
        capacity: int,
    ) -> PreparedIngestChunk:
        overflow = evaluate_overflow(int(chunk.shape[0]), capacity)
        if overflow.drop_count:
            LOGGER.warning(
                "Sample chunk for %s exceeds buffer capacity %d; discarding %d oldest samples "
                "from the incoming batch",
                client_id,
                capacity,
                overflow.drop_count,
            )
            chunk = chunk[overflow.start_offset :]
        return PreparedIngestChunk(chunk=chunk, overflow=overflow)
