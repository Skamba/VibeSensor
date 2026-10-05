"""Tests for car variant support in the car library and domain models."""

from __future__ import annotations

import pytest

from vibesensor.settings.car_config import car_from_persistence_dict, car_to_persistence_dict

# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


def test_car_library_variant_entry_requires_drivetrain() -> None:
    """CarLibraryVariantEntry requires drivetrain field."""
    from pydantic import ValidationError

    from vibesensor.web.models.car_library import CarLibraryVariantEntry

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
