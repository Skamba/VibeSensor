"""Typed tuning collections for diagnostics peak analysis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PeakClassificationSettings:
    """Thresholds for classifying persistent, patterned, and transient peaks."""

    persistent_peak_min_presence: float
    transient_burstiness_threshold: float
    baseline_noise_snr_threshold: float
    spatial_uniformity_high: float
    spatial_uniformity_medium: float
    noise_presence_min_high: float
    noise_burstiness_max_low: float
    noise_speed_uniformity_max: float
    noise_presence_low_min: float
    noise_presence_low_max: float
    noise_burstiness_band_min: float
    noise_burstiness_band_max: float
    patterned_min_presence: float
    patterned_max_burstiness: float


PEAK_CLASSIFICATION_SETTINGS = PeakClassificationSettings(
    persistent_peak_min_presence=0.15,
    transient_burstiness_threshold=5.0,
    baseline_noise_snr_threshold=1.5,
    spatial_uniformity_high=0.85,
    spatial_uniformity_medium=0.80,
    noise_presence_min_high=0.60,
    noise_burstiness_max_low=2.0,
    noise_speed_uniformity_max=0.10,
    noise_presence_low_min=0.20,
    noise_presence_low_max=0.40,
    noise_burstiness_band_min=3.0,
    noise_burstiness_band_max=5.0,
    patterned_min_presence=0.40,
    patterned_max_burstiness=3.0,
)


@dataclass(frozen=True, slots=True)
class PeakConfidenceSettings:
    """Weights and caps for peak confidence and persistence scoring."""

    location_rescue_min_samples: int
    baseline_noise_confidence_min: float
    baseline_noise_confidence_max: float
    baseline_noise_confidence_base: float
    baseline_noise_presence_weight: float
    transient_confidence_min: float
    transient_confidence_max: float
    transient_confidence_base: float
    transient_presence_weight: float
    transient_snr_weight: float
    confidence_min: float
    confidence_max: float
    confidence_base: float
    presence_weight: float
    snr_weight: float
    burstiness_weight: float
    spatial_penalty_base: float
    spatial_penalty_range: float
    low_spatial_concentration_threshold: float
    low_spatial_concentration_cap: float
    negligible_strength_cap: float


PEAK_CONFIDENCE_SETTINGS = PeakConfidenceSettings(
    location_rescue_min_samples=3,
    baseline_noise_confidence_min=0.02,
    baseline_noise_confidence_max=0.12,
    baseline_noise_confidence_base=0.02,
    baseline_noise_presence_weight=0.05,
    transient_confidence_min=0.05,
    transient_confidence_max=0.22,
    transient_confidence_base=0.05,
    transient_presence_weight=0.10,
    transient_snr_weight=0.07,
    confidence_min=0.10,
    confidence_max=0.75,
    confidence_base=0.10,
    presence_weight=0.35,
    snr_weight=0.15,
    burstiness_weight=0.15,
    spatial_penalty_base=0.35,
    spatial_penalty_range=0.65,
    low_spatial_concentration_threshold=0.35,
    low_spatial_concentration_cap=0.35,
    negligible_strength_cap=0.40,
)
