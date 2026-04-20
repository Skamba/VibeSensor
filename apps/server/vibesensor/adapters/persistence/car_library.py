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

from vibesensor.shared._data_files import resolve_static_data_file

LOGGER = logging.getLogger(__name__)

__all__ = [
    "CarLibraryEntry",
    "get_brands",
    "get_models_for_brand_type",
    "get_types_for_brand",
    "load_car_library",
    "get_variants_for_model",
    "resolve_variant",
]

_DATA_FILE = resolve_static_data_file("car_library.json")
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


for _typed_dict in (
    CarLibraryGearbox,
    CarLibraryTireOption,
    CarLibraryVariant,
    CarLibraryEntry,
):
    cast(Any, _typed_dict).__pydantic_config__ = _STRICT_TYPEDDICT_CONFIG

_CAR_LIBRARY_ADAPTER = TypeAdapter(list[CarLibraryEntry])


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


# Query helpers reuse one import-time snapshot; explicit loaders can call
# ``load_car_library()`` when they need a fresh validated read from disk.
_CAR_LIBRARY: list[CarLibraryEntry] = _load_library()


def load_car_library() -> list[CarLibraryEntry]:
    """Load and return a fresh validated car-library snapshot."""

    return _load_library()


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
