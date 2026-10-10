"""One analysis window's combined amplitude spectrum, kept for the post-stop order tracking."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from math import hypot, sqrt
from typing import cast

import numpy as np
import numpy.typing as npt

from vibesensor.dsp.constants import PEAK_BANDWIDTH_HZ

__all__ = [
    "LineRead",
    "SpectraByRows",
    "WindowSpectrum",
    "line_half_width_hz",
    "line_reach_hz",
    "line_reads",
    "peak_band_bins",
    "peak_scale_g",
    "spectra_by_rows",
    "tone_line_level_g",
]

# A Hann window spreads a steady tone over its main lobe, two bins either side
# of the tone's nearest bin: 99.95 % of its power whatever its offset from the
# bin centre.
_MAIN_LOBE_BINS = 2
# The floor a line is compared with is read in this many bins either side, just
# past its band: enough to place the floor's bend under a broad resonance, few
# enough to sit on the same stretch of it.
_FLANK_BINS = 3
# A steady tone's power over a Hann window's bins is its peak amplitude squared
# times the window's equivalent noise bandwidth, 1.5 bins (Harris, *Proc. IEEE*
# 66(1), 1978).
_HANN_ENBW_BINS = 1.5


def peak_band_bins(bin_hz: float) -> int:
    """The bins of a peak's band: its centre bin and ``PEAK_BANDWIDTH_HZ`` either side."""
    return 2 * int(PEAK_BANDWIDTH_HZ / bin_hz + 1e-9) + 1


def line_half_width_hz(
    predicted_hz: float, speed_kmh: float | None, rate_kmh_per_s: float, window_s: float
) -> float:
    """How far an order's line sweeps either side of its centre within one window.

    A speed-following order moves with the speed: braking from 100 km/h at
    5 m/s² sweeps it 46 % over a 2.56 s window, smearing it over many bins.
    The read takes in the whole sweep.
    """
    if speed_kmh is None or speed_kmh <= 0:
        return 0.0
    return predicted_hz * abs(rate_kmh_per_s) * window_s / (2.0 * speed_kmh)


def line_reach_hz[Hz: (float, npt.NDArray[np.float64])](half_width_hz: Hz, bin_hz: float) -> Hz:
    """How far either side of a line's centre its read takes in: the band and the flanks past it.

    Of one line, or of each of an array of lines.
    """
    return half_width_hz + (_MAIN_LOBE_BINS + _FLANK_BINS) * bin_hz


def peak_scale_g(level_g: float, floor_g: float) -> float:
    """The band RMS a ranked peak of an order at *level_g* reads on a floor *floor_g*.

    A line read is the order alone (``LineRead.excess``); a peak's band holds
    the floor under it as well, so in power the two add. A finding's strength
    (dB over its window's floor) and its 8 dB negligible edge are on a peak's
    scale: an order read at its line at 2.3 times the floor stands 8 dB over
    it as a peak, 7.2 dB as its level alone.
    """
    return hypot(level_g, floor_g)


def tone_line_level_g(peak_g: float, bin_hz: float, *, axes: int = 3) -> float:
    """The level line reads give a steady tone of peak amplitude *peak_g* on one axis.

    The combined spectrum is the RMS over *axes* axes, so the tone's power
    there is ``peak_g² / axes`` times the window's 1.5 bins, and a read spreads
    it over a peak band's bins (``LineRead.excess``): about 0.27 of the peak at
    800 Hz and 2048 samples. A tone at the same peak on every axis reads
    ``sqrt(axes)`` times more.
    """
    return peak_g * sqrt(_HANN_ENBW_BINS / (axes * peak_band_bins(bin_hz)))


@dataclass(frozen=True, slots=True)
class LineRead:
    """One window's power at an order's line over the floor beside it (g²).

    ``excess`` is the power in the line's band (the window's main lobe about
    it, widened by the band its frequency swept through in the window) above
    the local floor, per bin of a peak's band: a steady tone's ``excess`` is
    its peak level squared (band RMS, ``PEAK_BANDWIDTH_HZ``) over the floor,
    and a swept one's adds up the same way. The floor under the band follows
    a parabola through the few bins either side of it, so a body resonance
    the line sits on is not read as the order. ``flanks`` is the local floor,
    the mean power per bin of those bins. ``excess`` comes out below zero in
    a window where the order is absent about as often as above: it is meant
    to be judged over many windows.
    """

    excess: float
    flanks: float


