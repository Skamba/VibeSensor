"""One analysis window's combined amplitude spectrum, kept for the post-stop order tracking."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, sqrt

import numpy as np
import numpy.typing as npt

from vibesensor.dsp.constants import PEAK_BANDWIDTH_HZ

__all__ = [
    "LineRead",
    "WindowSpectrum",
    "line_half_width_hz",
    "line_reach_hz",
    "peak_band_bins",
    "peak_scale_g",
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


def line_reach_hz(half_width_hz: float, bin_hz: float) -> float:
    """How far either side of a line's centre its read takes in: the band and the flanks past it."""
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
