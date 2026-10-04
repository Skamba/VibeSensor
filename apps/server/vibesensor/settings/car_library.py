"""Grouped car-picker projections derived from canonical vehicle configurations."""

from __future__ import annotations

import copy
from typing import Literal, NotRequired, TypedDict, cast

from vibesensor.domain.tire_spec import AxleTireSetup
from vibesensor.domain.vehicle_configuration import VehicleConfiguration
from vibesensor.settings.vehicle_configurations import load_vehicle_configurations

__all__ = [
    "CarLibraryEntry",
    "get_brands",
    "get_models_for_brand_type",
    "get_types_for_brand",
    "load_car_library",
    "get_variants_for_model",
    "get_exact_configurations_for_variant",
    "resolve_variant",
    "resolve_vehicle_configurations",
]


class CarLibraryGearbox(TypedDict):
    name: str
    final_drive_ratio: float | None
    """``None`` when the library has no driven final drive for this row (unknown)."""
    top_gear_ratio: float
    fuel_type: Literal["ICE", "PHEV", "EV"]
    gear_ratios: NotRequired[list[float]]
    source_status: NotRequired[Literal["exact_row"]]
    final_drive_ratio_confidence: NotRequired[str]
    top_gear_ratio_confidence: NotRequired[str]
    gear_ratios_confidence: NotRequired[str]
    transmission_confidence: NotRequired[str]
    requires_manual_confirmation: NotRequired[bool]


class CarLibraryTireDimensions(TypedDict):
    width_mm: float
    aspect_pct: float
    rim_in: float


class CarLibraryTireOption(TypedDict):
    name: str
    tire_width_mm: NotRequired[float]
    tire_aspect_pct: NotRequired[float]
    rim_in: NotRequired[float]
    front: NotRequired[CarLibraryTireDimensions]
    rear: NotRequired[CarLibraryTireDimensions]
    default_axle_for_speed: NotRequired[Literal["front", "rear", "average"]]
    source_confidence: NotRequired[str]


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


class ResolvedCarLibraryEntry(CarLibraryEntry, total=False):
    drivetrain: Literal["FWD", "RWD", "AWD"]
    engine: str


def _deep_copy_entry(entry: CarLibraryEntry) -> CarLibraryEntry:
    return copy.deepcopy(entry)


def _deep_copy_variants(variants: list[CarLibraryVariant]) -> list[CarLibraryVariant]:
    return copy.deepcopy(variants)


def _tire_payload_from_setup(name: str, setup: AxleTireSetup) -> CarLibraryTireOption:
    payload: CarLibraryTireOption = {
        "name": name,
        "tire_width_mm": setup.boundary_tire_spec.width_mm,
        "tire_aspect_pct": setup.boundary_tire_spec.aspect_pct,
        "rim_in": setup.boundary_tire_spec.rim_in,
        "front": {
            "width_mm": setup.front.width_mm,
            "aspect_pct": setup.front.aspect_pct,
            "rim_in": setup.front.rim_in,
        },
        "default_axle_for_speed": setup.default_axle_for_speed,
    }
    if setup.is_staggered:
        payload["rear"] = {
            "width_mm": setup.rear.width_mm,
            "aspect_pct": setup.rear.aspect_pct,
            "rim_in": setup.rear.rim_in,
        }
    if setup.source_confidence is not None:
        payload["source_confidence"] = setup.source_confidence
    return payload


def _default_tire_option(config: VehicleConfiguration) -> CarLibraryTireOption:
    setup = AxleTireSetup.square(
        config.default_tire,
        source_confidence=(
            config.tire_metadata.confidence if config.tire_metadata is not None else None
        ),
    )
    return _tire_payload_from_setup("Default", setup)


def _tire_options_for_config(config: VehicleConfiguration) -> list[CarLibraryTireOption]:
    if config.tire_options:
        return [
            _tire_payload_from_setup(option.name, option.tire_setup)
            for option in config.tire_options
        ]
    return [_default_tire_option(config)]


