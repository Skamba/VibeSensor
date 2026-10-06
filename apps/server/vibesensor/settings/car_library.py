"""Grouped car-picker projections derived from canonical vehicle configurations."""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from itertools import pairwise
from typing import Literal, NotRequired, TypedDict

from vibesensor.domain.car import Car
from vibesensor.domain.engine_profile import EngineLayout, EngineProfile
from vibesensor.domain.tire_spec import AxleTireSetup
from vibesensor.domain.vehicle_configuration import VehicleConfiguration
from vibesensor.settings.car_config import needs_library_fields
from vibesensor.settings.vehicle_configurations import load_vehicle_configurations

__all__ = [
    "CarLibraryEntry",
    "get_brands",
    "get_models_for_brand_type",
    "get_types_for_brand",
    "load_car_library",
    "with_library_fields",
]


class CarLibraryGearbox(TypedDict):
    name: str
    final_drive_ratio: float | None
    """``None`` when the library has no driven final drive for this row (unknown)."""
    top_gear_ratio: float | None
    """``None`` when the library has no top gear for this row (unknown)."""
    fuel_type: Literal["ICE", "PHEV", "EV"]
    final_drive_axle: NotRequired[Literal["front", "rear"] | None]
    """The axle ``final_drive_ratio`` belongs to; ``None`` when the row doesn't say."""
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


class CarLibraryEngineProfile(TypedDict):
    layout: EngineLayout
    cylinders: int


class CarLibraryVariant(TypedDict):
    name: str
    drivetrain: Literal["FWD", "RWD", "AWD"]
    engine: NotRequired[str]
    engine_profile: NotRequired[CarLibraryEngineProfile]
    """Read from the rows' engine text when they agree; absent for an EV."""
    gearboxes: NotRequired[list[CarLibraryGearbox]]
    tire_options: NotRequired[list[CarLibraryTireOption]]
    tire_width_mm: NotRequired[float]
    tire_aspect_pct: NotRequired[float]
    rim_in: NotRequired[float]
    production_start_year: NotRequired[int]
    production_end_year: NotRequired[int]


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
        "final_drive_axle": config.driven_final_drive_axle,
        "source_status": config.source_status,
        "transmission_confidence": config.order_reference_confidence("transmission_name"),
        "requires_manual_confirmation": config.requires_manual_drivetrain_confirmation,
    }
    if final_drive_ratio is not None:
        row["final_drive_ratio_confidence"] = config.order_reference_confidence("final_drive_ratio")
    if config.top_gear_ratio is not None:
        row["top_gear_ratio_confidence"] = config.order_reference_confidence("current_gear_ratio")
    if config.gear_ratios is not None:
        row["gear_ratios"] = list(config.gear_ratios)
        row["gear_ratios_confidence"] = (
            config.gear_ratios_metadata.confidence
            if config.gear_ratios_metadata is not None
            else config.order_reference_confidence("current_gear_ratio")
        )
    return row


def _sort_configs(configs: list[VehicleConfiguration]) -> list[VehicleConfiguration]:
    return sorted(
        configs,
        key=lambda config: (
            config.variant_name,
            config.transmission_name,
            config.id or "",
        ),
    )


def _year_span(configs: list[VehicleConfiguration]) -> tuple[int | None, int | None]:
    starts = [c.production_start_year for c in configs if c.production_start_year is not None]
    ends = [c.production_end_year for c in configs if c.production_end_year is not None]
    return min(starts, default=None), max(ends, default=None)


def _year_label(start: int | None, end: int | None) -> str:
    """``"2016"`` or ``"2016\u20132022"`` (en dash); ``""`` when no years are known."""

    if start is None or end is None:
        return str(start or end or "")
    return str(start) if start == end else f"{start}\u2013{end}"


def _library_variant_from_configs(
    name: str,
    configs: list[VehicleConfiguration],
    years: tuple[int | None, int | None],
) -> CarLibraryVariant:
    first = configs[0]
    variant: CarLibraryVariant = {
        "name": name,
        "drivetrain": first.drivetrain,
        "engine": first.engine_name or first.engine_code or "",
        "gearboxes": [_gearbox_row_from_configuration(config) for config in configs],
        "tire_options": _union_tire_options(configs),
        "tire_width_mm": first.default_tire.width_mm,
        "tire_aspect_pct": first.default_tire.aspect_pct,
        "rim_in": first.default_tire.rim_in,
    }
    profile = _agreed_engine_profile(configs)
    if profile is not None:
        variant["engine_profile"] = {"layout": profile.layout, "cylinders": profile.cylinders}
    start, end = years
    if start is not None:
        variant["production_start_year"] = start
    if end is not None:
        variant["production_end_year"] = end
    return variant


def _agreed_engine_profile(configs: Iterable[VehicleConfiguration]) -> EngineProfile | None:
    """The engine profile every row names; ``None`` when they differ or name none."""
    profiles = {config.engine_profile for config in configs}
    return profiles.pop() if len(profiles) == 1 else None


