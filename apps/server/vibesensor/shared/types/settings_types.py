"""Common settings-facing shared type aliases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypedDict

__all__ = [
    "AnalysisSettingsPayload",
    "analysis_settings_payload_from_mapping",
    "LanguageCode",
    "SpeedUnitCode",
]


class AnalysisSettingsPayload(TypedDict, total=False):
    """Structured partial payload for analysis-setting updates and car aspects."""

    tire_width_mm: float
    tire_aspect_pct: float
    rim_in: float
    final_drive_ratio: float
    current_gear_ratio: float
    wheel_bandwidth_pct: float
    driveshaft_bandwidth_pct: float
    engine_bandwidth_pct: float
    speed_uncertainty_pct: float
    tire_diameter_uncertainty_pct: float
    final_drive_uncertainty_pct: float
    gear_uncertainty_pct: float
    min_abs_band_hz: float
    max_band_half_width_pct: float
    tire_deflection_factor: float


def analysis_settings_payload_from_mapping(
    values: Mapping[str, float | int],
) -> AnalysisSettingsPayload:
    """Project a trusted flat mapping into the named-field settings payload."""
    payload: AnalysisSettingsPayload = {}
    if (value := values.get("tire_width_mm")) is not None:
        payload["tire_width_mm"] = float(value)
    if (value := values.get("tire_aspect_pct")) is not None:
        payload["tire_aspect_pct"] = float(value)
    if (value := values.get("rim_in")) is not None:
        payload["rim_in"] = float(value)
    if (value := values.get("final_drive_ratio")) is not None:
        payload["final_drive_ratio"] = float(value)
    if (value := values.get("current_gear_ratio")) is not None:
        payload["current_gear_ratio"] = float(value)
    if (value := values.get("wheel_bandwidth_pct")) is not None:
        payload["wheel_bandwidth_pct"] = float(value)
    if (value := values.get("driveshaft_bandwidth_pct")) is not None:
        payload["driveshaft_bandwidth_pct"] = float(value)
    if (value := values.get("engine_bandwidth_pct")) is not None:
        payload["engine_bandwidth_pct"] = float(value)
    if (value := values.get("speed_uncertainty_pct")) is not None:
        payload["speed_uncertainty_pct"] = float(value)
    if (value := values.get("tire_diameter_uncertainty_pct")) is not None:
        payload["tire_diameter_uncertainty_pct"] = float(value)
    if (value := values.get("final_drive_uncertainty_pct")) is not None:
        payload["final_drive_uncertainty_pct"] = float(value)
    if (value := values.get("gear_uncertainty_pct")) is not None:
        payload["gear_uncertainty_pct"] = float(value)
    if (value := values.get("min_abs_band_hz")) is not None:
        payload["min_abs_band_hz"] = float(value)
    if (value := values.get("max_band_half_width_pct")) is not None:
        payload["max_band_half_width_pct"] = float(value)
    if (value := values.get("tire_deflection_factor")) is not None:
        payload["tire_deflection_factor"] = float(value)
    return payload


type LanguageCode = Literal["en", "nl"]
type SpeedUnitCode = Literal["kmh", "mps"]
