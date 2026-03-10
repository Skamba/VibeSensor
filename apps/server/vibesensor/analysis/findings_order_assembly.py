"""Assembly of matched order evidence into final diagnosis findings."""

from __future__ import annotations

from collections.abc import Callable
from math import log1p

from vibesensor.core.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ..constants import MEMS_NOISE_FLOOR_G
from ..domain_models import as_float_or_none as _as_float
from ._types import Finding, JsonValue, LocationHotspot, PhaseEvidence
from .findings_constants import SNR_LOG_DIVISOR
from .findings_order_models import OrderFindingBuildContext, OrderMatchAccumulator
from .order_analysis import (
    OrderHypothesis,
    _finding_actions_for_source,
    _i18n_ref,
    _order_label,
)


def assemble_order_finding(
    hypothesis: OrderHypothesis,
    match: OrderMatchAccumulator,
    *,
    context: OrderFindingBuildContext,
    location_speedbin_summary: Callable[..., tuple[object, LocationHotspot | None]],
    compute_phase_stats: Callable[..., tuple[dict[str, float] | None, int]],
    compute_amplitude_and_error_stats: Callable[
        ...,
        tuple[float, float, float, float, float | None],
    ],
    apply_localization_override: Callable[..., tuple[float, bool]],
    detect_diffuse_excitation: Callable[..., tuple[bool, float]],
    compute_order_confidence: Callable[..., float],
    compute_matched_speed_phase_evidence: Callable[
        ...,
        tuple[float | None, list[float], str | None, PhaseEvidence, str | None],
    ],
) -> tuple[float, Finding]:
    """Build a single order finding from a successful match result."""
    per_phase_confidence, phases_with_evidence = compute_phase_stats(
        match.has_phases,
        match.possible_by_phase,
        match.matched_by_phase,
        context.min_match_rate,
    )
    mean_amp, mean_floor, mean_rel_err, corr_val, corr = compute_amplitude_and_error_stats(
        match.matched_amp,
        match.matched_floor,
        match.rel_errors,
        match.predicted_vals,
        match.measured_vals,
        match.matched_points,
        context.constant_speed,
    )

    relevant_speed_bins = [context.focused_speed_band] if context.focused_speed_band else None
    location_line, location_hotspot = location_speedbin_summary(
        match.matched_points,
        lang=context.lang,
        relevant_speed_bins=relevant_speed_bins,
        connected_locations=context.connected_locations,
        suspected_source=hypothesis.suspected_source,
    )
    hotspot_dict = location_hotspot if isinstance(location_hotspot, dict) else None
    weak_spatial_separation = (
        bool(hotspot_dict.get("weak_spatial_separation")) if hotspot_dict is not None else True
    )
    dominance_ratio = (
        _as_float(hotspot_dict.get("dominance_ratio")) if hotspot_dict is not None else None
    )
    localization_confidence = (
        _as_float(hotspot_dict.get("localization_confidence")) or 0.05
        if hotspot_dict is not None
        else 0.05
    )

    unique_match_locations = {
        str(point.get("location") or "") for point in match.matched_points if point.get("location")
    }
    no_wheel_override = (
        bool(hotspot_dict.get("no_wheel_sensors")) if hotspot_dict is not None else False
    )
    localization_confidence, weak_spatial_separation = apply_localization_override(
        context.per_location_dominant,
        unique_match_locations,
        context.connected_locations,
        match.matched,
        no_wheel_override,
        localization_confidence,
        weak_spatial_separation,
    )

    corroborating_locations = len(unique_match_locations)
    error_denominator = 0.25 * match.compliance
    error_score = max(0.0, 1.0 - min(1.0, mean_rel_err / error_denominator))
    snr_score = min(1.0, log1p(mean_amp / max(MEMS_NOISE_FLOOR_G, mean_floor)) / SNR_LOG_DIVISOR)
    if mean_amp <= 2 * MEMS_NOISE_FLOOR_G:
        snr_score = min(snr_score, 0.40)
    absolute_strength_db = canonical_vibration_db(
        peak_band_rms_amp_g=mean_amp,
        floor_amp_g=max(MEMS_NOISE_FLOOR_G, mean_floor),
    )

    diffuse_excitation, diffuse_penalty = detect_diffuse_excitation(
        context.connected_locations,
        match.possible_by_location,
        match.matched_by_location,
        match.matched_points,
    )
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
        diffuse_penalty=diffuse_penalty,
        n_connected_locations=len(context.connected_locations),
        no_wheel_sensors=no_wheel_override,
        path_compliance=match.compliance,
    )

    ranking_score = (
        context.effective_match_rate
        * log1p(mean_amp / max(MEMS_NOISE_FLOOR_G, mean_floor))
        * max(0.0, (1.0 - min(1.0, mean_rel_err / (0.25 * match.compliance))))
    )

    ref_text = ", ".join(sorted(match.ref_sources))
    evidence = _i18n_ref(
        "EVIDENCE_ORDER_TRACKED",
        order_label=_order_label(hypothesis.order, hypothesis.order_label_base),
        matched=match.matched,
        possible=match.possible,
        match_rate=context.effective_match_rate,
        mean_rel_err=mean_rel_err,
        ref_text=ref_text,
    )
    if location_line:
        evidence = dict(evidence)
        evidence["_suffix"] = f" {location_line}"

    strongest_location = str(hotspot_dict.get("location")) if hotspot_dict is not None else ""
    hotspot_speed_band = str(hotspot_dict.get("speed_range")) if hotspot_dict is not None else ""
    (
        peak_speed_kmh,
        speed_window_kmh,
        strongest_speed_band,
        phase_evidence,
        dominant_phase,
    ) = compute_matched_speed_phase_evidence(
        match.matched_points,
        focused_speed_band=context.focused_speed_band,
        hotspot_speed_band=hotspot_speed_band,
    )
    actions = _finding_actions_for_source(
        hypothesis.suspected_source,
        strongest_location=strongest_location,
        strongest_speed_band=strongest_speed_band or "",
        weak_spatial_separation=weak_spatial_separation,
    )
    quick_checks: list[JsonValue] = [action["what"] for action in actions if action.get("what")][:3]
    finding: Finding = {
        "finding_id": "F_ORDER",
        "finding_key": hypothesis.key,
        "suspected_source": hypothesis.suspected_source,
        "evidence_summary": evidence,
        "frequency_hz_or_order": _order_label(hypothesis.order, hypothesis.order_label_base),
        "amplitude_metric": {
            "name": "vibration_strength_db",
            "value": absolute_strength_db,
            "units": "dB",
            "definition": _i18n_ref("METRIC_VIBRATION_STRENGTH_DB"),
        },
        "confidence_0_to_1": confidence,
        "quick_checks": quick_checks,
        "matched_points": match.matched_points,
        "location_hotspot": hotspot_dict,
        "strongest_location": strongest_location or None,
        "strongest_speed_band": strongest_speed_band or None,
        "dominant_phase": dominant_phase,
        "peak_speed_kmh": peak_speed_kmh,
        "speed_window_kmh": list(speed_window_kmh) if speed_window_kmh else None,
        "dominance_ratio": dominance_ratio,
        "localization_confidence": localization_confidence,
        "weak_spatial_separation": weak_spatial_separation,
        "corroborating_locations": corroborating_locations,
        "diffuse_excitation": diffuse_excitation,
        "phase_evidence": phase_evidence,
        "evidence_metrics": {
            "match_rate": context.effective_match_rate,
            "global_match_rate": context.match_rate,
            "focused_speed_band": context.focused_speed_band,
            "mean_relative_error": mean_rel_err,
            "mean_noise_floor_db": canonical_vibration_db(
                peak_band_rms_amp_g=max(MEMS_NOISE_FLOOR_G, mean_floor),
                floor_amp_g=MEMS_NOISE_FLOOR_G,
            ),
            "vibration_strength_db": absolute_strength_db,
            "possible_samples": match.possible,
            "matched_samples": match.matched,
            "frequency_correlation": corr,
            "per_phase_confidence": per_phase_confidence,
            "phases_with_evidence": phases_with_evidence,
        },
        "next_sensor_move": (
            actions[0].get("what") if actions else _i18n_ref("NEXT_SENSOR_MOVE_DEFAULT")
        ),
        "actions": actions,
        "_ranking_score": ranking_score,
    }
    return ranking_score, finding
