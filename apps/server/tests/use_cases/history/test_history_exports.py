"""Behavior tests for history export flattening."""

from __future__ import annotations

import json

from vibesensor.use_cases.history.exports import flatten_for_csv as _flatten_for_csv


class TestFlattenForCSV:
    """Cover CSV flattening for nested known fields and omission of unknown extras."""

    def test_nested_dict_serialised_as_json(self) -> None:
        row = {"top_peaks": [{"hz": 30, "amp": 0.1}], "accel_x_g": 0.5}
        flat = _flatten_for_csv(row)
        assert isinstance(flat["top_peaks"], str)
        parsed = json.loads(flat["top_peaks"])
        assert parsed == [{"hz": 30, "amp": 0.1}]
        assert flat["accel_x_g"] == 0.5

    def test_unknown_keys_are_dropped(self) -> None:
        row = {"accel_x_g": 1.0, "custom_field": "hello", "another": 42}
        flat = _flatten_for_csv(row)
        assert "custom_field" not in flat
        assert "another" not in flat
        assert "extras" not in flat

    def test_no_extras_when_all_known(self) -> None:
        row = {"accel_x_g": 1.0, "speed_kmh": 80.0}
        flat = _flatten_for_csv(row)
        assert "extras" not in flat or flat.get("extras") is None

    def test_empty_row(self) -> None:
        flat = _flatten_for_csv({})
        assert isinstance(flat, dict)
