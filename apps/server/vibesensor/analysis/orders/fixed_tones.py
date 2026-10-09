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
from math import ceil, floor, log

from vibesensor.analysis._sample_metrics import _estimate_strength_floor_amp_g
from vibesensor.analysis._types import Sample
from vibesensor.analysis.orders.settings import ORDER_CONFIDENCE_SETTINGS
from vibesensor.dsp.order_bands import ORDER_TOLERANCE_REL

__all__ = ["fixed_tones", "near_fixed_tone", "without_fixed_tones"]

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


def near_fixed_tone(hz: float, half_width_hz: float, tones: Sequence[float]) -> bool:
    """Whether a band ``hz ± half_width_hz`` takes in one of *tones*."""
    return any(abs(hz - tone) <= half_width_hz + _tone_width_hz(tone) for tone in tones)


def without_fixed_tones(
    peaks: Sequence[Sequence[tuple[float, float]]],
    tones: Sequence[Sequence[float]],
) -> list[list[tuple[float, float]]]:
    """Each spectrum's peaks without those at its sensor's fixed tones (``fixed_tones``)."""
    return [
        [(hz, amp) for hz, amp in sample_peaks if not near_fixed_tone(hz, 0.0, sample_tones)]
        for sample_peaks, sample_tones in zip(peaks, tones, strict=True)
    ]
