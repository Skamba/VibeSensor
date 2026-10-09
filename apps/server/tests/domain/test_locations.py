from __future__ import annotations

import pytest

from vibesensor.domain.locations import (
    all_locations,
    is_wheel_location,
    label_for_code,
    wheel_axle,
)


def test_location_lookup_roundtrip() -> None:
    options = all_locations()
    assert options
    for row in options:
        assert label_for_code(row["code"]) == row["label"]


def test_empty_location_labels_are_not_wheels() -> None:
    assert not is_wheel_location("")
    assert not is_wheel_location("   ")


@pytest.mark.parametrize(
    ("location", "axle"),
    [
        ("front_left_wheel", "front"),
        ("Front Right Wheel", "front"),
        ("rear_left_wheel", "rear"),
        ("Rear Right Wheel", "rear"),
        ("trunk", None),
        ("Front Subframe", None),
        ("", None),
    ],
)
def test_only_wheel_sensors_sit_on_an_axle(location: str, axle: str | None) -> None:
    assert wheel_axle(location) == axle
