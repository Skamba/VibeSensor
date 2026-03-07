"""Order-tracking hypothesis matching engine.

Matches vibration peaks against predicted frequencies for wheel, driveshaft,
and engine orders; computes confidence scores; suppresses engine aliases.
"""

from __future__ import annotations

from collections import defaultdict
from math import log1p
from typing import Any, TypedDict

from vibesensor_core.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ...constants import MEMS_NOISE_FLOOR_G
from ...runlog import as_float_or_none as _as_float
from .._types import PhaseLabels
from ..helpers import (
    CONSTANT_SPEED_STDDEV_KMH,
    ORDER_CONSTANT_SPEED_MIN_MATCH_RATE,
    ORDER_MIN_CONFIDENCE,
    ORDER_MIN_COVERAGE_POINTS,
    ORDER_MIN_MATCH_POINTS,
    ORDER_TOLERANCE_MIN_HZ,
    ORDER_TOLERANCE_REL,
    _corr_abs_clamped,
    _estimate_strength_floor_amp_g,
    _location_label,
    _sample_top_peaks,
    _speed_bin_label,
    _speed_bin_sort_key,
)
from ..order_analysis import (
    _finding_actions_for_source,
    _i18n_ref,
    _order_hypotheses,
    _order_label,
)
from ..test_plan import _location_speedbin_summary
from ._constants import (
    _SNR_LOG_DIVISOR,
)
from .order_scoring import (
    _NEGLIGIBLE_STRENGTH_CONF_CAP as _NEGLIGIBLE_STRENGTH_CONF_CAP_IMPORTED,
)
from .order_scoring import (
    compute_order_confidence as _compute_order_confidence_impl,
)
from .order_scoring import (
    detect_diffuse_excitation as _detect_diffuse_excitation_impl,
)
from .order_scoring import (
    suppress_engine_aliases as _suppress_engine_aliases_impl,
)
from .order_support import (
    apply_localization_override as _apply_localization_override_impl,
)
from .order_support import (
    compute_amplitude_and_error_stats as _compute_amplitude_and_error_stats_impl,
)
from .order_support import (
    compute_matched_speed_phase_evidence as _compute_matched_speed_phase_evidence_impl,
)
from .order_support import (
    compute_phase_stats as _compute_phase_stats_impl,
)
from .speed_profile import _phase_to_str, _speed_profile_from_points

_NEGLIGIBLE_STRENGTH_CONF_CAP = _NEGLIGIBLE_STRENGTH_CONF_CAP_IMPORTED

# Source-audit note: the delegated scoring implementation still applies
# min(confidence, _NEGLIGIBLE_STRENGTH_CONF_CAP) for negligible-strength findings.

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class MatchAccumulator(TypedDict):
    """Accumulated statistics from matching a hypothesis against all samples.

    Returned by :func:`_match_samples_for_hypothesis` and consumed by
    :func:`_build_order_findings` to compute confidence and assemble findings.
    """

    possible: int
    matched: int
    matched_amp: list[float]
    matched_floor: list[float]
    rel_errors: list[float]
    predicted_vals: list[float]
    measured_vals: list[float]
    matched_points: list[dict[str, Any]]
    ref_sources: set[str]
    possible_by_speed_bin: dict[str, int]
    matched_by_speed_bin: dict[str, int]
    possible_by_phase: dict[str, int]
    matched_by_phase: dict[str, int]
    possible_by_location: dict[str, int]
    matched_by_location: dict[str, int]
    has_phases: bool
    compliance: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
                if loc_rate > best_loc_rate:
                    best_loc_rate = loc_rate
        if best_loc_rate >= min_match_rate:
            effective_match_rate = best_loc_rate
            per_location_dominant = True
    return effective_match_rate, focused_speed_band, per_location_dominant


def _detect_diffuse_excitation(
    connected_locations: set[str],
    possible_by_location: dict[str, int],
    matched_by_location: dict[str, int],
    matched_points: list[dict[str, Any]],
) -> tuple[bool, float]:
    return _detect_diffuse_excitation_impl(
        connected_locations,
        possible_by_location,
        matched_by_location,
        matched_points,
        min_match_points=ORDER_MIN_MATCH_POINTS,
    )


