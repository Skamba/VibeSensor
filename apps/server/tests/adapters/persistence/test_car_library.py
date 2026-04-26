"""Core grouped-picker checks derived from canonical vehicle configurations."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from vibesensor.adapters.persistence.car_library import (
    get_brands,
    get_models_for_brand_type,
    get_types_for_brand,
    load_car_library,
)


def test_car_library_has_entries() -> None:
    assert len(load_car_library()) > 50


def test_car_library_module_no_longer_exports_compat_alias() -> None:
    import vibesensor.adapters.persistence.car_library as car_library_module

    assert not hasattr(car_library_module, "CAR_LIBRARY")


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
    for model in models:
        assert model["brand"] == "BMW"
        assert model["type"] == "Sedan"


def test_every_grouped_entry_has_required_fields() -> None:
    for entry in load_car_library():
        assert "brand" in entry
        assert "type" in entry
        assert "model" in entry
        assert "gearboxes" in entry
        assert isinstance(entry["gearboxes"], list)
        assert "tire_options" in entry
        assert isinstance(entry["tire_options"], list)
        assert len(entry["variants"]) > 0


def test_variant_gearboxes_are_derived_from_canonical_exact_rows() -> None:
    hatchbacks = get_models_for_brand_type("BMW", "Hatchback")
    f45 = next(
        model for model in hatchbacks if model["model"] == "2 Series Active Tourer (F45, 2014-2021)"
    )
    exact_variant = next(variant for variant in f45["variants"] if variant["name"] == "225xe")
    exact_gearbox = exact_variant["gearboxes"][0]

    assert exact_gearbox["source_status"] == "exact_row"
    assert exact_gearbox["final_drive_ratio_confidence"] == "family_default"
    assert exact_gearbox["top_gear_ratio_confidence"] == "family_default"
    assert exact_gearbox["transmission_confidence"] == "family_default"
    assert exact_gearbox["requires_manual_confirmation"] is True

    sedans = get_models_for_brand_type("BMW", "Sedan")
    g20 = next(model for model in sedans if model["model"] == "3 Series (G20, 2019-2025)")
    derived_variant = next(variant for variant in g20["variants"] if variant["name"] == "330i")

    assert {gearbox["source_status"] for gearbox in derived_variant["gearboxes"]} == {"exact_row"}
    assert {gearbox["transmission_confidence"] for gearbox in derived_variant["gearboxes"]} == {
        "family_default"
    }
    assert all(gearbox["requires_manual_confirmation"] for gearbox in derived_variant["gearboxes"])


def test_migrated_staggered_tire_option_exposes_front_rear_setup() -> None:
    suvs = get_models_for_brand_type("BMW", "SUV")
    x5 = next(model for model in suvs if model["model"] == "X5 (G05, 2019-2026)")
    staggered = next(option for option in x5["tire_options"] if option["name"] == 'M Sport 22"')

    assert staggered["default_axle_for_speed"] == "rear"
    assert staggered["source_confidence"] == "reputable_secondary_crosschecked"
    assert staggered["front"] == {
        "width_mm": pytest.approx(275.0),
        "aspect_pct": pytest.approx(35.0),
        "rim_in": pytest.approx(22.0),
    }
    assert staggered["rear"] == {
        "width_mm": pytest.approx(315.0),
        "aspect_pct": pytest.approx(30.0),
        "rim_in": pytest.approx(22.0),
    }
    assert staggered["tire_width_mm"] == pytest.approx(315.0)
    assert staggered["tire_aspect_pct"] == pytest.approx(30.0)


def test_car_library_models_response_accepts_actual_data() -> None:
    from vibesensor.adapters.http.models import CarLibraryModelsResponse

    models = get_models_for_brand_type("BMW", "Sedan")
    resp = CarLibraryModelsResponse(models=models)

    assert len(resp.models) == len(models)
    assert all(model.brand == "BMW" and model.type == "Sedan" for model in resp.models)


def test_load_library_handles_bad_vehicle_configurations() -> None:
    with patch(
        "vibesensor.adapters.persistence.car_library.load_vehicle_configurations",
        return_value=[],
    ):
        assert load_car_library() == []
