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
# The order is in at least half of the braking spectra...
_MIN_BRAKING_HEARD_SHARE = 0.5
# ...and in at most one in ten of the other spectra at the same speeds, counting
# only peaks within 12 dB (a quarter of the amplitude) of its braking level:
# road noise lands a floor-level peak near the predicted frequency now and then.
_PRESENT_LEVEL_RATIO = 0.25
_MAX_CLEAR_PRESENT_SHARE = 0.1
# Half a spectrum's span when the sample does not carry its analysis window.
_DEFAULT_HALF_WINDOW_S = 1.28


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


def only_while_braking(
    match: OrderMatchAccumulator,
    samples: Sequence[Sample],
    per_sample_phases: PhaseLabels | None,
) -> bool:
    """Whether the matched order is there while braking and not otherwise."""
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
    locations = match.heard_locations or {location for _idx, location in match.possible_samples}
    # True: a braking spectrum; False: a spectrum clear of any braking; spectra
    # that straddle a braking spell are left out.
    side: dict[int, bool] = {}
    for idx, location in match.possible_samples:
        if location not in locations:
            continue
        sample = samples[idx]
        if braking[idx]:
            side[idx] = True
        elif sample.t_s is not None and not _near(
            braking_times, sample.t_s, _half_window_s(sample)
        ):
            side[idx] = False
    heard = [
        (side[idx], point)
        for idx, point in zip(match.matched_sample_indices, match.matched_points, strict=True)
        if point.heard and idx in side
    ]
    braking_possible = [idx for idx, is_braking in side.items() if is_braking]
    braking_heard = [point for is_braking, point in heard if is_braking]
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
        for is_braking, point in heard
        if not is_braking and in_band(point.speed_kmh) and point.amp >= _PRESENT_LEVEL_RATIO * level
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
