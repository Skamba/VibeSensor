"""Per-client ring buffer for live accelerometer data.

``ClientBuffer`` holds one sensor's circular sample buffer, its latest computed
metrics/spectrum, and the generation counters used to discard stale compute
results and reuse cached payloads. All methods assume the caller holds the
owning :class:`~vibesensor.live.processor.SignalProcessor` lock.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from vibesensor.dsp.vibration_strength import (
    VibrationStrengthMetrics,
    empty_vibration_strength_metrics,
)
from vibesensor.live.analysis_time_range import AnalysisTimeRange
from vibesensor.live.models import (
    ClientMetrics,
    FloatArray,
    MetricsComputationResult,
    SpectrumByAxis,
)
from vibesensor.live.payload_types import SpectrumSeriesPayload
from vibesensor.live.time_align import analysis_time_range

LOGGER = logging.getLogger(__name__)

MAX_CLIENT_SAMPLE_RATE_HZ = 4096
_MAX_SAMPLES_SINCE_T0 = 2**28


@dataclass(slots=True, eq=False, repr=False)
class ClientBuffer:
    """Ring-buffer accumulator for a single ESP32 client's raw accelerometer data."""

    data: np.ndarray
    capacity: int
    buffer_epoch: int = 0
    reset_generation: int = 0
    write_idx: int = 0
    count: int = 0
    sample_rate_hz: int = 0
    latest_metrics: ClientMetrics = field(default_factory=ClientMetrics)
    latest_analysis_time_range: AnalysisTimeRange | None = None
    latest_spectrum: SpectrumByAxis = field(default_factory=dict)
    latest_strength_metrics: VibrationStrengthMetrics = field(
        default_factory=empty_vibration_strength_metrics
    )
    last_ingest_mono_s: float = 0.0
    # Sensor-clock timestamp (µs) of the most recent ingested frame.
    # After CMD_SYNC_CLOCK this is server-relative and comparable across sensors.
    last_t0_us: int = 0
    # Number of samples ingested since last_t0_us was recorded.  Used to
    # back-compute the timestamp of the oldest sample in the analysis window.
    samples_since_t0: int = 0
    # Generation counters: reset_generation invalidates in-flight compute work
    # across buffer flushes, ingest_generation increments on new samples,
    # compute_generation marks which ingest generation metrics reflect, and
    # spectrum_generation marks spectrum snapshot updates for payload caching.
    ingest_generation: int = 0
    compute_generation: int = -1
    compute_sample_rate_hz: int = 0
    spectrum_generation: int = 0
    cached_spectrum_payload: SpectrumSeriesPayload | None = None
    cached_spectrum_payload_generation: int = -1

    def __repr__(self) -> str:
        """Compact repr that omits large numpy array data."""
        return (
            f"ClientBuffer(capacity={self.capacity}, count={self.count}, "
            f"write_idx={self.write_idx}, sr={self.sample_rate_hz}Hz, "
            f"igen={self.ingest_generation}, cgen={self.compute_generation})"
        )

    def invalidate_caches(self) -> None:
        """Drop the cached spectrum payload so the next read rebuilds it."""
        self.cached_spectrum_payload = None
        self.cached_spectrum_payload_generation = -1

    def reset(self) -> None:
        """Discard all samples and computed state; in-flight compute results become stale."""
        self.data[:] = 0.0
        self.reset_generation += 1
        self.write_idx = 0
        self.count = 0
        self.last_t0_us = 0
        self.samples_since_t0 = 0
        self.latest_metrics = {}
        self.latest_analysis_time_range = None
        self.latest_spectrum = {}
        self.latest_strength_metrics = empty_vibration_strength_metrics()
        self.compute_generation = -1
        self.compute_sample_rate_hz = 0
        self.invalidate_caches()
        self.ingest_generation += 1

    def copy_latest(self, n: int) -> FloatArray:
        """Return a ``(3, n)`` copy of the newest *n* samples in chronological order."""
        if n <= 0 or self.count == 0:
            return np.empty((3, 0), dtype=np.float32)
        n = min(n, self.count)
        start = (self.write_idx - n) % self.capacity
        if start + n <= self.capacity:
            return self.data[:, start : start + n].copy()
        first = self.capacity - start
        return np.concatenate((self.data[:, start:], self.data[:, : n - first]), axis=1)

    def resize(self, new_capacity: int) -> None:
        """Change capacity, keeping the newest samples."""
        new_capacity = max(1, int(new_capacity))
        if new_capacity == self.capacity:
            return
        latest = self.copy_latest(min(self.count, new_capacity))
        resized: FloatArray = np.zeros((3, new_capacity), dtype=np.float32)
        if latest.size:
            resized[:, : latest.shape[1]] = latest
        self.data = resized
        self.capacity = new_capacity
        self.write_idx = latest.shape[1] % new_capacity
        self.count = min(latest.shape[1], new_capacity)

    def set_sample_rate(self, sample_rate_hz: int, *, resize_to_seconds: int | None) -> None:
        """Apply a client-reported sample rate clamped to ``[1, MAX_CLIENT_SAMPLE_RATE_HZ]``.

        When *resize_to_seconds* is given, a rate change also resizes the buffer to
        hold that many seconds of samples.
        """
        requested = int(sample_rate_hz)
        rate = max(1, min(MAX_CLIENT_SAMPLE_RATE_HZ, requested))
        if rate != requested:
            LOGGER.warning(
                "Clamped client sample_rate_hz from %d to %d to bound buffer growth",
                requested,
                rate,
            )
        if rate == self.sample_rate_hz:
            return
        self.sample_rate_hz = rate
        if resize_to_seconds is not None:
            self.resize(rate * resize_to_seconds)

    def append(self, chunk: FloatArray, *, t0_us: int | None) -> None:
        """Write an ``(N, 3)`` chunk (``N <= capacity``) and advance the sensor-clock anchor."""
        sample_count = int(chunk.shape[0])
        capacity = self.capacity
        end = self.write_idx + sample_count
        if end <= capacity:
            self.data[:, self.write_idx : end] = chunk.T
        else:
            first = capacity - self.write_idx
            self.data[:, self.write_idx :] = chunk[:first].T
            self.data[:, : end % capacity] = chunk[first:].T
        self.write_idx = end % capacity
        self.count = min(capacity, self.count + sample_count)
        if t0_us is not None and t0_us > 0 and int(t0_us) > self.last_t0_us:
            self.last_t0_us = int(t0_us)
            self.samples_since_t0 = sample_count
        else:
            self.samples_since_t0 = min(
                self.samples_since_t0 + sample_count,
                _MAX_SAMPLES_SINCE_T0,
            )
        self.ingest_generation += 1
        self.invalidate_caches()

    def commit_metrics(self, result: MetricsComputationResult) -> bool:
        """Store *result* unless the buffer was reset, replaced, or already has newer metrics."""
        if (
            result.buffer_epoch != self.buffer_epoch
            or result.reset_generation != self.reset_generation
            or result.ingest_generation < self.compute_generation
        ):
            return False
        self.latest_metrics = result.metrics
        self.latest_analysis_time_range = result.analysis_time_range
        self.compute_generation = result.ingest_generation
        self.compute_sample_rate_hz = result.sample_rate_hz
        if result.has_fft_data:
            self.latest_spectrum = result.spectrum_by_axis
            self.latest_strength_metrics = result.strength_metrics
        else:
            self.latest_spectrum = {}
            self.latest_strength_metrics = empty_vibration_strength_metrics()
        self.spectrum_generation += 1
        self.invalidate_caches()
        return True

    def analysis_time_range(
        self,
        *,
        default_sample_rate_hz: int,
        fft_n: int,
    ) -> AnalysisTimeRange | None:
        """Return the time range of the newest FFT block (what the spectrum describes)."""
        time_range = analysis_time_range(
            count=self.count,
            last_ingest_mono_s=self.last_ingest_mono_s,
            sample_rate_hz=self.sample_rate_hz or default_sample_rate_hz,
            window_samples=fft_n,
            last_t0_us=self.last_t0_us,
            samples_since_t0=self.samples_since_t0,
        )
        if time_range is None:
            return None
        start_s, end_s, synced = time_range
        return AnalysisTimeRange(start_s=start_s, end_s=end_s, synced=synced)
