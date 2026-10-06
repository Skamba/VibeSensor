"""Heuristic filters and tuning constants for order-tracking analysis."""

from __future__ import annotations

import math
from dataclasses import replace

from vibesensor.analysis.constants import ORDER_MIN_CONFIDENCE, ORDER_MIN_MATCH_POINTS
from vibesensor.analysis.math_utils import _mean, _ramp
from vibesensor.analysis.orders.settings import ORDER_HEURISTIC_SETTINGS
from vibesensor.domain.finding import Finding as DomainFinding
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.locations import is_wheel_location
from vibesensor.domain.order_match import OrderMatchObservation


def detect_diffuse_excitation(
    connected_locations: set[str],
    possible_by_location: dict[str, int],
    matched_by_location: dict[str, int],
    matched_points: list[OrderMatchObservation],
    *,
    min_match_points: int = ORDER_MIN_MATCH_POINTS,
) -> tuple[bool, float]:
    """Detect diffuse, non-localized excitation across multiple sensors.

    Returns whether the order is diffuse (similar match rates and amplitudes at
    every sensor that saw it) and the confidence factor for that. Past each
    edge of the test (amplitude ratio, match-rate range, mean match rate) the
    penalty eases out over a ramp rather than vanishing, so the flag is the
    full-penalty region and the factor can sit just under 1 outside it.
    """
    settings = ORDER_HEURISTIC_SETTINGS
    if len(connected_locations) < 2 or not possible_by_location:
        return False, 1.0
    loc_rates: list[float] = []
    loc_mean_amps: dict[str, float] = {}
    min_loc_points = max(3, min_match_points)
    for location in connected_locations:
        loc_possible = possible_by_location.get(location, 0)
        loc_matched = matched_by_location.get(location, 0)
        if loc_possible >= min_loc_points:
            loc_rates.append(loc_matched / max(1, loc_possible))
            loc_amps = [
                point.amp
                for point in matched_points
                if (point.location or "").strip() == location and point.amp > 0
            ]
            if loc_amps:
                loc_mean_amps[location] = _mean(loc_amps)
    if len(loc_rates) < 2:
        return False, 1.0
    rate_range = max(loc_rates) - min(loc_rates)
    mean_rate = _mean(loc_rates)
    amp_uniformity = 1.0
    if len(loc_mean_amps) >= 2:
        max_amp = max(loc_mean_amps.values())
        min_amp = min(loc_mean_amps.values())
        if min_amp > 0:
            amp_ratio = settings.diffuse_amplitude_dominance_ratio
            amp_uniformity = 1.0 - _ramp(
                max_amp / min_amp, amp_ratio, amp_ratio + settings.diffuse_amplitude_ramp
            )
    range_limit = settings.diffuse_match_rate_range_threshold
    min_mean_rate = settings.diffuse_min_mean_rate
    diffuseness = (
        amp_uniformity
        * (
            1.0
            - _ramp(rate_range, range_limit, range_limit + settings.diffuse_match_rate_range_ramp)
        )
        * _ramp(mean_rate, min_mean_rate - settings.diffuse_mean_rate_ramp, min_mean_rate)
    )
    if diffuseness <= 0.0:
        return False, 1.0
    penalty = max(
        settings.diffuse_penalty_floor,
        settings.diffuse_penalty_base - settings.diffuse_penalty_per_sensor * len(loc_rates),
    )
    return diffuseness >= 1.0, 1.0 - diffuseness * (1.0 - penalty)


# Brake judder is a wheel order heard only while braking (``brake_attribution``).
_WHEEL_ORDER_SOURCES = frozenset({VibrationSource.WHEEL_TIRE, VibrationSource.BRAKES})


