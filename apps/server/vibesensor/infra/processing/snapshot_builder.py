"""Compute-snapshot caching and window-size helpers.

Extracted from ``SignalBufferStore.snapshot_for_compute()`` so cache-hit
decisions and window-size arithmetic are independently testable and
separate from lock acquisition and buffer reads.
"""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.infra.processing.models import CachedMetricsHit, ClientMetrics


def check_cache_hit(
    *,
    ingest_generation: int,
    compute_generation: int,
    compute_sample_rate_hz: int,
    effective_sample_rate_hz: int,
    latest_metrics: ClientMetrics,
) -> CachedMetricsHit | None:
    """Return a cache hit when the buffer has already been computed at the current generation."""
    if (
        compute_generation == ingest_generation
        and compute_sample_rate_hz == effective_sample_rate_hz
    ):
        return CachedMetricsHit(metrics=latest_metrics)
    return None


@dataclass(frozen=True, slots=True)
class SnapshotWindow:
    """Computed window sizes for snapshot assembly."""

    n_time: int
    needs_separate_fft_block: bool


def compute_snapshot_window(
    *,
    count: int,
    capacity: int,
    sample_rate_hz: int,
    waveform_seconds: int,
    fft_n: int,
) -> SnapshotWindow:
    """Compute the time-window size and FFT-block strategy for a compute snapshot."""
    desired_samples = int(max(1.0, float(sample_rate_hz) * float(waveform_seconds)))
    n_time = min(count, capacity, max(1, desired_samples))
    needs_separate_fft_block = count >= fft_n and n_time < fft_n
    return SnapshotWindow(
        n_time=n_time,
        needs_separate_fft_block=needs_separate_fft_block,
    )
