"""Brake judder: a wheel order that is there while the car brakes, and only then.

A brake disc with thickness variation or runout pulses the brake torque once
(sometimes twice) per wheel turn, so it shakes the car at the wheel's own order,
but only with the brakes on. An unbalanced or out-of-round wheel shakes at the
same order whether or not the car brakes. A wheel order is put down to the
brakes when, at the sensors that hear it, it is there in most braking spectra
and, at the same speeds, practically never while the car is not braking.

Each spectrum spans a few seconds (2.56 s at 800 Hz), so the spectra that
straddle the start or end of a braking spell show it partly; they count for
neither side. See "Brake judder" in ``docs/analysis_pipeline.md``.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from statistics import median

from vibesensor.analysis._types import PhaseLabels, Sample
from vibesensor.analysis.orders.matching import OrderMatchAccumulator
from vibesensor.domain.driving_segment import DrivingPhase
from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_types import VibrationSource

__all__ = ["BRAKING_PHASE", "as_brake_finding", "only_while_braking"]

BRAKING_PHASE = DrivingPhase.BRAKING.value
# Enough braking spectra at the sensors that hear the order to judge it: about
# two seconds of braking per sensor at the 4 Hz spectrum rate (and as many
# spectra while not braking).
_MIN_SPECTRA = 8
# The order is in at least half of the braking spectra of the stops it shows
# in. A stop shows it when it is in at least a quarter of that stop's spectra
# within 12 dB (a quarter of the amplitude) of the loudest stop's level: road
# noise lands a floor-level peak near the predicted frequency in about a third
# of the spectra. A stop that does not show it may have been an EV's or PHEV's
# regeneration alone, without touching the discs, or judder may need hot discs.
_MIN_BRAKING_HEARD_SHARE = 0.5
_MIN_STOP_HEARD_SHARE = 0.25
_PRESENT_LEVEL_RATIO = 0.25
# ...and in at most one in ten of the other spectra at the same speeds, counting
# only peaks within 12 dB of its braking level.
_MAX_CLEAR_PRESENT_SHARE = 0.1
# Half a spectrum's span when the sample does not carry its analysis window.
_DEFAULT_HALF_WINDOW_S = 1.28
# Braking samples further apart than this belong to different stops.
_SPELL_GAP_S = 1.0


def _phase_value(phase: object) -> str:
    return str(getattr(phase, "value", phase))


def _half_window_s(sample: Sample) -> float:
    start = sample.analysis_window_start_us
    end = sample.analysis_window_end_us
    if start is None or end is None or end <= start:
        return _DEFAULT_HALF_WINDOW_S
    return (end - start) / 2e6


def _near(times: Sequence[float], t_s: float, distance_s: float) -> bool:
    idx = bisect_left(times, t_s)
    neighbours = times[max(0, idx - 1) : idx + 1]
    return any(abs(t - t_s) <= distance_s for t in neighbours)


def _braking_spells(samples: Sequence[Sample], braking: Sequence[bool]) -> dict[int, int]:
    """The stop (numbered in time order) each timed braking sample belongs to."""
    timed = sorted(
        (t_s, idx)
        for idx, (sample, is_braking) in enumerate(zip(samples, braking, strict=True))
        if is_braking and (t_s := sample.t_s) is not None
    )
    spell_of: dict[int, int] = {}
    spell = 0
    for position, (t_s, idx) in enumerate(timed):
        if position and t_s - timed[position - 1][0] > _SPELL_GAP_S:
            spell += 1
        spell_of[idx] = spell
    return spell_of


def only_while_braking(
    match: OrderMatchAccumulator,
    samples: Sequence[Sample],
    per_sample_phases: PhaseLabels | None,
) -> bool:
    """Whether the matched order is there while braking and not otherwise.

    Only the stops that show the order at its braking level count as braking
    (``_MIN_STOP_HEARD_SHARE``).
    """
    if per_sample_phases is None or len(per_sample_phases) != len(samples):
        return False
    braking = [_phase_value(phase) == BRAKING_PHASE for phase in per_sample_phases]
    braking_times = sorted(
        t_s
        for sample, is_braking in zip(samples, braking, strict=True)
        if is_braking and (t_s := sample.t_s) is not None
    )
    if not braking_times:
        return False
    spell_of = _braking_spells(samples, braking)
    locations = match.heard_locations or {location for _idx, location in match.possible_samples}
    # True: a braking spectrum; False: a spectrum clear of any braking; spectra
    # that straddle a braking spell are left out.
    side: dict[int, bool] = {}
    for idx, location in match.possible_samples:
        if location not in locations:
            continue
        sample = samples[idx]
        if idx in spell_of:
            side[idx] = True
        elif sample.t_s is not None and not _near(
            braking_times, sample.t_s, _half_window_s(sample)
        ):
            side[idx] = False
    heard = [
        (idx, point)
        for idx, point in zip(match.matched_sample_indices, match.matched_points, strict=True)
        if point.heard and idx in side
    ]
    possible_by_spell = Counter(spell_of[idx] for idx, is_braking in side.items() if is_braking)
    amps_by_spell: dict[int, list[float]] = {}
    for idx, point in heard:
        if side[idx]:
            amps_by_spell.setdefault(spell_of[idx], []).append(point.amp)
    # The loudest stop's level, among the stops heard often enough to judge.
    stop_levels = [
        median(amps)
        for spell, amps in amps_by_spell.items()
        if len(amps) >= _MIN_STOP_HEARD_SHARE * possible_by_spell[spell]
    ]
    if not stop_levels:
        return False
    stop_level = max(stop_levels)
    shown = {
        spell
        for spell, amps in amps_by_spell.items()
        if sum(amp >= _PRESENT_LEVEL_RATIO * stop_level for amp in amps)
        >= _MIN_STOP_HEARD_SHARE * possible_by_spell[spell]
    }
    braking_possible = [
        idx for idx, is_braking in side.items() if is_braking and spell_of[idx] in shown
    ]
    braking_heard = [point for idx, point in heard if side[idx] and spell_of[idx] in shown]
    if len(braking_possible) < _MIN_SPECTRA or len(braking_heard) < _MIN_BRAKING_HEARD_SHARE * len(
        braking_possible
    ):
        return False
    # Compare with driving at the speeds the car braked through.
    speeds = [point.speed_kmh for point in braking_heard if point.speed_kmh is not None]
    if not speeds:
        return False
    low, high = min(speeds), max(speeds)

    def in_band(speed: float | None) -> bool:
        return speed is not None and low <= speed <= high

    clear_possible = [
        idx
        for idx, is_braking in side.items()
        if not is_braking and in_band(samples[idx].speed_kmh)
    ]
    if len(clear_possible) < _MIN_SPECTRA:
        return False
    level = median(point.amp for point in braking_heard)
    clear_present = [
        point
        for idx, point in heard
        if not side[idx] and in_band(point.speed_kmh) and point.amp >= _PRESENT_LEVEL_RATIO * level
    ]
    return len(clear_present) <= _MAX_CLEAR_PRESENT_SHARE * len(clear_possible)


def as_brake_finding(finding: Finding) -> Finding:
    """The wheel-order *finding* put down to the brakes: its judder while braking."""
    origin = finding.origin
    if origin is not None:
        origin = replace(
            origin, suspected_source=VibrationSource.BRAKES, dominant_phase=BRAKING_PHASE
        )
    return replace(
        finding,
        suspected_source=VibrationSource.BRAKES,
        dominant_phase=BRAKING_PHASE,
        phases_detected=(BRAKING_PHASE,),
        # The judder is what the order did while braking; its other matches are
        # road noise that lands near the predicted frequency.
        matched_points=tuple(
            point for point in finding.matched_points if point.phase == BRAKING_PHASE
        ),
        origin=origin,
    )
