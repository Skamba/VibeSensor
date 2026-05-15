"""Tests for car variant support in the car library and domain models."""

from __future__ import annotations

import pytest

from vibesensor.adapters.persistence.car_library import (
    get_variants_for_model,
    load_car_library,
    resolve_variant,
)
from vibesensor.shared.types.car_config import car_from_persistence_dict, car_to_persistence_dict


def _library_entries() -> list[dict[str, object]]:
    return load_car_library()


# ---------------------------------------------------------------------------
# car_library.py helper tests
# ---------------------------------------------------------------------------


def test_get_variants_for_model_unknown_returns_empty() -> None:
    """Unknown brand/type/model returns empty list."""
    assert get_variants_for_model("Tesla", "Sedan", "Model S") == []


def test_resolve_variant_no_variant() -> None:
    """resolve_variant with None returns base entry."""
    base = _library_entries()[0]
    resolved = resolve_variant(base, None)
    assert resolved["gearboxes"] == base["gearboxes"]
    assert resolved["tire_options"] == base["tire_options"]


def test_resolve_variant_inherits_base_gearboxes() -> None:
    """Variant without gearbox override inherits base gearboxes."""
    entry = next(entry for entry in _library_entries() if not entry["variants"][0].get("gearboxes"))
    first_variant = entry["variants"][0]

    resolved = resolve_variant(entry, first_variant["name"])

    assert resolved["gearboxes"] == entry["gearboxes"]


def test_resolve_variant_unknown_name_returns_base() -> None:
    """resolve_variant with unknown name returns base entry unchanged."""
    base = _library_entries()[0]
    resolved = resolve_variant(base, "nonexistent_variant")
    assert resolved["gearboxes"] == base["gearboxes"]


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


def test_car_library_variant_entry_requires_drivetrain() -> None:
    """CarLibraryVariantEntry requires drivetrain field."""
    from pydantic import ValidationError

    from vibesensor.adapters.http.models import CarLibraryVariantEntry

    # Valid
    v = CarLibraryVariantEntry(name="320i", drivetrain="RWD")
    assert v.name == "320i"
    assert v.drivetrain == "RWD"

    # Missing drivetrain
    with pytest.raises(ValidationError, match=r"drivetrain"):
        CarLibraryVariantEntry(name="320i")


# ---------------------------------------------------------------------------
# Car persistence (boundary decoder) tests
# ---------------------------------------------------------------------------


def test_car_from_persistence_dict_without_variant() -> None:
    """Boundary car decoder without variant sets variant to None."""
    car = car_from_persistence_dict({"name": "Old Car", "type": "sedan"})
    assert car.variant is None
    d = car_to_persistence_dict(car)
    assert "variant" not in d


def test_car_from_persistence_dict_with_variant() -> None:
    """Boundary car decoder preserves the optional variant."""
    car = car_from_persistence_dict({"name": "BMW 320i", "type": "Sedan", "variant": "320i"})
    assert car.variant == "320i"
    d = car_to_persistence_dict(car)
    assert d["variant"] == "320i"


def test_car_from_persistence_dict_empty_variant() -> None:
    """Empty string variant is treated as None."""
    car = car_from_persistence_dict({"name": "Car", "type": "sedan", "variant": ""})
    assert car.variant is None


def test_car_from_persistence_dict_variant_truncated() -> None:
    """Very long variant names are truncated to 64 chars."""
    long_name = "x" * 100
    car = car_from_persistence_dict({"name": "Car", "type": "sedan", "variant": long_name})
    assert len(car.variant) == 64