# Best first; ``None`` (no metadata) ranks below every named confidence.
_TIRE_CONFIDENCE_RANK: dict[str | None, int] = {
    "user_confirmed": 0,
    "official_exact": 1,
    "official_derived": 2,
    "reputable_secondary_crosschecked": 3,
    "family_default": 4,
    "unverified": 5,
    None: 6,
}


def _tire_size_key(option: CarLibraryTireOption) -> tuple[object, ...]:
    front = option.get("front")
    rear = option.get("rear")
    return (
        tuple(front.values()) if front else None,
        tuple(rear.values()) if rear else None,
    )


def _union_tire_options(configs: list[VehicleConfiguration]) -> list[CarLibraryTireOption]:
    """Union the tire options of a variant's rows, one option per tire size.

    Rows of one variant (for example its manual and automatic gearbox rows)
    can list different tire sizes; the picker must offer all of them. When
    several rows list the same size, the option with the best source
    confidence wins and keeps the position where that size first appeared.
    """

    by_size: dict[tuple[object, ...], CarLibraryTireOption] = {}
    for config in configs:
        for option in _tire_options_for_config(config):
            key = _tire_size_key(option)
            current = by_size.get(key)
            if current is None:
                by_size[key] = option
            elif _TIRE_CONFIDENCE_RANK.get(
                option.get("source_confidence"), 6
            ) < _TIRE_CONFIDENCE_RANK.get(current.get("source_confidence"), 6):
                by_size[key] = option
    return list(by_size.values())


def _gearbox_row_from_configuration(config: VehicleConfiguration) -> CarLibraryGearbox:
    final_drive_ratio = config.driven_final_drive_ratio
    row: CarLibraryGearbox = {
        "name": config.transmission_name,
        "final_drive_ratio": final_drive_ratio,
        "top_gear_ratio": config.top_gear_ratio,
        "fuel_type": config.fuel_type,
        "source_status": config.source_status,
        "top_gear_ratio_confidence": config.order_reference_confidence("current_gear_ratio"),
        "transmission_confidence": config.order_reference_confidence("transmission_name"),
        "requires_manual_confirmation": config.requires_manual_drivetrain_confirmation,
    }
    if final_drive_ratio is not None:
        row["final_drive_ratio_confidence"] = config.order_reference_confidence("final_drive_ratio")
    if config.gear_ratios is not None:
        row["gear_ratios"] = list(config.gear_ratios)
        row["gear_ratios_confidence"] = (
            config.gear_ratios_metadata.confidence
            if config.gear_ratios_metadata is not None
            else config.order_reference_confidence("current_gear_ratio")
        )
    return row


def _library_variant_from_configs(configs: list[VehicleConfiguration]) -> CarLibraryVariant:
    first = configs[0]
    tire_options = _union_tire_options(configs)
    gearboxes = [_gearbox_row_from_configuration(config) for config in configs]
    variant: CarLibraryVariant = {
        "name": first.variant_name,
        "drivetrain": first.drivetrain,
        "engine": first.engine_name or first.engine_code or "",
        "gearboxes": gearboxes,
        "tire_options": tire_options,
        "tire_width_mm": first.default_tire.width_mm,
        "tire_aspect_pct": first.default_tire.aspect_pct,
        "rim_in": first.default_tire.rim_in,
    }
    return variant


def _sort_configs(configs: list[VehicleConfiguration]) -> list[VehicleConfiguration]:
    return sorted(
        configs,
        key=lambda config: (
            config.variant_name,
            config.transmission_name,
            config.id or "",
        ),
    )