@dataclass(frozen=True, slots=True, eq=False)
class WindowSpectrum:
    """The combined spectrum of one replayed window (``sqrt(mean(axis_amp²))``, g).

    Held in memory only, beside the window's ranked peaks: order tracking reads
    an order's level at its own frequency from it, whatever louder content
    the window has elsewhere ("Order-tracked reads" in docs/order_tracking.md).
    ``freq_hz`` is shared by every window of one sample rate.
    """

    freq_hz: npt.NDArray[np.float32]
    amp_g: npt.NDArray[np.float32]
    # Where the post-stop replay keeps a sample rate's spectra together:
    # ``amp_g`` is row ``row`` of ``rows``, so ``line_reads`` gathers many
    # windows' bands in one step. ``None`` for a spectrum on its own.
    rows: npt.NDArray[np.float32] | None = None
    row: int = 0

    @property
    def bin_hz(self) -> float:
        return float(self.freq_hz[1] - self.freq_hz[0]) if self.freq_hz.size > 1 else 0.0

    def line_read(self, hz: float, half_width_hz: float) -> LineRead | None:
        """The power in the band about a line at *hz* swept over ``±half_width_hz``, and beside it.

        The band is the sweep plus the window's main lobe either side. At the
        ends of the spectrum the flanks are the bins on the side that has them.
        ``None`` when the band, or both flanks, fall outside it.
        """
        freq = self.freq_hz
        size = freq.size
        if size < 2:
            return None
        start, bin_hz = float(freq[0]), self.bin_hz
        centre = int(round((hz - start) / bin_hz))
        half = int(round(half_width_hz / bin_hz)) + _MAIN_LOBE_BINS
        if centre - half < 0 or centre + half >= size:
            return None
        # The band and its flanks are a few bins: plain floats are faster than numpy here.
        bins = 2 * half + 1
        first = max(0, centre - half - _FLANK_BINS)
        power = [amp * amp for amp in self.amp_g[first : centre + half + 1 + _FLANK_BINS].tolist()]
        lower = power[: centre - half - first]
        upper = power[centre - half - first + bins :]
        if max(len(lower), len(upper)) < _FLANK_BINS:
            return None
        flanks = sum(lower + upper) / (len(lower) + len(upper))
        band = sum(power[centre - half - first : centre - half - first + bins])
        under = bins * flanks
        if len(lower) == len(upper):
            # The floor bends under a resonance: fit a + c x^2 through the flanks
            # (paired by distance x from the centre) and sum it over the band.
            distance = [float(half + 1 + offset) ** 2 for offset in range(_FLANK_BINS)]
            paired = [0.5 * (low + up) for low, up in zip(reversed(lower), upper, strict=True)]
            mean_distance = sum(distance) / _FLANK_BINS
            mean_paired = sum(paired) / _FLANK_BINS
            spread = [value - mean_distance for value in distance]
            bend = sum(
                step * (value - mean_paired) for step, value in zip(spread, paired, strict=True)
            ) / sum(step * step for step in spread)
            level = mean_paired - bend * mean_distance
            # The sum of x^2 over the band's offsets -half..half.
            under = bins * level + bend * half * (half + 1) * (2 * half + 1) / 3.0
        excess = (band - under) / peak_band_bins(bin_hz)
        return LineRead(excess=excess, flanks=flanks)


# Reads gathered at once in ``line_reads``: a few MB of float64 at most.
_READS_PER_STACK = 4096


@dataclass(frozen=True, slots=True)
class SpectraByRows:
    """Spectra (``None`` where there is none), with where each is kept as a row.

    Each spectrum's group (the array its row is kept in, ``WindowSpectrum.rows``;
    -1 on its own) and row, and each group's first spectrum: located once for
    every ``line_reads`` of them.
    """

    spectra: Sequence[WindowSpectrum | None]
    group_of: npt.NDArray[np.intp]
    row_of: npt.NDArray[np.intp]
    firsts: Sequence[WindowSpectrum]


def spectra_by_rows(spectra: Sequence[WindowSpectrum | None]) -> SpectraByRows:
    """*spectra* as ``SpectraByRows``."""
    groups: dict[tuple[int, int], int] = {}
    firsts: list[WindowSpectrum] = []
    group_of = np.full(len(spectra), -1, dtype=np.intp)
    row_of = np.zeros(len(spectra), dtype=np.intp)
    for index, spectrum in enumerate(spectra):
        if spectrum is None or spectrum.rows is None or spectrum.freq_hz.size < 2:
            continue
        key = (id(spectrum.rows), id(spectrum.freq_hz))
        group = groups.get(key)
        if group is None:
            group = groups[key] = len(firsts)
            firsts.append(spectrum)
        group_of[index] = group
        row_of[index] = spectrum.row
    return SpectraByRows(spectra, group_of, row_of, firsts)


