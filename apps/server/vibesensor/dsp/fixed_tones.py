"""Fixed-frequency tones: one rule for the report and the live view.

A body or seat resonance, a mirror buzz, a fan or pump, or an idle-speed engine
tone rings at the same frequency whatever the speed. A road-speed order sweeps
past such a tone, and while its line holds the tone the order borrows the
tone's level. A sensor's fixed tones are its peaks that stay put through a wide
spread of speeds (``sensor_fixed_tones``); a fixed tone that rings as a line,
not a broad hump, at a sensor (``ringing``) hides an order from that sensor's
reads where the order's line reaches the tone or its leak (``RingingTone``).
The post-stop analysis finds them over the whole drive
(``analysis/orders/fixed_tones.py``), the live view over the drive so far
(``live/order_hearing.py``). See "Fixed tones" in docs/order_tracking.md.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, floor, log, pi, sqrt
from statistics import median

from vibesensor.dsp.line_significance import (
    HEARD_OVER_FLOOR,
    MIN_INDEPENDENT_READS,
    SENSOR_STANDARD_ERRORS,
    deviations,
    independent_share,
    normalized,
    presence_block_s,
    present_level,
    scatter,
    stands_out,
)
from vibesensor.dsp.order_bands import ORDER_TOLERANCE_REL
from vibesensor.dsp.window_spectrum import peak_band_bins

__all__ = [
    "RingingTone",
    "clear_peak_hz",
    "ringing",
    "ringing_tone",
    "sensor_fixed_tones",
    "tone_groups",
    "tone_speed_bin",
    "tone_width_hz",
]

# A tone that stays put while the speed changes by half is no order: any
# order's frequency would have left its tolerance window (+/- 8 %) several
# times over. Each spectrum spans a few seconds, so on a quick sweep one
# order's peak is seen over a spread of up to about a fifth.
_MIN_SPEED_SPREAD = 1.5
# Speeds are judged in bins about an order's tolerance wide, so a drive that
# lingers at one speed weighs no more than one that sweeps past it.
_SPEED_BIN_RATIO = 1.0 + ORDER_TOLERANCE_REL
_MIN_SPECTRA_PER_BIN = 2
# A fixed tone is in at least three quarters of a speed bin's spectra (road
# noise lands on any one frequency far less often), in most of the bins over its
# speed span: an order and its harmonic meeting one frequency at two speeds is
# not one.
_HELD_IN_BIN = 0.75
_HELD_BINS = 0.8
# Spectral peaks of one tone wander over neighbouring FFT bins.
_SAME_TONE_HZ = 0.5
_SAME_TONE_REL = 0.02
# A ringing tone's power leaks into the bins either side of it through the
# Hann window's sidelobes; a line read is clear of it where the leak stays
# this far (10 dB) under the floor.
_LEAK_UNDER_FLOOR = 10.0
_MIN_LEAK_BINS = 2.0
_MAX_LEAK_BINS = 40.0
_LEAK_STEP_BINS = 0.25


def tone_width_hz(hz: float) -> float:
    """How far one tone's peaks wander over neighbouring FFT bins (Hz)."""
    return max(_SAME_TONE_HZ, _SAME_TONE_REL * hz)


def tone_speed_bin(speed_kmh: float) -> int:
    """The speed bin (about an order's tolerance wide) a spectrum at *speed_kmh* is judged in."""
    return floor(log(speed_kmh) / log(_SPEED_BIN_RATIO))


def clear_peak_hz(peaks: Sequence[tuple[float, float]], floor_amp_g: float) -> list[float]:
    """The frequencies of *peaks* (hz, amp) that stand out from their spectrum's floor.

    Only such a peak can be a tone: ``HEARD_OVER_FLOOR`` (6 dB) over the floor,
    as a ranked peak must stand to be heard.
    """
    return [hz for hz, amp in peaks if amp >= HEARD_OVER_FLOOR * floor_amp_g]


def sensor_fixed_tones(spectra: Sequence[tuple[int, Sequence[float]]]) -> list[float]:
    """The fixed tones (Hz) of one sensor: peaks there through a wide spread of speeds.

    *spectra* holds each spectrum taken while moving: its speed bin
    (``tone_speed_bin``) and its clear peaks' frequencies (``clear_peak_hz``).
    """
    bin_of = [speed_bin for speed_bin, _peaks in spectra]
    counts = Counter(bin_of)
    judged = {speed_bin for speed_bin, count in counts.items() if count >= _MIN_SPECTRA_PER_BIN}
    at_hz: dict[float, set[int]] = defaultdict(set)
    for index, (_speed_bin, peaks) in enumerate(spectra):
        for hz in peaks:
            at_hz[hz].add(index)
    tones = sorted(at_hz)
    min_bins = ceil(log(_MIN_SPEED_SPREAD) / log(_SPEED_BIN_RATIO))
    needed = {speed_bin: _HELD_IN_BIN * counts[speed_bin] for speed_bin in judged}
    # The speed bins where the spectra holding a peak within a tone's width of
    # each tone, counted once each, reach the bin's need: kept up to date as
    # the window of tones slides up.
    window = _HoldingWindow(at_hz, bin_of, needed)
    fixed: list[float] = []
    for hz in tones:
        width = tone_width_hz(hz)
        holding = window.slide(
            tones, bisect_left(tones, hz - width), bisect_right(tones, hz + width)
        )
        if len(holding) < 2:
            continue
        held = sorted(holding)
        if held[-1] - held[0] < min_bins:
            continue
        between = [speed_bin for speed_bin in judged if held[0] <= speed_bin <= held[-1]]
        if len(held) >= _HELD_BINS * len(between):
            fixed.append(hz)
    return fixed


