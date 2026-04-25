from __future__ import annotations

from vibesensor.adapters.persistence.car_library import (
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