_Period = tuple[int, int, list[VehicleConfiguration]]


def _model_year_periods(configs: list[VehicleConfiguration]) -> list[_Period]:
    """Split one variant name's rows into model-year periods.

    A period lists every row on sale throughout it, so a row whose years
    cover several periods (a manual gearbox kept while the automatic
    changed) appears in each. Adjacent years with the same rows merge;
    years without rows are dropped.
    """

    bounds = sorted(
        {c.production_start_year for c in configs if c.production_start_year is not None}
        | {c.production_end_year + 1 for c in configs if c.production_end_year is not None}
    )
    periods: list[_Period] = []
    for first, after in pairwise(bounds):
        rows = [
            c
            for c in configs
            if (c.production_start_year or first) <= first
            and after - 1 <= (c.production_end_year or after - 1)
        ]
        if not rows:
            continue
        if periods and periods[-1][1] == first - 1 and periods[-1][2] == rows:
            periods[-1] = (periods[-1][0], after - 1, rows)
        else:
            periods.append((first, after - 1, rows))
    return periods


_PickerVariant = tuple[CarLibraryVariant, tuple[VehicleConfiguration, ...]]


def _variants_for_generation(configs: list[VehicleConfiguration]) -> list[_PickerVariant]:
    """One picker variant per variant name, split by model year only when needed.

    A variant name stays one picker entry while its gearbox names are
    unique, so the gearbox choice picks the exact row. When a gearbox
    repeats (an xDrive25d sold in 2015-2020 and again in 2021-2022
    with another final drive), the model year decides the row: the variant is offered
    once per model-year period and named with its years
    ("xDrive25d (2021\u20132022)").
    """

    by_name: dict[str, list[VehicleConfiguration]] = {}
    for config in _sort_configs(configs):
        by_name.setdefault(config.variant_name, []).append(config)
    variants: list[_PickerVariant] = []
    for name, rows in by_name.items():
        gearbox_names = [row.transmission_name for row in rows]
        if len(set(gearbox_names)) == len(gearbox_names):
            variant = _library_variant_from_configs(name, rows, _year_span(rows))
            variants.append((variant, tuple(rows)))
            continue
        for first, last, period in _model_year_periods(rows):
            label = f"{name} ({_year_label(first, last)})"
            variant = _library_variant_from_configs(label, period, (first, last))
            variants.append((variant, tuple(period)))
    return variants


# "X1 (F48, 2015-2022)" -> "X1": the label's generation and years are rebuilt
# from the whole generation's rows.
_LABEL_SUFFIX = re.compile(r" \([^()]*\)$")

_GenerationKey = tuple[str, str, str, str | None]
_VariantKey = tuple[str, str, str, str]


def _generation_key(config: VehicleConfiguration) -> _GenerationKey:
    base = _LABEL_SUFFIX.sub("", config.model_name) if config.model_code else config.model_name
    return (config.brand, config.car_type, base, config.model_code)


def _generation_label(base: str, code: str | None, configs: list[VehicleConfiguration]) -> str:
    """``"X1 (F48, 2015\u20132022)"``: model, generation code and its years."""

    if code is None:
        return base
    years = _year_label(*_year_span(configs))
    return f"{base} ({code}, {years})" if years else f"{base} ({code})"


def _build_grouped_library(
    configs: list[VehicleConfiguration],
) -> tuple[list[CarLibraryEntry], dict[_VariantKey, tuple[VehicleConfiguration, ...]]]:
    """Group exact rows into picker models (one per generation) and variants.

    Returns the picker entries, ordered by brand, type, model and then
    generation start year, plus the exact rows behind every picker variant
    keyed by ``(brand, type, model, variant)``.
    """

    generations: dict[_GenerationKey, list[VehicleConfiguration]] = {}
    for config in configs:
        generations.setdefault(_generation_key(config), []).append(config)

    ordered: list[tuple[tuple[object, ...], CarLibraryEntry]] = []
    rows_by_variant: dict[_VariantKey, tuple[VehicleConfiguration, ...]] = {}
    for (brand, car_type, base, code), grouped_configs in generations.items():
        model = _generation_label(base, code, grouped_configs)
        variants = _variants_for_generation(grouped_configs)
        for variant, rows in variants:
            rows_by_variant[(brand, car_type, model, variant["name"])] = rows
        representative = _sort_configs(grouped_configs)[0]
        entry: CarLibraryEntry = {
            "brand": brand,
            "type": car_type,
            "model": model,
            "gearboxes": [_gearbox_row_from_configuration(representative)],
            "tire_options": _tire_options_for_config(representative),
            "tire_width_mm": representative.default_tire.width_mm,
            "tire_aspect_pct": representative.default_tire.aspect_pct,
            "rim_in": representative.default_tire.rim_in,
            "variants": [variant for variant, _ in variants],
        }
        start = _year_span(grouped_configs)[0]
        ordered.append(((brand, car_type, base, start or 0, code or ""), entry))
    ordered.sort(key=lambda item: item[0])
    return [entry for _, entry in ordered], rows_by_variant