class _HoldingWindow:
    """The speed bins where enough spectra hold a tone of a window ``tones[lo:hi]``.

    The spectra holding any of the window's tones are counted per speed bin,
    each once however many of the tones it holds; a bin holds the window where
    they reach its *needed* count. Moving the window adds and drops only the
    tones that enter or leave it.
    """

    def __init__(
        self, at_hz: dict[float, set[int]], bin_of: Sequence[int], needed: dict[int, float]
    ) -> None:
        self._at_hz = at_hz
        self._bin_of = bin_of
        self._needed = needed
        self._held_by: dict[int, int] = defaultdict(int)
        self._holding: dict[int, int] = defaultdict(int)
        self._held: set[int] = set()
        self._lo = 0
        self._hi = 0

    def slide(self, tones: Sequence[float], lo: int, hi: int) -> set[int]:
        # Widen first, so a tone is only dropped once it is in the window.
        while self._lo > lo:
            self._lo -= 1
            self._add(tones[self._lo], 1)
        while self._hi < hi:
            self._add(tones[self._hi], 1)
            self._hi += 1
        while self._hi > hi:
            self._hi -= 1
            self._add(tones[self._hi], -1)
        while self._lo < lo:
            self._add(tones[self._lo], -1)
            self._lo += 1
        return self._held

    def _add(self, tone: float, step: int) -> None:
        held_by, holding, bin_of = self._held_by, self._holding, self._bin_of
        for index in self._at_hz[tone]:
            held_by[index] += step
            # A spectrum enters on its first tone in the window, leaves after its last.
            if held_by[index] == (1 if step > 0 else 0):
                speed_bin = bin_of[index]
                holding[speed_bin] += step
                need = self._needed.get(speed_bin)
                if need is None:
                    continue
                if holding[speed_bin] >= need:
                    self._held.add(speed_bin)
                else:
                    self._held.discard(speed_bin)


def tone_groups(tones: Sequence[float]) -> list[list[float]]:
    """Sorted *tones* in runs within a tone's width of each other: one tone's wandering peaks."""
    groups: list[list[float]] = []
    for hz in tones:
        if groups and hz - groups[-1][-1] <= tone_width_hz(hz):
            groups[-1].append(hz)
        else:
            groups.append([hz])
    return groups


@dataclass(frozen=True, slots=True)
class RingingTone:
    """A fixed tone that rings as a line (``ringing``), and how far its power leaks."""

    hz: float
    reach_hz: float

    def takes_in(self, hz: float, half_width_hz: float) -> bool:
        """Whether a band ``hz ± half_width_hz`` reaches into the tone or its leak."""
        return abs(hz - self.hz) <= half_width_hz + self.reach_hz


def ringing(
    excess: Sequence[float], flanks: Sequence[float], t_s: Sequence[float], window_s: float
) -> tuple[float, float] | None:
    """The level and floor (g) of a fixed tone's line reads at one sensor, where it rings.

    ``None`` where it does not. The reads at a tone group's line are judged as
    an order's are at one sensor (``analysis/orders/tracking.TrackedCells``,
    with no control reads): the tone rings where the middle of the reads stands
    ``SENSOR_STANDARD_ERRORS`` out of their own scatter, over enough
    independent reads. A broad resonance the peak picker also holds fixed (a
    wheel's hop under the road) reads no level over the floor that follows its
    curve, so it does not ring. *t_s* is each read's time (NaN where unknown).
    """
    times = [t for t in t_s if t == t]
    share = independent_share(times, window_s)
    if len(excess) * share < MIN_INDEPENDENT_READS:
        return None
    reads = normalized(excess, flanks)
    if not stands_out(
        reads, scatter(deviations([reads], 1) or [0.0]), share, SENSOR_STANDARD_ERRORS
    ):
        return None
    level, _reads = present_level(excess, flanks, t_s, presence_block_s(window_s))
    if level <= 0:
        return None
    return sqrt(level), sqrt(median(flanks))


def ringing_tone(
    group: Sequence[float], level_g: float, floor_g: float, bin_hz: float
) -> list[RingingTone]:
    """Each tone of a ringing *group*, reaching over the group's span and its leak."""
    half_width = (group[-1] - group[0]) / 2.0
    leak_hz = _leak_reach_hz(level_g, floor_g, bin_hz)
    return [RingingTone(tone, max(tone_width_hz(tone), half_width + leak_hz)) for tone in group]


def _leak_reach_hz(level_g: float, floor_g: float, bin_hz: float) -> float:
    """How far either side of a tone its sidelobes leak within ``_LEAK_UNDER_FLOOR`` of the floor.

    A Hann window passes a tone ``k`` bins away at ``1 / (pi k (k^2 - 1))``
    of its level (Harris, *Proc. IEEE* 66(1), 1978); the tone holds
    ``(level / floor)^2`` times the floor's power over a peak's band. Two bins
    (the main lobe) at least, 40 at most.
    """
    if floor_g <= 0:
        return 0.0
    ratio = (level_g / floor_g) ** 2 * peak_band_bins(bin_hz)
    k = _MIN_LEAK_BINS
    while (pi * k * (k * k - 1.0)) ** 2 < _LEAK_UNDER_FLOOR * ratio and k < _MAX_LEAK_BINS:
        k += _LEAK_STEP_BINS
    return k * bin_hz
