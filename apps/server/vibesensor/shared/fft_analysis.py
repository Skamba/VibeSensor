from __future__ import annotations

import math
import threading
from collections import OrderedDict
from threading import RLock
from typing import Literal, TypedDict

import numpy as np
import numpy.typing as npt
import pyfftw
from scipy import fft as scipy_fft
from scipy.signal import windows as signal_windows

from vibesensor.shared.constants.dsp import PEAK_BANDWIDTH_HZ, PEAK_SEPARATION_HZ
from vibesensor.shared.types.payload_types import AxisPeak
from vibesensor.vibration_strength import (
    VibrationStrengthMetrics,
    _combined_spectrum_amp_g_array,
    compute_vibration_strength_db,
    empty_vibration_strength_metrics,
)

__all__ = [
    "AXES",
    "Axis",
    "BoolArray",
    "FftWindowFunction",
    "FftSpectrumResult",
    "FloatArray",
    "IntIndexArray",
    "SpectralAnalysisComputer",
    "SpectrumAxisData",
    "SpectrumByAxis",
    "broadband_energy_ratio",
    "compute_fft_spectrum",
    "fft_frequency_slice",
    "fft_window_values",
    "float_list",
    "medfilt3",
    "noise_floor",
]

type FloatArray = npt.NDArray[np.float32]
type IntIndexArray = npt.NDArray[np.intp]
type BoolArray = npt.NDArray[np.bool_]
type FftWindowFunction = Literal["hann", "boxcar"]

Axis = Literal["x", "y", "z"]


class SpectrumAxisData(TypedDict):
    freq: FloatArray
    amp: FloatArray


type SpectrumByAxis = dict[str, SpectrumAxisData]


class FftSpectrumResult(TypedDict):
    freq_slice: FloatArray
    spectrum_by_axis: SpectrumByAxis
    combined_amp: FloatArray
    has_valid_analysis_bins: bool
    strength_metrics: VibrationStrengthMetrics
    strength_metrics_analytically_valid: bool
    axis_peaks: dict[Axis, list[AxisPeak]]


AXES: tuple[Axis, Axis, Axis] = ("x", "y", "z")

_FFT_CACHE_MAXSIZE = 64
_EMPTY_F32: FloatArray = np.array([], dtype=np.float32)
_EMPTY_BOOL: BoolArray = np.empty(0, dtype=np.bool_)

# pyFFTW plans own internal aligned I/O buffers and are not safe to call
# concurrently from multiple threads with the same buffer. The processing
# pipeline dispatches per-client FFTs across a worker pool, so we keep one
# plan per (axes_count, fft_n) per thread via ``threading.local``. The dict
# itself is guarded by a lock; plan construction is lazy on first use.
_PLAN_CACHE_LOCK = threading.Lock()
_PLAN_CACHE: dict[tuple[int, int], threading.local] = {}
_RFFT_PLAN_FLAGS = ("FFTW_ESTIMATE",)


