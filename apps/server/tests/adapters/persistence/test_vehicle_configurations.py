from __future__ import annotations

import json
from unittest.mock import patch

from vibesensor.adapters.persistence.car_library import (
    load_car_library,
    resolve_vehicle_configurations,
)
from vibesensor.adapters.persistence.vehicle_configurations import (
    _VEHICLE_CONFIG_DATA_FILE,
    load_vehicle_configurations,
)


def _entry_for(model: str) -> dict[str, object]:
    for entry in load_car_library():
        if entry["brand"] == "BMW" and entry["model"] == model:
            return entry
    raise AssertionError(f"BMW model not found: {model}")


def test_canonical_vehicle_configurations_cover_picker_breadth() -> None:
    configs = load_vehicle_configurations()

    assert len(configs) > 400
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


def test_every_canonical_vehicle_configuration_exposes_required_metadata_and_policy() -> None:
    configs = load_vehicle_configurations()

    for config in configs:
        assert config.configuration_confidence in {
            "high_confidence",
            "medium_confidence",
            "low_confidence",
            "no_confidence",
            "not_applicable",
        }
        assert isinstance(config.order_analysis_policy.usable_for_engine_order, bool)
        assert isinstance(config.order_analysis_policy.usable_for_driveshaft_order, bool)
        assert isinstance(config.order_analysis_policy.usable_for_wheel_order, bool)
        assert isinstance(config.order_analysis_policy.requires_manual_confirmation, bool)
        assert config.metadata_for("drivetrain") is not None
        assert config.metadata_for("tire_dimensions") is not None
        assert config.metadata_for("transmission_name") is not None
        assert config.metadata_for("top_gear_ratio") is not None
        assert any(
            config.metadata_for(field_name) is not None
            for field_name in ("final_drive_front", "final_drive_rear")
        )


def test_load_vehicle_configurations_fails_closed_when_required_evidence_refs_are_missing(
    tmp_path,
) -> None:
    bad_payload = json.loads(_VEHICLE_CONFIG_DATA_FILE.read_text(encoding="utf-8"))
    bad_payload[0]["drivetrain"] = {
        "value": bad_payload[0]["drivetrain"]["value"],
        "confidence": "official_exact",
        "notes": "Broken test payload without evidence refs.",
    }
    bad_path = tmp_path / "vehicle_configurations.json"
    bad_path.write_text(json.dumps(bad_payload), encoding="utf-8")

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_FILE",
        bad_path,
    ):
        assert load_vehicle_configurations() == []


def test_resolve_vehicle_configurations_returns_only_canonical_exact_rows() -> None:
    configs = resolve_vehicle_configurations(
        _entry_for("3 Series (G20, 2019-2025)"),
        "330i",
    )

    assert len(configs) == 2
    assert {config.source_status for config in configs} == {"exact_row"}
    assert {config.transmission_name for config in configs} == {
        "8-speed automatic (ZF 8HP)",
        "6-speed manual",
    }
    assert all(
        config.order_reference_confidence("transmission_name") == "family_default"
        and config.requires_manual_drivetrain_confirmation
        for config in configs
    )


def test_exact_bmw_rows_keep_inline_source_backed_metadata() -> None:
    configs = {
        (config.model_name, config.variant_name, config.transmission_name): config
        for config in load_vehicle_configurations()
    }

    f45_220i = configs[
        (
            "2 Series Active Tourer (F45, 2014-2021)",
            "220i",
            "7-speed Steptronic dual-clutch transmission",
        )
    ]
    assert f45_220i.metadata_for("drivetrain") is not None
    assert f45_220i.metadata_for("drivetrain").confidence == "official_exact"
    assert f45_220i.metadata_for("drivetrain").evidence_refs
    assert f45_220i.metadata_for("top_gear_ratio") is not None
    assert f45_220i.metadata_for("top_gear_ratio").confidence == "family_default"

    g20_330i_xdrive = configs[
        ("3 Series (G20, 2019-2025)", "330i xDrive", "8-speed automatic (ZF 8HP)")
    ]
    assert g20_330i_xdrive.metadata_for("final_drive_front") is not None
    assert g20_330i_xdrive.metadata_for("final_drive_rear") is not None
    assert g20_330i_xdrive.metadata_for("tire_dimensions") is not None

    g60_i5 = configs[("5 Series (G60, 2024-2026)", "i5 eDrive40", "Single-speed fixed gear (EV)")]
    assert g60_i5.top_gear_ratio == 1.0
    assert g60_i5.gear_ratios is None
    assert g60_i5.metadata_for("top_gear_ratio") is not None
    assert g60_i5.metadata_for("top_gear_ratio").confidence == "family_default"
