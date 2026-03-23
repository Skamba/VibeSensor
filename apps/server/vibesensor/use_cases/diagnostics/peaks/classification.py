"""Peak classification thresholds and policy for diagnostics."""

from __future__ import annotations

from .settings import PEAK_CLASSIFICATION_SETTINGS


def classify_peak_type(
    presence_ratio: float,
    burstiness: float,
    *,
    snr: float | None = None,
    spatial_uniformity: float | None = None,
    speed_uniformity: float | None = None,
) -> str:
    """Classify a frequency peak as patterned/persistent/transient/baseline noise."""
    settings = PEAK_CLASSIFICATION_SETTINGS
    if snr is not None and snr < settings.baseline_noise_snr_threshold:
        return "baseline_noise"
    if (
        spatial_uniformity is not None
        and spatial_uniformity > settings.spatial_uniformity_high
        and presence_ratio >= settings.noise_presence_min_high
        and burstiness < settings.noise_burstiness_max_low
    ):
        return "baseline_noise"
    if (
        spatial_uniformity is not None
        and speed_uniformity is not None
        and spatial_uniformity >= settings.spatial_uniformity_medium
        and speed_uniformity <= settings.noise_speed_uniformity_max
        and settings.noise_presence_low_min <= presence_ratio <= settings.noise_presence_low_max
        and settings.noise_burstiness_band_min <= burstiness <= settings.noise_burstiness_band_max
    ):
        return "baseline_noise"

    if presence_ratio < settings.persistent_peak_min_presence:
        return "transient"
    if burstiness > settings.transient_burstiness_threshold:
        return "transient"
    if (
        presence_ratio >= settings.patterned_min_presence
        and burstiness < settings.patterned_max_burstiness
    ):
        return "patterned"
    return "persistent"
