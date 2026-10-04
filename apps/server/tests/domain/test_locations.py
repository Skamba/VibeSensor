from __future__ import annotations

from vibesensor.domain.locations import (
    all_locations,
    is_wheel_location,
    label_for_code,
)


def test_location_lookup_roundtrip() -> None:
    options = all_locations()
    assert options
    for row in options:
        assert label_for_code(row["code"]) == row["label"]


def test_empty_location_labels_are_not_wheels() -> None:
    assert not is_wheel_location("")
    assert not is_wheel_location("   ")
