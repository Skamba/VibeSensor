"""Order-tracking hypothesis matching engine.

Matches vibration peaks against predicted frequencies for wheel, driveshaft,
and engine orders; computes confidence scores; suppresses engine aliases.
"""

from __future__ import annotations

from math import log1p

from vibesensor.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ..constants import (
    CONSTANT_SPEED_STDDEV_KMH,
    MEMS_NOISE_FLOOR_G,
    ORDER_CONSTANT_SPEED_MIN_MATCH_RATE,
    ORDER_MIN_CONFIDENCE,
    ORDER_MIN_COVERAGE_POINTS,
    ORDER_MIN_MATCH_POINTS,
    SNR_LOG_DIVISOR,
)
from ..domain_models import as_float_or_none as _as_float
from ._types import Finding, JsonValue, MetadataDict, PhaseLabels, Sample
from .findings_order_analysis import (
    OrderFindingBuildContext,
    OrderMatchAccumulator,
    apply_localization_override,
    compute_amplitude_and_error_stats,
    compute_matched_speed_phase_evidence,
    compute_order_confidence,
    compute_phase_stats,
    detect_diffuse_excitation,
    match_samples_for_hypothesis,
    suppress_engine_aliases,
)
from .helpers import _sample_top_peaks, _speed_bin_sort_key
from .order_analysis import (
    OrderHypothesis,
    _finding_actions_for_source,
    _i18n_ref,
    _order_hypotheses,
    _order_label,
)
from .test_plan import _location_speedbin_summary


def assemble_order_finding(
    hypothesis: OrderHypothesis,
    match: OrderMatchAccumulator,
    *,
    context: OrderFindingBuildContext,
) -> tuple[float, Finding]:
    """Build a single order finding from a successful match result."""
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
    location_line, location_hotspot = _location_speedbin_summary(
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
        per_location_dominant=context.per_location_dominant,
        unique_match_locations=unique_match_locations,
        connected_locations=context.connected_locations,
        matched=match.matched,
        no_wheel_override=no_wheel_override,
        localization_confidence=localization_confidence,
        weak_spatial_separation=weak_spatial_separation,
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


def _compute_effective_match_rate(
    match_rate: float,
    min_match_rate: float,
    possible_by_speed_bin: dict[str, int],
    matched_by_speed_bin: dict[str, int],
    possible_by_location: dict[str, int],
    matched_by_location: dict[str, int],
) -> tuple[float, str | None, bool]:
    """Rescue a below-threshold match rate via focused speed-band or per-location evidence.

    Returns (effective_match_rate, focused_speed_band, per_location_dominant).
    """
    effective_match_rate = match_rate
    focused_speed_band: str | None = None
    if match_rate < min_match_rate and possible_by_speed_bin:
        highest_speed_bin = max(possible_by_speed_bin.keys(), key=_speed_bin_sort_key)
        focused_possible = int(possible_by_speed_bin[highest_speed_bin])
        focused_matched = int(matched_by_speed_bin.get(highest_speed_bin, 0))
        focused_rate = focused_matched / max(1, focused_possible)
        min_focused_possible = max(ORDER_MIN_MATCH_POINTS, ORDER_MIN_COVERAGE_POINTS // 2)
        if (
            focused_possible >= min_focused_possible
            and focused_matched >= ORDER_MIN_MATCH_POINTS
            and focused_rate >= min_match_rate
        ):
            focused_speed_band = highest_speed_bin
            effective_match_rate = focused_rate
    per_location_dominant: bool = False
    if effective_match_rate < min_match_rate and possible_by_location:
        best_loc_rate = 0.0
        for loc, loc_possible in possible_by_location.items():
            loc_matched = matched_by_location.get(loc, 0)
            if loc_possible >= ORDER_MIN_COVERAGE_POINTS and loc_matched >= ORDER_MIN_MATCH_POINTS:
                loc_rate = loc_matched / max(1, loc_possible)
                best_loc_rate = max(best_loc_rate, loc_rate)
        if best_loc_rate >= min_match_rate:
            effective_match_rate = best_loc_rate
            per_location_dominant = True
    return effective_match_rate, focused_speed_band, per_location_dominant


def _build_order_findings(
    *,
    metadata: MetadataDict,
    samples: list[Sample],
    speed_sufficient: bool,
    steady_speed: bool,
    speed_stddev_kmh: float | None,
    tire_circumference_m: float | None,
    engine_ref_sufficient: bool,
    raw_sample_rate_hz: float | None,
    connected_locations: set[str],
    lang: str,
    per_sample_phases: PhaseLabels | None = None,
) -> list[Finding]:
    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        return []

    # Pre-compute peaks for every sample once so that the inner hypothesis
    # loop does not redundantly call _sample_top_peaks() for each hypothesis.
    cached_peaks: list[list[tuple[float, float]]] = [_sample_top_peaks(s) for s in samples]

    findings: list[tuple[float, Finding]] = []
    for hypothesis in _order_hypotheses():
        if hypothesis.key.startswith(("wheel_", "driveshaft_")) and (
            not speed_sufficient or tire_circumference_m is None or tire_circumference_m <= 0
        ):
            continue
        if hypothesis.key.startswith("engine_") and not engine_ref_sufficient:
            continue

        m = match_samples_for_hypothesis(
            samples,
            cached_peaks,
            hypothesis,
            metadata,
            tire_circumference_m,
            per_sample_phases,
            lang,
        )

        if m.possible < ORDER_MIN_COVERAGE_POINTS or m.matched < ORDER_MIN_MATCH_POINTS:
            continue
        match_rate = m.matched / max(1, m.possible)
        # At constant speed the predicted frequency never varies, so random
        # broadband peaks match by chance at ~30-40%.  A genuine order source
        # would be present in the vast majority of samples.  Require a much
        # higher match rate before claiming a finding.
        constant_speed = (
            speed_stddev_kmh is not None and speed_stddev_kmh < CONSTANT_SPEED_STDDEV_KMH
        )
        min_match_rate = ORDER_CONSTANT_SPEED_MIN_MATCH_RATE if constant_speed else 0.25
        effective_match_rate, focused_speed_band, per_location_dominant = (
            _compute_effective_match_rate(
                match_rate,
                min_match_rate,
                m.possible_by_speed_bin,
                m.matched_by_speed_bin,
                m.possible_by_location,
                m.matched_by_location,
            )
        )
        if effective_match_rate < min_match_rate:
            continue

        ranking_score, finding = assemble_order_finding(
            hypothesis,
            m,
            context=OrderFindingBuildContext(
                effective_match_rate=effective_match_rate,
                focused_speed_band=focused_speed_band,
                per_location_dominant=per_location_dominant,
                match_rate=match_rate,
                min_match_rate=min_match_rate,
                constant_speed=constant_speed,
                steady_speed=steady_speed,
                connected_locations=connected_locations,
                lang=lang,
            ),
        )
        findings.append((ranking_score, finding))

    return suppress_engine_aliases(findings, min_confidence=ORDER_MIN_CONFIDENCE)
