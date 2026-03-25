"""Buffer capacity, overflow, and resize policy helpers.

Extracted from ``SignalBufferStore.ingest()`` so capacity decisions are
independently testable and separate from ring-buffer mutation mechanics.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_CLIENT_SAMPLE_RATE_HZ = 4096


@dataclass(frozen=True, slots=True)
class OverflowResult:
    """Outcome of evaluating an incoming chunk against buffer capacity."""

    keep_count: int
    drop_count: int
    start_offset: int


@dataclass(frozen=True, slots=True)
class ClampedRate:
    """Result of clamping a requested sample rate."""

    rate_hz: int
    was_clamped: bool


def evaluate_overflow(chunk_size: int, capacity: int) -> OverflowResult:
    """Decide how many samples to keep/drop from an incoming chunk.

    When the chunk exceeds capacity, the oldest incoming samples are
    discarded and only the most recent *capacity* samples are kept.
    """
    if chunk_size <= capacity:
        return OverflowResult(keep_count=chunk_size, drop_count=0, start_offset=0)
    drop_count = chunk_size - capacity
    return OverflowResult(
        keep_count=capacity,
        drop_count=drop_count,
        start_offset=drop_count,
    )


def clamp_sample_rate(
    requested_rate: int,
    *,
    max_rate: int = MAX_CLIENT_SAMPLE_RATE_HZ,
) -> ClampedRate:
    """Clamp a requested sample rate to the valid range ``[1, max_rate]``."""
    clamped = max(1, min(max_rate, int(requested_rate)))
    return ClampedRate(rate_hz=clamped, was_clamped=clamped != requested_rate)


def compute_resize_capacity(sample_rate_hz: int, waveform_seconds: int) -> int:
    """Compute target buffer capacity from sample rate and window duration."""
    return sample_rate_hz * waveform_seconds
