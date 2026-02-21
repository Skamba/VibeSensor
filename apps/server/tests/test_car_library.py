from __future__ import annotations

from vibesensor.car_library import (
    CAR_LIBRARY,
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
            assert "top_gear_ratio" in gb
            assert gb["final_drive_ratio"] > 0
            assert gb["top_gear_ratio"] > 0
        assert "tire_options" in entry, f"{entry['model']} missing tire_options"
        assert isinstance(entry["tire_options"], list)
        assert len(entry["tire_options"]) >= 2, f"{entry['model']} needs >=2 tire options"
        for opt in entry["tire_options"]:
            assert "name" in opt
            assert "tire_width_mm" in opt
            assert "tire_aspect_pct" in opt
            assert "rim_in" in opt


def test_tire_specs_reasonable() -> None:
    for entry in CAR_LIBRARY:
        assert entry["tire_width_mm"] >= 175, f"{entry['model']} tire too narrow"
        assert entry["tire_width_mm"] <= 335, f"{entry['model']} tire too wide"
        assert entry["tire_aspect_pct"] >= 20, f"{entry['model']} aspect too low"
        assert entry["tire_aspect_pct"] <= 65, f"{entry['model']} aspect too high"
        assert entry["rim_in"] >= 15, f"{entry['model']} rim too small"
        assert entry["rim_in"] <= 22, f"{entry['model']} rim too large"


def test_tire_options_specs_within_bounds() -> None:
    for entry in CAR_LIBRARY:
        for opt in entry["tire_options"]:
            label = f"{entry['model']} / {opt['name']}"
            assert opt["tire_width_mm"] <= 335, f"{label} width too large"
            assert opt["tire_aspect_pct"] >= 25, f"{label} aspect too low"
            assert opt["rim_in"] <= 22, f"{label} rim too large"
            assert opt["rim_in"] >= 15, f"{label} rim too small"


def test_tire_options_standard_matches_base() -> None:
    """The first tire option (Standard) should match the car's base tire specs."""
    for entry in CAR_LIBRARY:
        std = entry["tire_options"][0]
        assert std["tire_width_mm"] == entry["tire_width_mm"], entry["model"]
        assert std["tire_aspect_pct"] == entry["tire_aspect_pct"], entry["model"]
        assert std["rim_in"] == entry["rim_in"], entry["model"]
        assert "Standard" in std["name"], entry["model"]


def _matches_prefix(model: str, prefixes: list[str]) -> bool:
    return any(model.startswith(p + " ") or model.startswith(p + "(") for p in prefixes)


def test_tire_options_count_by_category() -> None:
    """Performance/EV models get 2 options, regular models get 3."""
    perf = ["M3", "M4", "M5", "RS 3", "RS 4", "RS 5", "RS 6", "RS 7", "RS Q8", "R8"]
    ev = ["iX", "i4", "e-tron GT", "Q4 e-tron"]

    for entry in CAR_LIBRARY:
        model = entry["model"]
        if _matches_prefix(model, perf) or _matches_prefix(model, ev):
            assert len(entry["tire_options"]) == 2, f"{model} should have 2 options"
        else:
            assert len(entry["tire_options"]) == 3, f"{model} should have 3 options"


def test_tire_option_name_format() -> None:
    """Each option name should end with a rim size in inches."""
    import re

    for entry in CAR_LIBRARY:
        for opt in entry["tire_options"]:
            assert re.search(r'\d+"$', opt["name"]), f"Bad name format: {opt['name']}"
