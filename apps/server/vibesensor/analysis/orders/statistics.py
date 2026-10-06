"""Statistical evidence computation for order-tracking analysis.

Pure computation helpers: confidence scoring, per-phase statistics,
amplitude/error aggregation, and speed-phase evidence derivation.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from vibesensor.analysis.constants import (
    LIGHT_STRENGTH_MAX_DB,
    NEGLIGIBLE_STRENGTH_MAX_DB,
    ORDER_MIN_MATCH_POINTS,
)
from vibesensor.analysis.math_utils import _corr_abs_clamped, _mean, _ramp
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
    min_match_rate: float,
    error_score: float,
    corr_val: float,
    snr_score: float,
    absolute_strength_db: float,
    localization_confidence: float,
    weak_spatial_separation: bool,
    dominance_ratio: float | None,
    constancy: float,
    steadiness: float,
    matched: int,
    corroborating_locations: int,
    phases_with_evidence: int,
    diffuse_penalty: float,
    n_connected_locations: int,
    weak_separation_edge: float | None = None,
    no_wheel_sensors: bool = False,
    path_compliance: float = 1.0,
    zone_source: bool = False,
    zone_match_rate: float = 0.0,
    wheel_shared_fraction: float = 0.0,
) -> float:
    """Compute calibrated confidence for an order-tracking finding.

    ``zone_source`` marks an engine/driveline order not pinned to one sensor by
    its per-location match rates. Those sources are diagnosed as a zone, so a
    missing dominant corner is expected: as the source evidence itself becomes
    established (see ``_zone_credit``), the zone counts as clearly located, like
    a wheel order at a clearly dominant corner, and the weak-separation penalty
    lifts. Otherwise (wheel orders, or poorly matched zone orders) the
    corner-dominance terms apply unchanged.

    *weak_separation_edge* is the dominance at which the hotspot stopped
    counting as weakly separated (``LocationAnalysisResult``); the spread
    penalty eases out past it instead of vanishing there. *constancy* and
    *steadiness* (0 to 1, ``speed_constancy`` / ``speed_steadiness``) grade how
    close the drive came to one speed.

    Every term ramps rather than steps, so a small change of any input moves
    the score a little ("Confidence levels" in docs/metrics.md). The integer
    gates (sensor counts, corroboration, phases) stay steps.
    """
    settings = ORDER_CONFIDENCE_SETTINGS
    weakness = _spatial_weakness(weak_spatial_separation, dominance_ratio, weak_separation_edge)
    zone_credit = _zone_credit(
        zone_source=zone_source,
        zone_match_rate=zone_match_rate,
        error_score=error_score,
        wheel_shared_fraction=wheel_shared_fraction,
        absolute_strength_db=absolute_strength_db,
        corroborating_locations=corroborating_locations,
    )
    localization_confidence += (
        weakness
        * zone_credit
        * max(0.0, settings.zone_localization_confidence - localization_confidence)
    )
    corr_shift = max(
        0.0,
        min(
            settings.correlation_max_shift,
            settings.correlation_compliance_factor * (path_compliance - 1.0),
        ),
    )
    match_weight = settings.match_weight + corr_shift
    # At one speed the predicted frequency barely moves, so correlating it with
    # the matched one measures noise.
    corr_weight = (settings.correlation_weight - corr_shift) * (1.0 - constancy)
    confidence = (
        settings.confidence_base
        + (match_weight * effective_match_rate)
        + (settings.error_weight * error_score)
        + (corr_weight * corr_val)
        + (settings.snr_weight * snr_score)
    )
    strength_cap = _strength_cap(absolute_strength_db)
    confidence = min(confidence * _light_strength_factor(absolute_strength_db), strength_cap)
    confidence *= settings.localization_base + (
        settings.localization_spread * max(0.0, min(1.0, localization_confidence))
    )
    spread = _spread_penalty(dominance_ratio, no_wheel_sensors=no_wheel_sensors)
    # An established zone needs no dominant corner: its credit lifts the penalty.
    spread += zone_credit * (1.0 - spread)
    confidence *= 1.0 - weakness * (1.0 - spread)
    confidence *= min(
        1.0 - (1.0 - settings.steady_speed_penalty) * steadiness,
        1.0 - (1.0 - settings.constant_speed_penalty) * constancy,
    )
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
    confidence *= diffuse_penalty
    confidence *= _few_sensor_scale(n_connected_locations, localization_confidence)
    # Again after the bonuses, so corroboration/phase bonuses cannot lift a
    # noise-level order over the cap and past a louder order of another source.
    confidence = min(confidence, strength_cap, _presence_cap(effective_match_rate, min_match_rate))
    return max(settings.confidence_floor, min(settings.confidence_ceiling, confidence))


def _strength_cap(absolute_strength_db: float) -> float:
    """The most a finding this strong may score: at most Weak under 8 dB, lifting above."""
    settings = ORDER_CONFIDENCE_SETTINGS
    cap = settings.weak_confidence_cap
    lifted = _ramp(
        absolute_strength_db,
        NEGLIGIBLE_STRENGTH_MAX_DB,
        NEGLIGIBLE_STRENGTH_MAX_DB + settings.negligible_strength_ramp_db,
    )
    return cap + lifted * (settings.confidence_ceiling - cap)


def _presence_cap(effective_match_rate: float, min_match_rate: float) -> float:
    """The most an order heard this often may score: at most Weak at the minimum rate.

    Below *min_match_rate* there is no finding at all; the cap lifts over the
    next ``presence_ramp`` of match rate, so passing the minimum adds a Weak
    finding rather than a Strong one.
    """
    settings = ORDER_CONFIDENCE_SETTINGS
    cap = settings.weak_confidence_cap
    lifted = _ramp(effective_match_rate, min_match_rate, min_match_rate + settings.presence_ramp)
    return cap + lifted * (settings.confidence_ceiling - cap)


def _light_strength_factor(absolute_strength_db: float) -> float:
    """Penalty for a light vibration (under 16 dB), easing out over the next few dB."""
    settings = ORDER_CONFIDENCE_SETTINGS
    penalty = settings.light_strength_penalty
    return penalty + (1.0 - penalty) * _ramp(
        absolute_strength_db,
        LIGHT_STRENGTH_MAX_DB,
        LIGHT_STRENGTH_MAX_DB + settings.light_strength_ramp_db,
    )


def _spatial_weakness(
    weak_spatial_separation: bool,
    dominance_ratio: float | None,
    weak_separation_edge: float | None,
) -> float:
    """How fully the weak-separation terms apply, 0 to 1.

    1 for a weakly separated hotspot; past the dominance edge where it stops
    counting as weak, fading to 0 over ``weak_separation_edge_ramp``. A hotspot
    declared separated by other evidence has no edge and takes none.
    """
    if weak_spatial_separation:
        return 1.0
    if weak_separation_edge is None or dominance_ratio is None:
        return 0.0
    return 1.0 - _ramp(
        dominance_ratio,
        weak_separation_edge,
        weak_separation_edge + ORDER_CONFIDENCE_SETTINGS.weak_separation_edge_ramp,
    )


def _spread_penalty(dominance_ratio: float | None, *, no_wheel_sensors: bool) -> float:
    """Weak-separation penalty: 0.70 when uniform (dominance < 1.05), 0.80 above.

    Without wheel sensors a clear cabin hotspot (dominance 1.5 and up) takes
    0.90. Each step eases in over the dominance just past its edge.
    """
    settings = ORDER_CONFIDENCE_SETTINGS
    if dominance_ratio is None:
        return settings.weak_separation_mild_penalty
    uniform_dominance = settings.weak_separation_uniform_dominance
    penalty = settings.weak_separation_uniform_penalty + (
        settings.weak_separation_mild_penalty - settings.weak_separation_uniform_penalty
    ) * _ramp(
        dominance_ratio,
        uniform_dominance,
        uniform_dominance + settings.weak_separation_uniform_ramp,
    )
    if no_wheel_sensors:
        threshold = settings.weak_separation_dominance_threshold
        penalty += (
            settings.weak_separation_strong_penalty - settings.weak_separation_mild_penalty
        ) * _ramp(
            dominance_ratio,
            threshold,
            threshold + settings.weak_separation_edge_ramp,
        )
    return penalty


def _few_sensor_scale(n_connected_locations: int, localization_confidence: float) -> float:
    """Discount a localisation claim made with one or two sensors."""
    settings = ORDER_CONFIDENCE_SETTINGS
    if n_connected_locations <= 1:
        scale = settings.single_sensor_confidence_scale
    elif n_connected_locations == 2:
        scale = settings.dual_sensor_confidence_scale
    else:
        return 1.0
    return 1.0 - (1.0 - scale) * _ramp(
        localization_confidence,
        settings.few_sensor_scale_from_localization,
        settings.few_sensor_scale_full_localization,
    )


def _zone_credit(
    *,
    zone_source: bool,
    zone_match_rate: float,
    error_score: float,
    wheel_shared_fraction: float,
    absolute_strength_db: float,
    corroborating_locations: int,
) -> float:
    """How far a zone-source order stands on its own evidence, 0 to 1.

    Needs the order heard at more than one sensor. It then grows with how
    often it is heard (*zone_match_rate*, 0.40-0.50), how closely it is on
    frequency (*error_score*, 0.50-0.60), how little of it is a wheel order's
    peaks (*wheel_shared_fraction*, full under 0.40, none from 0.50) and its
    strength (13-19 dB). Road noise near an engine/driveline order is faint
    and patchy, so it fails this and keeps the corner-dominance penalties
    ("Confidence levels" in docs/metrics.md).
    """
    settings = ORDER_CONFIDENCE_SETTINGS
    if not zone_source or corroborating_locations < settings.zone_min_corroborating_locations:
        return 0.0
    alias_fraction = settings.wheel_alias_shared_peak_fraction
    return (
        _ramp(
            zone_match_rate,
            settings.zone_min_match_rate,
            settings.zone_min_match_rate + settings.zone_match_rate_ramp,
        )
        * _ramp(
            error_score,
            settings.zone_min_error_score,
            settings.zone_min_error_score + settings.zone_error_score_ramp,
        )
        * (
            1.0
            - _ramp(
                wheel_shared_fraction,
                alias_fraction - settings.zone_wheel_alias_ramp,
                alias_fraction,
            )
        )
        * _ramp(
            absolute_strength_db,
            LIGHT_STRENGTH_MAX_DB - settings.zone_strength_ramp_db,
            LIGHT_STRENGTH_MAX_DB + settings.zone_strength_ramp_db,
        )
    )


# ═══════════════════════════════════════════════════════════════════════════
# Speed-phase evidence
# ═══════════════════════════════════════════════════════════════════════════

# Transient phases: a match there weighs less on the speed band than one at a
# cruise, and they make up the onset evidence. Braking is slowing down too.
_PHASE_ONSET_RELEVANT: frozenset[str] = frozenset(
    {
        DrivingPhase.ACCELERATION.value,
        DrivingPhase.DECELERATION.value,
        DrivingPhase.BRAKING.value,
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
    """Compute per-phase confidence and count phases with sufficient evidence.

    Braking counts as one phase with deceleration: both are slowing down, and
    splitting the spectra by how the car slowed may not add a phase bonus.
    """
    if not has_phases or not possible_by_phase:
        return None, 0
    per_phase_confidence: dict[str, float] = {}
    possible_by_group: Counter[str] = Counter()
    matched_by_group: Counter[str] = Counter()
    for phase_key, phase_possible in possible_by_phase.items():
        phase_matched = matched_by_phase.get(phase_key, 0)
        per_phase_confidence[phase_key] = phase_matched / max(1, phase_possible)
        group = (
            DrivingPhase.DECELERATION.value
            if phase_key == DrivingPhase.BRAKING.value
            else phase_key
        )
        possible_by_group[group] += phase_possible
        matched_by_group[group] += phase_matched
    phases_with_evidence = sum(
        1
        for group, possible in possible_by_group.items()
        if matched_by_group[group] >= min_match_points
        and matched_by_group[group] / max(1, possible) >= min_match_rate
    )
    return per_phase_confidence, phases_with_evidence


def compute_amplitude_and_error_stats(
    evidence: Sequence[tuple[OrderMatchObservation, float]],
    *,
    constant_speed: bool,
) -> tuple[float, float, float, float, float | None]:
    """Amplitude, floor, relative-error and correlation statistics of (match, floor) pairs."""
    points = [point for point, _floor in evidence]
    floors = [floor for _point, floor in evidence]
    mean_amp = _mean([point.amp for point in points])
    mean_floor = _mean(floors)
    mean_rel_err = _mean([point.rel_error for point in points]) if points else 1.0
    corr = (
        _corr_abs_clamped(
            [point.predicted_hz for point in points], [point.matched_hz for point in points]
        )
        if len(points) >= 3 and not constant_speed
        else None
    )
    corr_val = corr if corr is not None else 0.0
    return mean_amp, mean_floor, mean_rel_err, corr_val, corr
