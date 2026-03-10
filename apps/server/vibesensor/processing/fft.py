"""Pure spectral-analysis functions used by the signal processor.

All functions in this module are stateless: they take arrays (and scalar
parameters) and return results without touching any shared mutable state.
This makes them independently testable and reusable outside of the
:class:`~vibesensor.processing.processor.SignalProcessor` class.
"""

from __future__ import annotations

import math
import warnings
from typing import TypeAlias

import numpy as np
import numpy.typing as npt

from vibesensor.core.vibration_strength import (
    PEAK_THRESHOLD_FLOOR_RATIO,
    STRENGTH_EPSILON_MIN_G,
    VibrationStrengthMetrics,
    combined_spectrum_amp_g,
    compute_vibration_strength_db,
    empty_vibration_strength_metrics,
    noise_floor_amp_p20_g,
)

from ..constants import PEAK_BANDWIDTH_HZ, PEAK_SEPARATION_HZ
from .models import AxisPeak, FftSpectrumResult, SpectrumByAxis

AXES = ("x", "y", "z")

FloatArray: TypeAlias = npt.NDArray[np.float32]
IntIndexArray: TypeAlias = npt.NDArray[np.intp]


def medfilt3(block: FloatArray) -> FloatArray:
    """Apply a 3-point median filter per-row (per-axis).

    Eliminates isolated single-sample spikes caused by I2C bus
    glitches while preserving genuine vibration signal content.
    Edge samples are left unchanged.

    Parameters
    ----------
    block:
        Must be a 2-D array with shape ``(axes, samples)``.
        1-D inputs are rejected with a ``ValueError``.

    """
    if block.ndim != 2:
        raise ValueError(f"medfilt3 expects a 2-D (axes, samples) array, got ndim={block.ndim}")
    if block.shape[-1] < 3:
        return block
    stacked = np.stack([block[:, :-2], block[:, 1:-1], block[:, 2:]], axis=0)
    filtered = block.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        filtered[:, 1:-1] = np.nanmedian(stacked, axis=0)
    return filtered


def smooth_spectrum(amps: FloatArray, bins: int = 5) -> FloatArray:
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


def noise_floor(amps: FloatArray) -> float:
    """Compute the P20 noise floor, filtering non-finite and negative values.

    Returns ``0.0`` for empty or all-invalid inputs.  Delegates the
    actual percentile computation to
    :func:`~vibesensor.core.vibration_strength.noise_floor_amp_p20_g`.

    Pre-sorts the array so that when ``noise_floor_amp_p20_g`` strips the DC
    bin (index 0), it discards the global minimum amplitude, yielding a
    slightly more conservative (higher) floor estimate.  A single-element
    array returns that element directly since there is no minimum to strip.
    """
    if amps.size == 0:
        return 0.0
    finite = amps[np.isfinite(amps)]
    if finite.size == 0:
        return 0.0
    non_neg = finite[finite >= 0.0]
    if non_neg.size == 0:
        return 0.0
    sorted_non_neg = np.sort(non_neg).tolist()
    if len(sorted_non_neg) == 1:
        # noise_floor_amp_p20_g treats a single-element input as DC-only and
        # returns 0.0, which is correct for the full-spectrum context but not
        # here — the single value is a valid amplitude reading, not the DC
        # bias.  Return it directly so callers get a usable floor estimate.
        return float(sorted_non_neg[0])
    return float(noise_floor_amp_p20_g(combined_spectrum_amp_g=sorted_non_neg))


def float_list(values: FloatArray | list[float]) -> list[float]:
    """Convert an array-like to a plain Python ``list[float]``.

    Non-finite values (NaN, ±Inf) are replaced with ``0.0`` so downstream
    JSON serialisation never encounters them.
    """
    _isfinite = math.isfinite
    if isinstance(values, np.ndarray):
        return [float(v) if _isfinite(v) else 0.0 for v in values.ravel().tolist()]
    return [float(v) if _isfinite(v) else 0.0 for v in values]


