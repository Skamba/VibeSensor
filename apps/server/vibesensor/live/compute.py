from __future__ import annotations

import time
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from vibesensor.dsp.fft_analysis import (
    SpectralAnalysisComputer,
    fill_lost_samples,
    present_centre,
)
from vibesensor.dsp.vibration_strength import empty_vibration_strength_metrics
from vibesensor.live.models import (
    FloatArray,
    MetricsComputationResult,
    MetricsSnapshot,
    ProcessorConfig,
    SpectrumByAxis,
)
from vibesensor.live.payload_types import ClientMetrics

if TYPE_CHECKING:
    from vibesensor.live.analysis_time_range import AnalysisTimeRange


def _fft_input(snapshot: MetricsSnapshot, fft_window: FloatArray) -> FloatArray | None:
    """The FFT block with its lost samples filled; ``None`` when too much was lost.

    The block is not filtered, as the post-stop raw replay does not filter it:
    the strength and noise floor a summary row stores are the ones the replay
    would compute, whichever of the two a run's rows come from.
    """
    fft_block = snapshot.fft_block
    if fft_block is None:
        return None
    return fill_lost_samples(fft_block, fft_window)


def _spectrum_time_range(
    snapshot: MetricsSnapshot, fft_window: FloatArray
) -> AnalysisTimeRange | None:
    """The snapshot's time range, centred where the FFT block's samples present weigh in."""
    time_range = snapshot.analysis_time_range
    fft_block = snapshot.fft_block
    if time_range is None or fft_block is None:
        return time_range
    lost = np.isnan(fft_block).any(axis=0)
    if not lost.any():
        return time_range
    centre_s = time_range.start_s + present_centre(lost, fft_window) / snapshot.sample_rate_hz
    return replace(time_range, centre_s=centre_s)


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
        fft_input = _fft_input(snapshot, self.fft_window)

        metrics: ClientMetrics = {"combined": {"peaks": []}}
        spectrum_by_axis: SpectrumByAxis = {}
        strength_metrics_dict = empty_vibration_strength_metrics()
        has_fft_data = fft_input is not None
        if fft_input is not None:
            fft_result = self.compute_fft_spectrum(fft_input, snapshot.sample_rate_hz)
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
            analysis_time_range=_spectrum_time_range(snapshot, self.fft_window),
        )
