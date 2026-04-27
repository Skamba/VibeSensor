"""Tests for car variant support in the car library and domain models."""

from __future__ import annotations

import pytest

from vibesensor.adapters.persistence.car_library import (
    get_models_for_brand_type,
    get_variants_for_model,
    load_car_library,
    resolve_variant,
)
from vibesensor.shared.types.car_config import car_from_persistence_dict, car_to_persistence_dict


def _variant_label(entry: dict[str, object], variant: dict[str, object]) -> str:
    """Short label for assertion messages: ``'3 Series (G20) / 320i'``."""
    return f"{entry['model']} / {variant.get('name', '?')}"


def _library_entries() -> list[dict[str, object]]:
    return load_car_library()


# ---------------------------------------------------------------------------
# Car library JSON structure tests
# ---------------------------------------------------------------------------


def test_every_model_has_variants() -> None:
    """Every car library entry must have at least one variant."""
    for entry in _library_entries():
        assert "variants" in entry, f"{entry['model']} missing variants"
        assert isinstance(entry["variants"], list), f"{entry['model']} variants not a list"
        assert len(entry["variants"]) >= 1, f"{entry['model']} has no variants"


def test_every_variant_has_required_fields() -> None:
    """Each variant must have name and drivetrain."""
    for entry in _library_entries():
        for v in entry["variants"]:
            label = _variant_label(entry, v)
            assert "name" in v, f"{label} missing name"
            assert isinstance(v["name"], str), f"{label} name not str"
            assert len(v["name"]) > 0, f"{label} empty name"
            assert "drivetrain" in v, f"{label} missing drivetrain"
            assert v["drivetrain"] in ("FWD", "RWD", "AWD"), (
                f"{label} bad drivetrain: {v['drivetrain']}"
            )


def test_variant_names_unique_within_model() -> None:
    """Variant names must be unique within each model."""
    for entry in _library_entries():
        names = [v["name"] for v in entry["variants"]]
        assert len(names) == len(set(names)), (
            f"{entry['model']} has duplicate variant names: {names}"
        )


def test_variant_gearbox_overrides_valid() -> None:
    """Variant gearbox overrides must be valid (positive ratios)."""
    for entry in _library_entries():
        for v in entry["variants"]:
            gbs = v.get("gearboxes")
            if not gbs:
                continue
            label = _variant_label(entry, v)
            assert isinstance(gbs, list), f"{label} gearboxes not list"
            assert len(gbs) > 0, f"{label} gearboxes empty"
            for gb in gbs:
                assert "name" in gb, f"{label} gearbox missing name"
                assert gb["final_drive_ratio"] > 0, f"{label} bad FD ratio"
                assert gb["top_gear_ratio"] > 0, f"{label} bad top gear ratio"


def test_variant_tire_overrides_valid() -> None:
    """Variant tire overrides must be within reasonable bounds."""
    for entry in _library_entries():
        for v in entry["variants"]:
            label = _variant_label(entry, v)
            if "tire_width_mm" in v and v["tire_width_mm"] is not None:
                assert 175 <= v["tire_width_mm"] <= 335, f"{label} tire width out of range"
            if "tire_aspect_pct" in v and v["tire_aspect_pct"] is not None:
                assert 20 <= v["tire_aspect_pct"] <= 65, f"{label} aspect out of range"
            if "rim_in" in v and v["rim_in"] is not None:
                assert 15 <= v["rim_in"] <= 22, f"{label} rim out of range"


# ---------------------------------------------------------------------------
# car_library.py helper tests
# ---------------------------------------------------------------------------


def test_get_variants_for_model_returns_variants() -> None:
    """get_variants_for_model returns the variants for a known model."""
    variants = get_variants_for_model("BMW", "Sedan", "3 Series (G20, 2019-2025)")
    assert len(variants) >= 3
    names = [v["name"] for v in variants]
    assert "320i" in names
    assert "330i" in names


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
    # Find a model where first variant has no gearbox override
    for entry in _library_entries():
        first_v = entry["variants"][0]
        if not first_v.get("gearboxes"):
            resolved = resolve_variant(entry, first_v["name"])
            assert resolved["gearboxes"] == entry["gearboxes"]
            break


def test_resolve_variant_carries_variant_engine_and_drivetrain() -> None:
    """Resolved variants should expose the selected variant's identity fields."""
    for entry in _library_entries():
        if entry["brand"] == "BMW" and entry["model"] == "8 Series Coupe (G15, 2019)":
            resolved = resolve_variant(entry, "M8")
            assert resolved["engine"] == "4.4L V8 Turbo"
            assert resolved["drivetrain"] == "AWD"
            break
    else:
        raise AssertionError("BMW G15 not found")