def _compute_order_confidence(
    *,
    effective_match_rate: float,
    error_score: float,
    corr_val: float,
    snr_score: float,
    absolute_strength_db: float,
    localization_confidence: float,
    weak_spatial_separation: bool,
    dominance_ratio: float | None,
    constant_speed: bool,
    steady_speed: bool,
    matched: int,
    corroborating_locations: int,
    phases_with_evidence: int,
    is_diffuse_excitation: bool,
    diffuse_penalty: float,
    n_connected_locations: int,
    no_wheel_sensors: bool = False,
    path_compliance: float = 1.0,
) -> float:
    return _compute_order_confidence_impl(
        effective_match_rate=effective_match_rate,
        error_score=error_score,
        corr_val=corr_val,
        snr_score=snr_score,
        absolute_strength_db=absolute_strength_db,
        localization_confidence=localization_confidence,
        weak_spatial_separation=weak_spatial_separation,
        dominance_ratio=dominance_ratio,
        constant_speed=constant_speed,
        steady_speed=steady_speed,
        matched=matched,
        corroborating_locations=corroborating_locations,
        phases_with_evidence=phases_with_evidence,
        is_diffuse_excitation=is_diffuse_excitation,
        diffuse_penalty=diffuse_penalty,
        n_connected_locations=n_connected_locations,
        no_wheel_sensors=no_wheel_sensors,
        path_compliance=path_compliance,
    )


def _suppress_engine_aliases(
    findings: list[tuple[float, dict[str, Any]]],
) -> list[dict[str, Any]]:
    return _suppress_engine_aliases_impl(findings, min_confidence=ORDER_MIN_CONFIDENCE)


def _compute_matched_speed_phase_evidence(
    matched_points: list[dict[str, Any]],
    *,
    focused_speed_band: str | None,
    hotspot_speed_band: str,
) -> tuple[float | None, list[float], str | None, dict[str, Any], str | None]:
    return _compute_matched_speed_phase_evidence_impl(
        matched_points,
        focused_speed_band=focused_speed_band,
        hotspot_speed_band=hotspot_speed_band,
        speed_profile_from_points=_speed_profile_from_points,
    )


