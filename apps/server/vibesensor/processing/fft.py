"""Pure spectral-analysis functions used by the signal processor.

All functions in this module are stateless: they take arrays (and scalar
parameters) and return results without touching any shared mutable state.
This makes them independently testable and reusable outside of the
:class:`~vibesensor.processing.processor.SignalProcessor` class.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from vibesensor_core.vibration_strength import (
    PEAK_THRESHOLD_FLOOR_RATIO,
    STRENGTH_EPSILON_MIN_G,
    combined_spectrum_amp_g,
    compute_vibration_strength_db,
    noise_floor_amp_p20_g,
)

from ..constants import PEAK_BANDWIDTH_HZ, PEAK_SEPARATION_HZ

AXES = ("x", "y", "z")


def medfilt3(block: np.ndarray) -> np.ndarray:
    """Apply a 3-point median filter per-row (per-axis).

    Eliminates isolated single-sample spikes caused by I2C bus
    glitches while preserving genuine vibration signal content.
    Edge samples are left unchanged.
    """
    if block.shape[-1] < 3:
        return block
    stacked = np.stack([block[:, :-2], block[:, 1:-1], block[:, 2:]], axis=0)
    filtered = block.copy()
    filtered[:, 1:-1] = np.nanmedian(stacked, axis=0)
    return filtered


def smooth_spectrum(amps: np.ndarray, bins: int = 5) -> np.ndarray:
    """Smooth a spectrum using a sliding-average convolution kernel."""
    if amps.size == 0:
        return amps
    width = max(1, int(bins))
    if width <= 1:
        return amps.astype(np.float32, copy=True)
    if (width % 2) == 0:
        width += 1
    if amps.size < width:
        return amps.astype(np.float32, copy=True)
    kernel = np.ones(width, dtype=np.float32) / np.float32(width)
    half = width // 2
    padded = np.pad(amps, (half, half), mode="edge")
    return np.convolve(padded, kernel, mode="valid").astype(np.float32)


def noise_floor(amps: np.ndarray) -> float:
    """P20 noise floor delegating to the canonical core-lib implementation."""
    if amps.size == 0:
        return 0.0
    finite = amps[np.isfinite(amps)]
    if finite.size == 0:
        return 0.0
    return noise_floor_amp_p20_g(
        combined_spectrum_amp_g=sorted(float(v) for v in finite if v >= 0.0)
    )


def float_list(values: np.ndarray | list[float]) -> list[float]:
    """Convert an array-like to a plain Python ``list[float]``."""
    if isinstance(values, np.ndarray):
        return values.ravel().tolist()
    return [float(v) for v in values]


def top_peaks(
    freqs: np.ndarray,
    amps: np.ndarray,
    *,
    top_n: int = 5,
    floor_ratio: float = PEAK_THRESHOLD_FLOOR_RATIO,
    smoothing_bins: int = 5,
) -> list[dict[str, float]]:
    """Extract the *top_n* spectral peaks above the noise floor."""
    if freqs.size == 0 or amps.size == 0:
        return []
    smoothed = smooth_spectrum(amps, bins=smoothing_bins)
    floor_amp = noise_floor(smoothed)
    if not math.isfinite(floor_amp) or floor_amp < 0:
        floor_amp = 0.0
    threshold = max(floor_amp * max(1.1, floor_ratio), floor_amp + STRENGTH_EPSILON_MIN_G)

    peak_idx: list[int] = []
    for idx in range(1, smoothed.size - 1):
        amp = float(smoothed[idx])
        if amp < threshold:
            continue
        if amp > float(smoothed[idx - 1]) and amp >= float(smoothed[idx + 1]):
            peak_idx.append(idx)
    # Boundary check: last bin can be a peak if it exceeds its left neighbor.
    if smoothed.size > 1:
        last = smoothed.size - 1
        amp_last = float(smoothed[last])
        if amp_last >= threshold and amp_last > float(smoothed[last - 1]):
            peak_idx.append(last)

    if not peak_idx:
        if smoothed.size > 1:
            candidate = int(np.argmax(smoothed[1:]) + 1)
        else:
            candidate = int(np.argmax(smoothed))
        if candidate >= 0 and float(smoothed[candidate]) > 0:
            peak_idx = [candidate]

    peak_idx.sort(key=lambda idx: float(smoothed[idx]), reverse=True)
    peaks: list[dict[str, float]] = []
    for idx in peak_idx[:top_n]:
        raw_amp = float(amps[idx])
        peaks.append(
            {
                "hz": float(freqs[idx]),
                "amp": raw_amp,
                "snr_ratio": (
                    (raw_amp + STRENGTH_EPSILON_MIN_G) / (floor_amp + STRENGTH_EPSILON_MIN_G)
                ),
            }
        )
    return peaks


def compute_fft_spectrum(
    fft_block: np.ndarray,
    sample_rate_hz: int,
    *,
    fft_window: np.ndarray,
    fft_scale: float,
    freq_slice: np.ndarray,
    valid_idx: np.ndarray,
    spike_filter_enabled: bool = True,
) -> dict[str, Any]:
    """Compute per-axis and combined FFT spectra from a sample block.

    This is the core spectral computation used by both
    :meth:`~SignalProcessor.compute_metrics` and
    :meth:`~SignalProcessor.debug_spectrum`.

    Parameters
    ----------
    fft_block:
        ``(3, fft_n)`` array of time-domain samples (one row per axis).
    sample_rate_hz:
        Current sample rate in Hz.
    fft_window:
        Pre-computed window function (Hann, etc.).
    fft_scale:
        Normalisation scalar ``2 / sum(window)``.
    freq_slice:
        Pre-computed frequency bins within the display range.
    valid_idx:
        Indices into the full FFT output that correspond to *freq_slice*.
    spike_filter_enabled:
        Whether to apply the 3-point median spike filter.

    Returns
    -------
    dict with keys: ``freq_slice``, ``valid_idx``, ``spectrum_by_axis``,
    ``axis_amp_slices``, ``axis_amps``, ``combined_amp``,
    ``strength_metrics``, ``axis_peaks``.
    """
    if spike_filter_enabled:
        fft_block = medfilt3(fft_block)
    fft_block = fft_block - np.mean(fft_block, axis=1, keepdims=True)
    fft_n = fft_window.shape[0]

    spectrum_by_axis: dict[str, dict[str, np.ndarray]] = {}
    axis_amp_slices: list[np.ndarray] = []
    axis_amps: dict[str, np.ndarray] = {}
    axis_peaks: dict[str, list] = {}

    for axis_idx, axis in enumerate(AXES):
        windowed = fft_block[axis_idx] * fft_window
        spec = np.abs(np.fft.rfft(windowed)).astype(np.float32)
        spec *= fft_scale
        if spec.size > 0:
            spec[0] *= 0.5
        if (fft_n % 2) == 0 and spec.size > 1:
            spec[-1] *= 0.5
        amp_slice = spec[valid_idx]
        amp_for_peaks = amp_slice.copy()
        if amp_for_peaks.size > 1 and freq_slice.size > 0 and freq_slice[0] < 0.5:
            amp_for_peaks[0] = 0.0
        axis_peaks[axis] = top_peaks(
            freq_slice,
            amp_for_peaks,
            top_n=3,
            smoothing_bins=3,
        )
        spectrum_by_axis[axis] = {
            "freq": freq_slice,
            "amp": amp_slice,
        }
        axis_amps[axis] = amp_slice
        axis_amp_slices.append(amp_slice)

    combined_amp = np.empty(0, dtype=np.float32)
    strength_metrics: dict[str, Any] = {}
    if axis_amp_slices:
        combined_amp = np.asarray(
            combined_spectrum_amp_g(
                axis_spectra_amp_g=axis_amp_slices,  # type: ignore[arg-type]
                axis_count_for_mean=len(axis_amp_slices),
            ),
            dtype=np.float32,
        )
        strength_metrics = compute_vibration_strength_db(
            freq_hz=float_list(freq_slice),
            combined_spectrum_amp_g_values=float_list(combined_amp),
            peak_bandwidth_hz=PEAK_BANDWIDTH_HZ,
            peak_separation_hz=PEAK_SEPARATION_HZ,
            top_n=8,
        )

    return {
        "freq_slice": freq_slice,
        "valid_idx": valid_idx,
        "spectrum_by_axis": spectrum_by_axis,
        "axis_amp_slices": axis_amp_slices,
        "axis_amps": axis_amps,
        "combined_amp": combined_amp,
        "strength_metrics": strength_metrics,
        "axis_peaks": axis_peaks,
    }
