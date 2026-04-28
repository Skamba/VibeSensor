"""Validate every committed vehicle-configuration shard against the schema."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from vibesensor.adapters.persistence.vehicle_configurations import _VEHICLE_CONFIG_DATA_DIR
from vibesensor.shared._data_files import resolve_static_data_file

_SCHEMA_PATH = resolve_static_data_file("schema/vehicle_configuration_shard.schema.json")


def _load_validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_schema_file_is_valid_json_schema_2020_12() -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$schema"].endswith("2020-12/schema")


@pytest.mark.parametrize(
    "shard_path",
    sorted(_VEHICLE_CONFIG_DATA_DIR.rglob("*.json")),
    ids=lambda p: str(p.relative_to(_VEHICLE_CONFIG_DATA_DIR)),
)
def test_every_committed_shard_matches_schema(shard_path: Path) -> None:
    validator = _load_validator()
    payload = json.loads(shard_path.read_text(encoding="utf-8"))
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    assert not errors, "\n".join(
        f"{list(error.absolute_path)}: {error.message}" for error in errors[:5]
    )


def test_schema_rejects_unknown_top_level_key() -> None:
    validator = _load_validator()
    payload = {"configurations": [], "bogus": True}
    assert list(validator.iter_errors(payload))


def test_schema_rejects_bad_drivetrain_value() -> None:
    validator = _load_validator()
    payload = {
        "configurations": [
            {
                "id": "x",
                "variant_name": "v",
                "fuel_type": "ICE",
                "drivetrain": {"value": "BOGUS", "confidence": "official_exact"},
                "transmission": {"name": "M", "confidence": "official_exact"},
                "ratios": {"top_gear_ratio": {"value": 0.7, "confidence": "official_exact"}},
                "tires": {
                    "default": {
                        "front": {"width_mm": 1, "aspect_pct": 1, "rim_in": 1},
                        "confidence": "official_exact",
                    }
                },
                "configuration_confidence": "high_confidence",
            }
        ]
    }
    assert list(validator.iter_errors(payload))


def test_schema_rejects_tires_with_both_default_and_default_ref() -> None:
    validator = _load_validator()
    payload = {
        "configurations": [
            {
                "id": "x",
                "variant_name": "v",
                "fuel_type": "ICE",
                "drivetrain": {"value": "FWD", "confidence": "official_exact"},
                "transmission": {"name": "M", "confidence": "official_exact"},
                "ratios": {"top_gear_ratio": {"value": 0.7, "confidence": "official_exact"}},
                "tires": {
                    "default": {
                        "front": {"width_mm": 1, "aspect_pct": 1, "rim_in": 1},
                        "confidence": "official_exact",
                    },
                    "default_ref": "x",
                },
                "configuration_confidence": "high_confidence",
            }
        ]
    }
    assert list(validator.iter_errors(payload))


def test_schema_rejects_override_without_reason() -> None:
    validator = _load_validator()
    payload = {
        "configurations": [
            {
                "id": "x",
                "variant_name": "v",
                "fuel_type": "ICE",
                "drivetrain": {"value": "FWD", "confidence": "official_exact"},
                "transmission": {"name": "M", "confidence": "official_exact"},
                "ratios": {"top_gear_ratio": {"value": 0.7, "confidence": "official_exact"}},
                "tires": {
                    "default": {
                        "front": {"width_mm": 1, "aspect_pct": 1, "rim_in": 1},
                        "confidence": "official_exact",
                    }
                },
                "configuration_confidence": "high_confidence",
                "order_analysis_policy_override": {"usable_for_wheel_order": False},
            }
        ]
    }
    assert list(validator.iter_errors(payload))
