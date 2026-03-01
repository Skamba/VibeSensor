"""Static library of BMW and Audi cars with realistic drivetrain data.

Data is loaded from ``apps/server/data/car_library.json`` which is the
canonical source.  This module caches the parsed list at import time and
exposes lightweight query helpers used by the API layer.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "car_library.json"


@lru_cache(maxsize=1)
def _load_library() -> list[dict]:
    try:
        with open(_DATA_FILE) as fh:
            data: list[dict] = json.load(fh)
        return data
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        import logging

        logging.getLogger(__name__).warning(
            "Could not load car library from %s: %s", _DATA_FILE, exc
        )
        return []


# Module-level alias keeps existing ``from vibesensor.car_library import CAR_LIBRARY`` working.
CAR_LIBRARY: list[dict] = _load_library()


def get_brands() -> list[str]:
    """Return sorted list of unique brands in the library."""
    return sorted({e["brand"] for e in CAR_LIBRARY})


def get_types_for_brand(brand: str) -> list[str]:
    """Return sorted body types available for *brand*."""
    return sorted({e["type"] for e in CAR_LIBRARY if e["brand"] == brand})


def get_models_for_brand_type(brand: str, car_type: str) -> list[dict]:
    """Return all library entries matching *brand* and *car_type*."""
    return [e for e in CAR_LIBRARY if e["brand"] == brand and e["type"] == car_type]


def get_variants_for_model(brand: str, car_type: str, model: str) -> list[dict]:
    """Return the variants list for a specific model, or [] if none."""
    for e in CAR_LIBRARY:
        if e["brand"] == brand and e["type"] == car_type and e["model"] == model:
            return list(e.get("variants") or [])
    return []


def resolve_variant(
    base_entry: dict,
    variant_name: str | None,
) -> dict:
    """Merge a variant's overrides onto a base model entry.

    Returns a new dict with the effective gearboxes, tire_options, and
    default tire specs.  Unknown *variant_name* or ``None`` returns a copy
    of the base entry.
    """
    result = dict(base_entry)
    if not variant_name:
        return result
    for v in base_entry.get("variants") or []:
        if v.get("name") == variant_name:
            if v.get("gearboxes"):
                result["gearboxes"] = v["gearboxes"]
            if v.get("tire_options"):
                result["tire_options"] = v["tire_options"]
            for k in ("tire_width_mm", "tire_aspect_pct", "rim_in"):
                if v.get(k) is not None:
                    result[k] = v[k]
            break
    return result
