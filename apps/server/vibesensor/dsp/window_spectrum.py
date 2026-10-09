"""One analysis window's combined amplitude spectrum, kept for the post-stop order tracking."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np
import numpy.typing as npt

from vibesensor.dsp.constants import PEAK_BANDWIDTH_HZ

__all__ = ["LineRead", "WindowSpectrum", "peak_band_bins", "tone_line_level_g"]

# A Hann window spreads a steady tone over its main lobe, two bins either side
# of the tone's nearest bin: 99.95 % of its power whatever its offset from the
# bin centre.
_MAIN_LOBE_BINS = 2
# The floor a line is compared with is read in this many bins either side, just
# past its band: the closer they sit, the less a broad resonance's curvature
# under the line reads as the line's level.
_FLANK_BINS = 3
# A steady tone's power over a Hann window's bins is its peak amplitude squared
# times the window's equivalent noise bandwidth, 1.5 bins (Harris, *Proc. IEEE*
# 66(1), 1978).
_HANN_ENBW_BINS = 1.5


def peak_band_bins(bin_hz: float) -> int:
    """The bins of a peak's band: its centre bin and ``PEAK_BANDWIDTH_HZ`` either side."""
    return 2 * int(PEAK_BANDWIDTH_HZ / bin_hz + 1e-9) + 1


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
    and a swept one's adds up the same way. ``flanks`` is the local floor, the
    mean power per bin of the few bins either side of the band. ``excess``
    comes out below zero in a window where the order is absent about as often
    as above: it is meant to be averaged.
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
        start, bin_hz = float(freq[0]), float(freq[1] - freq[0])
        centre = int(round((hz - start) / bin_hz))
        half = int(round(half_width_hz / bin_hz)) + _MAIN_LOBE_BINS
        if centre - half < 0 or centre + half >= size:
            return None
        lower = self.amp_g[max(0, centre - half - _FLANK_BINS) : centre - half]
        upper = self.amp_g[centre + half + 1 : centre + half + 1 + _FLANK_BINS]
        if max(lower.size, upper.size) < _FLANK_BINS:
            return None
        flanks = float(np.mean(np.square(np.concatenate((lower, upper)), dtype=np.float64)))
        band = np.square(self.amp_g[centre - half : centre + half + 1], dtype=np.float64)
        excess = (float(np.sum(band)) - band.size * flanks) / peak_band_bins(bin_hz)
        return LineRead(excess=excess, flanks=flanks)
