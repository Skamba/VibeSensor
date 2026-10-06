from __future__ import annotations

import time

from vibesensor.dsp.fft_analysis import SpectralAnalysisComputer, medfilt3
from vibesensor.dsp.vibration_strength import empty_vibration_strength_metrics
from vibesensor.live.models import (
    FloatArray,
    MetricsComputationResult,
    MetricsSnapshot,
    ProcessorConfig,
    SpectrumByAxis,
)
from vibesensor.live.payload_types import ClientMetrics


def _filtered_fft_input(snapshot: MetricsSnapshot) -> FloatArray | None:
    """Median-filter the FFT block, using the time window's history at its edge.

    A filtered sample depends only on itself and its two neighbours, so only the
    sample just before the block is read from the history: filtering that tail
    gives the same block as filtering the whole time window, for a fraction of
    the work on every live tick.
    """
    fft_block = snapshot.fft_block
    if fft_block is None:
        return None

    fft_n = fft_block.shape[1]
    if snapshot.time_window.shape[1] >= fft_n:
        return medfilt3(snapshot.time_window[:, -(fft_n + 1) :])[:, -fft_n:]

    return medfilt3(fft_block)


class SignalMetricsComputer(SpectralAnalysisComputer):
    """Own FFT cache/window state and compute metrics from immutable snapshots."""

    def __init__(self, config: ProcessorConfig) -> None:
        self._config = config
        super().__init__(
            fft_n=config.fft_n,
            spectrum_min_hz=config.spectrum_min_hz,
            spectrum_max_hz=config.spectrum_max_hz,
        )

    def compute(self, snapshot: MetricsSnapshot) -> MetricsComputationResult:
        t0 = time.monotonic()
        fft_input = _filtered_fft_input(snapshot)

        metrics: ClientMetrics = {"combined": {"peaks": []}}
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

            for ax_key, axis_peaks in fft_result["axis_peaks"].items():
                metrics[ax_key] = {"peaks": axis_peaks}

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
