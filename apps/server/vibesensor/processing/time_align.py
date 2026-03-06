"""Time-alignment utilities for multi-sensor overlap analysis.

Pure functions that compute intersection-over-union overlap metrics
and per-buffer analysis time ranges.  Used by the
:class:`~vibesensor.processing.processor.SignalProcessor` for
multi-sensor alignment metadata.
"""

from __future__ import annotations

from typing import NamedTuple

_ALIGNMENT_MIN_OVERLAP = 0.5  # shared window must cover ≥50 % of the union


class OverlapResult(NamedTuple):
    """Computed overlap between multiple sensor time-ranges."""

    overlap_ratio: float
    aligned: bool
    shared_start: float
    shared_end: float
    overlap_s: float


def compute_overlap(starts: list[float], ends: list[float]) -> OverlapResult:
    """Compute the intersection-over-union overlap for a set of time ranges.

    Each pair ``(starts[i], ends[i])`` defines one sensor's active window.
    Returns an :class:`OverlapResult` with the overlap ratio, alignment flag,
    and the shared window boundaries.
    """
    if not starts or not ends or len(starts) != len(ends):
        return OverlapResult(
            overlap_ratio=0.0,
            aligned=False,
            shared_start=0.0,
            shared_end=0.0,
            overlap_s=0.0,
        )

    # Fast path: single range is trivially fully overlapping.
    if len(starts) == 1:
        s, e = starts[0], ends[0]
        dur = max(0.0, e - s)
        return OverlapResult(
            overlap_ratio=1.0 if dur > 0 else 0.0,
            aligned=dur > 0,
            shared_start=s,
            shared_end=e,
            overlap_s=dur,
        )

    shared_start = max(starts)
    shared_end = min(ends)
    overlap = max(0.0, shared_end - shared_start)

    # Early exit when ranges don't intersect — skip union computation.
    if overlap <= 0.0:
        return OverlapResult(
            overlap_ratio=0.0,
            aligned=False,
            shared_start=shared_start,
            shared_end=shared_end,
            overlap_s=0.0,
        )

    union = max(1e-9, max(ends) - min(starts))
    overlap_ratio = overlap / union
    return OverlapResult(
        overlap_ratio=overlap_ratio,
        aligned=overlap_ratio >= _ALIGNMENT_MIN_OVERLAP,
        shared_start=shared_start,
        shared_end=shared_end,
        overlap_s=overlap,
    )


def analysis_time_range(
    *,
    count: int,
    last_ingest_mono_s: float,
    sample_rate_hz: int,
    waveform_seconds: int,
    capacity: int,
    last_t0_us: int,
    samples_since_t0: int,
) -> tuple[float, float, bool] | None:
    """Return ``(start_s, end_s, synced)`` for a buffer's analysis window.

    When the sensor has reported a ``t0_us`` (set by ``CMD_SYNC_CLOCK``),
    the range is derived from the *sensor* timestamp which is already in
    server-relative microseconds — this is precise.  Otherwise the range
    is estimated from the server-side ``last_ingest_mono_s``.

    The third element *synced* is ``True`` when ``t0_us``-based alignment
    is in use.

    Returns ``None`` when the buffer has no data or no timing information.

    Parameters
    ----------
    count:
        Number of valid samples currently held in the circular buffer.
    last_ingest_mono_s:
        Server-side monotonic timestamp of the most recently ingested frame,
        used as the fallback end-of-window reference when ``last_t0_us`` is 0.
    sample_rate_hz:
        Current sensor sample rate in Hz; used to convert sample counts to
        seconds.
    waveform_seconds:
        Desired analysis window duration in seconds (bounded by *capacity*).
    capacity:
        Total buffer capacity in samples.
    last_t0_us:
        Sensor-clock timestamp (µs, server-relative after ``CMD_SYNC_CLOCK``)
        of the first sample in the most-recently ingested frame.  Zero if the
        sensor has not yet been clock-synced.
    samples_since_t0:
        Number of samples ingested since ``last_t0_us`` was recorded; used to
        advance the end-of-window pointer to the newest sample.
    """
    if count == 0 or last_ingest_mono_s <= 0:
        return None
    sr = sample_rate_hz
    if sr <= 0:
        return None
    if waveform_seconds <= 0:
        return None
    desired = max(1, sr * waveform_seconds)
    n_window = min(count, capacity, desired)
    duration_s = n_window / sr

    if last_t0_us > 0:
        # Sensor-clock path (precise, after CMD_SYNC_CLOCK).
        # last_t0_us marks the *first sample* in the most recently
        # ingested frame.  Advance by the samples in that frame to
        # approximate the newest sample time.
        safe_since_t0 = max(0, samples_since_t0)
        end_us = last_t0_us + (safe_since_t0 * 1_000_000) // max(1, sr)
        end_s = end_us / 1_000_000
        start_s = end_s - duration_s
        return (start_s, end_s, True)

    # Fallback: server arrival time.
    end = last_ingest_mono_s
    start = end - duration_s
    return (start, end, False)
