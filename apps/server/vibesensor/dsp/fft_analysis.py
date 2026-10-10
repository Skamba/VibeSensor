from __future__ import annotations

import math
import sys
import threading
from collections import OrderedDict
from collections.abc import Sequence
from threading import RLock
from typing import TYPE_CHECKING, Literal, TypedDict, cast

import numpy as np
import numpy.typing as npt

from vibesensor.dsp.constants import (
    FFT_MIN_WINDOW_COVERAGE,
    PEAK_BANDWIDTH_HZ,
    PEAK_SEPARATION_HZ,
)
from vibesensor.dsp.vibration_strength import (
    VibrationStrengthMetrics,
    _combined_spectrum_amp_g_array,
    compute_vibration_strength_db,
    compute_vibration_strength_rows,
    empty_vibration_strength_metrics,
)
from vibesensor.dsp.window_spectrum import WindowSpectrum
from vibesensor.live.payload_types import AxisPeak

if TYPE_CHECKING:
    from types import ModuleType

    import pyfftw

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
    "axis_peaks_from_spectrum",
    "SpectrumByAxis",
    "combined_spectrum",
    "combined_spectra",
    "combined_strength_metrics",
    "compute_fft_spectrum",
    "fft_frequency_slice",
    "fft_window_values",
    "fill_lost_samples",
    "float_list",
    "present_centre",
]

type FloatArray = npt.NDArray[np.float32]
type IntIndexArray = npt.NDArray[np.intp]
type BoolArray = npt.NDArray[np.bool_]
type FftWindowFunction = Literal["hann", "boxcar"]

Axis = Literal["x", "y", "z"]

# The combined spectrum's ranked peaks, live and in the post-stop replay.
_COMBINED_TOP_N = 8


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


_PYFFTW_IMPORT_LOCK = threading.Lock()


def _import_pyfftw() -> ModuleType:
    """Import pyfftw without the scipy interfaces it would otherwise load.

    pyfftw's package imports ``pyfftw.interfaces``, which imports
    ``scipy.fftpack`` and ``scipy.fft`` (and with them scipy.special,
    scipy.linalg, numpy.testing, ...) when scipy is installed, only to offer
    drop-in scipy FFT functions. This module uses ``pyfftw.FFTW`` alone, and
    nothing else in the server imports scipy. A ``None`` entry in
    ``sys.modules`` makes that optional import fail, so pyfftw skips them:
    about 30 MB less resident and over a second less on the first FFT on the
    Pi. The entry is removed again, so a later ``import scipy.fftpack`` works.
    """
    with _PYFFTW_IMPORT_LOCK:
        loaded = sys.modules.get("pyfftw")
        if loaded is not None:
            return loaded
        block = "scipy.fftpack" not in sys.modules
        if block:
            sys.modules["scipy.fftpack"] = None  # type: ignore[assignment]
        try:
            import pyfftw
        finally:
            if block and sys.modules.get("scipy.fftpack", ...) is None:
                del sys.modules["scipy.fftpack"]
        return cast("ModuleType", pyfftw)


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
        # Imported on the first FFT, not at server start.
        pyfftw = _import_pyfftw()

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


def fft_window_values(
    *,
    fft_n: int,
    window_function: FftWindowFunction = "hann",
) -> FloatArray:
    """Return FFT window coefficients for supported shared analysis windows."""

    if window_function == "hann":
        # Symmetric Hann, computed like scipy.signal.windows.hann(fft_n, sym=True)
        # without importing scipy.signal (seconds of start-up time on the Pi).
        if fft_n <= 1:
            return np.ones(max(fft_n, 0), dtype=np.float32)
        window = np.full(fft_n, 0.5)
        window += 0.5 * np.cos(np.linspace(-np.pi, np.pi, fft_n))
        return window.astype(np.float32)
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
    freqs = np.fft.rfftfreq(fft_n, d=1.0 / float(sample_rate_hz))
    valid = (freqs >= spectrum_min_hz) & (freqs <= spectrum_max_hz)
    freq_slice = freqs[valid].astype(np.float32)
    valid_idx = np.flatnonzero(valid)
    strength_range_mask = np.ones(freq_slice.shape, dtype=np.bool_)
    return freq_slice, valid_idx, strength_range_mask