def _match_samples_for_hypothesis(
    samples: list[dict[str, Any]],
    cached_peaks: list[list[tuple[float, float]]],
    hypothesis: Any,
    metadata: dict[str, Any],
    tire_circumference_m: float | None,
    per_sample_phases: PhaseLabels | None,
    lang: str,
) -> MatchAccumulator:
    """Match hypothesis order frequencies against each sample's top peaks.

    Iterates over all samples once, accumulating match counts, amplitudes,
    relative errors, per-speed-bin and per-location statistics, and the
    matched-points list used for downstream confidence and localization.

    Returns a dict of accumulated statistics with the following keys:

    - ``possible``, ``matched``: total possible/matched sample counts
    - ``matched_amp``, ``matched_floor``: amplitude and noise-floor lists for matched samples
    - ``rel_errors``, ``predicted_vals``, ``measured_vals``: error and frequency tracking lists
    - ``matched_points``: list of per-match detail dicts
    - ``ref_sources``: set of reference-source labels used to predict frequencies
    - ``possible_by_speed_bin``, ``matched_by_speed_bin``: per-speed-bin counters
    - ``possible_by_phase``, ``matched_by_phase``: per-phase counters
    - ``possible_by_location``, ``matched_by_location``: per-sensor-location counters
    - ``has_phases``: whether per-sample phase labels were applied
    - ``compliance``: mechanical path compliance factor from the hypothesis
    """
    possible = 0
    matched = 0
    matched_amp: list[float] = []
    matched_floor: list[float] = []
    rel_errors: list[float] = []
    predicted_vals: list[float] = []
    measured_vals: list[float] = []
    matched_points: list[dict[str, Any]] = []
    ref_sources: set[str] = set()
    possible_by_speed_bin: dict[str, int] = defaultdict(int)
    matched_by_speed_bin: dict[str, int] = defaultdict(int)
    possible_by_phase: dict[str, int] = defaultdict(int)
    matched_by_phase: dict[str, int] = defaultdict(int)
    # Per-location tracking: multi-sensor runs dilute the global match rate
    # because only the fault sensor matches.  Track per-location stats so we
    # can recognise a single-sensor signal even when the global rate is low.
    possible_by_location: dict[str, int] = defaultdict(int)
    matched_by_location: dict[str, int] = defaultdict(int)
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)
    compliance = getattr(hypothesis, "path_compliance", 1.0)
    # Scale tolerance by sqrt(compliance) — a conservative widening
    # for mechanically compliant paths (wheel/bushing) without
    # inflating false-positive match rates excessively.
    compliance_scale = compliance**0.5

    for sample_idx, sample in enumerate(samples):
        peaks = cached_peaks[sample_idx]
        if not peaks:
            continue
        predicted_hz, ref_source = hypothesis.predicted_hz(
            sample,
            metadata,
            tire_circumference_m,
        )
        if predicted_hz is None or predicted_hz <= 0:
            continue
        possible += 1
        ref_sources.add(ref_source)
        sample_location = _location_label(sample, lang=lang)
        if sample_location:
            possible_by_location[sample_location] += 1
        sample_speed = _as_float(sample.get("speed_kmh"))
        sample_speed_bin = (
            _speed_bin_label(sample_speed)
            if sample_speed is not None and sample_speed > 0
            else None
        )
        if sample_speed_bin is not None:
            possible_by_speed_bin[sample_speed_bin] += 1
        if has_phases:
            assert per_sample_phases is not None
            ph = per_sample_phases[sample_idx]
            phase_key = str(ph.value if hasattr(ph, "value") else ph)
            possible_by_phase[phase_key] += 1

        tolerance_hz = max(
            ORDER_TOLERANCE_MIN_HZ,
            predicted_hz * ORDER_TOLERANCE_REL * compliance_scale,
        )
        best_hz, best_amp = min(peaks, key=lambda item: abs(item[0] - predicted_hz))
        delta_hz = abs(best_hz - predicted_hz)
        if delta_hz > tolerance_hz:
            continue

        matched += 1
        if sample_location:
            matched_by_location[sample_location] += 1
        if sample_speed_bin is not None:
            matched_by_speed_bin[sample_speed_bin] += 1
        if has_phases:
            matched_by_phase[phase_key] += 1
        rel_errors.append(delta_hz / max(1e-9, predicted_hz))
        matched_amp.append(best_amp)
        _floor_est = _estimate_strength_floor_amp_g(sample)
        floor_amp = _floor_est if _floor_est is not None else 0.0
        matched_floor.append(max(0.0, floor_amp))
        predicted_vals.append(predicted_hz)
        measured_vals.append(best_hz)
        sample_phase: str | None = None
        # Only assign phase when has_phases is True (lengths verified equal),
        # otherwise matched_points would have inconsistent phase coverage.
        if has_phases:
            assert per_sample_phases is not None
            sample_phase = _phase_to_str(per_sample_phases[sample_idx])
        matched_points.append(
            {
                "t_s": _as_float(sample.get("t_s")),
                "speed_kmh": _as_float(sample.get("speed_kmh")),
                "predicted_hz": predicted_hz,
                "matched_hz": best_hz,
                "rel_error": delta_hz / max(1e-9, predicted_hz),
                "amp": best_amp,
                "location": sample_location,
                "phase": sample_phase,
            }
        )

    return {
        "possible": possible,
        "matched": matched,
        "matched_amp": matched_amp,
        "matched_floor": matched_floor,
        "rel_errors": rel_errors,
        "predicted_vals": predicted_vals,
        "measured_vals": measured_vals,
        "matched_points": matched_points,
        "ref_sources": ref_sources,
        "possible_by_speed_bin": dict(possible_by_speed_bin),
        "matched_by_speed_bin": dict(matched_by_speed_bin),
        "possible_by_phase": dict(possible_by_phase),
        "matched_by_phase": dict(matched_by_phase),
        "possible_by_location": dict(possible_by_location),
        "matched_by_location": dict(matched_by_location),
        "has_phases": has_phases,
        "compliance": compliance,
    }


