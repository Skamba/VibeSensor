"""Common settings-facing shared type aliases."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Literal, TypedDict, cast

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
    # Optional references: absent or null means unknown (a null on a car update clears it).
    final_drive_ratio: float | None
    current_gear_ratio: float | None
    speed_uncertainty_pct: float
    tire_diameter_uncertainty_pct: float
    final_drive_uncertainty_pct: float
    gear_uncertainty_pct: float
    tire_deflection_factor: float


def analysis_settings_payload_from_mapping(
    values: Mapping[str, object],
) -> AnalysisSettingsPayload:
    """Keep the finite numeric settings and a valid speed axle from *values*.

    Keys follow the ``AnalysisSettingsPayload`` field order; anything else is dropped.
    """
    payload: dict[str, float | str] = {}
    for key in AnalysisSettingsPayload.__annotations__:
        value = values.get(key)
        if key == "default_axle_for_speed":
            if (axle := analysis_settings_axle_from_mapping(value)) is not None:
                payload[key] = axle
        elif (number := _finite_float_or_none(value)) is not None:
            payload[key] = number
    return cast(AnalysisSettingsPayload, payload)


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
