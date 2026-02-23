from __future__ import annotations

from pydantic import ValidationError

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


class TestSetLocationRequestAcceptsEmptyCode:
    """Verify that SetLocationRequest allows empty location_code for clearing."""

    def test_empty_string_accepted(self) -> None:
        from vibesensor.api import SetLocationRequest

        req = SetLocationRequest(location_code="")
        assert req.location_code == ""

    def test_valid_code_accepted(self) -> None:
        from vibesensor.api import SetLocationRequest

        req = SetLocationRequest(location_code="front_left_wheel")
        assert req.location_code == "front_left_wheel"

    def test_too_long_rejected(self) -> None:
        from vibesensor.api import SetLocationRequest

        try:
            SetLocationRequest(location_code="x" * 65)
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass
