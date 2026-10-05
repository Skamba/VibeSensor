"""Typed tuning collections for diagnostics order analysis."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.analysis.constants import CONFIDENCE_CEILING, CONFIDENCE_FLOOR


@dataclass(frozen=True, slots=True)
class OrderConfidenceSettings:
    """Weights and caps used when calibrating order-finding confidence."""

    confidence_floor: float
    confidence_ceiling: float
    single_sensor_confidence_scale: float
    dual_sensor_confidence_scale: float
    confidence_base: float
    match_weight: float
    error_weight: float
    correlation_weight: float
    snr_weight: float
    correlation_max_shift: float
    correlation_compliance_factor: float
    negligible_strength_confidence_cap: float
    negligible_strength_ramp_db: float
    light_strength_penalty: float
    light_strength_ramp_db: float
    localization_base: float
    localization_spread: float
    weak_separation_dominance_threshold: float
    weak_separation_strong_penalty: float
    weak_separation_uniform_dominance: float
    weak_separation_uniform_penalty: float
    weak_separation_mild_penalty: float
    no_wheel_sensor_penalty: float
    zone_localization_confidence: float
    zone_min_match_rate: float
    zone_strength_ramp_db: float
    heard_peak_over_floor: float
    heard_location_min_share: float
    zone_min_error_score: float
    zone_min_corroborating_locations: int
    constant_speed_penalty: float
    steady_speed_penalty: float
    sample_saturation_count: int
    sample_weight_base: float
    sample_weight_range: float
    corroborating_three_bonus: float
    corroborating_two_bonus: float
    phases_three_bonus: float
    phases_two_bonus: float
    localization_min_scale_threshold: float


ORDER_CONFIDENCE_SETTINGS = OrderConfidenceSettings(
    confidence_floor=CONFIDENCE_FLOOR,
    confidence_ceiling=CONFIDENCE_CEILING,
    single_sensor_confidence_scale=0.85,
    dual_sensor_confidence_scale=0.92,
    confidence_base=0.10,
    match_weight=0.35,
    error_weight=0.20,
    correlation_weight=0.10,
    snr_weight=0.20,
    correlation_max_shift=0.05,
    correlation_compliance_factor=0.10,
    # Just below Moderate (0.40): an order at road-noise level is at most Weak.
    negligible_strength_confidence_cap=0.39,
    # Ramps over the band edges (docs/metrics.md, "Confidence levels"): the cap
    # lifts over 8–12 dB, the light penalty eases out over 16–19 dB.
    negligible_strength_ramp_db=4.0,
    light_strength_penalty=0.80,
    light_strength_ramp_db=3.0,
    localization_base=0.70,
    localization_spread=0.30,
    weak_separation_dominance_threshold=1.5,
    weak_separation_strong_penalty=0.90,
    weak_separation_uniform_dominance=1.05,
    weak_separation_uniform_penalty=0.70,
    weak_separation_mild_penalty=0.80,
    no_wheel_sensor_penalty=0.75,
    # What a wheel order at a clearly dominant corner earns with four sensors.
    zone_localization_confidence=0.69,
    # Share of windows with the order heard, at the sensors that hear it. Road
    # noise sitting on the order's frequency by chance does not count, so a
    # tone heard for under 40 % of the drive is not established evidence
    # however exactly a measured speed tracks it.
    zone_min_match_rate=0.40,
    # Half-width of the zone credit's ramp around 16 dB (13–19 dB).
    zone_strength_ramp_db=3.0,
    # A match is heard when its peak stands at least 6 dB over its window's
    # floor, at a sensor where that happens at least half as often as at the
    # sensor where it happens most (docs/order_tracking.md, "Heard matches").
    heard_peak_over_floor=2.0,
    heard_location_min_share=0.5,
    zone_min_error_score=0.50,
    zone_min_corroborating_locations=2,
    constant_speed_penalty=0.75,
    steady_speed_penalty=0.82,
    sample_saturation_count=20,
    sample_weight_base=0.70,
    sample_weight_range=0.30,
    corroborating_three_bonus=1.08,
    corroborating_two_bonus=1.04,
    phases_three_bonus=1.06,
    phases_two_bonus=1.03,
    localization_min_scale_threshold=0.30,
)


@dataclass(frozen=True, slots=True)
class OrderHeuristicSettings:
    """Thresholds and penalties used by order-analysis heuristics."""

    diffuse_amplitude_dominance_ratio: float
    diffuse_match_rate_range_threshold: float
    diffuse_min_mean_rate: float
    diffuse_penalty_base: float
    diffuse_penalty_per_sensor: float
    diffuse_penalty_floor: float
    harmonic_alias_ratio: float
    engine_alias_suppression: float
    wheel_locked_alias_margin_db: float
    spread_engine_alias_margin_db: float
    dominant_single_location_base: float
    dominant_single_location_step: float
    fallback_single_location_base: float
    fallback_single_location_step: float


ORDER_HEURISTIC_SETTINGS = OrderHeuristicSettings(
    diffuse_amplitude_dominance_ratio=2.0,
    diffuse_match_rate_range_threshold=0.15,
    diffuse_min_mean_rate=0.15,
    diffuse_penalty_base=0.85,
    diffuse_penalty_per_sensor=0.04,
    diffuse_penalty_floor=0.65,
    harmonic_alias_ratio=1.15,
    engine_alias_suppression=0.60,
    # An engine order locked to a wheel order (estimated RPM, shared peaks) is
    # that wheel's harmonic when a wheel order is at least twice as strong.
    wheel_locked_alias_margin_db=6.0,
    # An engine order with no dominant location is demoted next to a wheel
    # order about three times as strong at its corner. Peak levels from a
    # speed sweep favour the slower-moving (lower) order by a few dB, so this
    # margin is wider than the one for a locked engine order.
    spread_engine_alias_margin_db=9.0,
    dominant_single_location_base=0.50,
    dominant_single_location_step=0.15,
    fallback_single_location_base=0.40,
    fallback_single_location_step=0.10,
)
