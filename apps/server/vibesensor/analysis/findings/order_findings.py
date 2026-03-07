"""Order-tracking hypothesis matching engine.

Matches vibration peaks against predicted frequencies for wheel, driveshaft,
and engine orders; computes confidence scores; suppresses engine aliases.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from math import log1p
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mean(xs: list[float]) -> float:
    """Arithmetic mean; returns 0.0 for empty lists (avoids statistics.mean overhead)."""
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def _normalized_source(finding: dict[str, Any]) -> str:
    return str(finding.get("suspected_source") or "").strip().lower()


# Phase values used as constants across hypothesis iterations.
_PHASE_ONSET_RELEVANT: frozenset[str] = frozenset(
    {
        DrivingPhase.ACCELERATION.value,
        DrivingPhase.DECELERATION.value,
        DrivingPhase.COAST_DOWN.value,
    }
)

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

# ── Confidence weight budget ─────────────────────────────────────────────
# Total weight sums to 0.95 (with the 0.10 base).
# Baseline (stiff path): match=0.35, error=0.20, corr=0.10, snr=0.20
# Compliant path (1.5): match=0.40, error=0.20, corr=0.05, snr=0.20
_CONF_BASE = 0.10
_MATCH_BASE_WEIGHT = 0.35
_ERROR_WEIGHT = 0.20
_CORR_BASE_WEIGHT = 0.10
_SNR_WEIGHT = 0.20
# Per-unit compliance shift: moves weight from correlation → match.
# At path_compliance=1.5 the full _CORR_MAX_SHIFT is consumed.
_CORR_MAX_SHIFT = 0.05
_CORR_COMPLIANCE_FACTOR = 0.10

# ── Strength-based confidence adjustments ────────────────────────────────
_NEGLIGIBLE_STRENGTH_CONF_CAP = 0.40  # cap for negligible-strength findings
_LIGHT_STRENGTH_PENALTY = 0.80  # multiplier for light-strength findings

# ── Localization scaling ──────────────────────────────────────────────────
_LOCALIZATION_BASE = 0.70  # base factor before localization contribution
_LOCALIZATION_SPREAD = 0.30  # range that localization_confidence can add

# ── Spatial separation penalties ─────────────────────────────────────────
# Applied when weak_spatial_separation is True (can't pinpoint corner).
_WEAK_SEP_DOMINANCE_THRESHOLD = 1.5  # dominance ratio to qualify for lighter penalty
_WEAK_SEP_STRONG_PENALTY = 0.90  # lighter penalty: clear amplitude asymmetry present
_WEAK_SEP_UNIFORM_DOMINANCE = 1.05  # below this → vibration is spatially uniform
_WEAK_SEP_UNIFORM_PENALTY = 0.70  # heavier penalty: spatially uniform excitation
_WEAK_SEP_MILD_PENALTY = 0.80  # default penalty: mild spatial asymmetry
_NO_WHEEL_SENSOR_PENALTY = 0.75  # extra penalty when no wheel-corner sensors at all

# ── Speed-profile penalties ───────────────────────────────────────────────
_CONSTANT_SPEED_PENALTY = 0.75  # confidence reduction for constant-speed runs
_STEADY_SPEED_PENALTY = 0.82  # smaller reduction for steady (non-varying) speed

# ── Sample-count saturation ───────────────────────────────────────────────
_SAMPLE_SATURATION_COUNT = 20  # matched samples needed to reach full weight
_SAMPLE_WEIGHT_BASE = 0.70  # base weight with zero samples
_SAMPLE_WEIGHT_RANGE = 0.30  # extra weight added as samples accumulate

# ── Corroborating-evidence bonuses ───────────────────────────────────────
_CORROBORATING_3_BONUS = 1.08  # bonus: ≥3 corroborating locations
_CORROBORATING_2_BONUS = 1.04  # bonus: 2 corroborating locations
_PHASES_3_BONUS = 1.06  # bonus: ≥3 driving phases with evidence
_PHASES_2_BONUS = 1.03  # bonus: 2 driving phases with evidence

# ── Minimum localization threshold for sensor-count scaling ──────────────
_LOCALIZATION_MIN_SCALE_THRESHOLD = 0.30


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
    _min_loc_points = max(3, ORDER_MIN_MATCH_POINTS)
    for loc in connected_locations:
        loc_p = possible_by_location.get(loc, 0)
        loc_m = matched_by_location.get(loc, 0)
        if loc_p >= _min_loc_points:
            loc_rates.append(loc_m / max(1, loc_p))
            loc_amps: list[float] = []
            for pt in matched_points:
                if str(pt.get("location") or "").strip() != loc:
                    continue
                amp_val = _as_float(pt.get("amp")) or 0.0
                if amp_val > 0:
                    loc_amps.append(amp_val)
            if loc_amps:
                loc_mean_amps[loc] = _mean(loc_amps)
    if len(loc_rates) < 2:
        return False, 1.0
    _rate_range = max(loc_rates) - min(loc_rates)
    _mean_rate = _mean(loc_rates)
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
    # Weight values are defined as module-level constants; see _CONF_BASE,
    # _MATCH_BASE_WEIGHT, _ERROR_WEIGHT, _CORR_BASE_WEIGHT, _SNR_WEIGHT.
    # Correlation is intentionally the lightest component: on real roads
    # FFT-bin wander, road noise, and suspension compliance all degrade
    # correlation for genuine faults, while amplitude (SNR) and consistent
    # detection (match) are more robust fault indicators.
    # Clamp corr_shift to [0, _CORR_MAX_SHIFT]: path_compliance < 1.0 would
    # otherwise produce a negative shift, reversing the intended weight transfer.
    corr_shift = max(0.0, min(_CORR_MAX_SHIFT, _CORR_COMPLIANCE_FACTOR * (path_compliance - 1.0)))
    match_weight = _MATCH_BASE_WEIGHT + corr_shift
    corr_weight = _CORR_BASE_WEIGHT - corr_shift
    confidence = (
        _CONF_BASE
        + (match_weight * effective_match_rate)
        + (_ERROR_WEIGHT * error_score)
        + (corr_weight * corr_val)
        + (_SNR_WEIGHT * snr_score)
    )
    if absolute_strength_db < _NEGLIGIBLE_STRENGTH_MAX_DB:
        confidence = min(confidence, _NEGLIGIBLE_STRENGTH_CONF_CAP)
    elif absolute_strength_db < _LIGHT_STRENGTH_MAX_DB:
        confidence *= _LIGHT_STRENGTH_PENALTY
    confidence *= _LOCALIZATION_BASE + (
        _LOCALIZATION_SPREAD * max(0.0, min(1.0, localization_confidence))
    )
    if weak_spatial_separation:
        if (
            no_wheel_sensors
            and dominance_ratio is not None
            and dominance_ratio >= _WEAK_SEP_DOMINANCE_THRESHOLD
        ):
            # When weak_spatial_separation was forced by no_wheel_sensors but
            # the actual spatial signal is strong (e.g. trunk 2× driver seat),
            # apply a lighter penalty.  We can't resolve the specific wheel
            # corner, but the clear amplitude asymmetry is still diagnostic.
            confidence *= _WEAK_SEP_STRONG_PENALTY
        else:
            uniform = dominance_ratio is not None and dominance_ratio < _WEAK_SEP_UNIFORM_DOMINANCE
            confidence *= _WEAK_SEP_UNIFORM_PENALTY if uniform else _WEAK_SEP_MILD_PENALTY
    if no_wheel_sensors and not weak_spatial_separation:
        # Only apply the no-wheel-sensors penalty when weak_spatial_separation
        # wasn't already triggered.  When no_wheel_sensors forced
        # weak_spatial_separation (test_plan.py), the location uncertainty
        # is already penalised; stacking a second penalty double-counts
        # the same underlying lack of wheel-corner resolution.
        confidence *= _NO_WHEEL_SENSOR_PENALTY
    if constant_speed:
        confidence *= _CONSTANT_SPEED_PENALTY
    elif steady_speed:
        confidence *= _STEADY_SPEED_PENALTY
    sample_factor = min(1.0, matched / _SAMPLE_SATURATION_COUNT)
    confidence = confidence * (_SAMPLE_WEIGHT_BASE + _SAMPLE_WEIGHT_RANGE * sample_factor)
    if corroborating_locations >= 3:
        confidence *= _CORROBORATING_3_BONUS
    elif corroborating_locations >= 2:
        confidence *= _CORROBORATING_2_BONUS
    if phases_with_evidence >= 3:
        confidence *= _PHASES_3_BONUS
    elif phases_with_evidence >= 2:
        confidence *= _PHASES_2_BONUS
    if is_diffuse_excitation:
        confidence *= diffuse_penalty
    # Sensor-coverage scaling: only apply when localization_confidence is
    # above a minimum threshold.  For single-sensor runs,
    # localization_confidence is typically very low (~0.05) which already
    # produces a heavy multiplicative penalty via the localization term
    # above, AND weak_spatial_separation adds another penalty.  Stacking
    # the explicit sensor-count scale on top triple-counts the same
    # underlying uncertainty.
    if n_connected_locations <= 1 and localization_confidence >= _LOCALIZATION_MIN_SCALE_THRESHOLD:
        confidence *= _SINGLE_SENSOR_CONFIDENCE_SCALE
    elif (
        n_connected_locations == 2 and localization_confidence >= _LOCALIZATION_MIN_SCALE_THRESHOLD
    ):
        confidence *= _DUAL_SENSOR_CONFIDENCE_SCALE
    return max(_CONFIDENCE_FLOOR, min(_CONFIDENCE_CEILING, confidence))


def _suppress_engine_aliases(
    findings: list[tuple[float, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Suppress engine findings that are likely harmonic aliases of wheel findings.

    Sorts by ranking score, filters below minimum confidence, and returns the top 5.
    """
    _HARMONIC_ALIAS_RATIO = 1.15
    _ENGINE_ALIAS_SUPPRESSION = 0.60
    _best_wheel_conf = max(
        (
            float(f.get("confidence_0_to_1", 0))
            for _, f in findings
            if _normalized_source(f) == "wheel/tire"
        ),
        default=0.0,
    )
    if _best_wheel_conf > 0:
        for i, (rs, f) in enumerate(findings):
            src = _normalized_source(f)
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


