"""Signal processor facade with explicit state, compute, and view subsystems.

``SignalProcessor`` preserves the external API used by runtime, routes, and
metrics logging while delegating to focused collaborators:

- :mod:`vibesensor.processing.buffer_store` owns buffer lifecycle, shared state,
  locking, and state snapshots.
- :mod:`vibesensor.processing.compute` owns FFT cache/window state and metric
  computation from immutable snapshots.
- :mod:`vibesensor.processing.views` owns payload shaping, debug output, and
  time-alignment views.
"""

from __future__ import annotations

import logging
import time
from typing import cast

import numpy as np

from ..json_types import JsonObject
from ..payload_types import (
    AxisPeak,
    DebugSpectrumErrorPayload,
    DebugSpectrumPayload,
    IntakeStatsPayload,
    RawSamplesErrorPayload,
    RawSamplesPayload,
    SelectedClientPayload,
    SpectraPayload,
    TimeAlignmentPayload,
)
from ..worker_pool import WorkerPool
from .buffer_store import MAX_CLIENT_SAMPLE_RATE_HZ as _MAX_CLIENT_SAMPLE_RATE_HZ
from .buffer_store import SignalBufferStore
from .buffers import ClientBuffer
from .compute import SignalMetricsComputer
from .models import (
    CachedMetricsHit,
    ClientMetrics,
    FftSpectrumResult,
    FloatArray,
    IntIndexArray,
    ProcessorConfig,
)
from .payload import SpectrumSeriesPayload
from .views import SignalProcessorViews

LOGGER = logging.getLogger(__name__)
MAX_CLIENT_SAMPLE_RATE_HZ = _MAX_CLIENT_SAMPLE_RATE_HZ


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
        self._views = SignalProcessorViews(store=self._store, metrics=self._metrics)
        self._worker_pool = worker_pool

        # Preserve the established internal surface used by tests/regressions.
        self._buffers = self._store.buffers
        self._lock = self._store.lock
        self._fft_window = self._metrics.fft_window
        self._fft_scale = self._metrics.fft_scale
        self._fft_cache = self._metrics.fft_cache
        self._fft_cache_lock = self._metrics.fft_cache_lock

    @staticmethod
    def _smooth_spectrum(amps: np.ndarray, bins: int = 5) -> np.ndarray:
        return SignalMetricsComputer.smooth_spectrum(amps, bins=bins)

    @staticmethod
    def _noise_floor(amps: np.ndarray) -> float:
        return SignalMetricsComputer.noise_floor(amps)

    @classmethod
    def _top_peaks(
        cls,
        freqs: np.ndarray,
        amps: np.ndarray,
        *,
        top_n: int = 5,
        floor_ratio: float | None = None,
        smoothing_bins: int = 5,
    ) -> list[AxisPeak]:
        return SignalMetricsComputer.top_peaks(
            freqs,
            amps,
            top_n=top_n,
            floor_ratio=floor_ratio,
            smoothing_bins=smoothing_bins,
        )

    def flush_client_buffer(self, client_id: str) -> None:
        self._store.flush_client_buffer(client_id)

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

    def _get_or_create(self, client_id: str) -> ClientBuffer:
        with self._lock:
            return self._store._get_or_create_unlocked(client_id)

    def _resize_buffer(self, buf: ClientBuffer, new_capacity: int) -> None:
        with self._lock:
            self._store._resize_buffer_unlocked(buf, new_capacity)

    def _latest(self, buf: ClientBuffer, n: int) -> FloatArray:
        with self._lock:
            return self._store.copy_latest(buf, n)

    def _fft_params(self, sample_rate_hz: int) -> tuple[FloatArray, IntIndexArray]:
        return self._metrics.fft_params(sample_rate_hz)

    def _compute_fft_spectrum(
        self,
        fft_block: np.ndarray,
        sample_rate_hz: int,
    ) -> FftSpectrumResult:
        return self._metrics.compute_fft_spectrum(fft_block, sample_rate_hz)

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

        if len(client_ids) <= 1 or self._worker_pool is None:
            result = self._compute_all_serial(client_ids, rates)
            self._store.record_compute_all_duration(time.monotonic() - t0)
            return result

        try:
            result = self._worker_pool.map_unordered(
                lambda client_id: self.compute_metrics(
                    client_id,
                    sample_rate_hz=rates.get(client_id),
                ),
                client_ids,
            )
        except (RuntimeError, OSError):
            LOGGER.warning(
                "compute_all: worker pool raised; falling back to serial execution.",
                exc_info=True,
            )
            result = self._compute_all_serial(client_ids, rates, serial_fallback=True)
        self._store.record_compute_all_duration(time.monotonic() - t0)
        return result

    def spectrum_payload(self, client_id: str) -> SpectrumSeriesPayload:
        return self._views.spectrum_payload(client_id)

    def multi_spectrum_payload(self, client_ids: list[str]) -> SpectraPayload:
        return self._views.multi_spectrum_payload(client_ids)

    def selected_payload(self, client_id: str) -> SelectedClientPayload:
        return self._views.selected_payload(client_id)

    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float] | None:
        return self._store.latest_sample_xyz(client_id)

    def latest_sample_rate_hz(self, client_id: str) -> int | None:
        return self._store.latest_sample_rate_hz(client_id)

    def debug_spectrum(self, client_id: str) -> DebugSpectrumPayload | DebugSpectrumErrorPayload:
        return self._views.debug_spectrum(client_id)

    def raw_samples(
        self,
        client_id: str,
        n_samples: int = 2048,
    ) -> RawSamplesPayload | RawSamplesErrorPayload:
        return self._views.raw_samples(client_id, n_samples=n_samples)

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        return self._store.clients_with_recent_data(client_ids, max_age_s=max_age_s)

    def evict_clients(self, keep_client_ids: set[str]) -> None:
        self._store.evict_clients(keep_client_ids)

    def intake_stats(self) -> IntakeStatsPayload:
        stats = self._store.intake_stats()
        if self._worker_pool is not None:
            stats["worker_pool"] = cast("JsonObject", self._worker_pool.stats())
        return stats

    def _analysis_time_range(self, buf: ClientBuffer) -> tuple[float, float, bool] | None:
        return self._views.analysis_time_range(buf)

    def time_alignment_info(self, client_ids: list[str]) -> TimeAlignmentPayload:
        return self._views.time_alignment_info(client_ids)

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
