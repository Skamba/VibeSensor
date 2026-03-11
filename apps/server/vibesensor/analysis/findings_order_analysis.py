"""Order-tracking models, matching, scoring, and support helpers.

Consolidated from four single-consumer modules:
``findings_order_models``, ``findings_order_matching``,
``findings_order_scoring``, ``findings_order_support``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from ..constants import (
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    LIGHT_STRENGTH_MAX_DB,
    NEGLIGIBLE_STRENGTH_MAX_DB,
    ORDER_MIN_CONFIDENCE,
    ORDER_MIN_MATCH_POINTS,
    ORDER_TOLERANCE_MIN_HZ,
    ORDER_TOLERANCE_REL,
)
from ..domain_models import as_float_or_none as _as_float
from ._types import Finding, MatchedPoint, MetadataDict, PhaseEvidence, PhaseLabels, Sample
from .findings_speed_profile import _phase_to_str, _speed_profile_from_points
from .helpers import (
    _corr_abs_clamped,
    _estimate_strength_floor_amp_g,
    _location_label,
    _speed_bin_label,
)
from .order_analysis import OrderHypothesis
from .phase_segmentation import DrivingPhase

# ═══════════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class OrderMatchAccumulator:
    """Accumulated statistics from matching one hypothesis across samples."""

    possible: int
    matched: int
    matched_amp: list[float]
    matched_floor: list[float]
    rel_errors: list[float]
    predicted_vals: list[float]
    measured_vals: list[float]
    matched_points: list[MatchedPoint]
    ref_sources: set[str]
    possible_by_speed_bin: dict[str, int]
    matched_by_speed_bin: dict[str, int]
    possible_by_phase: dict[str, int]
    matched_by_phase: dict[str, int]
    possible_by_location: dict[str, int]
    matched_by_location: dict[str, int]
    has_phases: bool
    compliance: float


@dataclass(frozen=True)
class OrderFindingBuildContext:
    """Stable context for assembling a matched order hypothesis into a finding."""

    effective_match_rate: float
    focused_speed_band: str | None
    per_location_dominant: bool
    match_rate: float
    min_match_rate: float
    constant_speed: bool
    steady_speed: bool
    connected_locations: set[str]
    lang: str


# ═══════════════════════════════════════════════════════════════════════════
# Matching
# ═══════════════════════════════════════════════════════════════════════════


def match_samples_for_hypothesis(
    samples: list[Sample],
    cached_peaks: list[list[tuple[float, float]]],
    hypothesis: OrderHypothesis,
    metadata: MetadataDict,
    tire_circumference_m: float | None,
    per_sample_phases: PhaseLabels | None,
    lang: str,
) -> OrderMatchAccumulator:
    """Match one hypothesis against all samples and accumulate evidence."""
    possible = 0
    matched = 0
    matched_amp: list[float] = []
    matched_floor: list[float] = []
    rel_errors: list[float] = []
    predicted_vals: list[float] = []
    measured_vals: list[float] = []
    matched_points: list[MatchedPoint] = []
    ref_sources: set[str] = set()
    possible_by_speed_bin: dict[str, int] = defaultdict(int)
    matched_by_speed_bin: dict[str, int] = defaultdict(int)
    possible_by_phase: dict[str, int] = defaultdict(int)
    matched_by_phase: dict[str, int] = defaultdict(int)
    possible_by_location: dict[str, int] = defaultdict(int)
    matched_by_location: dict[str, int] = defaultdict(int)
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)
    compliance = getattr(hypothesis, "path_compliance", 1.0)
    compliance_scale = compliance**0.5

    for sample_idx, sample in enumerate(samples):
        peaks = cached_peaks[sample_idx]
        if not peaks:
            continue
        predicted_hz, ref_source = hypothesis.predicted_hz(sample, metadata, tire_circumference_m)
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

        phase_key: str | None = None
        if has_phases:
            assert per_sample_phases is not None
            phase = per_sample_phases[sample_idx]
            phase_key = str(phase.value if hasattr(phase, "value") else phase)
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
        if has_phases and phase_key is not None:
            matched_by_phase[phase_key] += 1

        rel_errors.append(delta_hz / max(1e-9, predicted_hz))
        matched_amp.append(best_amp)
        floor_amp = _estimate_strength_floor_amp_g(sample)
        matched_floor.append(max(0.0, floor_amp if floor_amp is not None else 0.0))
        predicted_vals.append(predicted_hz)
        measured_vals.append(best_hz)
        matched_points.append(
            {
                "t_s": _as_float(sample.get("t_s")),
                "speed_kmh": _as_float(sample.get("speed_kmh")),
                "predicted_hz": predicted_hz,
                "matched_hz": best_hz,
                "rel_error": delta_hz / max(1e-9, predicted_hz),
                "amp": best_amp,
                "location": sample_location,
                "phase": (
                    _phase_to_str(per_sample_phases[sample_idx])
                    if has_phases and per_sample_phases is not None
                    else None
                ),
            },
        )

    return OrderMatchAccumulator(
        possible=possible,
        matched=matched,
        matched_amp=matched_amp,
        matched_floor=matched_floor,
        rel_errors=rel_errors,
        predicted_vals=predicted_vals,
        measured_vals=measured_vals,
        matched_points=matched_points,
        ref_sources=ref_sources,
        possible_by_speed_bin=dict(possible_by_speed_bin),
        matched_by_speed_bin=dict(matched_by_speed_bin),
        possible_by_phase=dict(possible_by_phase),
        matched_by_phase=dict(matched_by_phase),
        possible_by_location=dict(possible_by_location),
        matched_by_location=dict(matched_by_location),
        has_phases=has_phases,
        compliance=compliance,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Scoring
# ═══════════════════════════════════════════════════════════════════════════

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
    min_match_points: int = ORDER_MIN_MATCH_POINTS,
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


# ═══════════════════════════════════════════════════════════════════════════
# Support helpers
# ═══════════════════════════════════════════════════════════════════════════

_PHASE_ONSET_RELEVANT: frozenset[str] = frozenset(
    {
        DrivingPhase.ACCELERATION.value,
        DrivingPhase.DECELERATION.value,
        DrivingPhase.COAST_DOWN.value,
    },
)


def compute_matched_speed_phase_evidence(
    matched_points: list[MatchedPoint],
    *,
    focused_speed_band: str | None,
    hotspot_speed_band: str,
) -> tuple[float | None, list[float], str | None, PhaseEvidence, str | None]:
    """Derive speed-profile and phase-evidence from matched points."""
    cruise_value = DrivingPhase.CRUISE.value
    speed_points: list[tuple[float, float]] = []
    speed_phase_weights: list[float] = []
    for point in matched_points:
        point_speed = _as_float(point.get("speed_kmh"))
        point_amp = _as_float(point.get("amp"))
        if point_speed is None or point_amp is None:
            continue
        speed_points.append((point_speed, point_amp))
        phase = str(point.get("phase") or "")
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

    matched_phase_strs = [
        str(point.get("phase") or "") for point in matched_points if point.get("phase")
    ]
    cruise_matched = sum(1 for phase in matched_phase_strs if phase == cruise_value)
    phase_evidence: PhaseEvidence = {
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
    matched_points: list[MatchedPoint],
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
    if (
        per_location_dominant
        and len(unique_match_locations) == 1
        and len(connected_locations) >= 2
        and not no_wheel_override
    ):
        localization_confidence = min(1.0, 0.50 + 0.15 * (len(connected_locations) - 1))
        weak_spatial_separation = False
    elif (
        len(unique_match_locations) == 1
        and len(connected_locations) >= 2
        and matched >= min_match_points
        and not no_wheel_override
    ):
        localization_confidence = max(
            localization_confidence,
            min(1.0, 0.40 + 0.10 * (len(connected_locations) - 1)),
        )
        weak_spatial_separation = False
    return localization_confidence, weak_spatial_separation