def line_reads(
    spectra: SpectraByRows,
    spectrum_index: npt.NDArray[np.intp],
    hz: npt.NDArray[np.float64],
    half_width_hz: npt.NDArray[np.float64],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.bool_]]:
    """Each read ``spectra.spectra[spectrum_index[i]].line_read(hz[i], half_width_hz[i])``.

    Returned as each read's excess, flanks and whether it has a read (NaN
    where not); every spectrum read must be there. The same reads, bit for
    bit, at a fraction of the cost: the
    reads of spectra kept together (``WindowSpectrum.rows``) are located as
    arrays, and those with a full band and both flanks inside their spectrum
    are gathered by band width and computed as arrays in the same
    floating-point order as one read (``_python_sum``). The rest are located
    one by one (``_loose_line_reads``).
    """
    count = hz.size
    excess = np.full(count, np.nan)
    flanks = np.full(count, np.nan)
    taken = np.zeros(count, dtype=np.bool_)
    group_of, row_of, firsts = spectra.group_of, spectra.row_of, spectra.firsts
    read_group = group_of[spectrum_index]
    alone = read_group < 0
    for group, first in enumerate(firsts):
        rows = cast("npt.NDArray[np.float32]", first.rows)
        start, bin_hz, size = float(first.freq_hz[0]), first.bin_hz, first.freq_hz.size
        positions = np.flatnonzero(read_group == group)
        row = row_of[spectrum_index[positions]]
        # As ``line_read``: Python's ``round`` and ``np.rint`` both round half to even.
        centre = np.rint((hz[positions] - start) / bin_hz).astype(np.intp)
        half = np.rint(half_width_hz[positions] / bin_hz).astype(np.intp) + _MAIN_LOBE_BINS
        inside = (centre - half - _FLANK_BINS >= 0) & (centre + half + _FLANK_BINS < size)
        alone[positions[~inside]] = True
        if _USE_NUMBA:
            _jit_stacked_reads(rows, row, centre, half, positions, inside, bin_hz, excess, flanks)
            taken[positions[inside]] = True
            continue
        for band_half in np.unique(half[inside]).tolist():
            selected = np.flatnonzero(inside & (half == band_half))
            offsets = np.arange(-band_half - _FLANK_BINS, band_half + _FLANK_BINS + 1)
            for chunk_start in range(0, selected.size, _READS_PER_STACK):
                chosen = selected[chunk_start : chunk_start + _READS_PER_STACK]
                segments = rows[row[chosen, None], centre[chosen, None] + offsets]
                target = positions[chosen]
                excess[target], flanks[target] = _stacked_line_reads(segments, band_half, bin_hz)
                taken[target] = True
    _loose_line_reads(
        spectra.spectra,
        spectrum_index,
        hz,
        half_width_hz,
        np.flatnonzero(alone),
        (excess, flanks, taken),
    )
    return excess, flanks, taken


# EXPERIMENT: VS_EXP_NUMBA=1 reads the stacked line reads with a numba kernel.
_USE_NUMBA = os.environ.get("VS_EXP_NUMBA") == "1"
_JIT_TABLES: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}


def _jit_stacked_reads(
    rows: npt.NDArray[np.float32],
    row: npt.NDArray[np.intp],
    centre: npt.NDArray[np.intp],
    half: npt.NDArray[np.intp],
    positions: npt.NDArray[np.intp],
    inside: npt.NDArray[np.bool_],
    bin_hz: float,
    excess: npt.NDArray[np.float64],
    flanks: npt.NDArray[np.float64],
) -> None:
    from vibesensor.dsp._line_reads_jit import stacked_reads

    chosen = np.flatnonzero(inside)
    if chosen.size == 0:
        return
    sel_half = half[chosen]
    max_half = int(sel_half.max())
    tables = _JIT_TABLES.get(max_half)
    if tables is None:
        mean_distance = np.zeros(max_half + 1)
        spread = np.zeros((max_half + 1, _FLANK_BINS))
        spread_squares = np.ones(max_half + 1)
        for h in range(max_half + 1):
            _distance, mean_distance[h], spread_h, spread_squares[h] = _flank_distances(h)
            spread[h] = spread_h
        tables = _JIT_TABLES[max_half] = (mean_distance, spread, spread_squares)
    stacked_reads(
        rows,
        row[chosen],
        centre[chosen],
        sel_half,
        positions[chosen],
        _FLANK_BINS,
        float(peak_band_bins(bin_hz)),
        *tables,
        excess,
        flanks,
    )