def _empty_fft_spectrum_result(freq_slice: FloatArray) -> FftSpectrumResult:
    empty_amp = np.empty(0, dtype=np.float32)
    spectrum_by_axis: SpectrumByAxis = {}
    for axis in AXES:
        spectrum_by_axis[axis] = {
            "freq": freq_slice,
            "amp": empty_amp.copy(),
        }
    return {
        "freq_slice": freq_slice,
        "spectrum_by_axis": spectrum_by_axis,
        "combined_amp": empty_amp,
        "has_valid_analysis_bins": False,
        "strength_metrics": empty_vibration_strength_metrics(),
        "strength_metrics_analytically_valid": False,
    }


def axis_peaks_from_spectrum(*, freq_slice: FloatArray, amp_slice: FloatArray) -> list[AxisPeak]:
    """The strength peaks of one axis's spectrum, with their ratio to its noise floor.

    Computed only when a summary row asks which axis carries the dominant peak
    (``dominant_axis``), not on every live tick: it costs as much as the
    combined spectrum's strength.
    """
    if freq_slice.size == 0 or amp_slice.size == 0:
        return []
    strength_metrics = compute_vibration_strength_db(
        freq_hz=freq_slice,
        combined_spectrum_amp_g_values=amp_slice,
        peak_bandwidth_hz=PEAK_BANDWIDTH_HZ,
        peak_separation_hz=PEAK_SEPARATION_HZ,
        top_n=8,
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


def fill_lost_samples(fft_block: FloatArray, fft_window: FloatArray) -> FloatArray | None:
    """Fill the lost samples (NaN) of a ``(3, N)`` FFT block.

    A frame lost on the way leaves its time in the block, so the block spans
    exactly its stated time and a tone keeps its phase across the gap: its peak
    stays on its frequency at the block's time. Lost samples take each axis's
    mean over the samples present, which the FFT removes. The rest is scaled by
    the window energy lost, so the spectrum keeps the signal's power (its noise
    floor exactly; a tone's level to within a few percent). ``None`` when the
    samples present carry under ``FFT_MIN_WINDOW_COVERAGE`` of the window's
    energy.
    """
    lost = np.isnan(fft_block).any(axis=0)
    if not lost.any():
        return fft_block
    energy = np.square(fft_window, dtype=np.float64)
    coverage = float(np.sum(energy[~lost])) / max(float(np.sum(energy)), 1e-12)
    if coverage < FFT_MIN_WINDOW_COVERAGE:
        return None
    mean = np.nanmean(fft_block, axis=1, keepdims=True)
    present = mean + (fft_block - mean) / np.float32(np.sqrt(coverage))
    return np.where(lost, mean, present).astype(np.float32, copy=False)


def present_centre(lost: BoolArray, fft_window: FloatArray) -> float:
    """Where an FFT block's samples present weigh in, in samples from its start.

    Their centroid under the window's energy, which a lost frame pulls away
    from the block's middle (``len(fft_window) / 2`` when none was lost): while
    a tone's frequency changes, the block's peak sits at its frequency there.
    """
    energy = np.square(fft_window, dtype=np.float64) * ~lost
    total = float(np.sum(energy))
    if total <= 0.0:
        return len(fft_window) / 2.0
    return float(np.sum(energy * (np.arange(fft_window.shape[0]) + 0.5))) / total


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


def compute_fft_spectrum(
    fft_block: FloatArray,
    sample_rate_hz: int,
    *,
    fft_window: FloatArray,
    fft_scale: float,
    freq_slice: FloatArray,
    valid_idx: IntIndexArray,
    strength_range_mask: BoolArray | None = None,
) -> FftSpectrumResult:
    """Compute per-axis and combined FFT spectra from a sample block."""
    specs_all = _amplitude_spectra(
        fft_block,
        fft_window=fft_window,
        fft_scale=fft_scale,
    )
    if specs_all is None:
        return _empty_fft_spectrum_result(freq_slice)

    spectrum_by_axis: SpectrumByAxis = {}
    for axis_idx, axis in enumerate(AXES):
        spectrum_by_axis[axis] = {
            "freq": freq_slice,
            "amp": specs_all[axis_idx, valid_idx],
        }

    combined_amp, strength_metrics = _combined_strength_metrics(
        freq_slice=freq_slice,
        amp_slices=[spectrum_by_axis[axis]["amp"] for axis in spectrum_by_axis],
        strength_range_mask=strength_range_mask,
    )
    has_valid_analysis_bins = freq_slice.size > 0
    return {
        "freq_slice": freq_slice,
        "spectrum_by_axis": spectrum_by_axis,
        "combined_amp": combined_amp,
        "has_valid_analysis_bins": has_valid_analysis_bins,
        "strength_metrics": strength_metrics,
        "strength_metrics_analytically_valid": has_valid_analysis_bins,
    }


def combined_spectrum(
    fft_block: FloatArray,
    *,
    fft_window: FloatArray,
    fft_scale: float,
    freq_slice: FloatArray,
    valid_idx: IntIndexArray,
) -> WindowSpectrum | None:
    """The block's combined spectrum, as ``compute_fft_spectrum`` has it.

    Skips the per-axis peak search, for callers that read only the combined
    spectrum (post-stop raw replay). ``None`` when there are no analysis bins.
    """
    specs_all = _amplitude_spectra(
        fft_block,
        fft_window=fft_window,
        fft_scale=fft_scale,
    )
    if specs_all is None or freq_slice.size == 0:
        return None
    return WindowSpectrum(
        freq_hz=freq_slice,
        amp_g=_combined_amp([specs_all[axis_idx, valid_idx] for axis_idx in range(len(AXES))]),
    )


def combined_spectra(
    blocks: npt.NDArray[np.float32],
    *,
    fft_window: FloatArray,
    fft_scale: float,
    valid_idx: IntIndexArray,
    means: FloatArray | None = None,
) -> FloatArray:
    """Each ``(3, N)`` block's combined spectrum amplitude, bit for bit ``combined_spectrum``'s.

    Of the block in C order, as live hands it over: the mean's summation
    order, and so its last bit, follows the memory layout.

    *blocks* is ``(k, 3, N)`` and is overwritten; *means* is its
    ``np.mean(blocks, axis=2, keepdims=True)`` where the caller has it. The k
    blocks' 3k axes go through one FFT plan and every step runs over all of
    them at once: a fraction of the per-call cost of one block at a time, and
    most of the work runs with the GIL released, beside a thread running
    Python (post-stop raw replay).
    Returns ``(k, valid_idx.size)``; *valid_idx* must be a contiguous run.
    """
    if blocks.ndim != 3 or blocks.shape[1] != len(AXES):
        raise ValueError(f"blocks must have shape (k, 3, N), got {blocks.shape}")
    count, fft_n = blocks.shape[0], fft_window.shape[0]
    if blocks.shape[2] != fft_n:
        raise ValueError(
            f"blocks column count {blocks.shape[2]} does not match fft_window length {fft_n}",
        )
    if valid_idx.size == 0 or count == 0:
        return np.empty((count, valid_idx.size), dtype=np.float32)
    first, stop = int(valid_idx[0]), int(valid_idx[-1]) + 1
    if stop - first != valid_idx.size:
        raise ValueError("valid_idx must be a contiguous run of bins")
    blocks -= np.mean(blocks, axis=2, keepdims=True) if means is None else means
    plan = _get_rfft_plan(count * len(AXES), fft_n)
    np.multiply(blocks.reshape(count * len(AXES), fft_n), fft_window, out=plan.input_array)
    plan()
    # The steps of ``_amplitude_spectra`` and ``_combined_amp``, on the analysis
    # bins only, in place where they can be.
    amp: FloatArray = np.abs(plan.output_array[:, first:stop])
    amp *= fft_scale
    if first == 0:
        amp[:, 0] *= 0.5
    if (fft_n % 2) == 0 and stop == plan.output_array.shape[1] and plan.output_array.shape[1] > 1:
        amp[:, -1] *= 0.5
    if not np.isfinite(amp).all():
        amp = np.where(np.isfinite(amp), amp, np.float32(0.0))
    # Squared in float64 straight from float32 (exact widening), one pass.
    axes = np.square(amp, dtype=np.float64).reshape(count, len(AXES), stop - first)
    # The axes summed in order, as ``np.sum`` over that axis.
    combined = np.add(axes[:, 0], axes[:, 1])
    combined += axes[:, 2]
    combined /= float(len(AXES))
    return np.sqrt(combined, out=combined).astype(np.float32)


def combined_strength_metrics(
    spectra: Sequence[WindowSpectrum],
    *,
    strength_range_mask: BoolArray | None = None,
) -> list[VibrationStrengthMetrics]:
    """Each combined spectrum's strength metrics, as ``compute_fft_spectrum`` has them.

    All at once (``compute_vibration_strength_rows``): the spectra share their bins.
    """
    if not spectra:
        return []
    return compute_vibration_strength_rows(
        freq_hz=spectra[0].freq_hz,
        spectra=np.stack([spectrum.amp_g for spectrum in spectra]),
        peak_bandwidth_hz=PEAK_BANDWIDTH_HZ,
        peak_separation_hz=PEAK_SEPARATION_HZ,
        top_n=_COMBINED_TOP_N,
        strength_range_mask=strength_range_mask,
    )


def _amplitude_spectra(
    fft_block: FloatArray,
    *,
    fft_window: FloatArray,
    fft_scale: float,
) -> FloatArray | None:
    """Single-sided per-axis amplitude spectra (g) of a ``(3, N)`` block; ``None`` when N is 0."""
    if fft_block.ndim != 2 or fft_block.shape[0] != 3:
        raise ValueError(f"fft_block must have shape (3, N), got {fft_block.shape}")
    fft_n = fft_window.shape[0]
    if fft_block.shape[1] != fft_n:
        raise ValueError(
            f"fft_block column count {fft_block.shape[1]} does not match fft_window length {fft_n}",
        )
    if fft_n == 0:
        return None
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
    return specs_all


def _combined_amp(amp_slices: list[FloatArray]) -> FloatArray:
    return _combined_spectrum_amp_g_array(
        axis_spectra_amp_g=amp_slices,
        axis_count_for_mean=len(amp_slices),
    ).astype(
        np.float32,
        copy=False,
    )


def _combined_strength_metrics(
    *,
    freq_slice: FloatArray,
    amp_slices: list[FloatArray],
    strength_range_mask: BoolArray | None,
) -> tuple[FloatArray, VibrationStrengthMetrics]:
    combined_amp = _combined_amp(amp_slices)
    strength_metrics = compute_vibration_strength_db(
        freq_hz=freq_slice,
        combined_spectrum_amp_g_values=combined_amp,
        peak_bandwidth_hz=PEAK_BANDWIDTH_HZ,
        peak_separation_hz=PEAK_SEPARATION_HZ,
        top_n=_COMBINED_TOP_N,
        strength_range_mask=strength_range_mask,
    )
    return combined_amp, strength_metrics


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

    def strength_range_mask(self, sample_rate_hz: int) -> BoolArray:
        _, _, strength_range_mask = self._fft_cache_entry(sample_rate_hz)
        return strength_range_mask

    def combined_spectrum(
        self,
        fft_block: FloatArray,
        sample_rate_hz: int,
    ) -> WindowSpectrum | None:
        freq_slice, valid_idx, _strength_range_mask = self._fft_cache_entry(sample_rate_hz)
        return combined_spectrum(
            fft_block,
            fft_window=self.fft_window,
            fft_scale=self.fft_scale,
            freq_slice=freq_slice,
            valid_idx=valid_idx,
        )

    def combined_spectra(
        self,
        blocks: npt.NDArray[np.float32],
        sample_rate_hz: int,
        *,
        means: FloatArray | None = None,
    ) -> FloatArray | None:
        """``combined_spectrum`` of each ``(3, N)`` block of *blocks* (overwritten), as rows.

        Their bins are ``freq_slice(sample_rate_hz)``; ``None`` when there are
        none. *means* as for ``combined_spectra``.
        """
        freq_slice, valid_idx, _strength_range_mask = self._fft_cache_entry(sample_rate_hz)
        if freq_slice.size == 0:
            return None
        return combined_spectra(
            blocks,
            fft_window=self.fft_window,
            fft_scale=self.fft_scale,
            valid_idx=valid_idx,
            means=means,
        )

    def freq_slice(self, sample_rate_hz: int) -> FloatArray:
        """The analysis bins' frequencies at *sample_rate_hz*."""
        freq_slice, _valid_idx, _strength_range_mask = self._fft_cache_entry(sample_rate_hz)
        return freq_slice

    def combined_strength_metrics(
        self,
        spectra: Sequence[WindowSpectrum],
        sample_rate_hz: int,
    ) -> list[VibrationStrengthMetrics]:
        """The strength metrics of *spectra*, combined spectra at *sample_rate_hz*."""
        return combined_strength_metrics(
            spectra, strength_range_mask=self.strength_range_mask(sample_rate_hz)
        )

    def compute_fft_spectrum(
        self,
        fft_block: FloatArray,
        sample_rate_hz: int,
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
        )
