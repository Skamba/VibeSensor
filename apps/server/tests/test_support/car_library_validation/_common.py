"""Shared types and small helpers for vehicle library validation rules."""

from __future__ import annotations

import re
from dataclasses import dataclass

from vibesensor.domain import TireSpec, VehicleConfiguration

AWD_BADGE_TOKENS = ("xdrive", "quattro", "4matic")
RWD_BADGE_TOKENS = ("edrive",)
FINAL_DRIVE_RANGE = (2.0, 15.0)
TOP_GEAR_RANGE = (0.35, 1.1)
GEAR_RATIO_RANGE = (0.4, 8.0)
TIRE_DIAMETER_RANGE_MM = (550.0, 850.0)
RIM_SUFFIX_RE = re.compile(r'(?P<rim>\d+)"$')


@dataclass(frozen=True, slots=True)
class CarLibraryValidationIssue:
    """One machine-readable validation failure for bundled car data."""

    rule: str
    entity: str
    message: str


def model_entity(brand: str, model: str) -> str:
    return f"{brand}|{model}"


def variant_entity(brand: str, model: str, variant_name: str) -> str:
    return f"{brand}|{model}|{variant_name}"


def text(value: object) -> str:
    return str(value or "").strip()


def float_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def in_range(value: float, bounds: tuple[float, float]) -> bool:
    lower, upper = bounds
    return lower <= value <= upper


def classify_fuel_type(engine_name: str | None) -> str:
    normalized = (engine_name or "").lower()
    if "phev" in normalized:
        return "PHEV"
    if "electric" in normalized or normalized.startswith("ev "):
        return "EV"
    return "ICE"


def is_single_speed_gearbox(gearbox_name: str) -> bool:
    return "single-speed" in gearbox_name.lower()


def normalize_label(value: object) -> str:
    normalized = str(value or "").casefold()
    return re.sub(r"[^a-z0-9]+", "", normalized)


def round_ratio(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def tire_signature(tire: TireSpec | None) -> tuple[float, float, float] | None:
    if tire is None:
        return None
    return (round(tire.width_mm, 1), round(tire.aspect_pct, 1), round(tire.rim_in, 1))


def vehicle_configuration_identity_key(
    config: VehicleConfiguration,
) -> tuple[object, ...]:
    return (
        normalize_label(config.brand),
        normalize_label(config.model_name),
        normalize_label(config.variant_name),
        config.drivetrain,
        config.fuel_type,
        normalize_label(config.transmission_name),
        round_ratio(config.top_gear_ratio),
        round_ratio(config.final_drive_front),
        round_ratio(config.final_drive_rear),
        tire_signature(config.default_tire),
    )


def vehicle_configuration_fuzzy_label_key(config: VehicleConfiguration) -> tuple[str, str, str]:
    return (
        normalize_label(config.brand),
        normalize_label(config.model_name),
        normalize_label(config.variant_name),
    )
