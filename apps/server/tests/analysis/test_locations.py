from __future__ import annotations

import pytest
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

    from vibesensor.api_models import SetLocationRequest as _Req

    @pytest.mark.parametrize(
        "code",
        ["", "front_left_wheel"],
        ids=["empty", "valid_code"],
    )
    def test_accepted_codes(self, code: str) -> None:
        req = self._Req(location_code=code)
        assert req.location_code == code

    def test_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._Req(location_code="x" * 65)
