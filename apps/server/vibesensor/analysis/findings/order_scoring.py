"""Scoring helpers for order-tracked diagnosis findings."""

from __future__ import annotations

from ...runlog import as_float_or_none as _as_float
from .._types import Finding, MatchedPoint
from ._constants import (
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    LIGHT_STRENGTH_MAX_DB,
    NEGLIGIBLE_STRENGTH_MAX_DB,
    ORDER_MIN_CONFIDENCE,
)

# Local type bindings so mypy resolves correct types under follow_imports=skip.
_CONF_FLOOR: float = CONFIDENCE_FLOOR
_CONF_CEIL: float = CONFIDENCE_CEILING

# ── Diffuse excitation detection constants ──────────────────────────────
_DIFFUSE_AMPLITUDE_DOMINANCE_RATIO = 2.0
_DIFFUSE_MATCH_RATE_RANGE_THRESHOLD = 0.15
_DIFFUSE_MIN_MEAN_RATE = 0.15
_DIFFUSE_PENALTY_BASE = 0.85
_DIFFUSE_PENALTY_PER_SENSOR = 0.04
_DIFFUSE_PENALTY_FLOOR = 0.65
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
_HARMONIC_ALIAS_RATIO = 1.15
_ENGINE_ALIAS_SUPPRESSION = 0.60


def _mean(values: list[float]) -> float:
    """Arithmetic mean returning 0.0 for empty inputs."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _normalized_source(finding: Finding) -> str:
    return str(finding.get("suspected_source") or "").strip().lower()


def detect_diffuse_excitation(
    connected_locations: set[str],
    possible_by_location: dict[str, int],
    matched_by_location: dict[str, int],
    matched_points: list[MatchedPoint],
    *,
    min_match_points: int,
) -> tuple[bool, float]:
    """Detect diffuse, non-localized excitation across multiple sensors."""
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
                amp_val
                for point in matched_points
                if str(point.get("location") or "").strip() == location
                and (amp_val := _as_float(point.get("amp"))) is not None
                and amp_val > 0
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
        if min_amp > 0 and max_amp / min_amp > _DIFFUSE_AMPLITUDE_DOMINANCE_RATIO:
            amp_uniform = False
    if (
        rate_range < _DIFFUSE_MATCH_RATE_RANGE_THRESHOLD
        and mean_rate > _DIFFUSE_MIN_MEAN_RATE
        and amp_uniform
    ):
        penalty = max(
            _DIFFUSE_PENALTY_FLOOR,
            _DIFFUSE_PENALTY_BASE - _DIFFUSE_PENALTY_PER_SENSOR * len(loc_rates),
        )
        return True, penalty
    return False, 1.0


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


def suppress_engine_aliases(
    findings: list[tuple[float, Finding]],
    *,
    min_confidence: float = ORDER_MIN_CONFIDENCE,
) -> list[Finding]:
    """Suppress engine findings likely to be aliases of stronger wheel findings."""
    best_wheel_conf = max(
        (
            _as_float(finding.get("confidence_0_to_1")) or 0.0
            for _, finding in findings
            if _normalized_source(finding) == "wheel/tire"
        ),
        default=0.0,
    )
    if best_wheel_conf > 0:
        for index, (ranking_score, finding) in enumerate(findings):
            if _normalized_source(finding) != "engine":
                continue
            eng_conf = _as_float(finding.get("confidence_0_to_1")) or 0.0
            if eng_conf <= best_wheel_conf * _HARMONIC_ALIAS_RATIO:
                suppressed = eng_conf * _ENGINE_ALIAS_SUPPRESSION
                finding["confidence_0_to_1"] = suppressed
                new_ranking_score = ranking_score * _ENGINE_ALIAS_SUPPRESSION
                finding["_ranking_score"] = new_ranking_score
                findings[index] = (new_ranking_score, finding)
    findings.sort(key=lambda item: item[0], reverse=True)
    valid = [
        item[1]
        for item in findings
        if (_as_float(item[1].get("confidence_0_to_1")) or 0.0) >= min_confidence
    ]
    return valid[:5]
