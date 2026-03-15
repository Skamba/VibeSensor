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
import time
from typing import cast

import numpy as np

from vibesensor.infra.processing.buffer_store import (
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
    build_multi_spectrum_payload,
    build_spectrum_payload,
)
from vibesensor.infra.processing.time_align import analysis_time_range, compute_overlap
from vibesensor.infra.workers.worker_pool import WorkerPool
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.payload_types import (
    DebugSpectrumErrorPayload,
    DebugSpectrumPayload,
    DebugSpectrumStatsPayload,
    DebugSpectrumTopBinPayload,
    IntakeStatsPayload,
    RawSamplesErrorPayload,
    RawSamplesPayload,
    SharedWindowPayload,
    SpectraPayload,
    TimeAlignmentPayload,
    TimeAlignmentSensorPayload,
)

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
        self._worker_pool = worker_pool

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
        with self._store.lock:
            return self._spectrum_payload_unlocked(client_id)

    def multi_spectrum_payload(self, client_ids: list[str]) -> SpectraPayload:
        with self._store.lock:
            return build_multi_spectrum_payload(
                self._store.buffers,
                client_ids,
                spectrum_fn=self._spectrum_payload_unlocked,
                analysis_time_range_fn=self._analysis_time_range_unlocked,
            )

    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float] | None:
        return self._store.latest_sample_xyz(client_id)

    def latest_sample_rate_hz(self, client_id: str) -> int | None:
        return self._store.latest_sample_rate_hz(client_id)

    def latest_metrics(self, client_id: str) -> ClientMetrics:
        """Return latest computed metrics for a client."""
        return self._store.latest_metrics(client_id)

    def all_latest_metrics(self, client_ids: list[str]) -> dict[str, ClientMetrics]:
        """Return latest metrics for requested clients."""
        return self._store.all_latest_metrics(client_ids)

    def debug_spectrum(self, client_id: str) -> DebugSpectrumPayload | DebugSpectrumErrorPayload:
        request = self._store.debug_request(client_id)
        if request.fft_block is None:
            return {
                "error": "insufficient samples",
                "count": request.count,
                "fft_n": self._store.config.fft_n,
            }

        fft_block = request.fft_block
        raw_mean = fft_block.mean(axis=1).tolist()
        raw_std = fft_block.std(axis=1).tolist()
        raw_min = fft_block.min(axis=1).tolist()
        raw_max = fft_block.max(axis=1).tolist()

        fft_result = self._metrics.compute_fft_spectrum(fft_block, request.sample_rate_hz)
        freq_slice = fft_result["freq_slice"]
        combined_amp = fft_result["combined_amp"]
        strength_metrics = fft_result["strength_metrics"]
        detrended_std = (fft_block - fft_block.mean(axis=1, keepdims=True)).std(axis=1).tolist()

        sorted_idx = np.argsort(combined_amp)[::-1]
        spectrum = fft_result["spectrum_by_axis"]
        top_bins: list[DebugSpectrumTopBinPayload] = []
        for index in sorted_idx[:10]:
            top_bins.append(
                {
                    "bin": int(index),
                    "freq_hz": float(freq_slice[index]),
                    "combined_amp_g": float(combined_amp[index]),
                    "x_amp_g": float(spectrum["x"]["amp"][index]),
                    "y_amp_g": float(spectrum["y"]["amp"][index]),
                    "z_amp_g": float(spectrum["z"]["amp"][index]),
                },
            )

        raw_stats: DebugSpectrumStatsPayload = {
            "mean_g": raw_mean,
            "std_g": raw_std,
            "min_g": raw_min,
            "max_g": raw_max,
        }
        return {
            "client_id": client_id,
            "sample_rate_hz": request.sample_rate_hz,
            "fft_n": self._store.config.fft_n,
            "fft_scale": self._metrics.fft_scale,
            "window": "hann",
            "spectrum_min_hz": self._store.config.spectrum_min_hz,
            "spectrum_max_hz": self._store.config.spectrum_max_hz,
            "freq_bins": len(freq_slice),
            "freq_resolution_hz": float(request.sample_rate_hz) / self._store.config.fft_n,
            "raw_stats": raw_stats,
            "detrended_std_g": detrended_std,
            "vibration_strength_db": float(strength_metrics.get("vibration_strength_db", 0)),
            "top_bins_by_amplitude": top_bins,
            "strength_peaks": list(strength_metrics.get("top_peaks", [])),
        }

    def raw_samples(
        self,
        client_id: str,
        n_samples: int = 2048,
    ) -> RawSamplesPayload | RawSamplesErrorPayload:
        return self._store.raw_samples(client_id, n_samples=n_samples)

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
        with self._store.lock:
            return self._analysis_time_range_unlocked(buf)

    def time_alignment_info(self, client_ids: list[str]) -> TimeAlignmentPayload:
        with self._store.lock:
            per_sensor: dict[str, TimeAlignmentSensorPayload] = {}
            ranges: list[tuple[float, float]] = []
            included: list[str] = []
            excluded: list[str] = []
            all_synced = True

            for client_id in client_ids:
                buf = self._store.buffers.get(client_id)
                if buf is None:
                    excluded.append(client_id)
                    continue
                time_range = self._analysis_time_range_unlocked(buf)
                if time_range is None:
                    excluded.append(client_id)
                    continue
                start, end, synced = time_range
                if not synced:
                    all_synced = False
                per_sensor[client_id] = {
                    "start_s": start,
                    "end_s": end,
                    "duration_s": end - start,
                    "synced": synced,
                }
                ranges.append((start, end))
                included.append(client_id)

            if len(ranges) < 2:
                return {
                    "per_sensor": per_sensor,
                    "shared_window": None,
                    "overlap_ratio": 1.0 if len(ranges) == 1 else 0.0,
                    "aligned": True,
                    "clock_synced": all_synced and bool(included),
                    "sensors_included": included,
                    "sensors_excluded": excluded,
                }

            overlap = compute_overlap([start for start, _ in ranges], [end for _, end in ranges])
            shared: SharedWindowPayload | None = None
            if overlap.overlap_s > 0:
                shared = {
                    "start_s": overlap.shared_start,
                    "end_s": overlap.shared_end,
                    "duration_s": overlap.overlap_s,
                }

            return {
                "per_sensor": per_sensor,
                "shared_window": shared,
                "overlap_ratio": round(overlap.overlap_ratio, 4),
                "aligned": overlap.aligned,
                "clock_synced": all_synced,
                "sensors_included": included,
                "sensors_excluded": excluded,
            }

    def _spectrum_payload_unlocked(self, client_id: str) -> SpectrumSeriesPayload:
        buf = self._store.buffers.get(client_id)
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