def suppress_engine_aliases(
    findings: list[tuple[float, DomainFinding]],
    *,
    wheel_locked_engine_keys: frozenset[str] = frozenset(),
    min_confidence: float = ORDER_MIN_CONFIDENCE,
) -> list[DomainFinding]:
    """Suppress engine findings likely to be aliases of stronger wheel findings.

    A brake finding counts as a wheel finding here: it is a wheel order.

    Engine findings whose ranking score is at least as high as the best wheel
    finding are kept intact — a better ranking score indicates superior
    frequency tracking, meaning the engine hypothesis is a better physical
    explanation than the coincidentally close wheel harmonic.

    *wheel_locked_engine_keys* name engine orders placed by RPM estimated from
    speed and gear that land on a wheel order's peaks: such an order has no
    frequency of its own, it is a fixed multiple of the wheel's. When a wheel
    order is clearly louder than it (an engine fault does not excite the
    wheel's own orders, and the wheel order it coincides with is as loud as it
    is), it is that wheel's harmonic and is suppressed whatever the ranking and
    confidence say: those are built under different location rules (a wheel
    order is penalised for spreading into the cabin, an engine zone is not).

    The same holds for an engine order spread over the car (no dominant
    location): scoring exempts it from the spread and diffuse penalties a wheel
    order takes, because an engine is diagnosed as a zone, so neither its
    confidence nor its ranking score can be weighed against a wheel order with
    a dominant corner. When that wheel order is clearly louder than it at the
    wheel's own corner (in the windows both matched), the wheel is the
    vibration and the engine tone the whole car shares is suppressed.
    """
    wheels = [
        (score, finding)
        for score, finding in findings
        if finding.source_normalized in _WHEEL_ORDER_SOURCES
    ]
    best_wheel_conf = max((finding.effective_confidence for _, finding in wheels), default=0.0)
    best_wheel_ranking = max((score for score, _ in wheels), default=0.0)
    located_wheels = [finding for _, finding in wheels if not finding.weak_spatial_separation]
    if best_wheel_conf > 0:
        settings = ORDER_HEURISTIC_SETTINGS
        for index, (ranking_score, finding) in enumerate(findings):
            if finding.source_normalized != VibrationSource.ENGINE:
                continue
            wheel_harmonic = finding.finding_key in wheel_locked_engine_keys and any(
                _level_at_wheel_corner_db(wheel, finding) >= settings.wheel_locked_alias_margin_db
                for _, wheel in wheels
            )
            spread_under_wheel = finding.weak_spatial_separation and any(
                _level_at_wheel_corner_db(wheel, finding) >= settings.spread_engine_alias_margin_db
                for wheel in located_wheels
            )
            if not (wheel_harmonic or spread_under_wheel):
                if ranking_score >= best_wheel_ranking:
                    continue
                if finding.effective_confidence > best_wheel_conf * settings.harmonic_alias_ratio:
                    continue
            new_ranking_score = ranking_score * settings.engine_alias_suppression
            findings[index] = (
                new_ranking_score,
                replace(
                    finding,
                    confidence=finding.effective_confidence * settings.engine_alias_suppression,
                    ranking_score=new_ranking_score,
                ),
            )
    findings.sort(key=lambda item: item[0], reverse=True)
    valid = [item[1] for item in findings if item[1].effective_confidence >= min_confidence]
    return valid[:5]


def _level_at_wheel_corner_db(wheel: DomainFinding, other: DomainFinding) -> float:
    """dB by which *wheel* exceeds *other* at the wheel's strongest corner (-inf if unknown)."""
    location = (
        wheel.location.strongest_location
        if wheel.location is not None
        else wheel.strongest_location
    )
    excess_db = wheel.level_over_db(other, location=location) if location else None
    return -math.inf if excess_db is None else excess_db


def apply_localization_override(
    *,
    suspected_source: VibrationSource,
    per_location_dominant: bool,
    unique_match_locations: set[str],
    connected_locations: set[str],
    matched: int,
    no_wheel_override: bool,
    localization_confidence: float,
    weak_spatial_separation: bool,
    min_match_points: int = ORDER_MIN_MATCH_POINTS,
) -> tuple[float, bool, bool]:
    """Adjust localization confidence when only one connected sensor matched.

    Returns the localization confidence, whether the hotspot is weakly
    separated, and whether that verdict was declared here from the
    per-location evidence. A declared verdict stands at any dominance, so
    scoring must not ease the hotspot's own weak-separation penalty back in
    past its dominance edge.
    """
    settings = ORDER_HEURISTIC_SETTINGS
    wheel_sensor_count = sum(1 for location in connected_locations if is_wheel_location(location))
    if (
        suspected_source == VibrationSource.WHEEL_TIRE
        and per_location_dominant
        and wheel_sensor_count >= 4
        and not no_wheel_override
    ):
        localization_confidence = min(
            1.0,
            settings.dominant_single_location_base
            + settings.dominant_single_location_step * (wheel_sensor_count - 1),
        )
        return localization_confidence, False, True
    if (
        suspected_source == VibrationSource.DRIVELINE
        and per_location_dominant
        and wheel_sensor_count >= 4
        and matched >= min_match_points
    ):
        return localization_confidence, True, True
    if (
        suspected_source == VibrationSource.WHEEL_TIRE
        and per_location_dominant
        and len(unique_match_locations) == 1
        and len(connected_locations) >= 2
        and not no_wheel_override
    ):
        localization_confidence = min(
            1.0,
            settings.dominant_single_location_base
            + settings.dominant_single_location_step * (len(connected_locations) - 1),
        )
        return localization_confidence, False, True
    if (
        suspected_source == VibrationSource.WHEEL_TIRE
        and len(unique_match_locations) == 1
        and len(connected_locations) >= 2
        and matched >= min_match_points
        and not no_wheel_override
    ):
        localization_confidence = max(
            localization_confidence,
            min(
                1.0,
                settings.fallback_single_location_base
                + settings.fallback_single_location_step * (len(connected_locations) - 1),
            ),
        )
        return localization_confidence, False, True
    return localization_confidence, weak_spatial_separation, False