def _get_rfft_plan(axes_count: int, fft_n: int) -> pyfftw.FFTW:
    """Return a thread-local FFTW rfft plan for shape ``(axes_count, fft_n)``."""
    key = (axes_count, fft_n)
    with _PLAN_CACHE_LOCK:
        tls = _PLAN_CACHE.get(key)
        if tls is None:
            tls = threading.local()
            _PLAN_CACHE[key] = tls
    plan = getattr(tls, "plan", None)
    if plan is None:
        input_array = pyfftw.empty_aligned((axes_count, fft_n), dtype=np.float32)
        output_array = pyfftw.empty_aligned(
            (axes_count, fft_n // 2 + 1),
            dtype=np.complex64,
        )
        plan = pyfftw.FFTW(
            input_array,
            output_array,
            axes=(1,),
            direction="FFTW_FORWARD",
            flags=_RFFT_PLAN_FLAGS,
            threads=1,
        )
        tls.plan = plan
    return plan


def _sanitize_float_array(values: FloatArray) -> FloatArray:
    return np.nan_to_num(
        values,
        copy=True,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    ).astype(np.float32, copy=False)


def fft_window_values(
    *,
    fft_n: int,
    window_function: FftWindowFunction = "hann",
) -> FloatArray:
    """Return FFT window coefficients for supported shared analysis windows."""

    if window_function == "hann":
        return np.asarray(signal_windows.hann(fft_n, sym=True), dtype=np.float32)
    if window_function == "boxcar":
        return np.ones(fft_n, dtype=np.float32)
    raise ValueError(f"unsupported FFT window_function={window_function!r}")


def fft_frequency_slice(
    *,
    fft_n: int,
    sample_rate_hz: int,
    spectrum_min_hz: float,
    spectrum_max_hz: float,
) -> tuple[FloatArray, IntIndexArray, BoolArray]:
    """Return shared frequency bins, valid indices, and strength mask."""

    if sample_rate_hz <= 0 or fft_n <= 0:
        return _EMPTY_F32, np.empty(0, dtype=np.intp), _EMPTY_BOOL
    freqs = scipy_fft.rfftfreq(fft_n, d=1.0 / float(sample_rate_hz))
    valid = (freqs >= spectrum_min_hz) & (freqs <= spectrum_max_hz)
    freq_slice = freqs[valid].astype(np.float32)
    valid_idx = np.flatnonzero(valid)
    strength_range_mask = np.ones(freq_slice.shape, dtype=np.bool_)
    return freq_slice, valid_idx, strength_range_mask


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
        "has_valid_analysis_bins": False,
        "strength_metrics": empty_vibration_strength_metrics(),
        "strength_metrics_analytically_valid": False,
        "axis_peaks": axis_peaks,
    }


def _axis_peaks_from_spectrum(
    *,
    freq_slice: FloatArray,
    amp_slice: FloatArray,
    strength_range_mask: BoolArray | None,
) -> list[AxisPeak]:
    if freq_slice.size == 0 or amp_slice.size == 0:
        return []
    strength_metrics = compute_vibration_strength_db(
        freq_hz=freq_slice,
        combined_spectrum_amp_g_values=amp_slice,
        peak_bandwidth_hz=PEAK_BANDWIDTH_HZ,
        peak_separation_hz=PEAK_SEPARATION_HZ,
        top_n=8,
        strength_range_mask=strength_range_mask,
    )
    floor_amp_g = float(strength_metrics["noise_floor_amp_g"])
    peaks: list[AxisPeak] = []
    for peak in strength_metrics["top_peaks"]:
        hz = float(peak["hz"])
        amp = float(peak["amp"])
        if hz <= 0.0 or amp <= 0.0:
            continue
        axis_peak: AxisPeak = {
            "hz": hz,
            "amp": amp,
        }
        if floor_amp_g > 0.0:
            axis_peak["snr_ratio"] = amp / floor_amp_g
        peaks.append(axis_peak)
    return peaks


def medfilt3(block: FloatArray) -> FloatArray:
    """Apply a 3-point median filter per-row (per-axis)."""
    if block.ndim != 2:
        raise ValueError(f"medfilt3 expects a 2-D (axes, samples) array, got ndim={block.ndim}")
    if block.shape[-1] < 3:
        return block
    filtered = block.copy()
    center = filtered[:, 1:-1]
    left = block[:, :-2]
    mid = block[:, 1:-1]
    right = block[:, 2:]

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


def noise_floor(amps: FloatArray) -> float:
    """Compute the P20 noise floor from the provided analysis-band amplitudes."""
    if amps.size == 0:
        return 0.0
    finite = amps[np.isfinite(amps)]
    if finite.size == 0:
        return 0.0
    non_neg = finite[finite >= 0.0]
    return float(np.quantile(non_neg, 0.20)) if non_neg.size else 0.0


def float_list(values: FloatArray | list[float]) -> list[float]:
    """Convert an array-like to a plain Python ``list[float]``."""
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
        return sanitized.ravel().tolist()
    return [float(v) if _isfinite(v) else 0.0 for v in values]


