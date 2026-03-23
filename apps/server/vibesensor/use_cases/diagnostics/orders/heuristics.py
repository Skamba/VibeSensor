"""Heuristic filters and tuning constants for order-tracking analysis."""

from __future__ import annotations

from dataclasses import replace

from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain import OrderMatchObservation, VibrationSource
from vibesensor.shared.constants import ORDER_MIN_CONFIDENCE, ORDER_MIN_MATCH_POINTS
from vibesensor.use_cases.diagnostics.math_utils import _mean
from vibesensor.use_cases.diagnostics.orders.settings import ORDER_HEURISTIC_SETTINGS


def _normalized_source(finding: DomainFinding) -> str:
    src: str = finding.source_normalized
    return src


def detect_diffuse_excitation(
    connected_locations: set[str],
    possible_by_location: dict[str, int],
    matched_by_location: dict[str, int],
    matched_points: list[OrderMatchObservation],
    *,
    min_match_points: int = ORDER_MIN_MATCH_POINTS,
) -> tuple[bool, float]:
    """Detect diffuse, non-localized excitation across multiple sensors."""
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
    amp_uniform = True
    if loc_mean_amps and len(loc_mean_amps) >= 2:
        max_amp = max(loc_mean_amps.values())
        min_amp = min(loc_mean_amps.values())
        if min_amp > 0 and max_amp / min_amp > settings.diffuse_amplitude_dominance_ratio:
            amp_uniform = False
    if (
        rate_range < settings.diffuse_match_rate_range_threshold
        and mean_rate > settings.diffuse_min_mean_rate
        and amp_uniform
    ):
        penalty = max(
            settings.diffuse_penalty_floor,
            settings.diffuse_penalty_base - settings.diffuse_penalty_per_sensor * len(loc_rates),
        )
        return True, penalty
    return False, 1.0


def suppress_engine_aliases(
    findings: list[tuple[float, DomainFinding]],
    *,
    min_confidence: float = ORDER_MIN_CONFIDENCE,
) -> list[DomainFinding]:
    """Suppress engine findings likely to be aliases of stronger wheel findings.

    Engine findings whose ranking score is at least as high as the best wheel
    finding are kept intact — a better ranking score indicates superior
    frequency tracking, meaning the engine hypothesis is a better physical
    explanation than the coincidentally close wheel harmonic.
    """
    best_wheel_conf = max(
        (
            finding.effective_confidence
            for _, finding in findings
            if _normalized_source(finding) == VibrationSource.WHEEL_TIRE
        ),
        default=0.0,
    )
    best_wheel_ranking = max(
        (
            score
            for score, finding in findings
            if _normalized_source(finding) == VibrationSource.WHEEL_TIRE
        ),
        default=0.0,
    )
    if best_wheel_conf > 0:
        settings = ORDER_HEURISTIC_SETTINGS
        for index, (ranking_score, finding) in enumerate(findings):
            if _normalized_source(finding) != VibrationSource.ENGINE:
                continue
            if ranking_score >= best_wheel_ranking:
                continue
            eng_conf = finding.effective_confidence
            if eng_conf <= best_wheel_conf * settings.harmonic_alias_ratio:
                suppressed = eng_conf * settings.engine_alias_suppression
                new_ranking_score = ranking_score * settings.engine_alias_suppression
                finding = replace(
                    finding,
                    confidence=suppressed,
                    ranking_score=new_ranking_score,
                )
                findings[index] = (new_ranking_score, finding)
    findings.sort(key=lambda item: item[0], reverse=True)
    valid = [item[1] for item in findings if item[1].effective_confidence >= min_confidence]
    return valid[:5]


def apply_localization_override(
    *,
    per_location_dominant: bool,
    unique_match_locations: set[str],
    connected_locations: set[str],
    matched: int,
    no_wheel_override: bool,
    localization_confidence: float,
    weak_spatial_separation: bool,
    min_match_points: int = ORDER_MIN_MATCH_POINTS,
) -> tuple[float, bool]:
    """Adjust localization confidence when only one connected sensor matched."""
    settings = ORDER_HEURISTIC_SETTINGS
    if (
        per_location_dominant
        and len(unique_match_locations) == 1
        and len(connected_locations) >= 2
        and not no_wheel_override
    ):
        localization_confidence = min(
            1.0,
            settings.dominant_single_location_base
            + settings.dominant_single_location_step * (len(connected_locations) - 1),
        )
        weak_spatial_separation = False
    elif (
        len(unique_match_locations) == 1
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
        weak_spatial_separation = False
    return localization_confidence, weak_spatial_separation
