"""Focused regression coverage for canonical car-data validation."""

from __future__ import annotations

from dataclasses import replace

from vibesensor.adapters.persistence.car_library_validation import (
    validate_car_library_rows,
    validate_vehicle_configurations,
)
from vibesensor.domain import (
    AxleTireSetup,
    TireSpec,
    VehicleConfiguration,
    VehicleConfigurationTireOption,
    VehicleFieldConfidence,
    VehicleFieldMetadata,
    VehicleOrderAnalysisPolicy,
)


def _make_valid_car_library_entry() -> dict[str, object]:
    return {
        "brand": "BMW",
        "type": "SUV",
        "model": "Validation Test Model",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.15,
                "top_gear_ratio": 0.67,
            }
        ],
        "tire_options": [
            {
                "name": 'Standard 18"',
                "tire_width_mm": 225.0,
                "tire_aspect_pct": 45.0,
                "rim_in": 18.0,
                "front": {"width_mm": 225.0, "aspect_pct": 45.0, "rim_in": 18.0},
                "rear": {"width_mm": 225.0, "aspect_pct": 45.0, "rim_in": 18.0},
                "default_axle_for_speed": "rear",
            },
            {
                "name": 'Sport 19"',
                "tire_width_mm": 245.0,
                "tire_aspect_pct": 40.0,
                "rim_in": 19.0,
                "front": {"width_mm": 245.0, "aspect_pct": 40.0, "rim_in": 19.0},
                "rear": {"width_mm": 245.0, "aspect_pct": 40.0, "rim_in": 19.0},
                "default_axle_for_speed": "rear",
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 18.0,
        "variants": [
            {
                "name": "xDrive30i",
                "engine": "B48 2.0L I4 Turbo",
                "drivetrain": "AWD",
            }
        ],
    }


def _metadata(confidence: VehicleFieldConfidence) -> VehicleFieldMetadata:
    refs = ("test:source",) if confidence in {"official_exact", "official_derived"} else ()
    return VehicleFieldMetadata(confidence=confidence, evidence_refs=refs)


def _make_valid_vehicle_configuration() -> VehicleConfiguration:
    tire = TireSpec.from_aspects(
        {
            "tire_width_mm": 225.0,
            "tire_aspect_pct": 45.0,
            "rim_in": 18.0,
        }
    )
    assert tire is not None
    return VehicleConfiguration(
        brand="BMW",
        car_type="SUV",
        model_name="Validation Test Model",
        variant_name="xDrive30i",
        drivetrain="AWD",
        transmission_name="8-speed automatic (ZF 8HP)",
        top_gear_ratio=0.67,
        default_tire=tire,
        tire_options=(
            VehicleConfigurationTireOption(
                name='Standard 18"',
                tire_setup=AxleTireSetup.square(tire),
                metadata=_metadata("family_default"),
            ),
        ),
        fuel_type="ICE",
        final_drive_front=3.15,
        final_drive_rear=3.15,
        drivetrain_metadata=_metadata("official_exact"),
        tire_metadata=_metadata("family_default"),
        transmission_metadata=_metadata("official_exact"),
        top_gear_ratio_metadata=_metadata("official_exact"),
        final_drive_front_metadata=_metadata("official_exact"),
        final_drive_rear_metadata=_metadata("official_exact"),
        order_analysis_policy=VehicleOrderAnalysisPolicy(
            usable_for_engine_order=True,
            usable_for_driveshaft_order=True,
            usable_for_wheel_order=True,
            requires_manual_confirmation=False,
        ),
    )


def test_validate_car_library_rows_flags_major_invariant_breaks() -> None:
    entry = _make_valid_car_library_entry()
    entry["gearboxes"][0]["final_drive_ratio"] = 20.0

    issues = validate_car_library_rows([entry], allowlist={})

    assert [issue.rule for issue in issues] == ["final_drive_ratio_range"]
    assert "implausible final_drive_ratio" in issues[0].message


def test_validate_vehicle_configurations_flags_missing_metadata_for_populated_fields() -> None:
    config = _make_valid_vehicle_configuration()
    broken = replace(config, final_drive_rear_metadata=None)

    issues = validate_vehicle_configurations([broken], allowlist={})

    assert [issue.rule for issue in issues] == ["missing_field_metadata"]
    assert "final_drive_rear" in issues[0].message


def test_validate_vehicle_configurations_flags_layout_mismatch() -> None:
    config = _make_valid_vehicle_configuration()
    broken = replace(
        config,
        variant_name="Validation Test Variant",
        drivetrain="RWD",
        final_drive_front=3.15,
        final_drive_front_metadata=_metadata("official_exact"),
        final_drive_rear=None,
        final_drive_rear_metadata=None,
    )

    issues = validate_vehicle_configurations([broken], allowlist={})

    assert {issue.rule for issue in issues} == {"drivetrain_final_drive_layout"}
    assert any("final_drive_front" in issue.message for issue in issues)
    assert any("does not expose any driven final-drive ratio" in issue.message for issue in issues)


def test_validate_vehicle_configurations_allows_manual_only_partial_final_drive() -> None:
    config = _make_valid_vehicle_configuration()
    partial = replace(
        config,
        variant_name="Validation Partial Variant",
        final_drive_front=None,
        final_drive_front_metadata=None,
        final_drive_rear=None,
        final_drive_rear_metadata=None,
        order_analysis_policy=VehicleOrderAnalysisPolicy(
            usable_for_engine_order=True,
            usable_for_driveshaft_order=False,
            usable_for_wheel_order=False,
            requires_manual_confirmation=True,
        ),
    )

    issues = validate_vehicle_configurations([partial], allowlist={})

    assert not issues


def test_validate_vehicle_configurations_accepts_low_dct_top_gear() -> None:
    config = _make_valid_vehicle_configuration()
    low_top_gear = replace(
        config,
        transmission_name="7-speed S tronic",
        top_gear_ratio=0.386,
        final_drive_front=5.302,
        final_drive_rear=5.302,
    )

    issues = validate_vehicle_configurations([low_top_gear], allowlist={})

    assert not issues
