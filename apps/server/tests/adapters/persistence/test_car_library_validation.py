"""Focused regression coverage for car-library plausibility validation."""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from vibesensor.adapters.persistence.car_library import (
    _DATA_FILE,
    load_car_library,
    load_vehicle_configurations,
)
from vibesensor.adapters.persistence.car_library_validation import (
    load_car_library_validation_allowlist,
    validate_car_library_rows,
    validate_vehicle_configurations,
)
from vibesensor.domain import (
    AxleTireSetup,
    TireSpec,
    VehicleConfiguration,
    VehicleConfigurationTireOption,
    VehicleFieldProvenance,
)


def _make_valid_legacy_entry() -> dict[str, object]:
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
            },
            {
                "name": 'Sport 19"',
                "tire_width_mm": 245.0,
                "tire_aspect_pct": 40.0,
                "rim_in": 19.0,
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


def _make_valid_exact_configuration() -> VehicleConfiguration:
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
            ),
        ),
        fuel_type="ICE",
        final_drive_front=3.15,
        final_drive_rear=3.15,
        field_provenance=(
            VehicleFieldProvenance("final_drive_front", "official_exact", source_id="src:front"),
            VehicleFieldProvenance("final_drive_rear", "official_exact", source_id="src:rear"),
            VehicleFieldProvenance("top_gear_ratio", "official_exact", source_id="src:gear"),
            VehicleFieldProvenance("transmission_name", "official_exact", source_id="src:gear"),
            VehicleFieldProvenance("drivetrain", "official_exact", source_id="src:drive"),
            VehicleFieldProvenance("tire_dimensions", "family_default"),
        ),
    )


def test_current_car_library_rows_validate_with_documented_allowlist() -> None:
    assert validate_car_library_rows(load_car_library()) == ()


def test_current_exact_vehicle_configurations_validate_cleanly() -> None:
    assert validate_vehicle_configurations(load_vehicle_configurations()) == ()


def test_current_allowlist_matches_current_raw_legacy_ev_exceptions() -> None:
    with _DATA_FILE.open(encoding="utf-8") as fh:
        raw_rows = json.load(fh)

    issues = validate_car_library_rows(raw_rows, allowlist={})
    observed = {(issue.rule, issue.entity) for issue in issues}
    expected = set(load_car_library_validation_allowlist())

    assert (
        observed
        == expected
        == {
            ("pure_ev_requires_single_speed", "BMW|X1 (U11, 2023-2026)|iX1 xDrive30"),
            ("pure_ev_requires_single_speed", "BMW|X2 (U10, 2024-2026)|iX2 xDrive30"),
        }
    )


@pytest.mark.parametrize(
    ("mutate", "expected_rule", "message_snippet"),
    [
        (
            lambda entry: entry["variants"].append(
                {
                    "name": "xDrive30i",
                    "engine": "B58 3.0L I6 Turbo",
                    "drivetrain": "AWD",
                }
            ),
            "duplicate_variant_name",
            "duplicates a variant name",
        ),
        (
            lambda entry: entry["variants"][0].update({"drivetrain": "RWD"}),
            "badge_requires_awd",
            "AWD badge",
        ),
        (
            lambda entry: entry["variants"][0].update({"name": "eDrive40", "drivetrain": "AWD"}),
            "edrive_requires_rwd",
            "eDrive badge",
        ),
        (
            lambda entry: entry["variants"][0].update({"name": "Manual Edition"}),
            "manual_claim_mismatch",
            "claims manual",
        ),
        (
            lambda entry: entry["variants"][0].update(
                {
                    "name": "eDrive40",
                    "drivetrain": "RWD",
                    "engine": "Electric Single Motor",
                }
            ),
            "pure_ev_requires_single_speed",
            "is EV",
        ),
        (
            lambda entry: entry["variants"][0].update(
                {
                    "name": "330i",
                    "drivetrain": "RWD",
                    "gearboxes": [
                        {
                            "name": "Single-speed fixed gear (EV)",
                            "final_drive_ratio": 9.1,
                            "top_gear_ratio": 1.0,
                        }
                    ],
                }
            ),
            "ice_must_not_use_single_speed",
            "is ICE",
        ),
        (
            lambda entry: entry["gearboxes"][0].update({"final_drive_ratio": 20.0}),
            "final_drive_ratio_range",
            "implausible final_drive_ratio",
        ),
        (
            lambda entry: entry["gearboxes"][0].update({"top_gear_ratio": 1.5}),
            "top_gear_ratio_range",
            "implausible top_gear_ratio",
        ),
        (
            lambda entry: entry["gearboxes"][0].update({"gear_ratios": [3.5, 3.6, 1.1]}),
            "gear_ratio_order",
            "descending gear ratios",
        ),
        (
            lambda entry: entry["tire_options"][1].update({"rim_in": 18.0}),
            "tire_option_name_rim_mismatch",
            "name suffix says 19",
        ),
        (
            lambda entry: entry.update(
                {
                    "tire_width_mm": 145.0,
                    "tire_aspect_pct": 25.0,
                    "rim_in": 14.0,
                }
            ),
            "tire_diameter_range",
            "default tire has implausible diameter",
        ),
    ],
)
def test_validate_car_library_rows_flags_major_invariant_breaks(
    mutate,
    expected_rule: str,
    message_snippet: str,
) -> None:
    entry = _make_valid_legacy_entry()
    mutate(entry)

    issues = validate_car_library_rows([entry], allowlist={})

    assert [issue.rule for issue in issues] == [expected_rule]
    assert message_snippet in issues[0].message
    assert issues[0].entity.startswith("BMW|Validation Test Model")


