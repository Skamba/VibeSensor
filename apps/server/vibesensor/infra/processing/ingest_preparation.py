from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from vibesensor.infra.processing.buffer_capacity import OverflowResult, evaluate_overflow
from vibesensor.infra.processing.models import FloatArray, ProcessorConfig

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PreparedIngestChunk:
    """Normalized ingest chunk plus overflow trimming metadata."""

    chunk: FloatArray
    overflow: OverflowResult


class IngestChunkPreparer:
    """Own input normalization and overflow trimming for incoming sample chunks."""

    def __init__(self, config: ProcessorConfig) -> None:
        self._accel_scale_g_per_lsb = config.accel_scale_g_per_lsb

    def normalize_chunk(
        self,
        client_id: str,
        samples: FloatArray,
    ) -> FloatArray | None:
        chunk: FloatArray = np.asarray(samples, dtype=np.float32)
        if self._accel_scale_g_per_lsb is not None:
            chunk = chunk * np.float32(self._accel_scale_g_per_lsb)
        if chunk.ndim != 2 or chunk.shape[1] != 3:
            LOGGER.warning(
                "Dropping malformed sample chunk for %s with shape %s",
                client_id,
                chunk.shape,
            )
            return None
        return chunk

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
