from __future__ import annotations

from vibesensor.car_library import (
    CAR_LIBRARY,
    find_model,
    get_brands,
    get_models_for_brand_type,
    get_types_for_brand,
)


def test_car_library_has_entries() -> None:
    assert len(CAR_LIBRARY) > 50


def test_get_brands_returns_bmw_and_audi() -> None:
    brands = get_brands()
    assert "BMW" in brands
    assert "Audi" in brands


def test_get_types_for_brand_bmw() -> None:
    types = get_types_for_brand("BMW")
    assert "Sedan" in types
    assert "SUV" in types


def test_get_types_for_brand_audi() -> None:
    types = get_types_for_brand("Audi")
    assert "Sedan" in types
    assert "SUV" in types


def test_get_models_for_brand_type() -> None:
    models = get_models_for_brand_type("BMW", "Sedan")
    assert len(models) > 0
    for m in models:
        assert m["brand"] == "BMW"
        assert m["type"] == "Sedan"


def test_find_model_existing() -> None:
    models = get_models_for_brand_type("BMW", "Sedan")
    first = models[0]
    found = find_model("BMW", "Sedan", first["model"])
    assert found is not None
    assert found["model"] == first["model"]


def test_find_model_missing() -> None:
    assert find_model("BMW", "Sedan", "Nonexistent Model XYZ") is None


def test_every_entry_has_required_fields() -> None:
    for entry in CAR_LIBRARY:
        assert "brand" in entry
        assert "type" in entry
        assert "model" in entry
        assert "tire_width_mm" in entry
        assert "tire_aspect_pct" in entry
        assert "rim_in" in entry
        assert "gearboxes" in entry
        assert isinstance(entry["gearboxes"], list)
        assert len(entry["gearboxes"]) > 0
        for gb in entry["gearboxes"]:
            assert "name" in gb
            assert "final_drive_ratio" in gb
            assert "default_gear_ratio" in gb
            assert gb["final_drive_ratio"] > 0
            assert gb["default_gear_ratio"] > 0


def test_tire_specs_reasonable() -> None:
    for entry in CAR_LIBRARY:
        assert entry["tire_width_mm"] >= 175, f"{entry['model']} tire too narrow"
        assert entry["tire_width_mm"] <= 335, f"{entry['model']} tire too wide"
        assert entry["tire_aspect_pct"] >= 20, f"{entry['model']} aspect too low"
        assert entry["tire_aspect_pct"] <= 65, f"{entry['model']} aspect too high"
        assert entry["rim_in"] >= 15, f"{entry['model']} rim too small"
        assert entry["rim_in"] <= 22, f"{entry['model']} rim too large"
