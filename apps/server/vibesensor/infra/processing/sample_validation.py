from __future__ import annotations

import logging

import numpy as np

from vibesensor.infra.processing.models import FloatArray

LOGGER = logging.getLogger(__name__)


def normalize_sample_chunk(
    *,
    client_id: str,
    samples: FloatArray,
    accel_scale_g_per_lsb: float | None,
    logger: logging.Logger = LOGGER,
) -> FloatArray | None:
    """Return an ``(N, 3)`` float32 sample chunk or ``None`` when malformed."""
    chunk: FloatArray = np.asarray(samples, dtype=np.float32)
    if accel_scale_g_per_lsb is not None:
        chunk = chunk * np.float32(accel_scale_g_per_lsb)
    if chunk.ndim != 2 or chunk.shape[1] != 3:
        logger.warning(
            "Dropping malformed sample chunk for %s with shape %s",
            client_id,
            chunk.shape,
        )
        return None
    return chunk