def _compute_phase_stats(
    has_phases: bool,
    possible_by_phase: dict[str, int],
    matched_by_phase: dict[str, int],
    min_match_rate: float,
) -> tuple[dict[str, float] | None, int]:
    return _compute_phase_stats_impl(
        has_phases,
        possible_by_phase,
        matched_by_phase,
        min_match_rate=min_match_rate,
        min_match_points=ORDER_MIN_MATCH_POINTS,
    )


def _compute_amplitude_and_error_stats(
    matched_amp: list[float],
    matched_floor: list[float],
    rel_errors: list[float],
    predicted_vals: list[float],
    measured_vals: list[float],
    matched_points: list[dict[str, Any]],
    constant_speed: bool,
) -> tuple[float, float, float, float, float | None]:
    return _compute_amplitude_and_error_stats_impl(
        matched_amp,
        matched_floor,
        rel_errors,
        predicted_vals,
        measured_vals,
        matched_points,
        constant_speed=constant_speed,
        corr_abs_clamped=_corr_abs_clamped,
    )


def _apply_localization_override(
    per_location_dominant: bool,
    unique_match_locations: set[str],
    connected_locations: set[str],
    matched: int,
    no_wheel_override: bool,
    localization_confidence: float,
    weak_spatial_separation: bool,
) -> tuple[float, bool]:
    return _apply_localization_override_impl(
        per_location_dominant=per_location_dominant,
        unique_match_locations=unique_match_locations,
        connected_locations=connected_locations,
        matched=matched,
        no_wheel_override=no_wheel_override,
        localization_confidence=localization_confidence,
        weak_spatial_separation=weak_spatial_separation,
        min_match_points=ORDER_MIN_MATCH_POINTS,
    )


