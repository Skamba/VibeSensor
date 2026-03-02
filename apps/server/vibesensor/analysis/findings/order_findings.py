"""Order-tracking hypothesis matching engine.

Matches vibration peaks against predicted frequencies for wheel, driveshaft,
and engine orders; computes confidence scores; suppresses engine aliases.
"""

from __future__ import annotations

from collections import defaultdict
from math import log1p
from statistics import mean
from typing import Any

from vibesensor_core.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ...constants import MEMS_NOISE_FLOOR_G
from ...runlog import as_float_or_none as _as_float
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
from ..phase_segmentation import DrivingPhase
from ..test_plan import _location_speedbin_summary
from ._constants import (
    _CONFIDENCE_CEILING,
    _CONFIDENCE_FLOOR,
    _LIGHT_STRENGTH_MAX_DB,
    _NEGLIGIBLE_STRENGTH_MAX_DB,
    _SNR_LOG_DIVISOR,
)
from .speed_profile import _phase_to_str, _speed_profile_from_points

# ── Diffuse excitation detection constants ──────────────────────────────
# If one sensor's amplitude is more than this ratio above the weakest,
# the vibration is localized (not diffuse), even if match rates are uniform.
_DIFFUSE_AMPLITUDE_DOMINANCE_RATIO = 2.0
# Maximum allowable range (max−min) of per-sensor match rates before the
# excitation is considered non-uniform.  15 percentage-points.
_DIFFUSE_MATCH_RATE_RANGE_THRESHOLD = 0.15
# Minimum mean per-sensor match rate below which diffuse detection is moot.
_DIFFUSE_MIN_MEAN_RATE = 0.15
# Diffuse penalty: base factor, per-sensor decrement, and floor.
_DIFFUSE_PENALTY_BASE = 0.85
_DIFFUSE_PENALTY_PER_SENSOR = 0.04
_DIFFUSE_PENALTY_FLOOR = 0.65
# Sensor-coverage confidence scaling: confidence multipliers for sparse
# sensor layouts where localization evidence is inherently limited.
_SINGLE_SENSOR_CONFIDENCE_SCALE = 0.85
_DUAL_SENSOR_CONFIDENCE_SCALE = 0.92


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
        focused_possible = int(possible_by_speed_bin.get(highest_speed_bin, 0))
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
    """Detect diffuse (non-localized) excitation across multiple sensors.

    Returns (is_diffuse, penalty_factor) where penalty_factor is 1.0 if not diffuse.
    """
    if len(connected_locations) < 2 or not possible_by_location:
        return False, 1.0
    loc_rates: list[float] = []
    loc_mean_amps: dict[str, float] = {}
    for loc in connected_locations:
        loc_p = possible_by_location.get(loc, 0)
        loc_m = matched_by_location.get(loc, 0)
        if loc_p >= max(3, ORDER_MIN_MATCH_POINTS):
            loc_rates.append(loc_m / max(1, loc_p))
            loc_amps = [
                _as_float(pt.get("amp")) or 0.0
                for pt in matched_points
                if str(pt.get("location") or "").strip() == loc
                and (_as_float(pt.get("amp")) or 0.0) > 0
            ]
            if loc_amps:
                loc_mean_amps[loc] = mean(loc_amps)
    if len(loc_rates) < 2:
        return False, 1.0
    _rate_range = max(loc_rates) - min(loc_rates)
    _mean_rate = mean(loc_rates)
    _amp_uniform = True
    if loc_mean_amps and len(loc_mean_amps) >= 2:
        _max_amp_loc = max(loc_mean_amps.values())
        _min_amp_loc = min(loc_mean_amps.values())
        if _min_amp_loc > 0 and _max_amp_loc / _min_amp_loc > _DIFFUSE_AMPLITUDE_DOMINANCE_RATIO:
            _amp_uniform = False
    if (
        _rate_range < _DIFFUSE_MATCH_RATE_RANGE_THRESHOLD
        and _mean_rate > _DIFFUSE_MIN_MEAN_RATE
        and _amp_uniform
    ):
        penalty = max(
            _DIFFUSE_PENALTY_FLOOR,
            _DIFFUSE_PENALTY_BASE - _DIFFUSE_PENALTY_PER_SENSOR * len(loc_rates),
        )
        return True, penalty
    return False, 1.0


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
    """Compute calibrated confidence for an order-tracking finding (clamped 0.08–0.97).

    ``path_compliance`` accounts for mechanical transmission path damping:
    1.0 = stiff direct coupling (driveshaft/engine), higher = softer path
    (e.g. 1.5 for wheel orders through suspension bushings).  Compliant paths
    physically broaden the frequency peak, so we redistribute weight from
    correlation (which penalises peak wander) to match_rate (which rewards
    consistent detection despite wider peaks).

    Among speed-tracked findings the ranking favours stronger vibrations:
    SNR (amplitude above noise floor) receives more weight than correlation
    because on rough roads the wheel is already shaking from road input,
    reducing correlation, while the fault amplitude persists.
    """
    # Weight budget (sums to 0.95 including base 0.10):
    #   match  error  corr  snr
    #   0.35   0.20   0.10  0.20   (baseline, stiff path)
    #   0.40   0.20   0.05  0.20   (compliance=1.5, wheel path)
    #
    # Correlation is intentionally the lightest component: on real roads
    # FFT-bin wander, road noise, and suspension compliance all degrade
    # correlation for genuine faults, while amplitude (SNR) and consistent
    # detection (match) are more robust fault indicators.
    corr_shift = min(0.05, 0.10 * (path_compliance - 1.0))  # 0.0 at 1.0, 0.05 at 1.5
    match_weight = 0.35 + corr_shift
    corr_weight = 0.10 - corr_shift
    confidence = (
        0.10
        + (match_weight * effective_match_rate)
        + (0.20 * error_score)
        + (corr_weight * corr_val)
        + (0.20 * snr_score)
    )
    if absolute_strength_db < _NEGLIGIBLE_STRENGTH_MAX_DB:
        confidence = min(confidence, 0.40)
    elif absolute_strength_db < _LIGHT_STRENGTH_MAX_DB:
        confidence *= 0.80
    confidence *= 0.70 + (0.30 * max(0.0, min(1.0, localization_confidence)))
    if weak_spatial_separation:
        if no_wheel_sensors and dominance_ratio is not None and dominance_ratio >= 1.5:
            # When weak_spatial_separation was forced by no_wheel_sensors but
            # the actual spatial signal is strong (e.g. trunk 2× driver seat),
            # apply a lighter penalty.  We can't resolve the specific wheel
            # corner, but the clear amplitude asymmetry is still diagnostic.
            confidence *= 0.90
        else:
            confidence *= 0.70 if dominance_ratio is not None and dominance_ratio < 1.05 else 0.80
    if no_wheel_sensors and not weak_spatial_separation:
        # Only apply the no-wheel-sensors penalty when weak_spatial_separation
        # wasn't already triggered.  When no_wheel_sensors forced
        # weak_spatial_separation (test_plan.py), the location uncertainty
        # is already penalised; stacking a second penalty double-counts
        # the same underlying lack of wheel-corner resolution.
        confidence *= 0.75
    if constant_speed:
        confidence *= 0.75
    elif steady_speed:
        confidence *= 0.82
    sample_factor = min(1.0, matched / 20.0)
    confidence = confidence * (0.70 + 0.30 * sample_factor)
    if corroborating_locations >= 3:
        confidence *= 1.08
    elif corroborating_locations >= 2:
        confidence *= 1.04
    if phases_with_evidence >= 3:
        confidence *= 1.06
    elif phases_with_evidence >= 2:
        confidence *= 1.03
    if is_diffuse_excitation:
        confidence *= diffuse_penalty
    # Sensor-coverage scaling: only apply when localization_confidence is
    # above a minimum threshold.  For single-sensor runs,
    # localization_confidence is typically very low (~0.05) which already
    # produces a heavy multiplicative penalty via the localization term
    # above, AND weak_spatial_separation adds another penalty.  Stacking
    # the explicit sensor-count scale on top triple-counts the same
    # underlying uncertainty.
    if n_connected_locations <= 1 and localization_confidence >= 0.30:
        confidence *= _SINGLE_SENSOR_CONFIDENCE_SCALE
    elif n_connected_locations == 2 and localization_confidence >= 0.30:
        confidence *= _DUAL_SENSOR_CONFIDENCE_SCALE
    return max(_CONFIDENCE_FLOOR, min(_CONFIDENCE_CEILING, confidence))


