"""Statistical evidence computation for order-tracking analysis.

Pure computation helpers: confidence scoring, per-phase statistics,
amplitude/error aggregation, and speed-phase evidence derivation.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from vibesensor.analysis.constants import (
    LIGHT_STRENGTH_MAX_DB,
    NEGLIGIBLE_STRENGTH_MAX_DB,
    ORDER_MIN_MATCH_POINTS,
)
from vibesensor.analysis.math_utils import _corr_abs_clamped
from vibesensor.analysis.orders.settings import ORDER_CONFIDENCE_SETTINGS
from vibesensor.analysis.phase_segmentation import DrivingPhase
from vibesensor.analysis.speed_profile_helpers import _speed_profile_from_points
from vibesensor.domain.order_match import OrderMatchObservation

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
    spread_zone_source: bool = False,
) -> float:
    """Compute calibrated confidence for an order-tracking finding.

    ``spread_zone_source`` marks an engine/driveline order seen with no dominant
    corner. Those sources are diagnosed as a zone, so the missing corner is
    expected: once the source evidence itself is established (see
    ``_zone_evidence_established``), the zone counts as clearly located, like a
    wheel order at a clearly dominant corner, and the weak-separation penalty
    does not apply. Otherwise (wheel orders, or faint/poorly matched zone
    orders) the corner-dominance terms apply unchanged.
    """
    settings = ORDER_CONFIDENCE_SETTINGS
    if spread_zone_source and _zone_evidence_established(
        effective_match_rate=effective_match_rate,
        error_score=error_score,
        absolute_strength_db=absolute_strength_db,
        corroborating_locations=corroborating_locations,
    ):
        localization_confidence = max(
            localization_confidence, settings.zone_localization_confidence
        )
        weak_spatial_separation = False
    corr_shift = max(
        0.0,
        min(
            settings.correlation_max_shift,
            settings.correlation_compliance_factor * (path_compliance - 1.0),
        ),
    )
    match_weight = settings.match_weight + corr_shift
    corr_weight = settings.correlation_weight - corr_shift
    confidence = (
        settings.confidence_base
        + (match_weight * effective_match_rate)
        + (settings.error_weight * error_score)
        + (corr_weight * corr_val)
        + (settings.snr_weight * snr_score)
    )
    negligible = absolute_strength_db < NEGLIGIBLE_STRENGTH_MAX_DB
    if negligible:
        confidence = min(confidence, settings.negligible_strength_confidence_cap)
    elif absolute_strength_db < LIGHT_STRENGTH_MAX_DB:
        confidence *= settings.light_strength_penalty
    confidence *= settings.localization_base + (
        settings.localization_spread * max(0.0, min(1.0, localization_confidence))
    )
    if weak_spatial_separation:
        if (
            no_wheel_sensors
            and dominance_ratio is not None
            and dominance_ratio >= settings.weak_separation_dominance_threshold
        ):
            confidence *= settings.weak_separation_strong_penalty
        else:
            uniform = (
                dominance_ratio is not None
                and dominance_ratio < settings.weak_separation_uniform_dominance
            )
            confidence *= (
                settings.weak_separation_uniform_penalty
                if uniform
                else settings.weak_separation_mild_penalty
            )
    if no_wheel_sensors and not weak_spatial_separation:
        confidence *= settings.no_wheel_sensor_penalty
    if constant_speed:
        confidence *= settings.constant_speed_penalty
    elif steady_speed:
        confidence *= settings.steady_speed_penalty
    sample_factor = min(1.0, matched / settings.sample_saturation_count)
    confidence = confidence * (
        settings.sample_weight_base + settings.sample_weight_range * sample_factor
    )
    if corroborating_locations >= 3:
        confidence *= settings.corroborating_three_bonus
    elif corroborating_locations >= 2:
        confidence *= settings.corroborating_two_bonus
    if phases_with_evidence >= 3:
        confidence *= settings.phases_three_bonus
    elif phases_with_evidence >= 2:
        confidence *= settings.phases_two_bonus
    if is_diffuse_excitation:
        confidence *= diffuse_penalty
    if (
        n_connected_locations <= 1
        and localization_confidence >= settings.localization_min_scale_threshold
    ):
        confidence *= settings.single_sensor_confidence_scale
    elif (
        n_connected_locations == 2
        and localization_confidence >= settings.localization_min_scale_threshold
    ):
        confidence *= settings.dual_sensor_confidence_scale
    if negligible:
        # Again after the bonuses, so corroboration/phase bonuses cannot lift a
        # noise-level order over the cap and past a louder order of another source.
        confidence = min(confidence, settings.negligible_strength_confidence_cap)
    return max(settings.confidence_floor, min(settings.confidence_ceiling, confidence))


def _zone_evidence_established(
    *,
    effective_match_rate: float,
    error_score: float,
    absolute_strength_db: float,
    corroborating_locations: int,
) -> bool:
    """Whether a zone-source order stands on its own evidence, without a dominant corner.

    Requires a vibration of at least the moderate strength band, a tracked order
    present in at least half of its windows that matches its predicted frequency
    well, and more than one sensor seeing it. A fault-free run's road noise lands
    near engine/driveline orders by chance, but faint and patchy, so it fails
    this check and keeps the corner-dominance penalties.
    """
    settings = ORDER_CONFIDENCE_SETTINGS
    return (
        absolute_strength_db >= LIGHT_STRENGTH_MAX_DB
        and effective_match_rate >= settings.zone_min_match_rate
        and error_score >= settings.zone_min_error_score
        and corroborating_locations >= settings.zone_min_corroborating_locations
    )


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


@dataclass(frozen=True, slots=True)
class OrderPhaseEvidence:
    """Typed speed/phase evidence derived from matched order observations."""

    peak_speed_kmh: float | None
    speed_window_kmh: tuple[float, float] | None
    strongest_speed_band: str | None
    cruise_fraction: float
    phases_detected: tuple[str, ...]
    dominant_phase: str | None


def compute_matched_speed_phase_evidence(
    matched_points: list[OrderMatchObservation],
    *,
    focused_speed_band: str | None,
    hotspot_speed_band: str,
) -> OrderPhaseEvidence:
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
    cruise_fraction = cruise_matched / len(matched_phase_strs) if matched_phase_strs else 0.0
    phases_detected = tuple(sorted(set(matched_phase_strs)))
    dominant_phase: str | None = None
    onset_phase_labels = [phase for phase in matched_phase_strs if phase in _PHASE_ONSET_RELEVANT]
    if onset_phase_labels and len(onset_phase_labels) >= max(2, len(matched_points) // 2):
        top_phase, top_count = Counter(onset_phase_labels).most_common(1)[0]
        if top_count / len(matched_points) >= 0.50:
            dominant_phase = top_phase

    return OrderPhaseEvidence(
        peak_speed_kmh,
        speed_window_kmh,
        strongest_speed_band or None,
        cruise_fraction,
        phases_detected,
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
