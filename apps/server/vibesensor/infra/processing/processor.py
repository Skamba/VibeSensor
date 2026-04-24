"""Signal processor facade with explicit state and compute subsystems.

``SignalProcessor`` preserves the external API used by runtime, routes, and
metrics logging while delegating to focused collaborators:

- :mod:`vibesensor.infra.processing.buffer_store` owns buffer lifecycle, shared state,
  locking, and state snapshots.
- :mod:`vibesensor.infra.processing.compute` owns FFT cache/window state and metric
  computation from immutable snapshots.
"""

from __future__ import annotations

import logging
import math
import time
from typing import TYPE_CHECKING

import numpy as np

from vibesensor.infra.processing.buffer_capacity import (
    MAX_CLIENT_SAMPLE_RATE_HZ as _MAX_CLIENT_SAMPLE_RATE_HZ,
)
from vibesensor.infra.processing.buffer_store import SignalBufferStore
from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.compute import SignalMetricsComputer
from vibesensor.infra.processing.models import (
    CachedMetricsHit,
    ClientMetrics,
    ProcessorConfig,
)
from vibesensor.infra.processing.payload import (
    SpectrumSeriesPayload,
    _empty_spectrum_payload,
    build_intake_stats_payload,
    build_multi_spectrum_payload,
    build_spectrum_payload,
    build_time_alignment_payload,
)
from vibesensor.infra.processing.time_align import analysis_time_range
from vibesensor.infra.workers.worker_pool import WorkerPool
from vibesensor.shared.types.analysis_time_range import AnalysisTimeRange

if TYPE_CHECKING:
    from vibesensor.shared.types.payload_types import (
        IntakeStatsPayload,
        SpectraPayload,
        TimeAlignmentPayload,
    )

