"""Pure spectral-analysis functions used by the signal processor.

All functions in this module are stateless: they take arrays (and scalar
parameters) and return results without touching any shared mutable state.
This makes them independently testable and reusable outside of the
:class:`~vibesensor.infra.processing.processor.SignalProcessor` class.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from vibesensor.infra.processing.models import Axis, AxisPeak, FftSpectrumResult, SpectrumByAxis
from vibesensor.shared.constants.dsp import PEAK_BANDWIDTH_HZ, PEAK_SEPARATION_HZ
from vibesensor.vibration_strength import (
    VibrationStrengthMetrics,
    combined_spectrum_amp_g,
    compute_vibration_strength_db,
    empty_vibration_strength_metrics,
)

AXES: tuple[Axis, Axis, Axis] = ("x", "y", "z")

type FloatArray = npt.NDArray[np.float32]
type IntIndexArray = npt.NDArray[np.intp]


def _sanitize_float_array(values: FloatArray) -> FloatArray:
    return np.nan_to_num(
        values,
        copy=True,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    ).astype(np.float32, copy=False)


def _empty_fft_spectrum_result(freq_slice: FloatArray) -> FftSpectrumResult:
    empty_amp = np.empty(0, dtype=np.float32)
    spectrum_by_axis: SpectrumByAxis = {}
    axis_peaks: dict[Axis, list[AxisPeak]] = {}
    for axis in AXES:
        spectrum_by_axis[axis] = {
            "freq": freq_slice,
            "amp": empty_amp.copy(),
        }
        axis_peaks[axis] = []
    return {
        "freq_slice": freq_slice,
        "spectrum_by_axis": spectrum_by_axis,
        "combined_amp": empty_amp,
        "strength_metrics": empty_vibration_strength_metrics(),
        "axis_peaks": axis_peaks,
    }


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
    filtered = block.copy()
    center = filtered[:, 1:-1]
    left = block[:, :-2]
    mid = block[:, 1:-1]
    right = block[:, 2:]

    # Fast path for the common all-finite case: one scratch array + fixed-size
    # pairwise min/max avoids the large transient stack that ``np.nanmedian``
    # would allocate for a three-sample window.
    scratch = np.empty_like(center)
    np.minimum(left, mid, out=scratch)
    np.maximum(left, mid, out=center)
    np.minimum(center, right, out=center)
    np.maximum(scratch, center, out=center)
    if not np.any(np.isnan(block)):
        return filtered

    left_valid = ~np.isnan(left)
    mid_valid = ~np.isnan(mid)
    right_valid = ~np.isnan(right)

    missing_left = ~left_valid & mid_valid & right_valid
    center[missing_left] = (mid[missing_left] + right[missing_left]) * np.float32(0.5)

    missing_mid = left_valid & ~mid_valid & right_valid
    center[missing_mid] = (left[missing_mid] + right[missing_mid]) * np.float32(0.5)

    missing_right = left_valid & mid_valid & ~right_valid
    center[missing_right] = (left[missing_right] + mid[missing_right]) * np.float32(0.5)

    only_left = left_valid & ~mid_valid & ~right_valid
    center[only_left] = left[only_left]

    only_mid = ~left_valid & mid_valid & ~right_valid
    center[only_mid] = mid[only_mid]

    only_right = ~left_valid & ~mid_valid & right_valid
    center[only_right] = right[only_right]

    all_invalid = ~left_valid & ~mid_valid & ~right_valid
    center[all_invalid] = np.nan
    return _sanitize_float_array(filtered)


def smooth_spectrum(amps: FloatArray, bins: int = 5) -> FloatArray:
    """Smooth a spectrum using a sliding-average convolution kernel."""
    if amps.size == 0:
        return amps
    sanitized = _sanitize_float_array(amps)
    width = max(1, int(bins))
    if width <= 1:
        return sanitized
    if (width % 2) == 0:
        width += 1
    if sanitized.size < width:
        return sanitized
    kernel = np.ones(width, dtype=np.float32) / np.float32(width)
    half = width // 2
    padded = np.pad(sanitized, (half, half), mode="edge")
    return np.convolve(padded, kernel, mode="valid").astype(np.float32)


def noise_floor(amps: FloatArray) -> float:
    """Compute the P20 noise floor from the provided analysis-band amplitudes.

    The caller already provides a frequency-ordered spectrum slice, so this
    helper must not skip index 0 or delegate to helpers that assume DC is still
    present there. It simply filters invalid values and computes the 20th
    percentile of the remaining non-negative amplitudes.
    """
    if amps.size == 0:
        return 0.0
    finite = amps[np.isfinite(amps)]
    if finite.size == 0:
        return 0.0
    non_neg = finite[finite >= 0.0]
    return float(np.quantile(non_neg, 0.20)) if non_neg.size else 0.0


def float_list(values: FloatArray | list[float]) -> list[float]:
    """Convert an array-like to a plain Python ``list[float]``.

    Non-finite values (NaN, ±Inf) are replaced with ``0.0`` so downstream
    JSON serialisation never encounters them.
    """
    _isfinite = math.isfinite
    if isinstance(values, np.ndarray):
        if np.all(np.isfinite(values)):
            return values.ravel().tolist()
        sanitized: FloatArray = np.nan_to_num(
            values,
            copy=True,
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )
        result: list[float] = sanitized.ravel().tolist()
        return result
    return [float(v) if _isfinite(v) else 0.0 for v in values]


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
    ``combined_amp``, ``strength_metrics``, ``axis_peaks``.

    """
    if fft_block.ndim != 2 or fft_block.shape[0] != 3:
        raise ValueError(f"fft_block must have shape (3, N), got {fft_block.shape}")
    fft_n = fft_window.shape[0]
    if fft_block.shape[1] != fft_n:
        raise ValueError(
            f"fft_block column count {fft_block.shape[1]} does not match fft_window length {fft_n}",
        )
    if fft_n == 0:
        return _empty_fft_spectrum_result(freq_slice)
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
    axis_peaks: dict[Axis, list[AxisPeak]] = {}

    for axis_idx, axis in enumerate(AXES):
        amp_slice = specs_all[axis_idx, valid_idx]
        axis_peaks[axis] = []
        spectrum_by_axis[axis] = {
            "freq": freq_slice,
            "amp": amp_slice,
        }

    combined_amp: FloatArray = np.empty(0, dtype=np.float32)
    strength_metrics: VibrationStrengthMetrics = empty_vibration_strength_metrics()
    if spectrum_by_axis:
        amp_slices = [spectrum_by_axis[axis]["amp"] for axis in spectrum_by_axis]
        combined_amp = np.asarray(
            combined_spectrum_amp_g(
                axis_spectra_amp_g=amp_slices,
                axis_count_for_mean=len(amp_slices),
            ),
            dtype=np.float32,
        )
        strength_metrics = compute_vibration_strength_db(
            freq_hz=freq_slice,
            combined_spectrum_amp_g_values=combined_amp,
            peak_bandwidth_hz=PEAK_BANDWIDTH_HZ,
            peak_separation_hz=PEAK_SEPARATION_HZ,
            top_n=8,
        )

    return {
        "freq_slice": freq_slice,
        "spectrum_by_axis": spectrum_by_axis,
        "combined_amp": combined_amp,
        "strength_metrics": strength_metrics,
        "axis_peaks": axis_peaks,
    }
