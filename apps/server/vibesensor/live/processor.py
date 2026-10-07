"""Live signal processor: per-client ring buffers, metrics compute, and spectrum views.

``SignalProcessor`` owns every client buffer behind one lock. Compute follows a
snapshot → compute → commit sequence so the lock is held only while copying
samples in and committing results back; the FFT work itself runs unlocked.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

import numpy as np

from vibesensor.common.recent_counter import RecentCounter
from vibesensor.live.buffers import ClientBuffer
from vibesensor.live.compute import SignalMetricsComputer
from vibesensor.live.models import (
    ClientMetrics,
    FloatArray,
    MetricsSnapshot,
    ProcessorConfig,
    ProcessorStats,
)
from vibesensor.live.payload import build_multi_spectrum_payload

if TYPE_CHECKING:
    from vibesensor.live.analysis_time_range import AnalysisTimeRange
    from vibesensor.live.payload_types import IntakeStatsPayload, SpectraPayload

LOGGER = logging.getLogger(__name__)


class SignalProcessor:
    """Processes raw accelerometer frames into vibration-strength metrics."""

    def __init__(
        self,
        sample_rate_hz: int,
        waveform_seconds: int,
        waveform_display_hz: int,
        fft_n: int,
        spectrum_min_hz: float = 0.0,
        spectrum_max_hz: float = 200.0,
        accel_scale_g_per_lsb: float | None = None,
    ) -> None:
        self._config = ProcessorConfig(
            sample_rate_hz=sample_rate_hz,
            waveform_seconds=waveform_seconds,
            waveform_display_hz=waveform_display_hz,
            fft_n=fft_n,
            spectrum_min_hz=max(0.0, float(spectrum_min_hz)),
            spectrum_max_hz=spectrum_max_hz,
            accel_scale_g_per_lsb=(
                float(accel_scale_g_per_lsb)
                if isinstance(accel_scale_g_per_lsb, (int, float)) and accel_scale_g_per_lsb > 0
                else None
            ),
        )
        self._metrics = SignalMetricsComputer(self._config)
        self._lock = threading.Lock()
        self._buffers: dict[str, ClientBuffer] = {}
        self._next_buffer_epoch = 0
        self._stats = ProcessorStats()
        self._recent_buffer_overflow_drops = RecentCounter()

    # -- ingest --------------------------------------------------------------

    def flush_client_buffer(self, client_id: str, *, reason: str = "sensor reset") -> None:
        """Discard all stored samples and computed state for *client_id*."""
        with self._lock:
            buf = self._buffers.get(client_id)
            if buf is None:
                return
            buf.reset()
        LOGGER.info("Flushed signal buffer for client %s (%s)", client_id, reason)

    def ingest(
        self,
        client_id: str,
        samples: np.ndarray,
        sample_rate_hz: int | None = None,
        t0_us: int | None = None,
    ) -> None:
        """Append an ``(N, 3)`` sample chunk (raw LSB or g) to *client_id*'s buffer."""
        t_start = time.monotonic()
        if samples.size == 0:
            return
        chunk: FloatArray = np.asarray(samples, dtype=np.float32)
        if self._config.accel_scale_g_per_lsb is not None:
            chunk = chunk * np.float32(self._config.accel_scale_g_per_lsb)
        if chunk.ndim != 2 or chunk.shape[1] != 3:
            LOGGER.warning(
                "Dropping malformed sample chunk for %s with shape %s",
                client_id,
                chunk.shape,
            )
            return

        with self._lock:
            buf = self._buffers.get(client_id)
            if buf is None:
                buf = self._create_buffer_locked(client_id)
            if sample_rate_hz is not None and sample_rate_hz > 0:
                buf.set_sample_rate(
                    sample_rate_hz,
                    resize_to_seconds=self._config.waveform_seconds,
                )
            buf.last_ingest_mono_s = time.monotonic()
            dropped = max(0, int(chunk.shape[0]) - buf.capacity)
            if dropped:
                LOGGER.warning(
                    "Sample chunk for %s exceeds buffer capacity %d; discarding %d oldest "
                    "samples from the incoming batch",
                    client_id,
                    buf.capacity,
                    dropped,
                )
                chunk = chunk[dropped:]
                effective_rate_hz = buf.sample_rate_hz or self._config.sample_rate_hz
                if t0_us is not None and t0_us > 0 and effective_rate_hz > 0:
                    t0_us = int(t0_us) + (dropped * 1_000_000) // effective_rate_hz
            buf.append(chunk, t0_us=t0_us)
            self._stats.total_ingested_samples += int(chunk.shape[0])
            self._stats.buffer_overflow_drops += dropped
            self._recent_buffer_overflow_drops.add(dropped, t_start)
            self._stats.last_ingest_duration_s = time.monotonic() - t_start

    def _create_buffer_locked(self, client_id: str) -> ClientBuffer:
        capacity = self._config.max_samples
        buf = ClientBuffer(
            data=np.zeros((3, capacity), dtype=np.float32),
            capacity=capacity,
            buffer_epoch=self._next_buffer_epoch,
        )
        self._next_buffer_epoch += 1
        self._buffers[client_id] = buf
        return buf

    def evict_clients(self, keep_client_ids: set[str]) -> None:
        """Drop buffers for clients not in *keep_client_ids*.

        In-flight compute for an evicted client cannot commit: a later buffer for
        the same id gets a new epoch.
        """
        with self._lock:
            for client_id in [cid for cid in self._buffers if cid not in keep_client_ids]:
                del self._buffers[client_id]

    # -- compute -------------------------------------------------------------

    def compute_metrics(self, client_id: str, sample_rate_hz: int | None = None) -> ClientMetrics:
        """Compute (or return cached) metrics for the newest samples of *client_id*."""
        with self._lock:
            buf = self._buffers.get(client_id)
            if buf is None or buf.count == 0:
                return {}
            if sample_rate_hz is not None and sample_rate_hz > 0:
                buf.set_sample_rate(sample_rate_hz, resize_to_seconds=None)
            rate_hz = buf.sample_rate_hz or self._config.sample_rate_hz
            if buf.compute_generation == buf.ingest_generation and (
                buf.compute_sample_rate_hz == rate_hz
            ):
                return buf.latest_metrics
            snapshot = self._snapshot_locked(client_id, buf, rate_hz)

        result = self._metrics.compute(snapshot)

        with self._lock:
            buf = self._buffers.get(client_id)
            if buf is not None:
                buf.commit_metrics(result)
            self._stats.last_compute_duration_s = result.duration_s
            self._stats.total_compute_calls += 1
        return result.metrics

    def _snapshot_locked(
        self,
        client_id: str,
        buf: ClientBuffer,
        sample_rate_hz: int,
    ) -> MetricsSnapshot:
        fft_n = self._config.fft_n
        fft_block = buf.copy_latest(fft_n) if buf.count >= fft_n else None
        return MetricsSnapshot(
            client_id=client_id,
            sample_rate_hz=sample_rate_hz,
            ingest_generation=buf.ingest_generation,
            buffer_epoch=buf.buffer_epoch,
            reset_generation=buf.reset_generation,
            fft_block=fft_block,
            analysis_time_range=buf.analysis_time_range(
                default_sample_rate_hz=sample_rate_hz,
                fft_n=fft_n,
            ),
        )

    def compute_all(
        self,
        client_ids: list[str],
        sample_rates_hz: dict[str, int] | None = None,
    ) -> dict[str, ClientMetrics]:
        """Compute metrics for each client serially; failing clients are logged and skipped."""
        rates = sample_rates_hz or {}
        t0 = time.monotonic()
        result: dict[str, ClientMetrics] = {}
        for client_id in client_ids:
            try:
                result[client_id] = self.compute_metrics(
                    client_id,
                    sample_rate_hz=rates.get(client_id),
                )
            except (ValueError, ArithmeticError, np.exceptions.DTypePromotionError):
                LOGGER.warning("compute_metrics failed for %s; skipping.", client_id, exc_info=True)
        with self._lock:
            self._stats.last_compute_all_duration_s = time.monotonic() - t0
        return result

    # -- reads ---------------------------------------------------------------

    def multi_spectrum_payload(self, client_ids: list[str]) -> SpectraPayload:
        """Return the live ``spectra`` payload for *client_ids*."""
        with self._lock:
            return build_multi_spectrum_payload(
                self._buffers,
                client_ids,
            )

    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float] | None:
        with self._lock:
            buf = self._buffers.get(client_id)
            if buf is None or buf.count == 0:
                return None
            idx = (buf.write_idx - 1) % buf.capacity
            return (float(buf.data[0, idx]), float(buf.data[1, idx]), float(buf.data[2, idx]))

    def latest_sample_rate_hz(self, client_id: str) -> int | None:
        with self._lock:
            buf = self._buffers.get(client_id)
            rate = int(buf.sample_rate_hz or 0) if buf is not None else 0
        return rate if rate > 0 else None

    def latest_analysis_time_range(self, client_id: str) -> AnalysisTimeRange | None:
        with self._lock:
            buf = self._buffers.get(client_id)
            return buf.latest_analysis_time_range if buf is not None else None

    def latest_metrics(self, client_id: str) -> ClientMetrics:
        """Return latest computed metrics for a client."""
        with self._lock:
            buf = self._buffers.get(client_id)
            return buf.latest_metrics if buf is not None else {}

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        """Return the subset of *client_ids* that received samples within *max_age_s*."""
        now = time.monotonic()
        with self._lock:
            return [
                cid
                for cid in client_ids
                if (buf := self._buffers.get(cid)) is not None
                and buf.last_ingest_mono_s > 0
                and (now - buf.last_ingest_mono_s) <= max_age_s
            ]

    def intake_stats(self) -> IntakeStatsPayload:
        with self._lock:
            return {
                "total_ingested_samples": self._stats.total_ingested_samples,
                "total_compute_calls": self._stats.total_compute_calls,
                "last_compute_duration_s": self._stats.last_compute_duration_s,
                "last_compute_all_duration_s": self._stats.last_compute_all_duration_s,
                "last_ingest_duration_s": self._stats.last_ingest_duration_s,
            }

    def buffer_overflow_drops(self) -> int:
        with self._lock:
            return self._stats.buffer_overflow_drops

    def recent_buffer_overflow_drops(self, now_mono: float | None = None) -> int:
        """Samples discarded for buffer overflow in the recent window."""
        with self._lock:
            return self._recent_buffer_overflow_drops.total(
                time.monotonic() if now_mono is None else now_mono
            )
