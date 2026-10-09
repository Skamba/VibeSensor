"""One analysis window's combined amplitude spectrum, kept for the post-stop order tracking."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from vibesensor.dsp.constants import PEAK_BANDWIDTH_HZ

__all__ = ["LineRead", "WindowSpectrum"]

# The flanks a line is compared with start this far past the line's own band and
# span this much: close enough that a broad hump's curvature barely shows, wide
# enough to hold a few bins.
_FLANK_GAP_HZ = 0.8
_FLANK_SPAN_HZ = 1.8


@dataclass(frozen=True, slots=True)
class LineRead:
    """One window's power at an order's line over the floor beside it (g²).

    ``excess`` is the power in the line's band (``PEAK_BANDWIDTH_HZ`` about
    it, or the band its frequency swept through in the window) above the
    local floor, per bin of a peak's band: a steady tone's ``excess`` is its
    peak level squared (band RMS, ``PEAK_BANDWIDTH_HZ``) over the floor, and a
    swept one's adds up the same way. ``flanks`` is the local floor, the mean
    power per bin either side of the band. ``excess`` comes out below zero in
    a window where the order is absent about as often as above: it is meant to
    be averaged.
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

        At the ends of the spectrum the flanks are the bins on the side that has
        them. ``None`` when the band, or both flanks, fall outside it.
        """
        freq = self.freq_hz
        size = freq.size
        if size < 2:
            return None
        start, bin_hz = float(freq[0]), float(freq[1] - freq[0])
        centre = int(round((hz - start) / bin_hz))
        peak_half = int(PEAK_BANDWIDTH_HZ / bin_hz + 1e-9)
        swept = max(1, int(round(half_width_hz / bin_hz)))
        half = max(peak_half, swept)
        gap = swept + max(1, int(round(_FLANK_GAP_HZ / bin_hz)))
        span = max(2, int(round(_FLANK_SPAN_HZ / bin_hz)))
        if centre - half < 0 or centre + half >= size:
            return None
        lower = self.amp_g[max(0, centre - gap - span) : max(0, centre - gap + 1)]
        upper = self.amp_g[min(size, centre + gap) : min(size, centre + gap + span + 1)]
        if max(lower.size, upper.size) <= span:
            return None
        flanks = float(np.mean(np.square(np.concatenate((lower, upper)), dtype=np.float64)))
        band = np.square(self.amp_g[centre - half : centre + half + 1], dtype=np.float64)
        excess = (float(np.sum(band)) - band.size * flanks) / (2 * peak_half + 1)
        return LineRead(excess=excess, flanks=flanks)
