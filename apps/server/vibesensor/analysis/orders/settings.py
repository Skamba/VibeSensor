"""Typed tuning collections for diagnostics order analysis."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.analysis.constants import CONFIDENCE_CEILING, CONFIDENCE_FLOOR
from vibesensor.dsp.line_significance import HEARD_OVER_FLOOR


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
    weak_confidence_cap: float
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
    weak_separation_uniform_ramp: float
    weak_separation_edge_ramp: float
    zone_localization_confidence: float
    zone_min_match_rate: float
    zone_match_rate_ramp: float
    zone_strength_ramp_db: float
    heard_peak_over_floor: float
    heard_location_min_share: float
    zone_min_error_score: float
    zone_error_score_ramp: float
    corroboration_ramp: float
    wheel_alias_shared_peak_fraction: float
    zone_wheel_alias_ramp: float
    presence_ramp: float
    constant_speed_penalty: float
    steady_speed_penalty: float
    sample_saturation_count: int
    sample_weight_base: float
    sample_weight_range: float
    corroborating_three_bonus: float
    corroborating_two_bonus: float
    phases_three_bonus: float
    phases_two_bonus: float
    phase_rate_ramp: float
    few_sensor_scale_from_localization: float
    few_sensor_scale_full_localization: float


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
    # Just below Moderate (0.40): an order at road-noise level, or one heard in
    # barely enough windows to count, is at most Weak.
    weak_confidence_cap=0.39,
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
    # The spread penalties ease out over the next 0.10 / 0.15 of dominance past
    # each edge (uniform -> mild from 1.05, mild -> none from the location
    # count's weak-separation threshold, mild -> strong from 1.5 without wheel
    # sensors), so a dominance a hair over an edge moves the score a little.
    weak_separation_uniform_ramp=0.10,
    weak_separation_edge_ramp=0.15,
    # What a wheel order at a clearly dominant corner earns with four sensors.
    zone_localization_confidence=0.69,
    # Share of windows with the order heard, at the sensors that hear it. Road
    # noise sitting on the order's frequency by chance does not count, so a
    # tone heard for under 40 % of the drive is not established evidence
    # however exactly a measured speed tracks it.
    zone_min_match_rate=0.40,
    # The zone credit's evidence terms ramp in over the step above each
    # minimum: heard rate 0.40-0.50, error score 0.50-0.60.
    zone_match_rate_ramp=0.10,
    # Half-width of the zone credit's ramp around 16 dB (13–19 dB).
    zone_strength_ramp_db=3.0,
    # A match is heard when its peak stands at least 6 dB over its window's
    # floor, at a sensor where that happens at least half as often as at the
    # sensor where it happens most (docs/order_tracking.md, "Heard matches").
    heard_peak_over_floor=HEARD_OVER_FLOOR,
    heard_location_min_share=0.5,
    zone_min_error_score=0.50,
    zone_error_score_ramp=0.10,
    # A sensor counts towards corroboration (the zone credit's second sensor,
    # the corroboration bonus) in full only from 0.10 over the heard bar
    # (half the clearest sensor's clear rate), and a little just over it.
    corroboration_ramp=0.10,
    # An engine/driveline order is an alias of a wheel order when at least this
    # share of its matched peaks are peaks a wheel order matched too; the zone
    # credit fades out over the 0.10 below it.
    wheel_alias_shared_peak_fraction=0.50,
    zone_wheel_alias_ramp=0.10,
    # An order heard in just enough windows to count is at most Weak; the cap
    # lifts over the next 0.15 of effective match rate.
    presence_ramp=0.15,
    constant_speed_penalty=0.75,
    steady_speed_penalty=0.82,
    sample_saturation_count=20,
    sample_weight_base=0.70,
    sample_weight_range=0.30,
    corroborating_three_bonus=1.08,
    corroborating_two_bonus=1.04,
    phases_three_bonus=1.06,
    phases_two_bonus=1.03,
    # A phase counts for the phase bonus in full from 0.10 over the minimum
    # match rate, and a little just over it.
    phase_rate_ramp=0.10,
    # With one or two sensors a localisation claim is discounted, fully from
    # localisation 0.30 and easing in from the 0.05 floor.
    few_sensor_scale_from_localization=0.05,
    few_sensor_scale_full_localization=0.30,
)


@dataclass(frozen=True, slots=True)
class OrderHeuristicSettings:
    """Thresholds and penalties used by order-analysis heuristics."""

    diffuse_amplitude_dominance_ratio: float
    diffuse_match_rate_range_threshold: float
    diffuse_min_mean_rate: float
    diffuse_amplitude_ramp: float
    diffuse_match_rate_range_ramp: float
    diffuse_mean_rate_ramp: float
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
    # Past each edge the penalty eases out instead of vanishing: amplitude
    # ratio 2.0-3.0, match-rate range 0.15-0.30, mean match rate 0.15-0.05.
    diffuse_amplitude_ramp=1.0,
    diffuse_match_rate_range_ramp=0.15,
    diffuse_mean_rate_ramp=0.10,
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
