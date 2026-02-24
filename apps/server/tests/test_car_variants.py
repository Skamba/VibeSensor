"""Tests for car variant support in the car library and domain models."""

from __future__ import annotations

import json

from vibesensor.car_library import (
    CAR_LIBRARY,
    get_models_for_brand_type,
    get_variants_for_model,
    resolve_variant,
)
from vibesensor.domain_models import CarConfig

# ---------------------------------------------------------------------------
# Car library JSON structure tests
# ---------------------------------------------------------------------------


def test_every_model_has_variants() -> None:
    """Every car library entry must have at least one variant."""
    for entry in CAR_LIBRARY:
        assert "variants" in entry, f"{entry['model']} missing variants"
        assert isinstance(entry["variants"], list), f"{entry['model']} variants not a list"
        assert len(entry["variants"]) >= 1, f"{entry['model']} has no variants"


def test_every_variant_has_required_fields() -> None:
    """Each variant must have name and drivetrain."""
    for entry in CAR_LIBRARY:
        for v in entry["variants"]:
            label = f"{entry['model']} / {v.get('name', '?')}"
            assert "name" in v, f"{label} missing name"
            assert isinstance(v["name"], str), f"{label} name not str"
            assert len(v["name"]) > 0, f"{label} empty name"
            assert "drivetrain" in v, f"{label} missing drivetrain"
            assert v["drivetrain"] in ("FWD", "RWD", "AWD"), (
                f"{label} bad drivetrain: {v['drivetrain']}"
            )


def test_variant_names_unique_within_model() -> None:
    """Variant names must be unique within each model."""
    for entry in CAR_LIBRARY:
        names = [v["name"] for v in entry["variants"]]
        assert len(names) == len(set(names)), (
            f"{entry['model']} has duplicate variant names: {names}"
        )


def test_variant_gearbox_overrides_valid() -> None:
    """Variant gearbox overrides must be valid (positive ratios)."""
    for entry in CAR_LIBRARY:
        for v in entry["variants"]:
            gbs = v.get("gearboxes")
            if not gbs:
                continue
            label = f"{entry['model']} / {v['name']}"
            assert isinstance(gbs, list), f"{label} gearboxes not list"
            assert len(gbs) > 0, f"{label} gearboxes empty"
            for gb in gbs:
                assert "name" in gb, f"{label} gearbox missing name"
                assert gb["final_drive_ratio"] > 0, f"{label} bad FD ratio"
                assert gb["top_gear_ratio"] > 0, f"{label} bad top gear ratio"


def test_variant_tire_overrides_valid() -> None:
    """Variant tire overrides must be within reasonable bounds."""
    for entry in CAR_LIBRARY:
        for v in entry["variants"]:
            if "tire_width_mm" in v and v["tire_width_mm"] is not None:
                assert 175 <= v["tire_width_mm"] <= 335, (
                    f"{entry['model']} / {v['name']} tire width out of range"
                )
            if "tire_aspect_pct" in v and v["tire_aspect_pct"] is not None:
                assert 20 <= v["tire_aspect_pct"] <= 65, (
                    f"{entry['model']} / {v['name']} aspect out of range"
                )
            if "rim_in" in v and v["rim_in"] is not None:
                assert 15 <= v["rim_in"] <= 22, f"{entry['model']} / {v['name']} rim out of range"


# ---------------------------------------------------------------------------
# car_library.py helper tests
# ---------------------------------------------------------------------------


def test_get_variants_for_model_returns_variants() -> None:
    """get_variants_for_model returns the variants for a known model."""
    variants = get_variants_for_model("BMW", "Sedan", "3 Series (G20, 2019-2025)")
    assert len(variants) >= 3
    names = [v["name"] for v in variants]
    assert "320i" in names
    # Data source can include either a distinct M340i trim or only xDrive form.
    assert any("M340i" in name for name in names)


def test_get_variants_for_model_unknown_returns_empty() -> None:
    """Unknown brand/type/model returns empty list."""
    assert get_variants_for_model("Tesla", "Sedan", "Model S") == []


def test_resolve_variant_no_variant() -> None:
    """resolve_variant with None returns base entry."""
    base = CAR_LIBRARY[0]
    resolved = resolve_variant(base, None)
    assert resolved["gearboxes"] == base["gearboxes"]
    assert resolved["tire_options"] == base["tire_options"]


def test_resolve_variant_inherits_base_gearboxes() -> None:
    """Variant without gearbox override inherits base gearboxes."""
    # Find a model where first variant has no gearbox override
    for entry in CAR_LIBRARY:
        first_v = entry["variants"][0]
        if not first_v.get("gearboxes"):
            resolved = resolve_variant(entry, first_v["name"])
            assert resolved["gearboxes"] == entry["gearboxes"]
            break


def test_resolve_variant_overrides_gearboxes() -> None:
    """Variant with gearbox override replaces base gearboxes."""
    # BMW M3 G80 variants have gearbox overrides
    for entry in CAR_LIBRARY:
        if entry["model"] == "M3 (G80, 2021-2026)":
            # "M3 Competition" has only automatic
            resolved = resolve_variant(entry, "M3 Competition")
            assert len(resolved["gearboxes"]) == 1
            assert "automatic" in resolved["gearboxes"][0]["name"].lower()
            break
    else:
        raise AssertionError("M3 G80 not found")


def test_resolve_variant_unknown_name_returns_base() -> None:
    """resolve_variant with unknown name returns base entry unchanged."""
    base = CAR_LIBRARY[0]
    resolved = resolve_variant(base, "nonexistent_variant")
    assert resolved["gearboxes"] == base["gearboxes"]


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


def test_car_library_models_response_accepts_variants() -> None:
    """CarLibraryModelsResponse validates entries with variants."""
    from vibesensor.api import CarLibraryModelsResponse

    models = get_models_for_brand_type("BMW", "Sedan")
    resp = CarLibraryModelsResponse(models=models)
    for m in resp.models:
        assert len(m.variants) >= 1
        for v in m.variants:
            assert v.name
            assert v.drivetrain in ("FWD", "RWD", "AWD")


def test_car_library_variant_entry_requires_drivetrain() -> None:
    """CarLibraryVariantEntry requires drivetrain field."""
    from pydantic import ValidationError

    from vibesensor.api_models import CarLibraryVariantEntry

    # Valid
    v = CarLibraryVariantEntry(name="320i", drivetrain="RWD")
    assert v.name == "320i"
    assert v.drivetrain == "RWD"

    # Missing drivetrain
    try:
        CarLibraryVariantEntry(name="320i")  # type: ignore[call-arg]
        raise AssertionError("Should have raised")
    except ValidationError:
        pass


# ---------------------------------------------------------------------------
# CarConfig domain model tests
# ---------------------------------------------------------------------------


def test_car_config_from_dict_without_variant() -> None:
    """CarConfig.from_dict without variant sets variant to None (backward compat)."""
    car = CarConfig.from_dict({"name": "Old Car", "type": "sedan"})
    assert car.variant is None
    d = car.to_dict()
    assert "variant" not in d


def test_car_config_from_dict_with_variant() -> None:
    """CarConfig.from_dict with variant preserves it."""
    car = CarConfig.from_dict({"name": "BMW 320i", "type": "Sedan", "variant": "320i"})
    assert car.variant == "320i"
    d = car.to_dict()
    assert d["variant"] == "320i"


def test_car_config_from_dict_empty_variant() -> None:
    """Empty string variant is treated as None."""
    car = CarConfig.from_dict({"name": "Car", "type": "sedan", "variant": ""})
    assert car.variant is None


def test_car_config_variant_truncated() -> None:
    """Very long variant names are truncated to 64 chars."""
    long_name = "x" * 100
    car = CarConfig.from_dict({"name": "Car", "type": "sedan", "variant": long_name})
    assert len(car.variant) == 64  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# JSON structural integrity
# ---------------------------------------------------------------------------


def test_car_library_json_parseable() -> None:
    """The car library JSON is valid JSON and loadable."""
    from vibesensor.car_library import _DATA_FILE

    with open(_DATA_FILE) as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    assert len(data) == 73


def test_total_variant_count() -> None:
    """Sanity check: the library has a reasonable number of variants."""
    total = sum(len(e.get("variants", [])) for e in CAR_LIBRARY)
    assert total >= 150, f"Only {total} variants total, expected >=150"
