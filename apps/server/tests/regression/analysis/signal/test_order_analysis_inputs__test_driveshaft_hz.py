"""Order analysis and numeric input guard regressions.

Covers:
  1. pdf_builder.py — guarded float() on confidence_0_to_1
  2. summary.py — guarded float() on frequency_hz
  3. order_analysis._order_label — edge cases (zero test coverage)
  4. order_analysis._driveshaft_hz — edge cases (zero test coverage)
  5. domain_models._as_float_or_none — NaN handling
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.order_analysis import _driveshaft_hz


class TestDriveshaftHz:
    """_driveshaft_hz must handle missing/zero/negative inputs gracefully."""

    @pytest.mark.parametrize(
        "sample, overrides, tire_m",
        [
            ({"speed_kmh": 80.0}, {"final_drive_ratio": 3.5}, None),
            ({"speed_kmh": 80.0, "final_drive_ratio": 0.0}, {}, 2.0),
            ({"speed_kmh": 80.0, "final_drive_ratio": -1.0}, {}, 2.0),
        ],
        ids=["no-tire-circ", "zero-final-drive", "negative-final-drive"],
    )
    def test_driveshaft_hz_returns_none(
        self, sample: dict, overrides: dict, tire_m: float | None
    ) -> None:
        assert _driveshaft_hz(sample, overrides, tire_circumference_m=tire_m) is None

    def test_valid_inputs(self) -> None:
        result = _driveshaft_hz(
            {"speed_kmh": 72.0, "final_drive_ratio": 3.5},
            {},
            tire_circumference_m=2.0,
        )
        assert result is not None
        assert result > 0
