from __future__ import annotations

import logging
import math
import time
from collections import OrderedDict
from threading import RLock

import numpy as np
from scipy import fft as scipy_fft
from scipy.signal import windows as signal_windows

from vibesensor.infra.processing.fft import (
    AXES,
    compute_fft_spectrum,
    medfilt3,
)
from vibesensor.infra.processing.models import (
    BoolArray,
    ClientMetrics,
    FftSpectrumResult,
    FloatArray,
    IntIndexArray,
    MetricsComputationResult,
    MetricsSnapshot,
    ProcessorConfig,
    SpectrumByAxis,
)
from vibesensor.shared.types.payload_types import AxisMetrics
from vibesensor.vibration_strength import empty_vibration_strength_metrics

LOGGER = logging.getLogger(__name__)
_FFT_CACHE_MAXSIZE = 64
_EMPTY_F32: FloatArray = np.array([], dtype=np.float32)
_EMPTY_BOOL: BoolArray = np.empty(0, dtype=np.bool_)


def _finite_or_zero(value: float) -> float:
    return value if math.isfinite(value) else 0.0


class SignalMetricsComputer:
    """Own FFT cache/window state and compute metrics from immutable snapshots."""

    def __init__(self, config: ProcessorConfig) -> None:
        self._config = config
        self.fft_window: FloatArray = np.asarray(
            signal_windows.hann(config.fft_n, sym=True),
            dtype=np.float32,
        )
        self.fft_scale = float(2.0 / max(1.0, float(np.sum(self.fft_window))))
        self.fft_cache: OrderedDict[int, tuple[FloatArray, IntIndexArray, BoolArray]] = (
            OrderedDict()
        )
        self.fft_cache_lock = RLock()

    def _fft_cache_entry(self, sample_rate_hz: int) -> tuple[FloatArray, IntIndexArray, BoolArray]:
        with self.fft_cache_lock:
            cached = self.fft_cache.get(sample_rate_hz)
            if cached is not None:
                self.fft_cache.move_to_end(sample_rate_hz)
                return cached
            if sample_rate_hz <= 0:
                LOGGER.warning(
                    "_fft_params called with invalid sample_rate_hz=%d; "
                    "returning empty frequency slice.",
                    sample_rate_hz,
                )
                return _EMPTY_F32, np.empty(0, dtype=np.intp), _EMPTY_BOOL
            freqs = scipy_fft.rfftfreq(self._config.fft_n, d=1.0 / sample_rate_hz)
            valid = (freqs >= self._config.spectrum_min_hz) & (
                freqs <= self._config.spectrum_max_hz
            )
            freq_slice = freqs[valid].astype(np.float32)
            valid_idx = np.flatnonzero(valid)
            strength_range_mask = np.ones(freq_slice.shape, dtype=np.bool_)
            self.fft_cache[sample_rate_hz] = (freq_slice, valid_idx, strength_range_mask)
            if len(self.fft_cache) > _FFT_CACHE_MAXSIZE:
                self.fft_cache.popitem(last=False)
            return freq_slice, valid_idx, strength_range_mask

    def fft_params(self, sample_rate_hz: int) -> tuple[FloatArray, IntIndexArray]:
        freq_slice, valid_idx, _ = self._fft_cache_entry(sample_rate_hz)
        return freq_slice, valid_idx

    def strength_range_mask(self, sample_rate_hz: int) -> BoolArray:
        _, _, strength_range_mask = self._fft_cache_entry(sample_rate_hz)
        return strength_range_mask

    def compute_fft_spectrum(
        self,
        fft_block: FloatArray,
        sample_rate_hz: int,
        *,
        spike_filter_enabled: bool = True,
    ) -> FftSpectrumResult:
        freq_slice, valid_idx, strength_range_mask = self._fft_cache_entry(sample_rate_hz)
        return compute_fft_spectrum(
            fft_block,
            sample_rate_hz,
            fft_window=self.fft_window,
            fft_scale=self.fft_scale,
            freq_slice=freq_slice,
            valid_idx=valid_idx,
            strength_range_mask=strength_range_mask,
            spike_filter_enabled=spike_filter_enabled,
        )

    def _filtered_windows(self, snapshot: MetricsSnapshot) -> tuple[FloatArray, FloatArray | None]:
        fft_block = snapshot.fft_block
        if fft_block is None:
            return medfilt3(snapshot.time_window), None

        # The time window and FFT block are always overlapping suffixes from the
        # same immutable snapshot. Filter the larger window once, then reuse the
        # matching tail view for the smaller consumer.
        if snapshot.time_window.shape[1] >= fft_block.shape[1]:
            filtered_source = medfilt3(snapshot.time_window)
            return filtered_source, filtered_source[:, -fft_block.shape[1] :]

        filtered_source = medfilt3(fft_block)
        return filtered_source[:, -snapshot.time_window.shape[1] :], filtered_source

    def compute(self, snapshot: MetricsSnapshot) -> MetricsComputationResult:
        t0 = time.monotonic()
        time_window, fft_input = self._filtered_windows(snapshot)
        time_window_detrended = time_window - np.mean(time_window, axis=1, keepdims=True)

        metrics: ClientMetrics = {}
        if time_window_detrended.size > 0:
            squared = np.empty_like(time_window_detrended, dtype=np.float64)
            np.square(time_window_detrended, out=squared, dtype=np.float64)

            rms_vals = np.sqrt(np.mean(squared, axis=1))
            p2p_vals = np.ptp(time_window_detrended, axis=1)
            for axis_idx, axis in enumerate(AXES):
                metrics[axis] = {
                    "rms": _finite_or_zero(float(rms_vals[axis_idx])),
                    "p2p": _finite_or_zero(float(p2p_vals[axis_idx])),
                    "peaks": [],
                }

            vib_mag_sq = np.sum(squared, axis=0)
            vib_mag = np.sqrt(vib_mag_sq)
            vib_mag_rms = _finite_or_zero(
                float(np.sqrt(np.mean(vib_mag_sq, dtype=np.float64))),
            )
            vib_mag_p2p = _finite_or_zero(float(np.ptp(vib_mag)))
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
        has_fft_data = fft_input is not None
        if fft_input is not None:
            fft_result = self.compute_fft_spectrum(
                fft_input,
                snapshot.sample_rate_hz,
                spike_filter_enabled=False,
            )
            freq_slice = fft_result["freq_slice"]
            spectrum_by_axis = fft_result["spectrum_by_axis"]

            for ax_key in fft_result["axis_peaks"]:
                default_axis_metrics: AxisMetrics = {"rms": 0.0, "p2p": 0.0, "peaks": []}
                axis_metrics = metrics.setdefault(ax_key, default_axis_metrics)
                axis_metrics["peaks"] = fft_result["axis_peaks"][ax_key]

            if fft_result["spectrum_by_axis"]:
                combined_amp = fft_result["combined_amp"]
                strength_metrics = fft_result["strength_metrics"]
                combined_metrics = metrics["combined"]
                combined_metrics["peaks"] = list(strength_metrics["top_peaks"])
                combined_metrics["strength_metrics"] = strength_metrics
                spectrum_by_axis["combined"] = {
                    "freq": freq_slice,
                    "amp": combined_amp,
                }
                strength_metrics_dict = strength_metrics

        return MetricsComputationResult(
            client_id=snapshot.client_id,
            sample_rate_hz=snapshot.sample_rate_hz,
            ingest_generation=snapshot.ingest_generation,
            buffer_epoch=snapshot.buffer_epoch,
            metrics=metrics,
            spectrum_by_axis=spectrum_by_axis,
            strength_metrics=strength_metrics_dict,
            has_fft_data=has_fft_data,
            duration_s=time.monotonic() - t0,
        )
