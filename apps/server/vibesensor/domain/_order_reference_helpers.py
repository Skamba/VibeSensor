"""Domain-local helpers for order-reference aspect normalization and projection."""

from __future__ import annotations

import math
from collections.abc import Mapping

from vibesensor.domain.order_reference import (
    OrderReferenceSpec,
    order_reference_mapping_from_spec,
)
from vibesensor.domain.tire_spec import AxleTireSetup, TireSpec, TireSpeedAxle

ORDER_REFERENCE_KEYS: tuple[str, ...] = (
    "tire_width_mm",
    "tire_aspect_pct",
    "rim_in",
    "front_tire_width_mm",
    "front_tire_aspect_pct",
    "front_rim_in",
    "rear_tire_width_mm",
    "rear_tire_aspect_pct",
    "rear_rim_in",
    "default_axle_for_speed",
    "final_drive_ratio",
    "current_gear_ratio",
    "wheel_bandwidth_pct",
    "driveshaft_bandwidth_pct",
    "engine_bandwidth_pct",
    "speed_uncertainty_pct",
    "tire_diameter_uncertainty_pct",
    "final_drive_uncertainty_pct",
    "gear_uncertainty_pct",
    "min_abs_band_hz",
    "max_band_half_width_pct",
    "tire_deflection_factor",
)

__all__ = [
    "ORDER_REFERENCE_KEYS",
    "normalize_order_reference_mapping",
    "order_reference_mapping_from_spec",
    "order_reference_spec_from_mapping",
]


def order_reference_spec_from_mapping(
    settings: Mapping[str, object],
    *,
    deflection_factor: float | None = None,
) -> OrderReferenceSpec | None:
    resolved_deflection = _coerce_finite_float(
        settings.get("tire_deflection_factor"),
        default=1.0,
    )
    if deflection_factor is not None and math.isfinite(deflection_factor):
        resolved_deflection = float(deflection_factor)
    base_tire = _tire_spec_from_mapping(
        settings,
        width_key="tire_width_mm",
        aspect_key="tire_aspect_pct",
        rim_key="rim_in",
        deflection_factor=resolved_deflection,
    )
    front_tire = (
        _tire_spec_from_mapping(
            settings,
            width_key="front_tire_width_mm",
            aspect_key="front_tire_aspect_pct",
            rim_key="front_rim_in",
            deflection_factor=resolved_deflection,
        )
        or base_tire
    )
    rear_tire = (
        _tire_spec_from_mapping(
            settings,
            width_key="rear_tire_width_mm",
            aspect_key="rear_tire_aspect_pct",
            rim_key="rear_rim_in",
            deflection_factor=resolved_deflection,
        )
        or front_tire
    )
    if front_tire is None or rear_tire is None:
        return None
    default_axle_for_speed = _default_axle_for_speed(settings.get("default_axle_for_speed"))
    tire_setup = AxleTireSetup(
        front=front_tire,
        rear=rear_tire,
        default_axle_for_speed=default_axle_for_speed,
    )

    def _f(key: str, default: float = 0.0) -> float:
        value = _coerce_finite_float(settings.get(key), default=default)
        return default if value is None else value

    return OrderReferenceSpec(
        tire_setup=tire_setup,
        final_drive_ratio=_f("final_drive_ratio"),
        current_gear_ratio=_f("current_gear_ratio"),
        wheel_bandwidth_pct=_f("wheel_bandwidth_pct"),
        driveshaft_bandwidth_pct=_f("driveshaft_bandwidth_pct"),
        engine_bandwidth_pct=_f("engine_bandwidth_pct"),
        speed_uncertainty_pct=_f("speed_uncertainty_pct"),
        tire_diameter_uncertainty_pct=_f("tire_diameter_uncertainty_pct"),
        final_drive_uncertainty_pct=_f("final_drive_uncertainty_pct"),
        gear_uncertainty_pct=_f("gear_uncertainty_pct"),
        min_abs_band_hz=_f("min_abs_band_hz"),
        max_band_half_width_pct=_f("max_band_half_width_pct"),
    )


def normalize_order_reference_mapping(aspects: Mapping[str, object]) -> dict[str, float | str]:
    normalized: dict[str, float | str] = {}
    for key in ORDER_REFERENCE_KEYS:
        if key == "default_axle_for_speed":
            axle = aspects.get(key)
            if axle in {"front", "rear", "average"}:
                normalized[key] = axle
            continue
        value = _coerce_finite_float(aspects.get(key), default=None)
        if value is None:
            continue
        if (
            key
            in {
                "tire_width_mm",
                "tire_aspect_pct",
                "rim_in",
                "front_tire_width_mm",
                "front_tire_aspect_pct",
                "front_rim_in",
                "rear_tire_width_mm",
                "rear_tire_aspect_pct",
                "rear_rim_in",
            }
            and value <= 0
        ):
            raise ValueError(
                f"Car.aspects[{key!r}] must be a positive finite number, got {value}",
            )
        normalized[key] = value
    return normalized


def _tire_spec_from_mapping(
    settings: Mapping[str, object],
    *,
    width_key: str,
    aspect_key: str,
    rim_key: str,
    deflection_factor: float | None,
) -> TireSpec | None:
    tire_inputs = {
        mapped_key: value
        for mapped_key, raw_key in (
            ("tire_width_mm", width_key),
            ("tire_aspect_pct", aspect_key),
            ("rim_in", rim_key),
        )
        if (value := _coerce_finite_float(settings.get(raw_key), default=None)) is not None
    }
    return TireSpec.from_aspects(
        tire_inputs,
        deflection_factor=deflection_factor if deflection_factor is not None else 1.0,
    )


def _default_axle_for_speed(value: object) -> TireSpeedAxle:
    if value == "front":
        return "front"
    if value == "average":
        return "average"
    return "rear"


def _coerce_finite_float(value: object, *, default: float | None) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default
