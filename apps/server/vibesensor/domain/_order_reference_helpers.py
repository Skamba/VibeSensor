"""Domain-local helpers for order-reference aspect normalization and projection."""

from __future__ import annotations

import math
from collections.abc import Mapping

from vibesensor.domain.order_reference import (
    OrderReferenceSpec,
    order_reference_mapping_from_spec,
)
from vibesensor.domain.tire_spec import TireSpec

ORDER_REFERENCE_KEYS: tuple[str, ...] = (
    "tire_width_mm",
    "tire_aspect_pct",
    "rim_in",
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
    tire_inputs = {
        key: value
        for key in ("tire_width_mm", "tire_aspect_pct", "rim_in")
        if (value := _coerce_finite_float(settings.get(key), default=None)) is not None
    }
    tire = TireSpec.from_aspects(
        tire_inputs,
        deflection_factor=resolved_deflection if resolved_deflection is not None else 1.0,
    )
    if tire is None:
        return None

    def _f(key: str, default: float = 0.0) -> float:
        value = _coerce_finite_float(settings.get(key), default=default)
        return default if value is None else value

    return OrderReferenceSpec(
        tire_spec=tire,
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


def normalize_order_reference_mapping(aspects: Mapping[str, object]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for key in ORDER_REFERENCE_KEYS:
        value = _coerce_finite_float(aspects.get(key), default=None)
        if value is None:
            continue
        if key in {"tire_width_mm", "tire_aspect_pct", "rim_in"} and value <= 0:
            raise ValueError(
                f"Car.aspects[{key!r}] must be a positive finite number, got {value}",
            )
        normalized[key] = value
    return normalized


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
