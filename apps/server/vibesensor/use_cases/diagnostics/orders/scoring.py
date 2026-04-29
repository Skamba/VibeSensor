"""Order-finding scoring and confidence assembly over matched observations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import log1p

from vibesensor.domain import LocationHotspot, VibrationSource
from vibesensor.shared.constants.analysis import MEMS_NOISE_FLOOR_G, SNR_LOG_DIVISOR
from vibesensor.use_cases.diagnostics.location_analysis import (
    LocationAnalysisResult,
    summarize_order_match_locations,
)
from vibesensor.use_cases.diagnostics.orders.heuristics import (
    apply_localization_override,
    detect_diffuse_excitation,
)
from vibesensor.use_cases.diagnostics.orders.matching import OrderMatchAccumulator
from vibesensor.use_cases.diagnostics.orders.physics import OrderHypothesis
from vibesensor.use_cases.diagnostics.orders.statistics import (
    compute_amplitude_and_error_stats,
    compute_order_confidence,
    compute_phase_stats,
)
from vibesensor.vibration_strength import vibration_strength_db_scalar


@dataclass(frozen=True)
class OrderFindingBuildContext:
    """Stable context for scoring and assembling a matched order finding."""

    effective_match_rate: float
    focused_speed_band: str | None
    per_location_dominant: bool
    match_rate: float
    min_match_rate: float
    constant_speed: bool
    steady_speed: bool
    connected_locations: set[str]
    lang: str


@dataclass(frozen=True)
class OrderFindingScore:
    """Typed scoring result consumed by final finding construction."""

    confidence: float
    ranking_score: float
    absolute_strength_db: float
    mean_floor: float
    mean_relative_error: float
    frequency_correlation: float
    phases_with_evidence: int
    per_phase_confidence: dict[str, float] | None
    diffuse_excitation: bool
    weak_spatial_separation: bool
    dominance_ratio: float | None
    location_line: object
    domain_hotspot: LocationHotspot | None
    strongest_location: str
    hotspot_speed_band: str


def _normalized_domain_hotspot(
    loc_result: LocationAnalysisResult | None,
) -> LocationHotspot | None:
    if loc_result is None:
        return None

    domain_hotspot = loc_result.hotspot
    supporting_locations = list(domain_hotspot.alternative_locations)
    if loc_result.second_location and loc_result.second_location not in supporting_locations:
        supporting_locations.append(loc_result.second_location)
    return replace(
        domain_hotspot,
        alternative_locations=tuple(supporting_locations),
        location_count=max(
            1,
            len({domain_hotspot.strongest_location, *supporting_locations} - {""}),
        ),
    )


def score_order_finding(
    hypothesis: OrderHypothesis,
    match: OrderMatchAccumulator,
    *,
    context: OrderFindingBuildContext,
) -> OrderFindingScore:
    """Compute confidence, localization, and ranking inputs for one matched hypothesis."""
    per_phase_confidence, phases_with_evidence = compute_phase_stats(
        match.has_phases,
        match.possible_by_phase,
        match.matched_by_phase,
        min_match_rate=context.min_match_rate,
    )
    mean_amp, mean_floor, mean_rel_err, corr_val, corr = compute_amplitude_and_error_stats(
        match.matched_amp,
        match.matched_floor,
        match.rel_errors,
        match.predicted_vals,
        match.measured_vals,
        match.matched_points,
        constant_speed=context.constant_speed,
    )

    relevant_speed_bins = [context.focused_speed_band] if context.focused_speed_band else None
    location_line, loc_result = summarize_order_match_locations(
        match.matched_points,
        lang=context.lang,
        relevant_speed_bins=relevant_speed_bins,
        connected_locations=context.connected_locations,
        suspected_source=hypothesis.suspected_source,
    )
    domain_hotspot = _normalized_domain_hotspot(loc_result)
    weak_spatial_separation = (
        domain_hotspot.weak_spatial_separation if domain_hotspot is not None else True
    )
    dominance_ratio = domain_hotspot.dominance_ratio if domain_hotspot is not None else None
    localization_confidence = (
        domain_hotspot.localization_confidence or 0.05 if domain_hotspot is not None else 0.05
    )

    unique_match_locations = match.unique_match_locations
    no_wheel_override = loc_result.no_wheel_sensors if loc_result is not None else False
    localization_confidence, weak_spatial_separation = apply_localization_override(
        suspected_source=hypothesis.suspected_source,
        per_location_dominant=context.per_location_dominant,
        unique_match_locations=unique_match_locations,
        connected_locations=context.connected_locations,
        matched=match.matched,
        no_wheel_override=no_wheel_override,
        localization_confidence=localization_confidence,
        weak_spatial_separation=weak_spatial_separation,
    )
    if domain_hotspot is not None:
        domain_hotspot = replace(
            domain_hotspot,
            localization_confidence=localization_confidence,
            weak_spatial_separation=weak_spatial_separation,
        )

    corroborating_locations = len(unique_match_locations)
    error_denominator = 0.25 * match.compliance
    error_score = max(0.0, 1.0 - min(1.0, mean_rel_err / error_denominator))
    snr_score = min(1.0, log1p(mean_amp / max(MEMS_NOISE_FLOOR_G, mean_floor)) / SNR_LOG_DIVISOR)
    if mean_amp <= 2 * MEMS_NOISE_FLOOR_G:
        snr_score = min(snr_score, 0.40)
    absolute_strength_db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=mean_amp,
        floor_amp_g=max(MEMS_NOISE_FLOOR_G, mean_floor),
    )

    diffuse_excitation, diffuse_penalty = detect_diffuse_excitation(
        context.connected_locations,
        match.possible_by_location,
        match.matched_by_location,
        match.matched_points,
    )
    source_expects_diffuse = hypothesis.suspected_source in (
        VibrationSource.ENGINE,
        VibrationSource.DRIVELINE,
    )
    effective_diffuse_penalty = 1.0 if source_expects_diffuse else diffuse_penalty
    confidence = compute_order_confidence(
        effective_match_rate=context.effective_match_rate,
        error_score=error_score,
        corr_val=corr_val,
        snr_score=snr_score,
        absolute_strength_db=absolute_strength_db,
        localization_confidence=localization_confidence,
        weak_spatial_separation=weak_spatial_separation,
        dominance_ratio=dominance_ratio,
        constant_speed=context.constant_speed,
        steady_speed=context.steady_speed,
        matched=match.matched,
        corroborating_locations=corroborating_locations,
        phases_with_evidence=phases_with_evidence,
        is_diffuse_excitation=diffuse_excitation,
        diffuse_penalty=effective_diffuse_penalty,
        n_connected_locations=len(context.connected_locations),
        no_wheel_sensors=no_wheel_override,
        path_compliance=match.compliance,
    )

    ranking_score = (
        context.effective_match_rate
        * log1p(mean_amp / max(MEMS_NOISE_FLOOR_G, mean_floor))
        * max(0.0, (1.0 - min(1.0, mean_rel_err / (0.25 * match.compliance))))
    )

    return OrderFindingScore(
        confidence=confidence,
        ranking_score=ranking_score,
        absolute_strength_db=absolute_strength_db,
        mean_floor=mean_floor,
        mean_relative_error=mean_rel_err,
        frequency_correlation=corr or 0.0,
        phases_with_evidence=phases_with_evidence,
        per_phase_confidence=per_phase_confidence,
        diffuse_excitation=diffuse_excitation,
        weak_spatial_separation=weak_spatial_separation,
        dominance_ratio=dominance_ratio,
        location_line=location_line,
        domain_hotspot=domain_hotspot,
        strongest_location=loc_result.display_location if loc_result is not None else "",
        hotspot_speed_band=loc_result.speed_range if loc_result is not None else "",
    )
