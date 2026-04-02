"""Metadata-factory coverage for deriving Car and Symptom context from case inputs."""

from __future__ import annotations

import pytest

from vibesensor.shared.boundaries.diagnostic_case import (
    car_from_metadata,
    symptom_from_metadata,
)
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping


def test_car_from_metadata_returns_none_without_case_context() -> None:
    assert car_from_metadata(run_metadata_from_mapping({})) is None


def test_car_from_metadata_builds_context_from_vehicle_fields() -> None:
    car = car_from_metadata(
        run_metadata_from_mapping(
            {
                "active_car_snapshot": {
                    "name": "Golf",
                    "type": "hatchback",
                    "variant": "GTI",
                }
            }
        )
    )

    assert car is not None
    assert car.name == "Golf"
    assert car.car_type == "hatchback"
    assert car.variant == "GTI"


def test_car_from_metadata_keeps_order_reference_context_without_names() -> None:
    car = car_from_metadata(
        run_metadata_from_mapping(
            {
                "analysis_settings_snapshot": {
                    "tire_width_mm": 225,
                    "tire_aspect_pct": 40,
                    "rim_in": 18,
                }
            }
        )
    )

    assert car is not None
    assert car.name == "Unnamed Car"
    assert car.car_type == "sedan"
    assert car.tire_width_mm == pytest.approx(225.0)
    assert car.tire_aspect_pct == pytest.approx(40.0)
    assert car.rim_in == pytest.approx(18.0)


def test_symptom_from_metadata_defaults_to_unspecified() -> None:
    assert symptom_from_metadata(run_metadata_from_mapping({})).is_unspecified is True


def test_symptom_from_metadata_reads_canonical_fields_and_context() -> None:
    symptom = symptom_from_metadata(
        run_metadata_from_mapping(
            {
                "symptom": {
                    "description": "whine under load",
                    "onset": "after 60 km/h",
                    "context": "during acceleration",
                },
            }
        )
    )

    assert symptom.description == "whine under load"
    assert symptom.onset == "after 60 km/h"
    assert symptom.context == "during acceleration"


def test_symptom_from_metadata_ignores_removed_complaint_alias() -> None:
    metadata = run_metadata_from_mapping({"complaint": "legacy alias"})
    assert symptom_from_metadata(metadata).is_unspecified is True