def test_validate_vehicle_configurations_flags_missing_provenance_for_populated_fields() -> None:
    config = _make_valid_exact_configuration()
    broken = replace(
        config,
        field_provenance=tuple(
            entry for entry in config.field_provenance if entry.field_name != "final_drive_rear"
        ),
    )

    issues = validate_vehicle_configurations([broken], allowlist={})

    assert [issue.rule for issue in issues] == ["missing_field_provenance"]
    assert "final_drive_rear" in issues[0].message


def test_validate_vehicle_configurations_flags_layout_mismatch() -> None:
    config = _make_valid_exact_configuration()
    broken = replace(
        config,
        variant_name="330i",
        drivetrain="RWD",
        final_drive_front=3.15,
        final_drive_rear=None,
    )

    issues = validate_vehicle_configurations([broken], allowlist={})

    assert {issue.rule for issue in issues} == {"drivetrain_final_drive_layout"}
    assert any("final_drive_front" in issue.message for issue in issues)
    assert any("does not expose any driven final-drive ratio" in issue.message for issue in issues)


def test_load_car_library_fails_closed_on_validation_error(tmp_path) -> None:
    bad_file = tmp_path / "bad-library.json"
    entry = _make_valid_legacy_entry()
    entry["gearboxes"][0]["final_drive_ratio"] = 20.0
    bad_file.write_text(json.dumps([entry]), encoding="utf-8")

    with patch("vibesensor.adapters.persistence.car_library._DATA_FILE", bad_file):
        assert load_car_library() == []


def test_load_vehicle_configurations_fails_closed_on_validation_error(tmp_path) -> None:
    bad_file = tmp_path / "bad-configs.json"
    row = {
        "brand": "BMW",
        "type": "SUV",
        "market": "EU",
        "model_code": "TEST",
        "body_code": "TEST",
        "production_start_year": 2024,
        "production_end_year": 2026,
        "model_name": "Validation Test Model",
        "variant_name": "xDrive30i",
        "engine_code": "B48",
        "engine_name": "B48 2.0L I4 Turbo",
        "fuel_type": "ICE",
        "drivetrain": "RWD",
        "transmission_code": "AUTO8",
        "transmission_name": "8-speed automatic (ZF 8HP)",
        "top_gear_ratio": 0.67,
        "final_drive_front": 3.15,
        "tire_options": [
            {
                "name": 'Standard 18"',
                "tire_width_mm": 225.0,
                "tire_aspect_pct": 45.0,
                "rim_in": 18.0,
            }
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 18.0,
        "source_status": "exact_row",
        "field_provenance": [
            {
                "field_name": "top_gear_ratio",
                "confidence": "official_exact",
                "source_id": "src:gear",
            },
            {
                "field_name": "transmission_name",
                "confidence": "official_exact",
                "source_id": "src:gear",
            },
            {
                "field_name": "drivetrain",
                "confidence": "official_exact",
                "source_id": "src:drive",
            },
            {
                "field_name": "tire_dimensions",
                "confidence": "family_default",
            },
            {
                "field_name": "final_drive_front",
                "confidence": "official_exact",
                "source_id": "src:front",
            },
        ],
    }
    bad_file.write_text(json.dumps([row]), encoding="utf-8")

    with patch("vibesensor.adapters.persistence.car_library._VEHICLE_CONFIG_DATA_FILE", bad_file):
        assert load_vehicle_configurations() == []