def test_resolve_variant_overrides_gearboxes() -> None:
    """Variant with gearbox override replaces base gearboxes."""
    # BMW M3 G80 variants have gearbox overrides
    for entry in _library_entries():
        if entry["model"] == "M3 (G80, 2021-2026)":
            # "M3 Competition" has only automatic
            resolved = resolve_variant(entry, "M3 Competition")
            assert len(resolved["gearboxes"]) == 1
            assert "automatic" in resolved["gearboxes"][0]["name"].lower()
            break
    else:
        raise AssertionError("M3 G80 not found")


def test_resolve_variant_g20_330i_xdrive_uses_verified_automatic_ratio() -> None:
    """G20 330i xDrive keeps the automatic-only gearbox override with the verified ratio."""
    for entry in _library_entries():
        if entry["brand"] == "BMW" and entry["model"] == "3 Series (G20, 2019-2025)":
            resolved = resolve_variant(entry, "330i xDrive")
            assert len(resolved["gearboxes"]) == 1
            gearbox = resolved["gearboxes"][0]
            assert gearbox["name"] == "8-speed automatic (ZF 8HP)"
            assert gearbox["final_drive_ratio"] == pytest.approx(2.813)
            assert gearbox["top_gear_ratio"] == pytest.approx(0.64)
            assert gearbox["gear_ratios"] == pytest.approx(
                [5.25, 3.36, 2.172, 1.72, 1.316, 1.0, 0.822, 0.64]
            )
            assert gearbox["source_status"] == "exact_row"
            break
    else:
        raise AssertionError("BMW G20 330i xDrive not found")


@pytest.mark.parametrize(
    ("model", "variant", "expected_final_drive_ratio"),
    [
        ("A4 (B9, 2016-2025)", "35 TFSI", 4.234),
        ("A4 (B9, 2016-2025)", "40 TFSI", 4.234),
        ("A4 (B9, 2016-2025)", "45 TFSI quattro", 4.410),
        ("A5 (B9, 2017-2024)", "40 TFSI", 4.234),
        ("A5 (B9, 2017-2024)", "45 TFSI quattro", 4.410),
        ("Q5 (FY, 2017-2026)", "40 TFSI", 5.302),
        ("Q5 (FY, 2017-2026)", "45 TFSI quattro", 5.302),
        ("Q5 (FY, 2017-2026)", "55 TFSI e quattro", 5.302),
    ],
)
def test_resolve_variant_audi_b9_fy_s_tronic_uses_verified_final_drives(
    model: str, variant: str, expected_final_drive_ratio: float
) -> None:
    """Audi B9/FY S tronic entries keep the verified final-drive ratios from Audi docs."""
    for entry in _library_entries():
        if entry["brand"] == "Audi" and entry["model"] == model:
            resolved = resolve_variant(entry, variant)
            s_tronic = next(
                gearbox
                for gearbox in resolved["gearboxes"]
                if "s tronic" in gearbox["name"].lower()
            )
            assert s_tronic["final_drive_ratio"] == pytest.approx(expected_final_drive_ratio)
            break
    else:
        raise AssertionError(f"Audi model not found: {model}")


@pytest.mark.parametrize(
    ("model", "variant", "expected_engine", "expected_drivetrain"),
    [
        ("A3 (8V, 2013-2020)", "1.6 TDI", "1.6L I4 TDI Diesel", "FWD"),
        ("A3 (8V, 2013-2020)", "2.0 TDI", "2.0L I4 TDI Diesel", "FWD"),
        ("A3 (8V, 2013-2020)", "2.0 TDI quattro", "2.0L I4 TDI Diesel", "AWD"),
        ("A3 (8Y, 2021-2026)", "30 TDI", "2.0L I4 TDI Diesel", "FWD"),
        ("A3 (8Y, 2021-2026)", "35 TDI", "2.0L I4 TDI Diesel", "FWD"),
        ("A4 (B8, 2008-2016)", "2.0 TDI", "2.0L I4 TDI Diesel", "FWD"),
        ("A4 (B8, 2008-2016)", "2.0 TDI quattro", "2.0L I4 TDI Diesel", "AWD"),
        ("A4 (B8, 2008-2016)", "3.0 TDI quattro", "3.0L V6 TDI Diesel", "AWD"),
        ("A4 (B9, 2016-2025)", "30 TDI", "2.0L I4 TDI Diesel", "FWD"),
        ("A4 (B9, 2016-2025)", "35 TDI", "2.0L I4 TDI Diesel", "FWD"),
        ("Q3 (8U, 2012-2018)", "2.0 TDI", "2.0L I4 TDI Diesel", "FWD"),
        ("Q3 (8U, 2012-2018)", "2.0 TDI quattro", "2.0L I4 TDI Diesel", "AWD"),
        ("Q3 (F3, 2019-2025)", "35 TDI", "2.0L I4 TDI Diesel", "FWD"),
        ("Q3 (F3, 2019-2025)", "40 TDI quattro", "2.0L I4 TDI Diesel", "AWD"),
        ("Q5 (FY, 2017-2026)", "35 TDI quattro", "2.0L I4 TDI Diesel", "AWD"),
        ("Q5 (FY, 2017-2026)", "40 TDI quattro", "2.0L I4 TDI Diesel", "AWD"),
    ],
)
def test_audi_models_include_verified_tdi_variants(
    model: str, variant: str, expected_engine: str, expected_drivetrain: str
) -> None:
    """Audi core European-market models keep the verified TDI coverage added for #974."""
    for entry in _library_entries():
        if entry["brand"] == "Audi" and entry["model"] == model:
            variant_entry = next(
                candidate for candidate in entry["variants"] if candidate["name"] == variant
            )
            assert variant_entry["engine"] == expected_engine
            assert variant_entry["drivetrain"] == expected_drivetrain
            break
    else:
        raise AssertionError(f"Audi model not found: {model}")


