"""Common settings-facing shared type aliases."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Literal, TypedDict

from vibesensor.domain.tire_spec import TireSpeedAxle

__all__ = [
    "AnalysisSettingsPayload",
    "analysis_settings_axle_from_mapping",
    "analysis_settings_payload_from_mapping",
    "LanguageCode",
    "SpeedUnitCode",
    "TireSpeedAxle",
]


class AnalysisSettingsPayload(TypedDict, total=False):
    """Structured partial payload for analysis-setting updates and car aspects."""

    tire_width_mm: float
    tire_aspect_pct: float
    rim_in: float
    front_tire_width_mm: float
    front_tire_aspect_pct: float
    front_rim_in: float
    rear_tire_width_mm: float
    rear_tire_aspect_pct: float
    rear_rim_in: float
    default_axle_for_speed: TireSpeedAxle
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
    values: Mapping[str, object],
) -> AnalysisSettingsPayload:
    """Project a trusted flat mapping into the named-field settings payload."""
    payload: AnalysisSettingsPayload = {}
    if (tire_width := _finite_float_or_none(values.get("tire_width_mm"))) is not None:
        payload["tire_width_mm"] = tire_width
    if (tire_aspect := _finite_float_or_none(values.get("tire_aspect_pct"))) is not None:
        payload["tire_aspect_pct"] = tire_aspect
    if (rim := _finite_float_or_none(values.get("rim_in"))) is not None:
        payload["rim_in"] = rim
    if (front_width := _finite_float_or_none(values.get("front_tire_width_mm"))) is not None:
        payload["front_tire_width_mm"] = front_width
    if (front_aspect := _finite_float_or_none(values.get("front_tire_aspect_pct"))) is not None:
        payload["front_tire_aspect_pct"] = front_aspect
    if (front_rim := _finite_float_or_none(values.get("front_rim_in"))) is not None:
        payload["front_rim_in"] = front_rim
    if (rear_width := _finite_float_or_none(values.get("rear_tire_width_mm"))) is not None:
        payload["rear_tire_width_mm"] = rear_width
    if (rear_aspect := _finite_float_or_none(values.get("rear_tire_aspect_pct"))) is not None:
        payload["rear_tire_aspect_pct"] = rear_aspect
    if (rear_rim := _finite_float_or_none(values.get("rear_rim_in"))) is not None:
        payload["rear_rim_in"] = rear_rim
    if (
        default_axle := analysis_settings_axle_from_mapping(values.get("default_axle_for_speed"))
    ) is not None:
        payload["default_axle_for_speed"] = default_axle
    if (final_drive := _finite_float_or_none(values.get("final_drive_ratio"))) is not None:
        payload["final_drive_ratio"] = final_drive
    if (current_gear := _finite_float_or_none(values.get("current_gear_ratio"))) is not None:
        payload["current_gear_ratio"] = current_gear
    if (wheel_bandwidth := _finite_float_or_none(values.get("wheel_bandwidth_pct"))) is not None:
        payload["wheel_bandwidth_pct"] = wheel_bandwidth
    if (
        driveshaft_bandwidth := _finite_float_or_none(values.get("driveshaft_bandwidth_pct"))
    ) is not None:
        payload["driveshaft_bandwidth_pct"] = driveshaft_bandwidth
    if (engine_bandwidth := _finite_float_or_none(values.get("engine_bandwidth_pct"))) is not None:
        payload["engine_bandwidth_pct"] = engine_bandwidth
    if (
        speed_uncertainty := _finite_float_or_none(values.get("speed_uncertainty_pct"))
    ) is not None:
        payload["speed_uncertainty_pct"] = speed_uncertainty
    if (
        tire_diameter_uncertainty := _finite_float_or_none(
            values.get("tire_diameter_uncertainty_pct")
        )
    ) is not None:
        payload["tire_diameter_uncertainty_pct"] = tire_diameter_uncertainty
    if (
        final_drive_uncertainty := _finite_float_or_none(values.get("final_drive_uncertainty_pct"))
    ) is not None:
        payload["final_drive_uncertainty_pct"] = final_drive_uncertainty
    if (gear_uncertainty := _finite_float_or_none(values.get("gear_uncertainty_pct"))) is not None:
        payload["gear_uncertainty_pct"] = gear_uncertainty
    if (min_abs_band := _finite_float_or_none(values.get("min_abs_band_hz"))) is not None:
        payload["min_abs_band_hz"] = min_abs_band
    if (
        max_band_half_width := _finite_float_or_none(values.get("max_band_half_width_pct"))
    ) is not None:
        payload["max_band_half_width_pct"] = max_band_half_width
    if (deflection := _finite_float_or_none(values.get("tire_deflection_factor"))) is not None:
        payload["tire_deflection_factor"] = deflection
    return payload


def analysis_settings_axle_from_mapping(value: object) -> TireSpeedAxle | None:
    if value == "front":
        return "front"
    if value == "rear":
        return "rear"
    if value == "average":
        return "average"
    return None


def _finite_float_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


type LanguageCode = Literal["en", "nl"]
type SpeedUnitCode = Literal["kmh", "mps"]
