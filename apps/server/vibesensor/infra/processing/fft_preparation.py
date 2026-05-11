from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vibesensor.infra.processing.models import FloatArray, MetricsSnapshot
from vibesensor.shared.fft_analysis import medfilt3


@dataclass(frozen=True, slots=True)
class PreparedFftWindows:
    """Filtered and detrended sample windows for metrics and FFT analysis."""

    time_window: FloatArray
    fft_input: FloatArray | None
    time_window_detrended: FloatArray


def prepare_fft_windows(snapshot: MetricsSnapshot) -> PreparedFftWindows:
    """Apply live-processing sample filters and prepare detrended metrics input."""
    time_window, fft_input = _filtered_windows(snapshot)
    time_window_detrended = time_window - np.mean(time_window, axis=1, keepdims=True)
    return PreparedFftWindows(
        time_window=time_window,
        fft_input=fft_input,
        time_window_detrended=time_window_detrended,
    )


def _filtered_windows(snapshot: MetricsSnapshot) -> tuple[FloatArray, FloatArray | None]:
    fft_block = snapshot.fft_block
    if fft_block is None:
        return medfilt3(snapshot.time_window), None

    if snapshot.time_window.shape[1] >= fft_block.shape[1]:
        filtered_source = medfilt3(snapshot.time_window)
        return filtered_source, filtered_source[:, -fft_block.shape[1] :]

    filtered_source = medfilt3(fft_block)
    return filtered_source[:, -snapshot.time_window.shape[1] :], filtered_source