def _assemble_order_finding(
    hypothesis: Any,
    m: MatchAccumulator,
    *,
    effective_match_rate: float,
    focused_speed_band: str | None,
    per_location_dominant: bool,
    match_rate: float,
    min_match_rate: float,
    constant_speed: bool,
    steady_speed: bool,
    connected_locations: set[str],
    lang: str,
) -> tuple[float, dict[str, Any]]:
    """Build a single order finding from a successful match result.

    Called by :func:`_build_order_findings` for each hypothesis that passes the
    effective-match-rate threshold.  Delegates per-phase stats, amplitude stats,
    and localization override to dedicated helpers; assembles the final finding
    dict and returns ``(ranking_score, finding_dict)``.
    """
    possible = m["possible"]
    matched = m["matched"]
    matched_amp = m["matched_amp"]
    matched_floor = m["matched_floor"]
    rel_errors = m["rel_errors"]
    predicted_vals = m["predicted_vals"]
    measured_vals = m["measured_vals"]
    matched_points = m["matched_points"]
    ref_sources = m["ref_sources"]
    possible_by_phase = m["possible_by_phase"]
    matched_by_phase = m["matched_by_phase"]
    possible_by_location = m["possible_by_location"]
    matched_by_location = m["matched_by_location"]
    has_phases = m["has_phases"]
    compliance = m["compliance"]

    # Phase evidence
    per_phase_confidence, phases_with_evidence = _compute_phase_stats(
        has_phases, possible_by_phase, matched_by_phase, min_match_rate
    )

    # Amplitude / error / correlation statistics
    mean_amp, mean_floor, mean_rel_err, corr_val, corr = _compute_amplitude_and_error_stats(
        matched_amp,
        matched_floor,
        rel_errors,
        predicted_vals,
        measured_vals,
        matched_points,
        constant_speed,
    )

    # Compute location hotspot BEFORE confidence so spatial info is available.
    # When order evidence is accepted via focused high-speed coverage,
    # localize within that same speed band to avoid low-speed road-noise
    # bins dominating strongest-location selection.
    relevant_speed_bins = [focused_speed_band] if focused_speed_band else None
    location_line, location_hotspot = _location_speedbin_summary(
        matched_points,
        lang=lang,
        relevant_speed_bins=relevant_speed_bins,
        connected_locations=connected_locations,
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

    # Single-sensor dominance override: absence of matches from other connected
    # sensors is strong spatial evidence even when the hotspot formula cannot
    # compute a dominance ratio.  Exception: wheel/tire without wheel sensors.
    unique_match_locations = {
        str(pt.get("location") or "") for pt in matched_points if pt.get("location")
    }
    _no_wheel_override = (
        bool(hotspot_dict.get("no_wheel_sensors")) if hotspot_dict is not None else False
    )
    localization_confidence, weak_spatial_separation = _apply_localization_override(
        per_location_dominant,
        unique_match_locations,
        connected_locations,
        matched,
        _no_wheel_override,
        localization_confidence,
        weak_spatial_separation,
    )

    # Count how many distinct locations independently detected this order
    corroborating_locations = len(
        {str(pt.get("location") or "") for pt in matched_points if pt.get("location")}
    )

    # Error score: compliant paths (wheel through suspension) produce
    # broader peaks that wander more across FFT bins, so we use a more
    # lenient denominator (0.25 * compliance) to avoid over-penalising.
    error_denominator = 0.25 * compliance
    error_score = max(0.0, 1.0 - min(1.0, mean_rel_err / error_denominator))
    snr_score = min(1.0, log1p(mean_amp / max(MEMS_NOISE_FLOOR_G, mean_floor)) / _SNR_LOG_DIVISOR)
    # Absolute-strength guard: amplitude barely above MEMS noise cannot score > 0.40 on SNR.
    if mean_amp <= 2 * MEMS_NOISE_FLOOR_G:
        snr_score = min(snr_score, 0.40)
    absolute_strength_db = canonical_vibration_db(
        peak_band_rms_amp_g=mean_amp,
        floor_amp_g=max(MEMS_NOISE_FLOOR_G, mean_floor),
    )

    _diffuse_excitation, _diffuse_penalty = _detect_diffuse_excitation(
        connected_locations,
        possible_by_location,
        matched_by_location,
        matched_points,
    )

    confidence = _compute_order_confidence(
        effective_match_rate=effective_match_rate,
        error_score=error_score,
        corr_val=corr_val,
        snr_score=snr_score,
        absolute_strength_db=absolute_strength_db,
        localization_confidence=localization_confidence,
        weak_spatial_separation=weak_spatial_separation,
        dominance_ratio=dominance_ratio,
        constant_speed=constant_speed,
        steady_speed=steady_speed,
        matched=matched,
        corroborating_locations=corroborating_locations,
        phases_with_evidence=phases_with_evidence,
        is_diffuse_excitation=_diffuse_excitation,
        diffuse_penalty=_diffuse_penalty,
        n_connected_locations=len(connected_locations),
        no_wheel_sensors=_no_wheel_override,
        path_compliance=compliance,
    )

    # Use the same compliance-adjusted error denominator as the
    # confidence formula so ranking and confidence agree on how much
    # frequency-tracking error is tolerable.
    ranking_error_denom = 0.25 * compliance
    ranking_score = (
        effective_match_rate
        * log1p(mean_amp / max(MEMS_NOISE_FLOOR_G, mean_floor))
        * max(0.0, (1.0 - min(1.0, mean_rel_err / ranking_error_denom)))
    )

    ref_text = ", ".join(sorted(ref_sources))
    evidence = _i18n_ref(
        "EVIDENCE_ORDER_TRACKED",
        order_label=_order_label(hypothesis.order, hypothesis.order_label_base),
        matched=matched,
        possible=possible,
        match_rate=effective_match_rate,
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
    ) = _compute_matched_speed_phase_evidence(
        matched_points,
        focused_speed_band=focused_speed_band,
        hotspot_speed_band=hotspot_speed_band,
    )
    actions = _finding_actions_for_source(
        hypothesis.suspected_source,
        strongest_location=strongest_location,
        strongest_speed_band=strongest_speed_band or "",
        weak_spatial_separation=weak_spatial_separation,
    )
    # Preserve i18n reference dicts as-is so the report layer can resolve
    # them at render time.  Previously str() was applied, which converted
    # {"_i18n_key": "ACTION_WHEEL_BALANCE_WHAT", ...} to its Python repr
    # (e.g. "{'_i18n_key': 'ACTION_WHEEL_BALANCE_WHAT', ...}"), making
    # quick_checks inconsistent with builder.py and reference_checks.py
    # which both store actual dict objects.
    quick_checks = [action["what"] for action in actions if action.get("what")][:3]

    finding = {
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
        "matched_points": matched_points,
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
        "diffuse_excitation": _diffuse_excitation,
        "phase_evidence": phase_evidence,
        "evidence_metrics": {
            "match_rate": effective_match_rate,
            "global_match_rate": match_rate,
            "focused_speed_band": focused_speed_band,
            "mean_relative_error": mean_rel_err,
            "mean_noise_floor_db": canonical_vibration_db(
                peak_band_rms_amp_g=max(MEMS_NOISE_FLOOR_G, mean_floor),
                floor_amp_g=MEMS_NOISE_FLOOR_G,
            ),
            "vibration_strength_db": absolute_strength_db,
            "possible_samples": possible,
            "matched_samples": matched,
            "frequency_correlation": corr,
            "per_phase_confidence": per_phase_confidence,
            "phases_with_evidence": phases_with_evidence,
        },
        "next_sensor_move": actions[0].get("what")
        if actions
        else _i18n_ref("NEXT_SENSOR_MOVE_DEFAULT"),
        "actions": actions,
        "_ranking_score": ranking_score,
    }
    return ranking_score, finding


def _build_order_findings(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    speed_sufficient: bool,
    steady_speed: bool,
    speed_stddev_kmh: float | None,
    tire_circumference_m: float | None,
    engine_ref_sufficient: bool,
    raw_sample_rate_hz: float | None,
    connected_locations: set[str],
    lang: str,
    per_sample_phases: PhaseLabels | None = None,
) -> list[dict[str, Any]]:
    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        return []

    # Pre-compute peaks for every sample once so that the inner hypothesis
    # loop does not redundantly call _sample_top_peaks() for each hypothesis.
    cached_peaks: list[list[tuple[float, float]]] = [_sample_top_peaks(s) for s in samples]

    findings: list[tuple[float, dict[str, Any]]] = []
    for hypothesis in _order_hypotheses():
        if hypothesis.key.startswith(("wheel_", "driveshaft_")) and (
            not speed_sufficient or tire_circumference_m is None or tire_circumference_m <= 0
        ):
            continue
        if hypothesis.key.startswith("engine_") and not engine_ref_sufficient:
            continue

        m = _match_samples_for_hypothesis(
            samples,
            cached_peaks,
            hypothesis,
            metadata,
            tire_circumference_m,
            per_sample_phases,
            lang,
        )

        if m["possible"] < ORDER_MIN_COVERAGE_POINTS or m["matched"] < ORDER_MIN_MATCH_POINTS:
            continue
        match_rate = m["matched"] / max(1, m["possible"])
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
                m["possible_by_speed_bin"],
                m["matched_by_speed_bin"],
                m["possible_by_location"],
                m["matched_by_location"],
            )
        )
        if effective_match_rate < min_match_rate:
            continue

        ranking_score, finding = _assemble_order_finding(
            hypothesis,
            m,
            effective_match_rate=effective_match_rate,
            focused_speed_band=focused_speed_band,
            per_location_dominant=per_location_dominant,
            match_rate=match_rate,
            min_match_rate=min_match_rate,
            constant_speed=constant_speed,
            steady_speed=steady_speed,
            connected_locations=connected_locations,
            lang=lang,
        )
        findings.append((ranking_score, finding))

    return _suppress_engine_aliases(findings)