@pytest.mark.parametrize(
    ("model", "expected_electric_variants"),
    [
        (
            "5 Series (G60, 2024-2026)",
            {
                "i5 eDrive40": ("Electric Single Motor", "RWD"),
                "i5 M60 xDrive": ("Electric Dual Motor", "AWD"),
            },
        ),
        (
            "7 Series (G70, 2022-2026)",
            {
                "i7 eDrive50": ("Electric Single Motor", "RWD"),
            },
        ),
        (
            "7 Series (G70, 2023-2026)",
            {
                "i7 M70 xDrive": ("Electric Dual Motor", "AWD"),
            },
        ),
        (
            "X1 (U11, 2023-2026)",
            {
                "iX1 xDrive30": ("Electric Dual Motor", "AWD"),
            },
        ),
        (
            "X2 (U10, 2024-2026)",
            {
                "iX2 xDrive30": ("Electric Dual Motor", "AWD"),
            },
        ),
        (
            "iX (I20, 2022-2026)",
            {
                "xDrive40": ("Electric Dual Motor", "AWD"),
                "xDrive50": ("Electric Dual Motor", "AWD"),
                "M60": ("Electric Dual Motor (Performance)", "AWD"),
            },
        ),
        (
            "i4 (G26, 2022-2026)",
            {
                "eDrive40": ("Electric Single Motor", "RWD"),
                "M50": ("Electric Dual Motor", "AWD"),
            },
        ),
        (
            "e-tron GT (J1, 2022-2026)",
            {
                "e-tron GT quattro": ("Electric Dual Motor", "AWD"),
                "RS e-tron GT": ("Electric Dual Motor (Performance)", "AWD"),
            },
        ),
        (
            "Q4 e-tron (FZ, 2022-2026)",
            {
                "40 e-tron": ("Electric Single Motor", "RWD"),
                "50 e-tron quattro": ("Electric Dual Motor", "AWD"),
            },
        ),
    ],
)
def test_bev_models_match_verified_motor_layouts(
    model: str, expected_electric_variants: dict[str, tuple[str, str]]
) -> None:
    """Supported BEV entries keep the verified motor-layout variants from issue #975."""
    for entry in _library_entries():
        if entry["model"] == model:
            actual_electric_variants = {
                variant["name"]: (variant["engine"], variant["drivetrain"])
                for variant in entry["variants"]
                if variant["engine"].startswith("Electric")
            }
            assert actual_electric_variants == expected_electric_variants
            break
    else:
        raise AssertionError(f"EV model not found: {model}")


def test_resolve_variant_unknown_name_returns_base() -> None:
    """resolve_variant with unknown name returns base entry unchanged."""
    base = _library_entries()[0]
    resolved = resolve_variant(base, "nonexistent_variant")
    assert resolved["gearboxes"] == base["gearboxes"]


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


def test_car_library_models_response_accepts_variants() -> None:
    """CarLibraryModelsResponse validates entries with variants."""
    from vibesensor.adapters.http.models import CarLibraryModelsResponse

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


# ---------------------------------------------------------------------------
# JSON structural integrity
# ---------------------------------------------------------------------------


def test_car_library_json_parseable() -> None:
    """The grouped picker data is derivable from canonical vehicle configurations."""
    data = load_car_library()
    assert isinstance(data, list)
    assert len(data) >= 70


def test_total_variant_count() -> None:
    """Sanity check: the library has a reasonable number of variants."""
    total = sum(len(e.get("variants", [])) for e in _library_entries())
    assert total >= 150, f"Only {total} variants total, expected >=150"