_CAR_LIBRARY, _ROWS_BY_VARIANT = _build_grouped_library(load_vehicle_configurations())


def load_car_library() -> list[CarLibraryEntry]:
    """Load and return a fresh grouped picker snapshot from canonical configs."""

    return _build_grouped_library(load_vehicle_configurations())[0]


def get_brands() -> list[str]:
    """Return sorted list of unique brands in the grouped picker."""

    return sorted({entry["brand"] for entry in _CAR_LIBRARY})


def get_types_for_brand(brand: str) -> list[str]:
    """Return sorted body types available for *brand*."""

    return sorted({entry["type"] for entry in _CAR_LIBRARY if entry["brand"] == brand})


def get_models_for_brand_type(brand: str, car_type: str) -> list[CarLibraryEntry]:
    """Return all grouped picker entries matching *brand* and *car_type*."""

    return [
        copy.deepcopy(entry)
        for entry in _CAR_LIBRARY
        if entry["brand"] == brand and entry["type"] == car_type
    ]


_VARIANT_YEARS = re.compile(r" \(\d{4}(?:\u2013\d{4})?\)$")


def _names_generation(name: str, row: VehicleConfiguration) -> bool:
    """Whether a saved car name starts with the row's brand, model and generation.

    ``"BMW 1 Series (F40, 2019-2024) 118i"`` names the F40 whatever its label's
    years or dash: the picker's labels changed (#4153), the generation code did not.
    """

    brand, _, base, code = _generation_key(row)
    if code is None:
        return name.startswith(f"{brand} {base} ")
    prefix = f"{brand} {base} ({code}"
    return name.startswith(prefix) and name[len(prefix) : len(prefix) + 1] in {",", ")"}


def _library_rows_for_saved_car(car: Car) -> list[VehicleConfiguration]:
    """The library rows a saved car was picked from, best match first.

    The wizard saves a library car as ``"{brand} {model} {variant}"`` with the
    body type and variant name. A car saved before its variant was split by
    model year names the variant without the years; one saved before the
    picker's model labels changed names its generation with other years. A
    name that names a library generation only matches that generation's rows,
    so a variant name another generation shares (118i: F20 and F40) never lends
    its layout. Only a renamed car falls back to every row of its body type and
    variant.
    """

    if not car.variant:
        return []
    candidates = [
        (key, rows)
        for key, rows in _ROWS_BY_VARIANT.items()
        if key[1] == car.car_type and car.variant in {key[3], _VARIANT_YEARS.sub("", key[3])}
    ]
    named = [
        row
        for (brand, _, model, variant), rows in candidates
        if car.name == f"{brand} {model} {variant}"
        for row in rows
    ]
    if named:
        return named
    if any(_names_generation(car.name, row) for rows in _ROWS_BY_VARIANT.values() for row in rows):
        return [row for _, rows in candidates for row in rows if _names_generation(car.name, row)]
    return [row for _, rows in candidates for row in rows]


def with_library_fields(car: Car) -> Car:
    """Fill a saved car's missing drive layout, powertrain and engine from its library rows.

    Cars saved before the layout, the powertrain or the engine profile existed
    get them when their rows agree on one; an AWD car also gets the axle its
    gearbox's final drive is on (which axle the engine drives), also when the
    owner has corrected the ratio. A value the car already has is kept, and a
    car the library doesn't know stays without one.
    """

    if not needs_library_fields(car):
        return car
    rows = _library_rows_for_saved_car(car)
    drive_layout, final_drive_axle = car.drive_layout, car.final_drive_axle
    layouts = {row.drivetrain for row in rows}
    if drive_layout is None and len(layouts) == 1:
        status = car.order_reference_status
        transmission = status.transmission_name if status is not None else None
        same_gearbox = [row for row in rows if row.transmission_name == transmission] or rows
        axles = {row.driven_final_drive_axle for row in same_gearbox}
        drive_layout = layouts.pop()
        final_drive_axle = axles.pop() if len(axles) == 1 else None
    fuel_types = {row.fuel_type for row in rows}
    fuel_type = car.fuel_type
    if fuel_type is None and len(fuel_types) == 1:
        fuel_type = fuel_types.pop()
    engine_profile = car.engine_profile or (_agreed_engine_profile(rows) if rows else None)
    if (drive_layout, fuel_type, engine_profile) == (
        car.drive_layout,
        car.fuel_type,
        car.engine_profile,
    ):
        return car
    return Car(
        id=car.id,
        name=car.name,
        car_type=car.car_type,
        aspects=car.aspects,
        variant=car.variant,
        order_reference_status=car.order_reference_status,
        fuel_type=fuel_type,
        drive_layout=drive_layout,
        final_drive_axle=final_drive_axle,
        engine_profile=engine_profile,
    )