def _compute_matched_speed_phase_evidence(
    matched_points: list[dict[str, Any]],
    *,
    focused_speed_band: str | None,
    hotspot_speed_band: str,
) -> tuple[float | None, list[float], str | None, str, dict[str, Any], str | None]:
    """Derive speed-profile and phase-evidence from *matched_points*.

    Returns ``(peak_speed_kmh, speed_window_kmh, strongest_speed_band,
    hotspot_speed_band_out, phase_evidence, dominant_phase)``.
    """
    _cruise_val = DrivingPhase.CRUISE.value
    speed_points: list[tuple[float, float]] = []
    speed_phase_weights: list[float] = []
    for point in matched_points:
        point_speed = _as_float(point.get("speed_kmh"))
        point_amp = _as_float(point.get("amp"))
        if point_speed is None or point_amp is None:
            continue
        speed_points.append((point_speed, point_amp))
        ph = str(point.get("phase") or "")
        if ph == _cruise_val:
            speed_phase_weights.append(3.0)
        elif ph in _PHASE_ONSET_RELEVANT:
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

    matched_phase_strs = [str(pt.get("phase") or "") for pt in matched_points if pt.get("phase")]
    _cruise_matched = sum(1 for p in matched_phase_strs if p == _cruise_val)
    phase_evidence: dict[str, Any] = {
        "cruise_fraction": _cruise_matched / len(matched_phase_strs) if matched_phase_strs else 0.0,
        "phases_detected": sorted(set(matched_phase_strs)),
    }
    dominant_phase: str | None = None
    onset_phase_labels = [p for p in matched_phase_strs if p in _PHASE_ONSET_RELEVANT]
    if onset_phase_labels and len(onset_phase_labels) >= max(2, len(matched_points) // 2):
        top_phase, top_count = Counter(onset_phase_labels).most_common(1)[0]
        if top_count / len(matched_points) >= 0.50:
            dominant_phase = top_phase

    return (
        peak_speed_kmh,
        list(speed_window_kmh) if speed_window_kmh is not None else [],
        strongest_speed_band or None,
        hotspot_speed_band,
        phase_evidence,
        dominant_phase,
    )


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
        compliance = getattr(hypothesis, "path_compliance", 1.0)

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
                ph = per_sample_phases[sample_idx]
                phase_key = str(ph.value if hasattr(ph, "value") else ph)
                possible_by_phase[phase_key] += 1

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
            # Only assign phase when has_phases is True (lengths verified equal),
            # otherwise matched_points would have inconsistent phase coverage.
            if has_phases:
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

        mean_amp = _mean(matched_amp) if matched_amp else 0.0
        mean_floor = _mean(matched_floor) if matched_floor else 0.0
        mean_rel_err = _mean(rel_errors) if rel_errors else 1.0
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
        _hotspot_is_dict = isinstance(location_hotspot, dict)
        weak_spatial_separation = (
            bool(location_hotspot.get("weak_spatial_separation")) if _hotspot_is_dict else True
        )
        dominance_ratio = (
            _as_float(location_hotspot.get("dominance_ratio")) if _hotspot_is_dict else None
        )
        localization_confidence = (
            _as_float(location_hotspot.get("localization_confidence")) or 0.05
            if _hotspot_is_dict
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
            bool(location_hotspot.get("no_wheel_sensors")) if _hotspot_is_dict else False
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

        strongest_location = str(location_hotspot.get("location")) if _hotspot_is_dict else ""
        hotspot_speed_band = str(location_hotspot.get("speed_range")) if _hotspot_is_dict else ""
        (
            peak_speed_kmh,
            speed_window_kmh,
            strongest_speed_band,
            _hotspot_speed_band_out,
            phase_evidence,
            dominant_phase,
        ) = _compute_matched_speed_phase_evidence(
            matched_points,
            focused_speed_band=focused_speed_band,
            hotspot_speed_band=hotspot_speed_band,
        )
        actions = _finding_actions_for_source(
            lang,
            hypothesis.suspected_source,
            strongest_location=strongest_location,
            strongest_speed_band=strongest_speed_band,
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
            "location_hotspot": location_hotspot,
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
