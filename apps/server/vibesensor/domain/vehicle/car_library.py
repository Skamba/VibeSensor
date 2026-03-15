"""Static library of BMW and Audi cars with realistic drivetrain data.

Data is loaded from ``apps/server/data/car_library.json`` which is the
canonical source.  This module caches the parsed list at import time and
exposes lightweight query helpers used by the API layer.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)

__all__ = [
    "CAR_LIBRARY",
    "get_brands",
    "get_models_for_brand_type",
    "get_types_for_brand",
    "get_variants_for_model",
    "resolve_variant",
]

_DATA_FILE = Path(__file__).resolve().parents[3] / "data" / "car_library.json"
_TIRE_OVERRIDE_KEYS = ("tire_width_mm", "tire_aspect_pct", "rim_in")


def _entry_matches_identity(entry: dict, *, brand: str, car_type: str, model: str) -> bool:
    return (
        entry.get("brand") == brand
        and entry.get("type") == car_type
        and entry.get("model") == model
    )


def _load_library() -> list[dict]:
    """Load and return the car library from the canonical JSON file.

    Unlike an ``@lru_cache`` approach, this retries on every call so a
    transient I/O or permission error at first import does not permanently
    disable the library for the lifetime of the process.
    """
    try:
        with _DATA_FILE.open(encoding="utf-8") as fh:
            data: list[dict] = json.load(fh)
        return data
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError) as exc:
        LOGGER.warning("Could not load car library from %s: %s", _DATA_FILE, exc)
        return []


# Eagerly loaded; on transient failures the module-level list stays empty
# but callers can call ``_load_library()`` again to retry.


# Module-level alias keeps
# ``from vibesensor.domain.vehicle.car_library import CAR_LIBRARY`` working.
CAR_LIBRARY: list[dict] = _load_library()


def get_brands() -> list[str]:
    """Return sorted list of unique brands in the library."""
    return sorted({b for e in CAR_LIBRARY if (b := e.get("brand"))})


def get_types_for_brand(brand: str) -> list[str]:
    """Return sorted body types available for *brand*."""
    return sorted({t for e in CAR_LIBRARY if e.get("brand") == brand and (t := e.get("type"))})


def get_models_for_brand_type(brand: str, car_type: str) -> list[dict]:
    """Return all library entries matching *brand* and *car_type*.

    Returns deep copies so callers cannot corrupt the cached library.
    """
    return [
        copy.deepcopy(e)
        for e in CAR_LIBRARY
        if e.get("brand") == brand and e.get("type") == car_type
    ]


def get_variants_for_model(brand: str, car_type: str, model: str) -> list[dict]:
    """Return the variants list for a specific model, or [] if none.

    Returns deep copies so callers cannot corrupt the cached library.
    """
    for e in CAR_LIBRARY:
        if _entry_matches_identity(e, brand=brand, car_type=car_type, model=model):
            return copy.deepcopy(e.get("variants") or [])
    return []


def resolve_variant(
    base_entry: dict,
    variant_name: str | None,
) -> dict:
    """Merge a variant's overrides onto a base model entry.

    Returns a new dict with the effective gearboxes, tire_options, and
    default tire specs.  Unknown *variant_name* or ``None`` returns a
    deep copy of the base entry so callers cannot corrupt the cached
    library data.
    """
    result = copy.deepcopy(base_entry)
    if not variant_name:
        return result
    for v in base_entry.get("variants") or []:
        if v.get("name") == variant_name:
            if v.get("gearboxes"):
                result["gearboxes"] = v["gearboxes"]
            if v.get("tire_options"):
                result["tire_options"] = v["tire_options"]
            for k in _TIRE_OVERRIDE_KEYS:
                if v.get(k) is not None:
                    result[k] = v[k]
            break
    return result
