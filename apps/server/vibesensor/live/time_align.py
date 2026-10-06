"""Per-buffer analysis time ranges.

:class:`~vibesensor.live.buffers.ClientBuffer` uses this to report the time
window its latest spectrum describes, which recording uses to place each live
sample on the run timeline.
"""

from __future__ import annotations


def analysis_time_range(
    *,
    count: int,
    last_ingest_mono_s: float,
    sample_rate_hz: int,
    window_samples: int,
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
    window_samples:
        Length of the analysed block in samples (the FFT block: the spectrum
        and its peaks describe only the newest ``fft_n`` samples).
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
    if window_samples <= 0:
        return None
    n_window = min(count, window_samples)
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