def _suppress_engine_aliases(
    findings: list[tuple[float, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Suppress engine findings that are likely harmonic aliases of wheel findings.

    Sorts by ranking score, filters below minimum confidence, and returns the top 3.
    """
    _HARMONIC_ALIAS_RATIO = 1.15
    _ENGINE_ALIAS_SUPPRESSION = 0.60
    _best_wheel_conf = max(
        (
            float(f.get("confidence_0_to_1", 0))
            for _, f in findings
            if str(f.get("suspected_source") or "").strip().lower() == "wheel/tire"
        ),
        default=0.0,
    )
    if _best_wheel_conf > 0:
        for i, (rs, f) in enumerate(findings):
            src = str(f.get("suspected_source") or "").strip().lower()
            if src == "engine":
                eng_conf = float(f.get("confidence_0_to_1", 0))
                if eng_conf <= _best_wheel_conf * _HARMONIC_ALIAS_RATIO:
                    suppressed = eng_conf * _ENGINE_ALIAS_SUPPRESSION
                    f["confidence_0_to_1"] = suppressed
                    new_rs = rs * _ENGINE_ALIAS_SUPPRESSION
                    f["_ranking_score"] = new_rs
                    findings[i] = (new_rs, f)
    findings.sort(key=lambda item: item[0], reverse=True)
    # Filter below-threshold findings FIRST, then slice — otherwise
    # suppressed engine aliases consume top-N slots and valid findings
    # at later positions are permanently lost.
    valid = [
        item[1]
        for item in findings
        if float(item[1].get("confidence_0_to_1", 0)) >= ORDER_MIN_CONFIDENCE
    ]
    return valid[:5]


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
    accel_units: str,
    connected_locations: set[str],
    lang: str,
    per_sample_phases: list | None = None,
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

            compliance = getattr(hypothesis, "path_compliance", 1.0)
            # Scale tolerance by sqrt(compliance) — a conservative widening
            # for mechanically compliant paths (wheel/bushing) without
            # inflating false-positive match rates excessively.
            compliance_scale = compliance**0.5
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
            if per_sample_phases is not None and sample_idx < len(per_sample_phases):
                sample_phase = _phase_to_str(per_sample_phases[sample_idx])
            matched_points.append(
                {
                    "t_s": _as_float(sample.get("t_s")),
                    "speed_kmh": _as_float(sample.get("speed_kmh")),
                    "predicted_hz": predicted_hz,
                    "matched_hz": best_hz,
                    "rel_error": delta_hz / max(1e-9, predicted_hz),
                    "amp": best_amp,
                    "location": _location_label(sample, lang=lang),
                    "phase": sample_phase,
                }
            )

        if possible < ORDER_MIN_COVERAGE_POINTS or matched < ORDER_MIN_MATCH_POINTS:
            continue
        match_rate = matched / max(1, possible)
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
                possible_by_speed_bin,
                matched_by_speed_bin,
                possible_by_location,
                matched_by_location,
            )
        )
        if effective_match_rate < min_match_rate:
            continue

        # Per-phase confidence: compute match rate for each driving phase.
        # Phases with sufficient matches act as independent evidence sources.
        per_phase_confidence: dict[str, float] | None = None
        phases_with_evidence = 0
        if has_phases and possible_by_phase:
            per_phase_confidence = {}
            for ph_key, ph_possible in possible_by_phase.items():
                ph_matched = matched_by_phase.get(ph_key, 0)
                per_phase_confidence[ph_key] = ph_matched / max(1, ph_possible)
                if (
                    ph_matched >= ORDER_MIN_MATCH_POINTS
                    and per_phase_confidence[ph_key] >= min_match_rate
                ):
                    phases_with_evidence += 1

        mean_amp = mean(matched_amp) if matched_amp else 0.0
        mean_floor = mean(matched_floor) if matched_floor else 0.0
        mean_rel_err = mean(rel_errors) if rel_errors else 1.0
        corr = (
            _corr_abs_clamped(predicted_vals, measured_vals) if len(matched_points) >= 3 else None
        )
        # When speed is constant, predicted Hz never varies so correlation
        # is degenerate (undefined or misleading).  Zero it out.
        if constant_speed:
            corr = None
        corr_val = corr if corr is not None else 0.0

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
        weak_spatial_separation = (
            bool(location_hotspot.get("weak_spatial_separation"))
            if isinstance(location_hotspot, dict)
            else True
        )
        dominance_ratio = (
            _as_float(location_hotspot.get("dominance_ratio"))
            if isinstance(location_hotspot, dict)
            else None
        )
        localization_confidence = (
            float(location_hotspot.get("localization_confidence"))
            if isinstance(location_hotspot, dict)
            else 0.05
        )

        # ── Single-sensor dominance override ────────────────────────────
        # When matched points cluster at one location but multiple sensors
        # were connected, the standard localization_confidence formula
        # computes dominance_ratio = 1.0 (no second sensor to compare).
        # That gives localization_confidence ≈ 0.05, wrongly penalising a
        # finding that is actually well-localised.
        # Fix: absence of matches from other connected sensors IS strong
        # spatial evidence.
        # Exception: when diagnosing wheel/tire but no wheel sensors are
        # present, clustering at one cabin sensor does NOT imply corner
        # localization — keep weak_spatial_separation as set by the hotspot.
        unique_match_locations = {
            str(pt.get("location") or "") for pt in matched_points if pt.get("location")
        }
        _no_wheel_override = (
            bool(location_hotspot.get("no_wheel_sensors"))
            if isinstance(location_hotspot, dict)
            else False
        )
        if (
            per_location_dominant
            and len(unique_match_locations) == 1
            and len(connected_locations) >= 2
            and not _no_wheel_override
        ):
            # Strong localization: 1 of N sensors matched.
            localization_confidence = min(1.0, 0.50 + 0.15 * (len(connected_locations) - 1))
            weak_spatial_separation = False
        elif (
            len(unique_match_locations) == 1
            and len(connected_locations) >= 2
            and matched >= ORDER_MIN_MATCH_POINTS
            and not _no_wheel_override
        ):
            # Weaker case: global rate passed but all matches still from one sensor.
            localization_confidence = max(
                localization_confidence,
                min(1.0, 0.40 + 0.10 * (len(connected_locations) - 1)),
            )
            weak_spatial_separation = False

        # Count how many distinct locations independently detected this order
        corroborating_locations = len(
            {str(pt.get("location") or "") for pt in matched_points if pt.get("location")}
        )

        # Error score: compliant paths (wheel through suspension) produce
        # broader peaks that wander more across FFT bins, so we use a more
        # lenient denominator (0.25 * compliance) to avoid over-penalising.
        compliance = getattr(hypothesis, "path_compliance", 1.0)
        error_denominator = 0.25 * compliance
        error_score = max(0.0, 1.0 - min(1.0, mean_rel_err / error_denominator))
        snr_score = min(
            1.0, log1p(mean_amp / max(MEMS_NOISE_FLOOR_G, mean_floor)) / _SNR_LOG_DIVISOR
        )
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

        _no_wheel_sensors = (
            bool(location_hotspot.get("no_wheel_sensors"))
            if isinstance(location_hotspot, dict)
            else False
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
            no_wheel_sensors=_no_wheel_sensors,
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

        strongest_location = (
            str(location_hotspot.get("location")) if isinstance(location_hotspot, dict) else ""
        )
        hotspot_speed_band = (
            str(location_hotspot.get("speed_range")) if isinstance(location_hotspot, dict) else ""
        )
        speed_points: list[tuple[float, float]] = []
        speed_phase_weights: list[float] = []
        _cruise_val = DrivingPhase.CRUISE.value
        _accel_val = DrivingPhase.ACCELERATION.value
        _decel_val = DrivingPhase.DECELERATION.value
        _coast_val = DrivingPhase.COAST_DOWN.value
        for point in matched_points:
            point_speed = _as_float(point.get("speed_kmh"))
            point_amp = _as_float(point.get("amp"))
            if point_speed is None or point_amp is None:
                continue
            speed_points.append((point_speed, point_amp))
            # Phase-aware weight: CRUISE samples are most diagnostic (3x),
            # transient phases (ACCELERATION/DECELERATION) are down-weighted (0.3x).
            ph = str(point.get("phase") or "")
            if ph == _cruise_val:
                speed_phase_weights.append(3.0)
            elif ph in (_accel_val, _decel_val, _coast_val):
                speed_phase_weights.append(0.3)
            else:
                speed_phase_weights.append(1.0)
        peak_speed_kmh, speed_window_kmh, strongest_speed_band = _speed_profile_from_points(
            speed_points,
            allowed_speed_bins=[focused_speed_band] if focused_speed_band else None,
            phase_weights=speed_phase_weights if speed_phase_weights else None,
        )
        if not strongest_speed_band:
            strongest_speed_band = hotspot_speed_band
        if focused_speed_band and not strongest_speed_band:
            strongest_speed_band = focused_speed_band
        actions = _finding_actions_for_source(
            lang,
            hypothesis.suspected_source,
            strongest_location=strongest_location,
            strongest_speed_band=strongest_speed_band,
            weak_spatial_separation=weak_spatial_separation,
        )
        quick_checks = [
            str(action.get("what") or "")
            for action in actions
            if str(action.get("what") or "").strip()
        ][:3]

        # Compute phase evidence: how much of the matched evidence came from CRUISE phase.
        # CRUISE (steady driving) provides the most reliable diagnostic signal.
        _cruise_phase_val = DrivingPhase.CRUISE.value
        matched_phase_strs = [
            str(pt.get("phase") or "") for pt in matched_points if pt.get("phase")
        ]
        _cruise_matched = sum(1 for p in matched_phase_strs if p == _cruise_phase_val)
        phase_evidence: dict[str, Any] = {
            "cruise_fraction": _cruise_matched / len(matched_phase_strs)
            if matched_phase_strs
            else 0.0,
            "phases_detected": sorted(set(matched_phase_strs)),
        }
        # Dominant non-cruise onset phase helps explain whether issue appears on transitions.
        _phase_onset_relevant = {
            DrivingPhase.ACCELERATION.value,
            DrivingPhase.DECELERATION.value,
            DrivingPhase.COAST_DOWN.value,
        }
        dominant_phase: str | None = None
        onset_phase_labels = [p for p in matched_phase_strs if p in _phase_onset_relevant]
        if onset_phase_labels and len(onset_phase_labels) >= max(2, len(matched_points) // 2):
            from collections import Counter as _Counter

            top_phase, top_count = _Counter(onset_phase_labels).most_common(1)[0]
            if top_count / len(matched_points) >= 0.50:
                dominant_phase = top_phase

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
            "location_hotspot": location_hotspot,
            "strongest_location": strongest_location or None,
            "strongest_speed_band": strongest_speed_band or None,
            "dominant_phase": dominant_phase,
            "peak_speed_kmh": peak_speed_kmh,
            "speed_window_kmh": list(speed_window_kmh) if speed_window_kmh else None,
            "dominance_ratio": (
                float(location_hotspot.get("dominance_ratio"))
                if isinstance(location_hotspot, dict)
                else None
            ),
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
                "mean_matched_intensity_db": absolute_strength_db,
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
                "diffuse_excitation": _diffuse_excitation,
            },
            "next_sensor_move": actions[0].get("what")
            if actions
            else _i18n_ref("NEXT_SENSOR_MOVE_DEFAULT"),
            "actions": actions,
            "_ranking_score": ranking_score,
        }
        findings.append((ranking_score, finding))

    return _suppress_engine_aliases(findings)
