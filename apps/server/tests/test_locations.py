from __future__ import annotations

from vibesensor.locations import LOCATION_OPTIONS, all_locations, label_for_code


def test_location_options_are_unique_and_short() -> None:
    codes = [code for code, _ in LOCATION_OPTIONS]
    labels = [label for _, label in LOCATION_OPTIONS]
    assert len(codes) == len(set(codes))
    assert len(labels) == len(set(labels))
    for label in labels:
        assert len(label.encode("utf-8")) <= 32


def test_location_lookup_roundtrip() -> None:
    options = all_locations()
    assert options
    for row in options:
        assert label_for_code(row["code"]) == row["label"]