def _build_grouped_library(configs: list[VehicleConfiguration]) -> list[CarLibraryEntry]:
    model_groups: dict[tuple[str, str, str], list[VehicleConfiguration]] = {}
    for config in configs:
        key = (config.brand, config.car_type, config.model_name)
        model_groups.setdefault(key, []).append(config)

    entries: list[CarLibraryEntry] = []
    for (brand, car_type, model_name), grouped_configs in sorted(model_groups.items()):
        variant_groups: dict[str, list[VehicleConfiguration]] = {}
        for config in _sort_configs(grouped_configs):
            variant_groups.setdefault(config.variant_name, []).append(config)
        variants = [
            _library_variant_from_configs(configs_for_variant)
            for _, configs_for_variant in sorted(variant_groups.items())
        ]
        representative = grouped_configs[0]
        representative_tires = _tire_options_for_config(representative)
        representative_gearboxes = [
            _gearbox_row_from_configuration(config) for config in _sort_configs(grouped_configs)
        ]
        entries.append(
            {
                "brand": brand,
                "type": car_type,
                "model": model_name,
                "gearboxes": representative_gearboxes[:1] or representative_gearboxes,
                "tire_options": representative_tires,
                "tire_width_mm": representative.default_tire.width_mm,
                "tire_aspect_pct": representative.default_tire.aspect_pct,
                "rim_in": representative.default_tire.rim_in,
                "variants": variants,
            }
        )
    return entries


def _load_grouped_library_snapshot() -> list[CarLibraryEntry]:
    return _build_grouped_library(load_vehicle_configurations())


_VEHICLE_CONFIGURATIONS: list[VehicleConfiguration] = load_vehicle_configurations()
_CAR_LIBRARY: list[CarLibraryEntry] = _build_grouped_library(_VEHICLE_CONFIGURATIONS)


def load_car_library() -> list[CarLibraryEntry]:
    """Load and return a fresh grouped picker snapshot from canonical configs."""

    return _load_grouped_library_snapshot()


def get_brands() -> list[str]:
    """Return sorted list of unique brands in the grouped picker."""

    return sorted({entry["brand"] for entry in _CAR_LIBRARY})


def get_types_for_brand(brand: str) -> list[str]:
    """Return sorted body types available for *brand*."""

    return sorted({entry["type"] for entry in _CAR_LIBRARY if entry["brand"] == brand})


def get_models_for_brand_type(brand: str, car_type: str) -> list[CarLibraryEntry]:
    """Return all grouped picker entries matching *brand* and *car_type*."""

    return [
        _deep_copy_entry(entry)
        for entry in _CAR_LIBRARY
        if entry["brand"] == brand and entry["type"] == car_type
    ]


def get_variants_for_model(brand: str, car_type: str, model: str) -> list[CarLibraryVariant]:
    """Return grouped variants for a specific model, or [] if none."""

    for entry in _CAR_LIBRARY:
        if entry["brand"] == brand and entry["type"] == car_type and entry["model"] == model:
            return _deep_copy_variants(entry["variants"])
    return []


def get_exact_configurations_for_variant(
    brand: str,
    car_type: str,
    model: str,
    variant_name: str,
) -> tuple[VehicleConfiguration, ...]:
    """Return canonical configuration rows for one selected variant."""

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
) -> ResolvedCarLibraryEntry:
    """Merge a variant's overrides onto a base model entry.

    Returns a new dict with the effective engine/drivetrain metadata,
    gearboxes, tire_options, and default tire specs. Unknown
    *variant_name* or ``None`` returns a deep copy of the base entry so
    callers cannot corrupt the cached library data.
    """
    result = cast(ResolvedCarLibraryEntry, _deep_copy_entry(base_entry))
    if not variant_name:
        return result
    for variant in base_entry["variants"]:
        if variant["name"] == variant_name:
            result["drivetrain"] = variant["drivetrain"]
            if "engine" in variant:
                result["engine"] = variant["engine"]
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
    """Resolve one selected grouped variant to canonical exact rows."""

    if not variant_name:
        return ()
    return get_exact_configurations_for_variant(
        base_entry["brand"],
        base_entry["type"],
        base_entry["model"],
        variant_name,
    )
