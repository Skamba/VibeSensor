from __future__ import annotations

import pytest
from pydantic import ValidationError

from vibesensor.shared.locations import (
    LOCATION_OPTIONS,
    WHEEL_LOCATION_CODES,
    all_locations,
    is_wheel_location,
    label_for_code,
)


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


@pytest.mark.parametrize(
    "label",
    [
        "front-left",
        "front-right",
        "rear-left",
        "rear-right",
        "Front Left",
        "Front Right",
        "Rear Left",
        "Rear Right",
        "front_left_wheel",
        "front_right_wheel",
        "rear_left_wheel",
        "rear_right_wheel",
        "FL Wheel",
        "FR Wheel",
        "RL Wheel",
        "RR Wheel",
    ],
)
def test_wheel_location_labels_are_detected(label: str) -> None:
    assert is_wheel_location(label), f"Expected {label!r} to be classified as wheel"


@pytest.mark.parametrize(
    "label",
    [
        "driver-seat",
        "Driver Seat",
        "trunk",
        "Trunk",
        "engine_bay",
        "Engine Bay",
        "transmission",
        "Transmission",
        "driveshaft_tunnel",
        "front_subframe",
        "rear_subframe",
        "front-passenger",
        "rear-left-seat",
        "rear-center-seat",
    ],
)
def test_non_wheel_location_labels_are_not_detected(label: str) -> None:
    assert not is_wheel_location(label), f"Expected {label!r} not to be classified as wheel"


def test_empty_location_labels_are_not_wheels() -> None:
    assert not is_wheel_location("")
    assert not is_wheel_location("   ")


def test_wheel_location_codes_are_complete() -> None:
    assert len(WHEEL_LOCATION_CODES) == 4
    for code in WHEEL_LOCATION_CODES:
        assert is_wheel_location(code)


class TestSetLocationRequestAcceptsEmptyCode:
    """Verify that SetLocationRequest allows empty location_code for clearing."""

    from vibesensor.adapters.http.models import SetLocationRequest as _Req

    @pytest.mark.parametrize(
        "code",
        ["", "front_left_wheel"],
        ids=["empty", "valid_code"],
    )
    def test_accepted_codes(self, code: str) -> None:
        req = self._Req(location_code=code)
        assert req.location_code == code

    def test_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"location_code"):
            self._Req(location_code="x" * 65)
