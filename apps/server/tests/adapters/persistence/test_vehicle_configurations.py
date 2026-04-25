from __future__ import annotations

import json

from vibesensor.adapters.persistence.car_library import (
    _VEHICLE_CONFIG_DATA_FILE,
    load_car_library,
    load_vehicle_configurations,
    resolve_vehicle_configurations,
)


def _entry_for(model: str) -> dict[str, object]:
    for entry in load_car_library():
        if entry["brand"] == "BMW" and entry["model"] == model:
            return entry
    raise AssertionError(f"BMW model not found: {model}")


def test_exact_vehicle_configurations_cover_required_configuration_kinds() -> None:
    configs = load_vehicle_configurations()
    assert any(
        config.variant_name == "420i" and config.drivetrain == "RWD" and config.fuel_type == "ICE"
        for config in configs
    )
    assert any(
        config.variant_name == "330i xDrive"
        and config.drivetrain == "AWD"
        and config.fuel_type == "ICE"
        for config in configs
    )
    assert any(config.variant_name == "225xe" and config.fuel_type == "PHEV" for config in configs)
    assert any(
        config.variant_name == "i5 eDrive40"
        and config.fuel_type == "EV"
        and config.transmission_name == "Single-speed fixed gear (EV)"
        for config in configs
    )


def test_exact_vehicle_configurations_include_field_level_provenance_for_three_bmw_rows() -> None:
    configs = {
        (config.model_name, config.variant_name): config for config in load_vehicle_configurations()
    }

    expected_rows = [
        ("2 Series Active Tourer (F45, 2014-2021)", "220i"),
        ("3 Series (G20, 2019-2025)", "330i xDrive"),
        ("5 Series (G60, 2024-2026)", "i5 eDrive40"),
    ]
    for key in expected_rows:
        config = configs[key]
        assert config.provenance_for("drivetrain") is not None
        assert config.provenance_for("tire_dimensions") is not None
        assert config.provenance_for("transmission_name") is not None
        assert any(
            config.provenance_for(field_name) is not None
            for field_name in ("final_drive_front", "final_drive_rear")
        )
        assert config.provenance_for("top_gear_ratio") is not None

    i5 = configs[("5 Series (G60, 2024-2026)", "i5 eDrive40")]
    assert i5.provenance_for("gear_ratios") is not None


def test_official_exact_field_provenance_requires_source_id(tmp_path) -> None:
    bad_payload = json.loads(_VEHICLE_CONFIG_DATA_FILE.read_text(encoding="utf-8"))
    bad_payload[0]["field_provenance"] = [
        {
            "field_name": "drivetrain",
            "confidence": "official_exact",
            "verified_at": "2026-04-25",
            "notes": "Broken test payload without a source ID.",
        }
    ]
    bad_path = tmp_path / "vehicle_configurations.json"
    bad_path.write_text(json.dumps(bad_payload), encoding="utf-8")

    from unittest.mock import patch

    with patch("vibesensor.adapters.persistence.car_library._VEHICLE_CONFIG_DATA_FILE", bad_path):
        assert load_vehicle_configurations() == []


def test_resolve_vehicle_configurations_uses_exact_row_for_f45_220i() -> None:
    configs = resolve_vehicle_configurations(
        _entry_for("2 Series Active Tourer (F45, 2014-2021)"),
        "220i",
    )

    assert len(configs) == 1
    config = configs[0]
    assert config.source_status == "exact_row"
    assert config.transmission_name == "7-speed Steptronic dual-clutch transmission"
    assert config.final_drive_front == 3.231
    assert config.final_drive_rear is None
    assert config.provenance_for("final_drive_front") is not None
    assert config.provenance_for("top_gear_ratio") is not None
    assert config.provenance_for("drivetrain") is not None
    assert (
        config.order_reference_confidence("transmission_name") == "reputable_secondary_crosschecked"
    )
    assert config.provenance_for("tire_dimensions") is not None


def test_resolve_vehicle_configurations_uses_exact_row_for_g20_330i_xdrive() -> None:
    configs = resolve_vehicle_configurations(
        _entry_for("3 Series (G20, 2019-2025)"),
        "330i xDrive",
    )

    assert len(configs) == 1
    config = configs[0]
    assert config.source_status == "exact_row"
    assert config.transmission_name == "8-speed automatic (ZF 8HP)"
    assert config.final_drive_front == 2.813
    assert config.final_drive_rear == 2.813
    assert config.provenance_for("final_drive_front") is not None
    assert config.provenance_for("final_drive_rear") is not None
    assert config.provenance_for("top_gear_ratio") is not None
    assert config.provenance_for("drivetrain") is not None
    assert config.provenance_for("tire_dimensions") is not None


def test_resolve_vehicle_configurations_uses_exact_row_for_g60_i5_edrive40() -> None:
    configs = resolve_vehicle_configurations(
        _entry_for("5 Series (G60, 2024-2026)"),
        "i5 eDrive40",
    )

    assert len(configs) == 1
    config = configs[0]
    assert config.source_status == "exact_row"
    assert config.fuel_type == "EV"
    assert config.gear_ratios == (1.0,)
    assert config.final_drive_rear == 11.115
    assert config.provenance_for("final_drive_rear") is not None
    assert config.provenance_for("top_gear_ratio") is not None
    assert config.provenance_for("gear_ratios") is not None
    assert config.provenance_for("drivetrain") is not None
    assert config.order_reference_confidence("transmission_name") == "official_exact"
    assert config.provenance_for("tire_dimensions") is not None


def test_resolve_vehicle_configurations_projects_unmigrated_variant_per_gearbox() -> None:
    configs = resolve_vehicle_configurations(
        _entry_for("3 Series (G20, 2019-2025)"),
        "330i",
    )

    assert len(configs) == 2
    assert {config.source_status for config in configs} == {"compat_projection"}
    assert {config.transmission_name for config in configs} == {
        "8-speed automatic (ZF 8HP)",
        "6-speed manual",
    }
    assert all(
        config.order_reference_confidence("transmission_name") == "family_default"
        and config.requires_manual_drivetrain_confirmation
        for config in configs
    )
