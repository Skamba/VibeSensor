"""Focused tests for car order-reference provenance rules."""

from __future__ import annotations

import pytest

from vibesensor.domain.car import CarOrderReferenceStatus
from vibesensor.domain.vehicle_configuration import VehicleFieldConfidence
from vibesensor.settings.car_config import car_from_persistence_dict, car_to_persistence_dict


@pytest.mark.parametrize(
    ("final_drive", "top_gear", "expected"),
    [
        ("family_default", "official_exact", True),
        ("official_exact", "unverified", True),
        ("reputable_secondary_crosschecked", "reputable_secondary_crosschecked", False),
        (None, None, False),
    ],
)
def test_only_an_estimated_final_drive_or_top_gear_needs_confirming(
    final_drive: VehicleFieldConfidence | None,
    top_gear: VehicleFieldConfidence | None,
    expected: bool,
) -> None:
    status = CarOrderReferenceStatus(
        selection_source_status="exact_row",
        tire_dimensions_confidence="family_default",
        final_drive_ratio_confidence=final_drive,
        current_gear_ratio_confidence=top_gear,
        transmission_confidence="unverified",
    )

    assert status.requires_manual_confirmation is expected


def test_a_car_saved_under_the_old_rule_loads_with_the_current_flag() -> None:
    """The Pi's BMW F30 320i: family-default tires, cross-checked ratios, stored ``true``."""
    stored = {
        "id": "f30",
        "name": "BMW F30 320i",
        "type": "sedan",
        "aspects": {"final_drive_ratio": 3.15, "current_gear_ratio": 0.64},
        "order_reference_status": {
            "selection_source_status": "exact_row",
            "requires_manual_confirmation": True,
            "tire_dimensions_confidence": "family_default",
            "final_drive_ratio_confidence": "reputable_secondary_crosschecked",
            "current_gear_ratio_confidence": "reputable_secondary_crosschecked",
            "transmission_name": "8-speed automatic",
            "transmission_confidence": "reputable_secondary_crosschecked",
        },
    }

    payload = car_to_persistence_dict(car_from_persistence_dict(stored))

    status = payload["order_reference_status"]
    assert status is not None
    assert status["requires_manual_confirmation"] is False
    assert status["tire_dimensions_confidence"] == "family_default"
