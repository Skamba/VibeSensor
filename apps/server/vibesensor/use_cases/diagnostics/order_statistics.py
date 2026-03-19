"""Statistical evidence computation for order-tracking analysis.

Pure computation helpers: confidence scoring, per-phase statistics,
amplitude/error aggregation, and speed-phase evidence derivation.
"""

from __future__ import annotations

from collections import Counter

from vibesensor.domain import OrderMatchObservation
from vibesensor.shared.constants import (
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    LIGHT_STRENGTH_MAX_DB,
    NEGLIGIBLE_STRENGTH_MAX_DB,
    ORDER_MIN_MATCH_POINTS,
)
from vibesensor.use_cases.diagnostics.helpers import (
    _corr_abs_clamped,
    _speed_profile_from_points,
)
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase

# ═══════════════════════════════════════════════════════════════════════════
# Scoring constants
# ═══════════════════════════════════════════════════════════════════════════

_CONF_FLOOR: float = CONFIDENCE_FLOOR
_CONF_CEIL: float = CONFIDENCE_CEILING

_SINGLE_SENSOR_CONFIDENCE_SCALE = 0.85
_DUAL_SENSOR_CONFIDENCE_SCALE = 0.92
_CONF_BASE = 0.10
_MATCH_BASE_WEIGHT = 0.35
_ERROR_WEIGHT = 0.20
_CORR_BASE_WEIGHT = 0.10
_SNR_WEIGHT = 0.20
_CORR_MAX_SHIFT = 0.05
_CORR_COMPLIANCE_FACTOR = 0.10
_NEGLIGIBLE_STRENGTH_CONF_CAP = 0.40
_LIGHT_STRENGTH_PENALTY = 0.80
_LOCALIZATION_BASE = 0.70
_LOCALIZATION_SPREAD = 0.30
_WEAK_SEP_DOMINANCE_THRESHOLD = 1.5
_WEAK_SEP_STRONG_PENALTY = 0.90
_WEAK_SEP_UNIFORM_DOMINANCE = 1.05
_WEAK_SEP_UNIFORM_PENALTY = 0.70
_WEAK_SEP_MILD_PENALTY = 0.80
_NO_WHEEL_SENSOR_PENALTY = 0.75
_CONSTANT_SPEED_PENALTY = 0.75
_STEADY_SPEED_PENALTY = 0.82
_SAMPLE_SATURATION_COUNT = 20
_SAMPLE_WEIGHT_BASE = 0.70
_SAMPLE_WEIGHT_RANGE = 0.30
_CORROBORATING_3_BONUS = 1.08
_CORROBORATING_2_BONUS = 1.04
_PHASES_3_BONUS = 1.06
_PHASES_2_BONUS = 1.03
_LOCALIZATION_MIN_SCALE_THRESHOLD = 0.30

# ═══════════════════════════════════════════════════════════════════════════
# Statistical evidence functions
# ═══════════════════════════════════════════════════════════════════════════


