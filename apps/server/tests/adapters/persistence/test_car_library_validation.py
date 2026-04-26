"""Focused regression coverage for canonical car-data validation."""

from __future__ import annotations

from dataclasses import replace

from vibesensor.adapters.persistence.car_library import load_car_library
from vibesensor.adapters.persistence.car_library_validation import (
    validate_car_library_rows,
    validate_vehicle_configurations,
)
from vibesensor.adapters.persistence.vehicle_configurations import load_vehicle_configurations
from vibesensor.domain import (
    AxleTireSetup,
    TireSpec,
    VehicleConfiguration,
    VehicleConfigurationTireOption,
    VehicleFieldConfidence,
    VehicleFieldMetadata,
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
    )


def test_current_grouped_car_library_rows_validate_cleanly() -> None:
    assert validate_car_library_rows(load_car_library()) == ()


def test_current_canonical_vehicle_configurations_validate_cleanly() -> None:
    assert validate_vehicle_configurations(load_vehicle_configurations()) == ()


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