def _loose_line_reads(
    spectra: Sequence[WindowSpectrum | None],
    spectrum_index: npt.NDArray[np.intp],
    hz: npt.NDArray[np.float64],
    half_width_hz: npt.NDArray[np.float64],
    positions: npt.NDArray[np.intp],
    into: tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.bool_]],
) -> None:
    """``line_reads`` of the reads at *positions*, located one by one.

    The reads of a spectrum on its own, and those at a spectrum's edge. Those
    with a full band and both flanks inside their spectrum are still stacked
    by band width and computed as arrays; the rest are read one by one.
    """
    excess, flanks, taken = into
    # Each spectrum's first bin and bin width, once per frequency axis: a
    # drive's spectra share one or a few.
    bins_of: dict[int, tuple[float, float]] = {}
    chosen = positions.tolist()
    reads_hz = hz[positions].tolist()
    reads_half_width_hz = half_width_hz[positions].tolist()
    reads_spectrum = spectrum_index[positions].tolist()
    for chunk_start in range(0, len(chosen), _READS_PER_STACK):
        by_half: dict[tuple[int, float], tuple[list[int], list[npt.NDArray[np.float32]]]] = {}
        for at in range(chunk_start, min(len(chosen), chunk_start + _READS_PER_STACK)):
            position, read_hz, read_half_width_hz = (
                chosen[at],
                reads_hz[at],
                reads_half_width_hz[at],
            )
            spectrum = cast("WindowSpectrum", spectra[reads_spectrum[at]])
            freq = spectrum.freq_hz
            size = freq.size
            if size < 2:
                continue
            bins = bins_of.get(id(freq))
            if bins is None:
                bins = bins_of[id(freq)] = (float(freq[0]), spectrum.bin_hz)
            start, bin_hz = bins
            centre = int(round((read_hz - start) / bin_hz))
            half = int(round(read_half_width_hz / bin_hz)) + _MAIN_LOBE_BINS
            if centre - half - _FLANK_BINS < 0 or centre + half + _FLANK_BINS >= size:
                read = spectrum.line_read(read_hz, read_half_width_hz)
                if read is not None:
                    excess[position], flanks[position] = read.excess, read.flanks
                    taken[position] = True
                continue
            stacked_at, segments = by_half.setdefault((half, bin_hz), ([], []))
            stacked_at.append(position)
            segments.append(
                spectrum.amp_g[centre - half - _FLANK_BINS : centre + half + 1 + _FLANK_BINS]
            )
        for (half, bin_hz), (stacked_at, segments) in by_half.items():
            excess[stacked_at], flanks[stacked_at] = _stacked_line_reads(
                np.stack(segments), half, bin_hz
            )
            taken[stacked_at] = True


def _stacked_line_reads(
    segments: npt.NDArray[np.float32], half: int, bin_hz: float
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """``line_read``'s excess and flanks for rows of a band ``2 half + 1`` wide and its flanks."""
    power = np.square(segments, dtype=np.float64)
    lower = [power[:, offset] for offset in range(_FLANK_BINS)]
    upper = [power[:, -_FLANK_BINS + offset] for offset in range(_FLANK_BINS)]
    flanks = _python_sum(lower + upper) / (2 * _FLANK_BINS)
    band = _python_sum([power[:, _FLANK_BINS + offset] for offset in range(2 * half + 1)])
    bins = 2 * half + 1
    _distance, mean_distance, spread, spread_squares = _flank_distances(half)
    paired = [0.5 * (low + up) for low, up in zip(reversed(lower), upper, strict=True)]
    mean_paired = _python_sum(paired) / _FLANK_BINS
    bend = (
        _python_sum(
            [step * (value - mean_paired) for step, value in zip(spread, paired, strict=True)]
        )
        / spread_squares
    )
    level = mean_paired - bend * mean_distance
    under = bins * level + bend * half * (half + 1) * (2 * half + 1) / 3.0
    excess = (band - under) / peak_band_bins(bin_hz)
    return excess, flanks


def _python_sum(columns: Sequence[npt.NDArray[np.float64]]) -> npt.NDArray[np.float64]:
    """Python's ``sum`` of each row's values (one column per term), as arrays.

    ``sum`` of floats compensates its rounding (Neumaier, *ZAMM* 54, 1974;
    CPython 3.12+): the same steps here give the same bits.
    """
    total = 0.0 + columns[0]
    compensation = np.zeros_like(total)
    for column in columns[1:]:
        step = total + column
        compensation += np.where(
            np.abs(total) >= np.abs(column), (total - step) + column, (column - step) + total
        )
        total = step
    return np.where((compensation != 0) & np.isfinite(compensation), total + compensation, total)


@cache
def _flank_distances(half: int) -> tuple[list[float], float, list[float], float]:
    """The flank bins' squared distances from a band's centre: their mean, spread, its squares."""
    distance = [float(half + 1 + offset) ** 2 for offset in range(_FLANK_BINS)]
    mean_distance = sum(distance) / _FLANK_BINS
    spread = [value - mean_distance for value in distance]
    return distance, mean_distance, spread, sum(step * step for step in spread)
