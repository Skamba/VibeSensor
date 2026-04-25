"""Static library of BMW and Audi cars with realistic drivetrain data.

Data is loaded from ``apps/server/vibesensor/data/car_library.json``.
This module caches the parsed list at import time and exposes lightweight
query helpers used by the API layer.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Literal, NotRequired, TypedDict, cast

from pydantic import ConfigDict, TypeAdapter, ValidationError

from vibesensor.domain import TireSpec, VehicleConfiguration, VehicleConfigurationTireOption
from vibesensor.shared._data_files import resolve_static_data_file

LOGGER = logging.getLogger(__name__)

__all__ = [
    "CarLibraryEntry",
    "get_brands",
    "get_models_for_brand_type",
    "get_types_for_brand",
    "load_car_library",
    "load_vehicle_configurations",
    "get_variants_for_model",
    "get_exact_configurations_for_variant",
    "resolve_variant",
    "resolve_vehicle_configurations",
]

_DATA_FILE = resolve_static_data_file("car_library.json")
_VEHICLE_CONFIG_DATA_FILE = resolve_static_data_file("vehicle_configurations.json")
_STRICT_TYPEDDICT_CONFIG = ConfigDict(extra="forbid")


class CarLibraryGearbox(TypedDict):
    name: str
    final_drive_ratio: float
    top_gear_ratio: float
    gear_ratios: NotRequired[list[float]]


class CarLibraryTireOption(TypedDict):
    name: str
    tire_width_mm: float
    tire_aspect_pct: float
    rim_in: float


class CarLibraryVariant(TypedDict):
    name: str
    drivetrain: Literal["FWD", "RWD", "AWD"]
    engine: NotRequired[str]
    gearboxes: NotRequired[list[CarLibraryGearbox]]
    tire_options: NotRequired[list[CarLibraryTireOption]]
    tire_width_mm: NotRequired[float]
    tire_aspect_pct: NotRequired[float]
    rim_in: NotRequired[float]


class CarLibraryEntry(TypedDict):
    brand: str
    type: str
    model: str
    gearboxes: list[CarLibraryGearbox]
    tire_options: list[CarLibraryTireOption]
    tire_width_mm: float
    tire_aspect_pct: float
    rim_in: float
    variants: list[CarLibraryVariant]


class VehicleConfigurationRow(TypedDict):
    brand: str
    type: str
    market: str
    model_code: str
    body_code: str
    production_start_year: int
    production_end_year: int
    model_name: str
    variant_name: str
    engine_code: str
    engine_name: str
    fuel_type: Literal["ICE", "PHEV", "EV"]
    drivetrain: Literal["FWD", "RWD", "AWD"]
    transmission_code: str
    transmission_name: str
    top_gear_ratio: float
    gear_ratios: NotRequired[list[float]]
    final_drive_front: NotRequired[float]
    final_drive_rear: NotRequired[float]
    transfer_case_ratio: NotRequired[float]
    tire_options: list[CarLibraryTireOption]
    tire_width_mm: float
    tire_aspect_pct: float
    rim_in: float
    source_status: Literal["exact_row"]


for _typed_dict in (
    CarLibraryGearbox,
    CarLibraryTireOption,
    CarLibraryVariant,
    CarLibraryEntry,
    VehicleConfigurationRow,
):
    cast(Any, _typed_dict).__pydantic_config__ = _STRICT_TYPEDDICT_CONFIG

_CAR_LIBRARY_ADAPTER = TypeAdapter(list[CarLibraryEntry])
_VEHICLE_CONFIGURATION_ADAPTER = TypeAdapter(list[VehicleConfigurationRow])


def _entry_matches_identity(
    entry: CarLibraryEntry, *, brand: str, car_type: str, model: str
) -> bool:
    return entry["brand"] == brand and entry["type"] == car_type and entry["model"] == model


def _deep_copy_entry(entry: CarLibraryEntry) -> CarLibraryEntry:
    return copy.deepcopy(entry)


def _deep_copy_variants(variants: list[CarLibraryVariant]) -> list[CarLibraryVariant]:
    return copy.deepcopy(variants)


def _load_library() -> list[CarLibraryEntry]:
    """Load and return the car library from the canonical JSON file.

    Unlike an ``@lru_cache`` approach, this retries on every call so a
    transient I/O or permission error at first import does not permanently
    disable the library for the lifetime of the process.
    """
    try:
        with _DATA_FILE.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return _CAR_LIBRARY_ADAPTER.validate_python(data)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        PermissionError,
        OSError,
        ValidationError,
    ) as exc:
        LOGGER.warning("Could not load car library from %s: %s", _DATA_FILE, exc)
        return []


def _tire_spec_from_dimensions(
    *,
    tire_width_mm: float,
    tire_aspect_pct: float,
    rim_in: float,
) -> TireSpec:
    spec = TireSpec.from_aspects(
        {
            "tire_width_mm": tire_width_mm,
            "tire_aspect_pct": tire_aspect_pct,
            "rim_in": rim_in,
        }
    )
    if spec is None:
        raise ValueError(
            f"Invalid tire dimensions width={tire_width_mm} aspect={tire_aspect_pct} rim={rim_in}"
        )
    return spec


def _tire_options_from_rows(
    rows: list[CarLibraryTireOption],
) -> tuple[VehicleConfigurationTireOption, ...]:
    return tuple(
        VehicleConfigurationTireOption(
            name=row["name"],
            spec=_tire_spec_from_dimensions(
                tire_width_mm=row["tire_width_mm"],
                tire_aspect_pct=row["tire_aspect_pct"],
                rim_in=row["rim_in"],
            ),
        )
        for row in rows
    )


def _configuration_from_row(row: VehicleConfigurationRow) -> VehicleConfiguration:
    return VehicleConfiguration(
        brand=row["brand"],
        car_type=row["type"],
        market=row["market"],
        model_code=row["model_code"],
        body_code=row["body_code"],
        production_start_year=row["production_start_year"],
        production_end_year=row["production_end_year"],
        model_name=row["model_name"],
        variant_name=row["variant_name"],
        engine_code=row["engine_code"],
        engine_name=row["engine_name"],
        fuel_type=row["fuel_type"],
        drivetrain=row["drivetrain"],
        transmission_code=row["transmission_code"],
        transmission_name=row["transmission_name"],
        top_gear_ratio=row["top_gear_ratio"],
        gear_ratios=tuple(row["gear_ratios"]) if "gear_ratios" in row else None,
        final_drive_front=row.get("final_drive_front"),
        final_drive_rear=row.get("final_drive_rear"),
        transfer_case_ratio=row.get("transfer_case_ratio"),
        tire_options=_tire_options_from_rows(row["tire_options"]),
        default_tire=_tire_spec_from_dimensions(
            tire_width_mm=row["tire_width_mm"],
            tire_aspect_pct=row["tire_aspect_pct"],
            rim_in=row["rim_in"],
        ),
        source_status=row["source_status"],
    )


def _fuel_type_from_engine_name(engine_name: str | None) -> Literal["ICE", "PHEV", "EV"]:
    normalized = (engine_name or "").lower()
    if "electric" in normalized or normalized.startswith("ev "):
        return "EV"
    if "phev" in normalized:
        return "PHEV"
    return "ICE"


def _project_legacy_variant_rows(
    base_entry: CarLibraryEntry,
    variant_name: str,
) -> tuple[VehicleConfiguration, ...]:
    selected_variant = next(
        (variant for variant in base_entry["variants"] if variant["name"] == variant_name),
        None,
    )
    if selected_variant is None:
        return ()
    resolved = resolve_variant(base_entry, variant_name)
    tire_options = _tire_options_from_rows(resolved["tire_options"])
    default_tire = _tire_spec_from_dimensions(
        tire_width_mm=resolved["tire_width_mm"],
        tire_aspect_pct=resolved["tire_aspect_pct"],
        rim_in=resolved["rim_in"],
    )
    engine_name = selected_variant.get("engine")
    drivetrain = selected_variant["drivetrain"]
    configs: list[VehicleConfiguration] = []
    for gearbox in resolved["gearboxes"]:
        final_drive_ratio = gearbox["final_drive_ratio"]
        configs.append(
            VehicleConfiguration(
                brand=base_entry["brand"],
                car_type=base_entry["type"],
                model_name=base_entry["model"],
                variant_name=variant_name,
                drivetrain=drivetrain,
                transmission_name=gearbox["name"],
                top_gear_ratio=gearbox["top_gear_ratio"],
                default_tire=default_tire,
                tire_options=tire_options,
                fuel_type=_fuel_type_from_engine_name(engine_name),
                engine_code=engine_name,
                engine_name=engine_name,
                gear_ratios=tuple(gearbox["gear_ratios"]) if "gear_ratios" in gearbox else None,
                final_drive_front=final_drive_ratio if drivetrain in {"FWD", "AWD"} else None,
                final_drive_rear=final_drive_ratio if drivetrain in {"RWD", "AWD"} else None,
                transfer_case_ratio=1.0 if drivetrain == "AWD" else None,
                source_status="compat_projection",
            )
        )
    return tuple(configs)


def _load_vehicle_configurations_snapshot() -> list[VehicleConfiguration]:
    try:
        with _VEHICLE_CONFIG_DATA_FILE.open(encoding="utf-8") as fh:
            data = json.load(fh)
        rows = _VEHICLE_CONFIGURATION_ADAPTER.validate_python(data)
        return [_configuration_from_row(row) for row in rows]
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        PermissionError,
        OSError,
        ValidationError,
        ValueError,
    ) as exc:
        LOGGER.warning(
            "Could not load exact vehicle configurations from %s: %s",
            _VEHICLE_CONFIG_DATA_FILE,
            exc,
        )
        return []


# Query helpers reuse one import-time snapshot; explicit loaders can call
# ``load_car_library()`` when they need a fresh validated read from disk.
_CAR_LIBRARY: list[CarLibraryEntry] = _load_library()
_VEHICLE_CONFIGURATIONS: list[VehicleConfiguration] = _load_vehicle_configurations_snapshot()


def load_car_library() -> list[CarLibraryEntry]:
    """Load and return a fresh validated car-library snapshot."""

    return _load_library()


def load_vehicle_configurations() -> list[VehicleConfiguration]:
    """Load and return a fresh validated exact-configuration snapshot."""

    return _load_vehicle_configurations_snapshot()


def get_brands() -> list[str]:
    """Return sorted list of unique brands in the library."""
    return sorted({entry["brand"] for entry in _CAR_LIBRARY})


def get_types_for_brand(brand: str) -> list[str]:
    """Return sorted body types available for *brand*."""
    return sorted({entry["type"] for entry in _CAR_LIBRARY if entry["brand"] == brand})


def get_models_for_brand_type(brand: str, car_type: str) -> list[CarLibraryEntry]:
    """Return all library entries matching *brand* and *car_type*.

    Returns deep copies so callers cannot corrupt the cached library.
    """
    return [
        _deep_copy_entry(entry)
        for entry in _CAR_LIBRARY
        if entry["brand"] == brand and entry["type"] == car_type
    ]


def get_variants_for_model(brand: str, car_type: str, model: str) -> list[CarLibraryVariant]:
    """Return the variants list for a specific model, or [] if none.

    Returns deep copies so callers cannot corrupt the cached library.
    """
    for entry in _CAR_LIBRARY:
        if _entry_matches_identity(entry, brand=brand, car_type=car_type, model=model):
            return _deep_copy_variants(entry["variants"])
    return []


def get_exact_configurations_for_variant(
    brand: str,
    car_type: str,
    model: str,
    variant_name: str,
) -> tuple[VehicleConfiguration, ...]:
    """Return exact configuration rows for one selected legacy variant."""

    return tuple(
        config
        for config in _VEHICLE_CONFIGURATIONS
        if config.brand == brand
        and config.car_type == car_type
        and config.model_name == model
        and config.variant_name == variant_name
    )


def resolve_variant(
    base_entry: CarLibraryEntry,
    variant_name: str | None,
) -> CarLibraryEntry:
    """Merge a variant's overrides onto a base model entry.

    Returns a new dict with the effective gearboxes, tire_options, and
    default tire specs.  Unknown *variant_name* or ``None`` returns a
    deep copy of the base entry so callers cannot corrupt the cached
    library data.
    """
    result = _deep_copy_entry(base_entry)
    if not variant_name:
        return result
    for variant in base_entry["variants"]:
        if variant["name"] == variant_name:
            if variant.get("gearboxes"):
                result["gearboxes"] = copy.deepcopy(variant["gearboxes"])
            if variant.get("tire_options"):
                result["tire_options"] = copy.deepcopy(variant["tire_options"])
            if "tire_width_mm" in variant:
                result["tire_width_mm"] = variant["tire_width_mm"]
            if "tire_aspect_pct" in variant:
                result["tire_aspect_pct"] = variant["tire_aspect_pct"]
            if "rim_in" in variant:
                result["rim_in"] = variant["rim_in"]
            break
    return result


def resolve_vehicle_configurations(
    base_entry: CarLibraryEntry,
    variant_name: str | None,
) -> tuple[VehicleConfiguration, ...]:
    """Resolve one selected variant to explicit configuration rows.

    Exact configuration rows win when present. Otherwise the legacy model/variant
    data is projected into one compatibility row per available gearbox so broad
    inheritance does not stay implicit.
    """

    if not variant_name:
        return ()
    exact_rows = get_exact_configurations_for_variant(
        base_entry["brand"],
        base_entry["type"],
        base_entry["model"],
        variant_name,
    )
    if exact_rows:
        return exact_rows
    return _project_legacy_variant_rows(base_entry, variant_name)
