from __future__ import annotations

import logging

import numpy as np

from vibesensor.infra.processing.buffer_capacity import (
    clamp_sample_rate,
    compute_resize_capacity,
)
from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.models import FloatArray, MetricsComputationResult, ProcessorConfig
from vibesensor.vibration_strength import empty_vibration_strength_metrics

LOGGER = logging.getLogger(__name__)


class ClientBufferMutator:
    """Own in-place buffer mutation policy apart from registry/locking concerns."""

    def __init__(self, config: ProcessorConfig) -> None:
        self._waveform_seconds = config.waveform_seconds

    def reset(self, buf: ClientBuffer) -> None:
        buf.data[:] = 0.0
        buf.write_idx = 0
        buf.count = 0
        buf.last_t0_us = 0
        buf.samples_since_t0 = 0
        buf.latest_metrics = {}
        buf.latest_analysis_time_range = None
        buf.latest_spectrum = {}
        buf.latest_strength_metrics = empty_vibration_strength_metrics()
        self.invalidate_cached_payloads(buf)
        buf.ingest_generation += 1

    def commit_metrics_result(
        self,
        buf: ClientBuffer,
        result: MetricsComputationResult,
    ) -> bool:
        if (
            result.buffer_epoch != buf.buffer_epoch
            or result.ingest_generation < buf.compute_generation
        ):
            return False
        buf.latest_metrics = result.metrics
        buf.latest_analysis_time_range = result.analysis_time_range
        buf.compute_generation = result.ingest_generation
        buf.compute_sample_rate_hz = result.sample_rate_hz
        if result.has_fft_data:
            buf.latest_spectrum = result.spectrum_by_axis
            buf.latest_strength_metrics = result.strength_metrics
        else:
            buf.latest_spectrum = {}
            buf.latest_strength_metrics = empty_vibration_strength_metrics()
        buf.spectrum_generation += 1
        self.invalidate_cached_payloads(buf)
        return True

    def resize(self, buf: ClientBuffer, new_capacity: int) -> None:
        new_capacity = max(1, int(new_capacity))
        if new_capacity == buf.capacity:
            return
        latest = self.copy_latest(buf, min(buf.count, new_capacity))
        resized: FloatArray = np.zeros((3, new_capacity), dtype=np.float32)
        if latest.size:
            resized[:, : latest.shape[1]] = latest
        buf.data = resized
        buf.capacity = new_capacity
        buf.write_idx = latest.shape[1] % new_capacity
        buf.count = min(latest.shape[1], new_capacity)

    def invalidate_cached_payloads(self, buf: ClientBuffer) -> None:
        buf.invalidate_caches()

    def apply_sample_rate_override(
        self,
        buf: ClientBuffer,
        sample_rate_hz: int,
        *,
        resize_buffer: bool,
    ) -> None:
        result = clamp_sample_rate(int(sample_rate_hz))
        if result.was_clamped:
            LOGGER.warning(
                "Clamped client sample_rate_hz from %d to %d to bound buffer growth",
                int(sample_rate_hz),
                result.rate_hz,
            )
        if result.rate_hz == buf.sample_rate_hz:
            return
        buf.sample_rate_hz = result.rate_hz
        if resize_buffer:
            self.resize(
                buf,
                compute_resize_capacity(result.rate_hz, self._waveform_seconds),
            )

    def copy_latest(self, buf: ClientBuffer, n: int) -> FloatArray:
        if n <= 0 or buf.count == 0:
            return np.empty((3, 0), dtype=np.float32)
        n = min(n, buf.count)
        start = (buf.write_idx - n) % buf.capacity
        if start + n <= buf.capacity:
            return buf.data[:, start : start + n].copy()
        first = buf.capacity - start
        return np.concatenate((buf.data[:, start:], buf.data[:, : n - first]), axis=1)