def top_peaks(
    freqs: FloatArray,
    amps: FloatArray,
    *,
    top_n: int = 5,
    floor_ratio: float = PEAK_THRESHOLD_FLOOR_RATIO,
    smoothing_bins: int = 5,
) -> list[AxisPeak]:
    """Extract the *top_n* spectral peaks above the noise floor."""
    if freqs.size == 0 or amps.size == 0:
        return []
    smoothed = smooth_spectrum(amps, bins=smoothing_bins)
    floor_amp = noise_floor(smoothed)
    if not math.isfinite(floor_amp) or floor_amp < 0:
        floor_amp = 0.0
    threshold = max(floor_amp * max(1.1, floor_ratio), floor_amp + STRENGTH_EPSILON_MIN_G)

    # Vectorised interior-peak detection (replaces per-element Python loop).
    if smoothed.size > 2:
        interior = smoothed[1:-1]
        mask = (interior >= threshold) & (interior > smoothed[:-2]) & (interior >= smoothed[2:])
        peak_idx: list[int] = (np.flatnonzero(mask) + 1).tolist()
    else:
        peak_idx = []
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
    peaks: list[AxisPeak] = []
    for idx in peak_idx[:top_n]:
        raw_amp = float(amps[idx])
        peaks.append(
            {
                "hz": float(freqs[idx]),
                "amp": raw_amp,
                "snr_ratio": (
                    (raw_amp + STRENGTH_EPSILON_MIN_G) / (floor_amp + STRENGTH_EPSILON_MIN_G)
                ),
            },
        )
    return peaks


def compute_fft_spectrum(
    fft_block: FloatArray,
    sample_rate_hz: int,
    *,
    fft_window: FloatArray,
    fft_scale: float,
    freq_slice: FloatArray,
    valid_idx: IntIndexArray,
    spike_filter_enabled: bool = True,
) -> FftSpectrumResult:
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
        Normalisation scalar ``2 / max(1, sum(window))``.  The ``max(1, …)``
        guard prevents division-by-zero when the window sums to zero.
    freq_slice:
        Pre-computed frequency bins within the display range.
    valid_idx:
        Indices into the full FFT output that correspond to *freq_slice*.
    spike_filter_enabled:
        Whether to apply the 3-point median spike filter.

    Returns
    -------
    dict with keys: ``freq_slice``, ``spectrum_by_axis``,
    ``axis_amp_slices``, ``axis_amps``, ``combined_amp``,
    ``strength_metrics``, ``axis_peaks``.

    """
    if fft_block.ndim != 2 or fft_block.shape[0] != 3:
        raise ValueError(f"fft_block must have shape (3, N), got {fft_block.shape}")
    fft_n = fft_window.shape[0]
    if fft_block.shape[1] != fft_n:
        raise ValueError(
            f"fft_block column count {fft_block.shape[1]} does not match fft_window length {fft_n}",
        )
    if spike_filter_enabled:
        fft_block = medfilt3(fft_block)
    fft_block = fft_block - np.mean(fft_block, axis=1, keepdims=True)

    # Batch FFT: window and transform all axes in a single call instead of 3.
    windowed_all = fft_block * fft_window  # broadcasts (3, N) * (N,)
    specs_all = np.abs(np.fft.rfft(windowed_all, axis=1)).astype(np.float32)
    specs_all *= fft_scale
    if specs_all.shape[1] > 0:
        specs_all[:, 0] *= 0.5
    if (fft_n % 2) == 0 and specs_all.shape[1] > 1:
        specs_all[:, -1] *= 0.5

    spectrum_by_axis: SpectrumByAxis = {}
    axis_amp_slices: list[FloatArray] = []
    axis_amps: dict[str, FloatArray] = {}
    axis_peaks: dict[str, list[AxisPeak]] = {}

    for axis_idx, axis in enumerate(AXES):
        amp_slice = specs_all[axis_idx, valid_idx]
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

    combined_amp: FloatArray = np.empty(0, dtype=np.float32)
    strength_metrics: VibrationStrengthMetrics = empty_vibration_strength_metrics()
    if axis_amp_slices:
        combined_amp = np.asarray(
            combined_spectrum_amp_g(
                axis_spectra_amp_g=[float_list(amp_slice) for amp_slice in axis_amp_slices],
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
        "spectrum_by_axis": spectrum_by_axis,
        "axis_amp_slices": axis_amp_slices,
        "axis_amps": axis_amps,
        "combined_amp": combined_amp,
        "strength_metrics": strength_metrics,
        "axis_peaks": axis_peaks,
    }
