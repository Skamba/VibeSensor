from __future__ import annotations

import logging
import time
from collections.abc import Callable
from threading import RLock

import numpy as np

from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.models import (
    CachedMetricsHit,
    ClientMetrics,
    DebugSpectrumRequest,
    FloatArray,
    MetricsComputationResult,
    MetricsSnapshot,
    ProcessorConfig,
    ProcessorStats,
)
from vibesensor.shared.types.payload_types import (
    IntakeStatsPayload,
    RawSamplesErrorPayload,
    RawSamplesPayload,
)
from vibesensor.vibration_strength import empty_vibration_strength_metrics

LOGGER = logging.getLogger(__name__)
MAX_CLIENT_SAMPLE_RATE_HZ = 4096
_MAX_SAMPLES_SINCE_T0 = 2**28
"""Cap `samples_since_t0` so long sessions cannot grow the accumulator without bound."""


class SignalBufferStore:
    """Own shared client buffer state, lifecycle, and lock-protected snapshots."""

    def __init__(self, config: ProcessorConfig) -> None:
        self.config = config
        self.buffers: dict[str, ClientBuffer] = {}
        self.lock = RLock()
        self.stats = ProcessorStats()

    def flush_client_buffer(self, client_id: str) -> None:
        """Reset the buffer for *client_id*, discarding all stored samples."""
        with self.lock:
            buf = self.buffers.get(client_id)
            if buf is None:
                return
            buf.data[:] = 0.0
            buf.write_idx = 0
            buf.count = 0
            buf.last_t0_us = 0
            buf.samples_since_t0 = 0
            buf.latest_metrics = {}
            buf.latest_spectrum = {}
            buf.latest_strength_metrics = empty_vibration_strength_metrics()
            buf.invalidate_caches()
            buf.ingest_generation += 1
        LOGGER.info("Flushed signal buffer for client %s after sensor reset", client_id)

    def ingest(
        self,
        client_id: str,
        samples: FloatArray,
        *,
        sample_rate_hz: int | None = None,
        t0_us: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        t_start = clock()
        if samples.size == 0:
            return

        with self.lock:
            buf = self._get_or_create_unlocked(client_id)
            chunk: FloatArray = np.asarray(samples, dtype=np.float32)
            if self.config.accel_scale_g_per_lsb is not None:
                chunk = chunk * np.float32(self.config.accel_scale_g_per_lsb)
            if chunk.ndim != 2 or chunk.shape[1] != 3:
                LOGGER.warning(
                    "Dropping malformed sample chunk for %s with shape %s",
                    client_id,
                    chunk.shape,
                )
                return
            if sample_rate_hz is not None and sample_rate_hz > 0:
                requested_rate = int(sample_rate_hz)
                clamped_rate = max(1, min(MAX_CLIENT_SAMPLE_RATE_HZ, requested_rate))
                if clamped_rate != requested_rate:
                    LOGGER.warning(
                        "Clamped client sample_rate_hz from %d to %d to bound buffer growth",
                        requested_rate,
                        clamped_rate,
                    )
                buf.sample_rate_hz = clamped_rate
                self._resize_buffer_unlocked(
                    buf,
                    buf.sample_rate_hz * self.config.waveform_seconds,
                )
            now_mono = clock()
            buf.last_ingest_mono_s = now_mono

            n = int(chunk.shape[0])
            capacity = buf.capacity
            if n >= capacity:
                chunk = chunk[-capacity:]
                n = capacity

            end = buf.write_idx + n
            if end <= capacity:
                buf.data[:, buf.write_idx : end] = chunk.T
            else:
                first = capacity - buf.write_idx
                buf.data[:, buf.write_idx :] = chunk[:first].T
                buf.data[:, : end % capacity] = chunk[first:].T

            buf.write_idx = end % capacity
            buf.count = min(capacity, buf.count + n)
            if t0_us is not None and t0_us > 0:
                buf.last_t0_us = int(t0_us)
                buf.samples_since_t0 = n
            else:
                buf.samples_since_t0 = min(buf.samples_since_t0 + n, _MAX_SAMPLES_SINCE_T0)
            buf.ingest_generation += 1
            buf.invalidate_caches()
            self.stats.total_ingested_samples += n
            self.stats.last_ingest_duration_s = clock() - t_start

    def snapshot_for_compute(
        self,
        client_id: str,
        *,
        sample_rate_hz: int | None = None,
    ) -> CachedMetricsHit | MetricsSnapshot | None:
        """Return a cached hit or an immutable compute snapshot for *client_id*."""
        with self.lock:
            buf = self.buffers.get(client_id)
            if buf is None or buf.count == 0:
                return None
            if sample_rate_hz is not None and sample_rate_hz > 0:
                buf.sample_rate_hz = int(sample_rate_hz)
            sr = buf.sample_rate_hz or self.config.sample_rate_hz
            if buf.compute_generation == buf.ingest_generation and buf.compute_sample_rate_hz == sr:
                return CachedMetricsHit(metrics=buf.latest_metrics)

            desired_samples = int(max(1.0, float(sr) * float(self.config.waveform_seconds)))
            n_time = min(buf.count, buf.capacity, max(1, desired_samples))
            time_window = self.copy_latest(buf, n_time)
            fft_block: FloatArray | None = None
            if buf.count >= self.config.fft_n:
                if n_time >= self.config.fft_n:
                    fft_block = time_window[:, -self.config.fft_n :]
                else:
                    fft_block = self.copy_latest(buf, self.config.fft_n)
            return MetricsSnapshot(
                client_id=client_id,
                sample_rate_hz=sr,
                ingest_generation=buf.ingest_generation,
                time_window=time_window,
                fft_block=fft_block,
            )

    def store_metrics_result(self, result: MetricsComputationResult) -> ClientMetrics:
        """Commit a compute result back into shared state and update stats."""
        with self.lock:
            buf = self.buffers.get(result.client_id)
            if buf is not None and result.ingest_generation >= buf.compute_generation:
                buf.latest_metrics = result.metrics
                buf.compute_generation = result.ingest_generation
                buf.compute_sample_rate_hz = result.sample_rate_hz
                if result.has_fft_data:
                    buf.latest_spectrum = result.spectrum_by_axis
                    buf.latest_strength_metrics = result.strength_metrics
                else:
                    buf.latest_spectrum = {}
                    buf.latest_strength_metrics = empty_vibration_strength_metrics()
                buf.spectrum_generation += 1
                buf.invalidate_caches()
            self.stats.last_compute_duration_s = result.duration_s
            self.stats.total_compute_calls += 1
        return result.metrics

    def record_compute_all_duration(self, duration_s: float) -> None:
        with self.lock:
            self.stats.last_compute_all_duration_s = duration_s

    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float] | None:
        with self.lock:
            buf = self.buffers.get(client_id)
            if buf is None or buf.count == 0:
                return None
            idx = (buf.write_idx - 1) % buf.capacity
            return (
                float(buf.data[0, idx]),
                float(buf.data[1, idx]),
                float(buf.data[2, idx]),
            )

    def latest_sample_rate_hz(self, client_id: str) -> int | None:
        with self.lock:
            buf = self.buffers.get(client_id)
            if buf is None:
                return None
            rate = int(buf.sample_rate_hz or 0)
            return rate if rate > 0 else None

    def latest_metrics(self, client_id: str) -> ClientMetrics:
        """Return the most recent computed metrics for *client_id*."""
        with self.lock:
            buf = self.buffers.get(client_id)
            if buf is None:
                return {}
            return buf.latest_metrics

    def all_latest_metrics(self, client_ids: list[str]) -> dict[str, ClientMetrics]:
        """Return latest metrics for all requested clients (lock once)."""
        with self.lock:
            result: dict[str, ClientMetrics] = {}
            for cid in client_ids:
                buf = self.buffers.get(cid)
                if buf is not None and buf.latest_metrics:
                    result[cid] = buf.latest_metrics
            return result

    def debug_request(self, client_id: str) -> DebugSpectrumRequest:
        with self.lock:
            buf = self.buffers.get(client_id)
            if buf is None:
                return DebugSpectrumRequest(
                    client_id=client_id,
                    sample_rate_hz=self.config.sample_rate_hz,
                    count=0,
                    fft_block=None,
                )
            sr = buf.sample_rate_hz or self.config.sample_rate_hz
            if buf.count < self.config.fft_n:
                return DebugSpectrumRequest(
                    client_id=client_id,
                    sample_rate_hz=sr,
                    count=buf.count,
                    fft_block=None,
                )
            return DebugSpectrumRequest(
                client_id=client_id,
                sample_rate_hz=sr,
                count=buf.count,
                fft_block=self.copy_latest(buf, self.config.fft_n),
            )

    def raw_samples(
        self,
        client_id: str,
        *,
        n_samples: int,
    ) -> RawSamplesPayload | RawSamplesErrorPayload:
        with self.lock:
            buf = self.buffers.get(client_id)
            if buf is None or buf.count == 0:
                return {"error": "no data", "count": 0}
            sr = buf.sample_rate_hz or self.config.sample_rate_hz
            n = min(n_samples, buf.count)
            block = self.copy_latest(buf, n)
        return {
            "client_id": client_id,
            "sample_rate_hz": sr,
            "n_samples": n,
            "x": [float(v) for v in block[0].tolist()],
            "y": [float(v) for v in block[1].tolist()],
            "z": [float(v) for v in block[2].tolist()],
        }

    def clients_with_recent_data(
        self,
        client_ids: list[str],
        *,
        max_age_s: float = 3.0,
    ) -> list[str]:
        """Return subset of *client_ids* that received data within *max_age_s*."""
        now = time.monotonic()
        with self.lock:
            result: list[str] = []
            for client_id in client_ids:
                buf = self.buffers.get(client_id)
                if buf is None or buf.last_ingest_mono_s <= 0:
                    continue
                if (now - buf.last_ingest_mono_s) <= max_age_s:
                    result.append(client_id)
            return result

    def evict_clients(self, keep_client_ids: set[str]) -> None:
        with self.lock:
            stale_ids = [
                client_id for client_id in self.buffers if client_id not in keep_client_ids
            ]
            for client_id in stale_ids:
                self.buffers.pop(client_id, None)

    def intake_stats(self) -> IntakeStatsPayload:
        with self.lock:
            return {
                "total_ingested_samples": self.stats.total_ingested_samples,
                "total_compute_calls": self.stats.total_compute_calls,
                "last_compute_duration_s": self.stats.last_compute_duration_s,
                "last_compute_all_duration_s": self.stats.last_compute_all_duration_s,
                "last_ingest_duration_s": self.stats.last_ingest_duration_s,
            }

    def _get_or_create_unlocked(self, client_id: str) -> ClientBuffer:
        buf = self.buffers.get(client_id)
        if buf is None:
            data: FloatArray = np.zeros((3, self.config.max_samples), dtype=np.float32)
            buf = ClientBuffer(data=data, capacity=self.config.max_samples)
            self.buffers[client_id] = buf
        return buf

    def _resize_buffer_unlocked(self, buf: ClientBuffer, new_capacity: int) -> None:
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

    def copy_latest(self, buf: ClientBuffer, n: int) -> FloatArray:
        if n <= 0 or buf.count == 0:
            return np.empty((3, 0), dtype=np.float32)
        n = min(n, buf.count)
        start = (buf.write_idx - n) % buf.capacity
        if start + n <= buf.capacity:
            return buf.data[:, start : start + n].copy()
        first = buf.capacity - start
        return np.concatenate((buf.data[:, start:], buf.data[:, : n - first]), axis=1)
