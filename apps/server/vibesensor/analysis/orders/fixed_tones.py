"""Fixed-frequency tones: spectral peaks that stay put while the speed changes.

A body or seat resonance, a mirror buzz or an idle-speed engine tone rings at
the same frequency whatever the speed. A road-speed order sweeps past such a
tone, and while its tolerance window holds the tone the matcher lands on it:
the order then borrows the tone's level at every sensor that feels the tone,
and a crossing at a speed the drive lingers at reads as an order of its own.
A peak at a sensor's fixed tone is no evidence for an order that follows the
speed, so the speed-following hypotheses are matched without those peaks.
See "Fixed tones" in ``docs/order_tracking.md``.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, floor, log, pi

from vibesensor.analysis._sample_metrics import _estimate_strength_floor_amp_g
from vibesensor.analysis._types import Sample
from vibesensor.analysis.orders.settings import ORDER_CONFIDENCE_SETTINGS
from vibesensor.analysis.orders.tracking import TrackedCells
from vibesensor.domain.order_match import SensorOrderLevel
from vibesensor.dsp.order_bands import ORDER_TOLERANCE_REL
from vibesensor.dsp.window_spectrum import WindowSpectrum, peak_band_bins

__all__ = [
    "RingingTone",
    "fixed_tones",
    "ringing_tones",
    "without_fixed_tones",
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
_CLEAR_OVER_FLOOR = ORDER_CONFIDENCE_SETTINGS.heard_peak_over_floor
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


def _tone_width_hz(hz: float) -> float:
    return max(_SAME_TONE_HZ, _SAME_TONE_REL * hz)


def _speed_bin(speed_kmh: float) -> int:
    return floor(log(speed_kmh) / log(_SPEED_BIN_RATIO))


def _sensor_fixed_tones(
    indices: Sequence[int],
    samples: Sequence[Sample],
    peaks: Sequence[Sequence[tuple[float, float]]],
) -> list[float]:
    """The fixed tones of one sensor: peaks there through a wide spread of speeds."""
    bin_of = {index: _speed_bin(float(samples[index].speed_kmh or 0.0)) for index in indices}
    spectra = Counter(bin_of.values())
    judged = {speed_bin for speed_bin, count in spectra.items() if count >= _MIN_SPECTRA_PER_BIN}
    at_hz: dict[float, set[int]] = defaultdict(set)
    for index in indices:
        # Only a peak that stands out from its spectrum's floor can be a tone.
        floor_amp = _estimate_strength_floor_amp_g(samples[index]) or 0.0
        for hz, amp in peaks[index]:
            if amp >= _CLEAR_OVER_FLOOR * floor_amp:
                at_hz[hz].add(index)
    tones = sorted(at_hz)
    min_bins = ceil(log(_MIN_SPEED_SPREAD) / log(_SPEED_BIN_RATIO))
    fixed: list[float] = []
    for hz in tones:
        width = _tone_width_hz(hz)
        lo, hi = bisect_left(tones, hz - width), bisect_right(tones, hz + width)
        holding = Counter(
            bin_of[index] for index in set().union(*(at_hz[tone] for tone in tones[lo:hi]))
        )
        held = sorted(
            speed_bin
            for speed_bin in judged
            if holding[speed_bin] >= _HELD_IN_BIN * spectra[speed_bin]
        )
        if len(held) < 2 or held[-1] - held[0] < min_bins:
            continue
        between = [speed_bin for speed_bin in judged if held[0] <= speed_bin <= held[-1]]
        if len(held) >= _HELD_BINS * len(between):
            fixed.append(hz)
    return fixed


def fixed_tones(
    samples: Sequence[Sample],
    peaks: Sequence[Sequence[tuple[float, float]]],
) -> list[tuple[float, ...]]:
    """The fixed tones (Hz) of each spectrum's sensor.

    Only spectra taken while moving judge what is fixed; a tone found that way
    is a tone of every spectrum of that sensor.
    """
    by_sensor: dict[str, list[int]] = defaultdict(list)
    for index, sample in enumerate(samples):
        if sample.speed_kmh is not None and sample.speed_kmh > 0 and peaks[index]:
            by_sensor[sample.client_id].append(index)
    by_client = {
        sensor: tuple(_sensor_fixed_tones(indices, samples, peaks))
        for sensor, indices in by_sensor.items()
    }
    return [by_client.get(sample.client_id, ()) for sample in samples]


def _near_fixed_tone(hz: float, half_width_hz: float, tones: Sequence[float]) -> bool:
    """Whether a band ``hz ± half_width_hz`` takes in one of *tones*."""
    return any(abs(hz - tone) <= half_width_hz + _tone_width_hz(tone) for tone in tones)


def without_fixed_tones(
    peaks: Sequence[Sequence[tuple[float, float]]],
    tones: Sequence[Sequence[float]],
) -> list[list[tuple[float, float]]]:
    """Each spectrum's peaks without those at its sensor's fixed tones (``fixed_tones``)."""
    return [
        [(hz, amp) for hz, amp in sample_peaks if not _near_fixed_tone(hz, 0.0, sample_tones)]
        for sample_peaks, sample_tones in zip(peaks, tones, strict=True)
    ]


@dataclass(frozen=True, slots=True)
class RingingTone:
    """A fixed tone that rings as a line (``ringing_tones``), and how far its power leaks."""

    hz: float
    reach_hz: float

    def takes_in(self, hz: float, half_width_hz: float) -> bool:
        """Whether a band ``hz ± half_width_hz`` reaches into the tone or its leak."""
        return abs(hz - self.hz) <= half_width_hz + self.reach_hz


def ringing_tones(
    samples: Sequence[Sample],
    tones: Sequence[Sequence[float]],
    window_s: float,
) -> list[tuple[RingingTone, ...]]:
    """Each spectrum's sensor's fixed tones that ring as a line, not a broad hump.

    Each run of the car's tones within a tone's width of each other (one
    tone's peaks wandering over neighbouring bins) is read as a line over its
    span in every spectrum of each sensor, as an order is
    (``WindowSpectrum.line_read``), and judged as an order is
    (``TrackedCells``): it rings at a sensor where its reads stand out of
    their scatter there, whether or not the peak picker held it fixed at
    that sensor. A broad resonance the peak picker also holds fixed (a wheel's
    hop under the road) reads no level over the floor that follows its curve,
    so an order's read is no worse for crossing it. A ringing tone reaches as
    far as its power leaks (``_leak_reach_hz``).
    """
    by_sensor: dict[str, list[tuple[int, WindowSpectrum]]] = defaultdict(list)
    for index, sample in enumerate(samples):
        if sample.spectrum is not None:
            by_sensor[sample.client_id].append((index, sample.spectrum))
    candidates = sorted({tone for spectra in by_sensor.values() for tone in tones[spectra[0][0]]})
    ringing: dict[str, tuple[RingingTone, ...]] = {}
    for sensor, spectra in by_sensor.items():
        kept: list[RingingTone] = []
        for group in _tone_groups(candidates):
            centre, half_width = (group[0] + group[-1]) / 2.0, (group[-1] - group[0]) / 2.0
            cells = TrackedCells(window_s=window_s)
            for index, spectrum in spectra:
                read = spectrum.line_read(centre, half_width)
                if read is not None:
                    cells.add((sensor, "", ""), read, samples[index].t_s)
            levels = cells.sensor_levels(())
            if levels and levels[0].level_g > 0:
                bin_hz = spectra[0][1].bin_hz
                kept.extend(
                    RingingTone(tone, max(_tone_width_hz(tone), half_width + leak_hz))
                    for leak_hz in (_leak_reach_hz(levels[0], bin_hz),)
                    for tone in group
                )
        ringing[sensor] = tuple(kept)
    return [ringing.get(sample.client_id, ()) for sample in samples]


def _leak_reach_hz(level: SensorOrderLevel, bin_hz: float) -> float:
    """How far either side of a tone its sidelobes leak within ``_LEAK_UNDER_FLOOR`` of the floor.

    A Hann window passes a tone ``k`` bins away at ``1 / (pi k (k^2 - 1))``
    of its level (Harris, *Proc. IEEE* 66(1), 1978); the tone holds
    ``(level / floor)^2`` times the floor's power over a peak's band. Two bins
    (the main lobe) at least, 40 at most.
    """
    if level.floor_g <= 0:
        return 0.0
    ratio = (level.level_g / level.floor_g) ** 2 * peak_band_bins(bin_hz)
    k = _MIN_LEAK_BINS
    while (pi * k * (k * k - 1.0)) ** 2 < _LEAK_UNDER_FLOOR * ratio and k < _MAX_LEAK_BINS:
        k += _LEAK_STEP_BINS
    return k * bin_hz


def _tone_groups(tones: Sequence[float]) -> list[list[float]]:
    groups: list[list[float]] = []
    for hz in tones:
        if groups and hz - groups[-1][-1] <= _tone_width_hz(hz):
            groups[-1].append(hz)
        else:
            groups.append([hz])
    return groups