def broadband_energy_ratio(
    fft_block: FloatArray,
    *,
    top_bin_count: int = 3,
) -> float | None:
    """Return broadband energy share outside the strongest spectral bins."""

    if fft_block.ndim != 2 or fft_block.shape[1] < 8:
        return None
    sanitized = _sanitize_float_array(fft_block)
    centered = sanitized - np.mean(sanitized, axis=1, keepdims=True)
    spectrum = scipy_fft.rfft(centered, axis=1)
    magnitude = np.abs(spectrum).astype(np.float64, copy=False)
    power_by_bin = np.sum(magnitude * magnitude, axis=0)
    if power_by_bin.size <= 1:
        return None
    power = power_by_bin[1:]
    total_power = float(np.sum(power))
    if not math.isfinite(total_power) or total_power <= 1e-18:
        return None
    top_count = min(max(1, top_bin_count), power.size)
    top_power = float(np.sum(np.partition(power, -top_count)[-top_count:]))
    if not math.isfinite(top_power):
        return None
    return max(0.0, min(1.0, 1.0 - (top_power / total_power)))


def compute_fft_spectrum(
    fft_block: FloatArray,
    sample_rate_hz: int,
    *,
    fft_window: FloatArray,
    fft_scale: float,
    freq_slice: FloatArray,
    valid_idx: IntIndexArray,
    strength_range_mask: BoolArray | None = None,
    spike_filter_enabled: bool = True,
) -> FftSpectrumResult:
    """Compute per-axis and combined FFT spectra from a sample block."""
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

    plan = _get_rfft_plan(fft_block.shape[0], fft_n)
    np.multiply(fft_block, fft_window, out=plan.input_array)
    plan()
    specs_all: FloatArray = np.abs(plan.output_array)
    specs_all *= fft_scale
    if specs_all.shape[1] > 0:
        specs_all[:, 0] *= 0.5
    if (fft_n % 2) == 0 and specs_all.shape[1] > 1:
        specs_all[:, -1] *= 0.5

    spectrum_by_axis: SpectrumByAxis = {}
    axis_peaks: dict[Axis, list[AxisPeak]] = {}

    for axis_idx, axis in enumerate(AXES):
        amp_slice = specs_all[axis_idx, valid_idx]
        spectrum_by_axis[axis] = {
            "freq": freq_slice,
            "amp": amp_slice,
        }
        axis_peaks[axis] = _axis_peaks_from_spectrum(
            freq_slice=freq_slice,
            amp_slice=amp_slice,
            strength_range_mask=strength_range_mask,
        )

    combined_amp: FloatArray = np.empty(0, dtype=np.float32)
    strength_metrics: VibrationStrengthMetrics = empty_vibration_strength_metrics()
    has_valid_analysis_bins = freq_slice.size > 0
    if spectrum_by_axis:
        amp_slices = [spectrum_by_axis[axis]["amp"] for axis in spectrum_by_axis]
        combined_amp = _combined_spectrum_amp_g_array(
            axis_spectra_amp_g=amp_slices,
            axis_count_for_mean=len(amp_slices),
        ).astype(
            np.float32,
            copy=False,
        )
        strength_metrics = compute_vibration_strength_db(
            freq_hz=freq_slice,
            combined_spectrum_amp_g_values=combined_amp,
            peak_bandwidth_hz=PEAK_BANDWIDTH_HZ,
            peak_separation_hz=PEAK_SEPARATION_HZ,
            top_n=8,
            strength_range_mask=strength_range_mask,
        )
    return {
        "freq_slice": freq_slice,
        "spectrum_by_axis": spectrum_by_axis,
        "combined_amp": combined_amp,
        "has_valid_analysis_bins": has_valid_analysis_bins,
        "strength_metrics": strength_metrics,
        "strength_metrics_analytically_valid": has_valid_analysis_bins,
        "axis_peaks": axis_peaks,
    }


class SpectralAnalysisComputer:
    """Reusable FFT cache/window state for deterministic spectrum computations."""

    def __init__(
        self,
        *,
        fft_n: int,
        spectrum_min_hz: float,
        spectrum_max_hz: float,
    ) -> None:
        self._fft_n = int(fft_n)
        self._spectrum_min_hz = float(spectrum_min_hz)
        self._spectrum_max_hz = float(spectrum_max_hz)
        self.fft_window = fft_window_values(fft_n=self._fft_n)
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
            freq_slice, valid_idx, strength_range_mask = fft_frequency_slice(
                fft_n=self._fft_n,
                sample_rate_hz=sample_rate_hz,
                spectrum_min_hz=self._spectrum_min_hz,
                spectrum_max_hz=self._spectrum_max_hz,
            )
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
