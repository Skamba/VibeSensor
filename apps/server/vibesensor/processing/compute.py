from __future__ import annotations

import logging
import math
import time
from threading import RLock
from typing import cast

import numpy as np
from vibesensor_core.vibration_strength import empty_vibration_strength_metrics

from ..payload_types import AxisMetrics, AxisPeak, CombinedMetrics
from .fft import (
    AXES,
    compute_fft_spectrum,
    medfilt3,
    noise_floor,
    smooth_spectrum,
    top_peaks,
)
from .models import (
    FftSpectrumResult,
    FloatArray,
    IntIndexArray,
    MetricsComputationResult,
    MetricsPayload,
    MetricsSnapshot,
    ProcessorConfig,
    SpectrumByAxis,
)

LOGGER = logging.getLogger(__name__)
_FFT_CACHE_MAXSIZE = 64
_EMPTY_F32: FloatArray = np.array([], dtype=np.float32)


def _finite_or_zero(value: float) -> float:
    return value if math.isfinite(value) else 0.0


class SignalMetricsComputer:
    """Own FFT cache/window state and compute metrics from immutable snapshots."""

    def __init__(self, config: ProcessorConfig) -> None:
        self._config = config
        self.fft_window: FloatArray = np.hanning(config.fft_n).astype(np.float32)
        self.fft_scale = float(2.0 / max(1.0, float(np.sum(self.fft_window))))
        self.fft_cache: dict[int, tuple[FloatArray, IntIndexArray]] = {}
        self.fft_cache_lock = RLock()

    def fft_params(self, sample_rate_hz: int) -> tuple[FloatArray, IntIndexArray]:
        with self.fft_cache_lock:
            cached = self.fft_cache.get(sample_rate_hz)
            if cached is not None:
                return cached
            if sample_rate_hz <= 0:
                LOGGER.warning(
                    "_fft_params called with invalid sample_rate_hz=%d; "
                    "returning empty frequency slice.",
                    sample_rate_hz,
                )
                return _EMPTY_F32, np.empty(0, dtype=np.intp)
            freqs = np.fft.rfftfreq(self._config.fft_n, d=1.0 / sample_rate_hz)
            valid = (freqs >= self._config.spectrum_min_hz) & (
                freqs <= self._config.spectrum_max_hz
            )
            freq_slice = freqs[valid].astype(np.float32)
            valid_idx = np.flatnonzero(valid)
            self.fft_cache[sample_rate_hz] = (freq_slice, valid_idx)
            if len(self.fft_cache) > _FFT_CACHE_MAXSIZE:
                oldest = next(iter(self.fft_cache))
                del self.fft_cache[oldest]
            return freq_slice, valid_idx

    def compute_fft_spectrum(self, fft_block: FloatArray, sample_rate_hz: int) -> FftSpectrumResult:
        freq_slice, valid_idx = self.fft_params(sample_rate_hz)
        return compute_fft_spectrum(
            fft_block,
            sample_rate_hz,
            fft_window=self.fft_window,
            fft_scale=self.fft_scale,
            freq_slice=freq_slice,
            valid_idx=valid_idx,
            spike_filter_enabled=True,
        )

    def compute(self, snapshot: MetricsSnapshot) -> MetricsComputationResult:
        t0 = time.monotonic()
        time_window = medfilt3(snapshot.time_window)
        time_window_detrended = time_window - np.mean(time_window, axis=1, keepdims=True)

        metrics: MetricsPayload = {}
        if time_window_detrended.shape[1] > 0:
            rms_vals = np.sqrt(np.mean(np.square(time_window_detrended, dtype=np.float64), axis=1))
            p2p_vals = np.max(time_window_detrended, axis=1) - np.min(time_window_detrended, axis=1)
            for axis_idx, axis in enumerate(AXES):
                metrics[axis] = {
                    "rms": _finite_or_zero(float(rms_vals[axis_idx])),
                    "p2p": _finite_or_zero(float(p2p_vals[axis_idx])),
                    "peaks": [],
                }

        if time_window_detrended.size > 0:
            vib_mag = np.sqrt(np.sum(np.square(time_window_detrended, dtype=np.float64), axis=0))
            vib_mag_rms = _finite_or_zero(
                float(np.sqrt(np.mean(np.square(vib_mag), dtype=np.float64))),
            )
            vib_mag_p2p = _finite_or_zero(float(np.max(vib_mag) - np.min(vib_mag)))
        else:
            vib_mag_rms = 0.0
            vib_mag_p2p = 0.0

        metrics["combined"] = {
            "vib_mag_rms": vib_mag_rms,
            "vib_mag_p2p": vib_mag_p2p,
            "peaks": [],
        }

        spectrum_by_axis: SpectrumByAxis = {}
        strength_metrics_dict = empty_vibration_strength_metrics()
        has_fft_data = snapshot.fft_block is not None
        if has_fft_data and snapshot.fft_block is not None:
            fft_result = self.compute_fft_spectrum(snapshot.fft_block, snapshot.sample_rate_hz)
            freq_slice = fft_result["freq_slice"]
            spectrum_by_axis = fft_result["spectrum_by_axis"]

            for axis in fft_result["axis_peaks"]:
                default_axis_metrics: AxisMetrics = {"rms": 0.0, "p2p": 0.0, "peaks": []}
                axis_metrics = cast(
                    "AxisMetrics",
                    metrics.setdefault(axis, default_axis_metrics),
                )
                axis_metrics["peaks"] = fft_result["axis_peaks"][axis]

            if fft_result["axis_amp_slices"]:
                combined_amp = fft_result["combined_amp"]
                strength_metrics = fft_result["strength_metrics"]
                combined_metrics = cast("CombinedMetrics", metrics["combined"])
                combined_metrics["peaks"] = list(strength_metrics["top_peaks"])
                combined_metrics["strength_metrics"] = strength_metrics
                metrics["strength_metrics"] = strength_metrics
                spectrum_by_axis["combined"] = {
                    "freq": freq_slice,
                    "amp": combined_amp,
                }
                strength_metrics_dict = strength_metrics

        return MetricsComputationResult(
            client_id=snapshot.client_id,
            sample_rate_hz=snapshot.sample_rate_hz,
            ingest_generation=snapshot.ingest_generation,
            metrics=metrics,
            spectrum_by_axis=spectrum_by_axis,
            strength_metrics=strength_metrics_dict,
            has_fft_data=has_fft_data,
            duration_s=time.monotonic() - t0,
        )

    @staticmethod
    def smooth_spectrum(amps: np.ndarray, bins: int = 5) -> np.ndarray:
        return cast("np.ndarray", smooth_spectrum(np.asarray(amps, dtype=np.float32), bins=bins))

    @staticmethod
    def noise_floor(amps: np.ndarray) -> float:
        return noise_floor(amps)

    @classmethod
    def top_peaks(
        cls,
        freqs: np.ndarray,
        amps: np.ndarray,
        *,
        top_n: int = 5,
        floor_ratio: float | None = None,
        smoothing_bins: int = 5,
    ) -> list[AxisPeak]:
        if floor_ratio is not None:
            return top_peaks(
                freqs,
                amps,
                top_n=top_n,
                floor_ratio=floor_ratio,
                smoothing_bins=smoothing_bins,
            )
        return top_peaks(freqs, amps, top_n=top_n, smoothing_bins=smoothing_bins)