LOGGER = logging.getLogger(__name__)
MAX_CLIENT_SAMPLE_RATE_HZ = _MAX_CLIENT_SAMPLE_RATE_HZ
_MIN_PARALLEL_COMPUTE_WORK_UNITS = 4096


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
        worker_pool: WorkerPool | None = None,
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
        self.sample_rate_hz = self._config.sample_rate_hz
        self.waveform_seconds = self._config.waveform_seconds
        self.waveform_display_hz = self._config.waveform_display_hz
        self.fft_n = self._config.fft_n
        self.spectrum_min_hz = self._config.spectrum_min_hz
        self.spectrum_max_hz = self._config.spectrum_max_hz
        self.accel_scale_g_per_lsb = self._config.accel_scale_g_per_lsb
        self.max_samples = self._config.max_samples

        self._store = SignalBufferStore(self._config)
        self._metrics = SignalMetricsComputer(self._config)
        self._worker_pool = worker_pool

    def flush_client_buffer(
        self,
        client_id: str,
        *,
        reason: str = "sensor reset",
    ) -> None:
        self._store.flush_client_buffer(client_id, reason=reason)

    def ingest(
        self,
        client_id: str,
        samples: np.ndarray,
        sample_rate_hz: int | None = None,
        t0_us: int | None = None,
    ) -> None:
        self._store.ingest(
            client_id,
            samples,
            sample_rate_hz=sample_rate_hz,
            t0_us=t0_us,
            clock=time.monotonic,
        )

    def compute_metrics(self, client_id: str, sample_rate_hz: int | None = None) -> ClientMetrics:
        plan = self._store.snapshot_for_compute(client_id, sample_rate_hz=sample_rate_hz)
        if plan is None:
            return {}
        if isinstance(plan, CachedMetricsHit):
            return plan.metrics
        result = self._metrics.compute(plan)
        return self._store.store_metrics_result(result)

    def compute_all(
        self,
        client_ids: list[str],
        sample_rates_hz: dict[str, int] | None = None,
    ) -> dict[str, ClientMetrics]:
        rates = sample_rates_hz or {}
        t0 = time.monotonic()

        if not self._should_parallelize_compute_all(client_ids):
            result = self._compute_all_serial(client_ids, rates)
            self._store.record_compute_all_duration(time.monotonic() - t0)
            return result

        pool = self._worker_pool
        assert pool is not None
        try:
            result = self._compute_all_parallel_chunked(client_ids, rates, pool)
        except (RuntimeError, OSError):
            LOGGER.warning(
                "compute_all: worker pool raised; falling back to serial execution.",
                exc_info=True,
            )
            result = self._compute_all_serial(client_ids, rates, serial_fallback=True)
        self._store.record_compute_all_duration(time.monotonic() - t0)
        return result

    def _should_parallelize_compute_all(self, client_ids: list[str]) -> bool:
        if len(client_ids) <= 1 or self._worker_pool is None:
            return False
        return (len(client_ids) * self._config.fft_n) >= _MIN_PARALLEL_COMPUTE_WORK_UNITS

    def spectrum_payload(self, client_id: str) -> SpectrumSeriesPayload:
        with self._store.locked_client_buffer(client_id) as buf:
            if buf is None:
                return _empty_spectrum_payload()
            return build_spectrum_payload(buf)

    def multi_spectrum_payload(self, client_ids: list[str]) -> SpectraPayload:
        with self._store.locked_client_buffers(client_ids) as buffers:

            def _spectrum_payload(client_id: str) -> SpectrumSeriesPayload:
                return self._spectrum_payload_from_buffers(buffers, client_id)

            return build_multi_spectrum_payload(
                buffers,
                client_ids,
                spectrum_fn=_spectrum_payload,
                analysis_time_range_fn=self._analysis_time_range_unlocked,
            )

    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float] | None:
        return self._store.latest_sample_xyz(client_id)

    def latest_sample_rate_hz(self, client_id: str) -> int | None:
        return self._store.latest_sample_rate_hz(client_id)

    def latest_analysis_time_range(self, client_id: str) -> AnalysisTimeRange | None:
        return self._store.latest_analysis_time_range(client_id)

    def latest_metrics(self, client_id: str) -> ClientMetrics:
        """Return latest computed metrics for a client."""
        return self._store.latest_metrics(client_id)

    def all_latest_metrics(self, client_ids: list[str]) -> dict[str, ClientMetrics]:
        """Return latest metrics for requested clients."""
        return self._store.all_latest_metrics(client_ids)

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        return self._store.clients_with_recent_data(client_ids, max_age_s=max_age_s)

    def evict_clients(self, keep_client_ids: set[str]) -> None:
        self._store.evict_clients(keep_client_ids)

    def intake_stats(self) -> IntakeStatsPayload:
        worker_pool_stats = self._worker_pool.stats() if self._worker_pool is not None else None
        return build_intake_stats_payload(self._store.intake_stats(), worker_pool_stats)

    def buffer_overflow_drops(self) -> int:
        return self._store.buffer_overflow_drops()

    def time_alignment_info(self, client_ids: list[str]) -> TimeAlignmentPayload:
        with self._store.locked_client_buffers(client_ids) as buffers:
            return build_time_alignment_payload(
                buffers,
                client_ids,
                analysis_time_range_fn=self._analysis_time_range_unlocked,
            )

    def _spectrum_payload_from_buffers(
        self,
        buffers: dict[str, ClientBuffer],
        client_id: str,
    ) -> SpectrumSeriesPayload:
        buf = buffers.get(client_id)
        if buf is None:
            return _empty_spectrum_payload()
        return build_spectrum_payload(buf)

    def _analysis_time_range_unlocked(self, buf: ClientBuffer) -> tuple[float, float, bool] | None:
        sr = buf.sample_rate_hz or self._store.config.sample_rate_hz
        return analysis_time_range(
            count=buf.count,
            last_ingest_mono_s=buf.last_ingest_mono_s,
            sample_rate_hz=sr,
            waveform_seconds=self._store.config.waveform_seconds,
            capacity=buf.capacity,
            last_t0_us=buf.last_t0_us,
            samples_since_t0=buf.samples_since_t0,
        )

    def _compute_all_serial(
        self,
        client_ids: list[str],
        rates: dict[str, int],
        *,
        serial_fallback: bool = False,
    ) -> dict[str, ClientMetrics]:
        result: dict[str, ClientMetrics] = {}
        for client_id in client_ids:
            try:
                result[client_id] = self.compute_metrics(
                    client_id,
                    sample_rate_hz=rates.get(client_id),
                )
            except (ValueError, ArithmeticError, np.exceptions.DTypePromotionError):
                if serial_fallback:
                    LOGGER.warning(
                        "compute_metrics failed for %s (serial fallback); skipping.",
                        client_id,
                        exc_info=True,
                    )
                else:
                    LOGGER.warning(
                        "compute_metrics failed for %s; skipping.",
                        client_id,
                        exc_info=True,
                    )
        return result

    def _compute_all_parallel_chunked(
        self,
        client_ids: list[str],
        rates: dict[str, int],
        pool: WorkerPool,
    ) -> dict[str, ClientMetrics]:
        chunk_count = min(pool.max_workers, len(client_ids))
        chunk_size = max(1, math.ceil(len(client_ids) / chunk_count))
        chunks = [
            tuple(client_ids[start : start + chunk_size])
            for start in range(0, len(client_ids), chunk_size)
        ]

        chunk_results = pool.map_unordered(
            lambda chunk: self._compute_all_serial(list(chunk), rates, serial_fallback=True),
            chunks,
        )
        result: dict[str, ClientMetrics] = {}
        for chunk in chunks:
            result.update(chunk_results.get(chunk, {}))
        return result
