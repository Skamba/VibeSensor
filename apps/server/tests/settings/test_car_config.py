"""Car persistence codec: defaults, sanitizing and round trip."""

from __future__ import annotations

import pytest

from vibesensor.settings.car_config import car_from_persistence_dict, car_to_persistence_dict


def test_roundtrip_keeps_identity_name_and_type() -> None:
    car = car_from_persistence_dict({"id": "x", "name": "Test", "type": "suv"})
    payload = car_to_persistence_dict(car)
    assert (payload["id"], payload["name"], payload["type"]) == ("x", "Test", "suv")
    assert car_from_persistence_dict(payload) == car


@pytest.mark.parametrize(
    ("data", "field", "fallback"),
    [
        ({}, "name", "Unnamed Car"),
        ({}, "car_type", "sedan"),
        ({"name": "   "}, "name", "Unnamed Car"),
        ({"name": ""}, "name", "Unnamed Car"),
        ({"type": "   "}, "car_type", "sedan"),
    ],
    ids=["missing-name", "missing-type", "whitespace-name", "empty-name", "whitespace-type"],
)
def test_missing_or_blank_fields_fall_back_to_defaults(
    data: dict, field: str, fallback: str
) -> None:
    assert getattr(car_from_persistence_dict(data), field) == fallback


def test_name_truncated_at_64() -> None:
    assert len(car_from_persistence_dict({"name": "A" * 100}).name) == 64


def test_missing_id_gets_generated() -> None:
    first = car_from_persistence_dict({"name": "Generated"})
    second = car_from_persistence_dict({"name": "Generated"})
    assert first.id and second.id and first.id != second.id


def test_invalid_aspect_is_replaced_by_a_number() -> None:
    car = car_from_persistence_dict({"aspects": {"tire_width_mm": "not_a_number"}})
    assert isinstance(car.aspects.get("tire_width_mm"), (int, float))
