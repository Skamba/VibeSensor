"""Ring-buffer ingest mutation helpers extracted from ``SignalBufferStore``."""

from __future__ import annotations

from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.models import FloatArray

_MAX_SAMPLES_SINCE_T0 = 2**28


def apply_ring_buffer_ingest(
    buf: ClientBuffer,
    chunk: FloatArray,
    *,
    t0_us: int | None = None,
) -> int:
    """Write a prepared chunk into ``buf`` and return the number of samples written."""
    sample_count = int(chunk.shape[0])
    capacity = buf.capacity
    end = buf.write_idx + sample_count
    if end <= capacity:
        buf.data[:, buf.write_idx : end] = chunk.T
    else:
        first = capacity - buf.write_idx
        buf.data[:, buf.write_idx :] = chunk[:first].T
        buf.data[:, : end % capacity] = chunk[first:].T

    buf.write_idx = end % capacity
    buf.count = min(capacity, buf.count + sample_count)
    _advance_sensor_clock(buf, sample_count, t0_us=t0_us)
    buf.ingest_generation += 1
    return sample_count


def _advance_sensor_clock(
    buf: ClientBuffer,
    sample_count: int,
    *,
    t0_us: int | None,
) -> None:
    if t0_us is not None and t0_us > 0:
        next_t0_us = int(t0_us)
        if next_t0_us > buf.last_t0_us:
            buf.last_t0_us = next_t0_us
            buf.samples_since_t0 = sample_count
            return
    buf.samples_since_t0 = min(buf.samples_since_t0 + sample_count, _MAX_SAMPLES_SINCE_T0)
