"""Core grouped-picker behavior checks."""

from __future__ import annotations

from unittest.mock import patch

from vibesensor.adapters.persistence.car_library import load_car_library


def test_load_library_handles_bad_vehicle_configurations() -> None:
    with patch(
        "vibesensor.adapters.persistence.car_library.load_vehicle_configurations",
        return_value=[],
    ):
        assert load_car_library() == []
