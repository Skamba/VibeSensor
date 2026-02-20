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
    with open(_DATA_FILE) as fh:
        data: list[dict] = json.load(fh)
    return data


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


# Pre-built lookup for O(1) find_model()
_MODEL_INDEX: dict[tuple[str, str, str], dict] = {
    (e["brand"], e["type"], e["model"]): e for e in CAR_LIBRARY
}


def find_model(brand: str, car_type: str, model: str) -> dict | None:
    """Look up a single model entry by brand, type, and model name."""
    return _MODEL_INDEX.get((brand, car_type, model))
