from __future__ import annotations

import math
import time

import numpy as np

from vibesensor.infra.processing.models import (
    MetricsComputationResult,
    MetricsSnapshot,
    ProcessorConfig,
    SpectrumByAxis,
)
from vibesensor.shared.fft_analysis import AXES, SpectralAnalysisComputer, medfilt3
from vibesensor.shared.types.payload_types import AxisMetrics, ClientMetrics
from vibesensor.shared.types.processing_profile import (
    PROCESSING_FILTER_MEDIAN_3_SAMPLE,
    PROCESSING_PROFILE_LIVE_DISPLAY,
)
from vibesensor.vibration_strength import empty_vibration_strength_metrics


def _finite_or_zero(value: float) -> float:
    return value if math.isfinite(value) else 0.0


class SignalMetricsComputer(SpectralAnalysisComputer):
    """Own FFT cache/window state and compute metrics from immutable snapshots."""

    def __init__(self, config: ProcessorConfig) -> None:
        self._config = config
        super().__init__(
            fft_n=config.fft_n,
            spectrum_min_hz=config.spectrum_min_hz,
            spectrum_max_hz=config.spectrum_max_hz,
        )

    def _filtered_windows(self, snapshot: MetricsSnapshot) -> tuple[np.ndarray, np.ndarray | None]:
        fft_block = snapshot.fft_block
        if fft_block is None:
            return medfilt3(snapshot.time_window), None

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
            "processing_profile": PROCESSING_PROFILE_LIVE_DISPLAY,
            "filter_chain": [PROCESSING_FILTER_MEDIAN_3_SAMPLE],
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
            reset_generation=snapshot.reset_generation,
            metrics=metrics,
            spectrum_by_axis=spectrum_by_axis,
            strength_metrics=strength_metrics_dict,
            has_fft_data=has_fft_data,
            duration_s=time.monotonic() - t0,
            analysis_time_range=snapshot.analysis_time_range,
        )
