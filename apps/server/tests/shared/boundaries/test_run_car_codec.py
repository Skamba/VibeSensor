"""Tests for the minimal persisted run-car metadata codec."""

from __future__ import annotations

from vibesensor.shared.boundaries.runs.car import (
    run_car_metadata_from_mapping,
    run_car_metadata_to_json_object,
)
from vibesensor.shared.types.run_schema import RunCarMetadata


def test_run_car_metadata_from_mapping_returns_none_for_empty_payload() -> None:
    assert run_car_metadata_from_mapping({}) is None
    assert run_car_metadata_from_mapping("bad") is None


def test_run_car_metadata_from_mapping_keeps_identity_only_when_extra_fields_exist() -> None:
    run_car = run_car_metadata_from_mapping(
        {
            "id": "car-1",
            "name": "Track Car",
            "type": "coupe",
            "variant": "sport",
            "aspects": {"tire_width_mm": 245.0},
            "unused": "value",
        }
    )

    assert run_car == RunCarMetadata(
        car_id="car-1",
        name="Track Car",
        car_type="coupe",
        variant="sport",
    )


def test_run_car_metadata_to_json_object_keeps_identity_only() -> None:
    payload = run_car_metadata_to_json_object(
        RunCarMetadata(
            car_id="car-1",
            name="Track Car",
            car_type="coupe",
            variant="sport",
        )
    )

    assert payload == {
        "id": "car-1",
        "name": "Track Car",
        "type": "coupe",
        "variant": "sport",
    }