def compute_order_confidence(
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
    """Compute calibrated confidence for an order-tracking finding."""
    corr_shift = max(
        0.0,
        min(_CORR_MAX_SHIFT, _CORR_COMPLIANCE_FACTOR * (path_compliance - 1.0)),
    )
    match_weight = _MATCH_BASE_WEIGHT + corr_shift
    corr_weight = _CORR_BASE_WEIGHT - corr_shift
    confidence = (
        _CONF_BASE
        + (match_weight * effective_match_rate)
        + (_ERROR_WEIGHT * error_score)
        + (corr_weight * corr_val)
        + (_SNR_WEIGHT * snr_score)
    )
    if absolute_strength_db < NEGLIGIBLE_STRENGTH_MAX_DB:
        confidence = min(confidence, _NEGLIGIBLE_STRENGTH_CONF_CAP)
    elif absolute_strength_db < LIGHT_STRENGTH_MAX_DB:
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
            confidence *= _WEAK_SEP_STRONG_PENALTY
        else:
            uniform = dominance_ratio is not None and dominance_ratio < _WEAK_SEP_UNIFORM_DOMINANCE
            confidence *= _WEAK_SEP_UNIFORM_PENALTY if uniform else _WEAK_SEP_MILD_PENALTY
    if no_wheel_sensors and not weak_spatial_separation:
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
    if n_connected_locations <= 1 and localization_confidence >= _LOCALIZATION_MIN_SCALE_THRESHOLD:
        confidence *= _SINGLE_SENSOR_CONFIDENCE_SCALE
    elif (
        n_connected_locations == 2 and localization_confidence >= _LOCALIZATION_MIN_SCALE_THRESHOLD
    ):
        confidence *= _DUAL_SENSOR_CONFIDENCE_SCALE
    return max(_CONF_FLOOR, min(_CONF_CEIL, confidence))


# ═══════════════════════════════════════════════════════════════════════════
# Speed-phase evidence
# ═══════════════════════════════════════════════════════════════════════════

_PHASE_ONSET_RELEVANT: frozenset[str] = frozenset(
    {
        DrivingPhase.ACCELERATION.value,
        DrivingPhase.DECELERATION.value,
        DrivingPhase.COAST_DOWN.value,
    },
)


def compute_matched_speed_phase_evidence(
    matched_points: list[OrderMatchObservation],
    *,
    focused_speed_band: str | None,
    hotspot_speed_band: str,
) -> tuple[float | None, list[float], str | None, dict[str, object], str | None]:
    """Derive speed-profile and phase-evidence from matched points."""
    cruise_value = DrivingPhase.CRUISE.value
    speed_points: list[tuple[float, float]] = []
    speed_phase_weights: list[float] = []
    for point in matched_points:
        point_speed = point.speed_kmh
        point_amp = point.amp
        if point_speed is None or point_amp is None:
            continue
        speed_points.append((point_speed, point_amp))
        phase = str(point.phase or "")
        if phase == cruise_value:
            speed_phase_weights.append(3.0)
        elif phase in _PHASE_ONSET_RELEVANT:
            speed_phase_weights.append(0.3)
        else:
            speed_phase_weights.append(1.0)

    peak_speed_kmh, speed_window_kmh, strongest_speed_band = _speed_profile_from_points(
        speed_points,
        allowed_speed_bins=[focused_speed_band] if focused_speed_band else None,
        phase_weights=speed_phase_weights or None,
    )
    if not strongest_speed_band:
        strongest_speed_band = hotspot_speed_band
    if focused_speed_band and not strongest_speed_band:
        strongest_speed_band = focused_speed_band

    matched_phase_strs = [str(point.phase or "") for point in matched_points if point.phase]
    cruise_matched = sum(1 for phase in matched_phase_strs if phase == cruise_value)
    phase_evidence: dict[str, object] = {
        "cruise_fraction": cruise_matched / len(matched_phase_strs) if matched_phase_strs else 0.0,
        "phases_detected": sorted(set(matched_phase_strs)),
    }
    dominant_phase: str | None = None
    onset_phase_labels = [phase for phase in matched_phase_strs if phase in _PHASE_ONSET_RELEVANT]
    if onset_phase_labels and len(onset_phase_labels) >= max(2, len(matched_points) // 2):
        top_phase, top_count = Counter(onset_phase_labels).most_common(1)[0]
        if top_count / len(matched_points) >= 0.50:
            dominant_phase = top_phase

    return (
        peak_speed_kmh,
        list(speed_window_kmh) if speed_window_kmh is not None else [],
        strongest_speed_band or None,
        phase_evidence,
        dominant_phase,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Per-phase and amplitude statistics
# ═══════════════════════════════════════════════════════════════════════════


def compute_phase_stats(
    has_phases: bool,
    possible_by_phase: dict[str, int],
    matched_by_phase: dict[str, int],
    *,
    min_match_rate: float,
    min_match_points: int = ORDER_MIN_MATCH_POINTS,
) -> tuple[dict[str, float] | None, int]:
    """Compute per-phase confidence and count phases with sufficient evidence."""
    if not has_phases or not possible_by_phase:
        return None, 0
    per_phase_confidence: dict[str, float] = {}
    phases_with_evidence = 0
    for phase_key, phase_possible in possible_by_phase.items():
        phase_matched = matched_by_phase.get(phase_key, 0)
        per_phase_confidence[phase_key] = phase_matched / max(1, phase_possible)
        if phase_matched >= min_match_points and per_phase_confidence[phase_key] >= min_match_rate:
            phases_with_evidence += 1
    return per_phase_confidence, phases_with_evidence


def compute_amplitude_and_error_stats(
    matched_amp: list[float],
    matched_floor: list[float],
    rel_errors: list[float],
    predicted_vals: list[float],
    measured_vals: list[float],
    matched_points: list[OrderMatchObservation],
    *,
    constant_speed: bool,
) -> tuple[float, float, float, float, float | None]:
    """Compute amplitude, floor, relative-error, and correlation statistics."""
    mean_amp = (sum(matched_amp) / len(matched_amp)) if matched_amp else 0.0
    mean_floor = (sum(matched_floor) / len(matched_floor)) if matched_floor else 0.0
    mean_rel_err = (sum(rel_errors) / len(rel_errors)) if rel_errors else 1.0
    corr = _corr_abs_clamped(predicted_vals, measured_vals) if len(matched_points) >= 3 else None
    if constant_speed:
        corr = None
    corr_val = corr if corr is not None else 0.0
    return mean_amp, mean_floor, mean_rel_err, corr_val, corr
