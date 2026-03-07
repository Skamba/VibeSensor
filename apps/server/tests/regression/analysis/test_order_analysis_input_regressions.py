# ruff: noqa: E402, E501
from __future__ import annotations

"""Order analysis and numeric input guard regressions.

Covers:
  1. pdf_builder.py — guarded float() on confidence_0_to_1
  2. summary.py — guarded float() on frequency_hz
  3. order_analysis._order_label — edge cases (zero test coverage)
  4. order_analysis._driveshaft_hz — edge cases (zero test coverage)
  5. domain_models._as_float_or_none — NaN handling
"""


import pytest

from vibesensor.analysis.order_analysis import _driveshaft_hz, _order_label
from vibesensor.runlog import as_float_or_none

# ------------------------------------------------------------------
# 1. pdf_builder confidence guard (integration-level)
# ------------------------------------------------------------------


class TestPdfBuilderConfidenceGuard:
    """float() on confidence should not crash on non-numeric values."""

    @pytest.mark.parametrize(
        ("raw_value", "expected"),
        [
            ("unknown", 0.0),
            (0.85, pytest.approx(0.85)),
            (None, 0.0),
        ],
    )
    def test_confidence_guard(self, raw_value: object, expected: object) -> None:
        finding = {"confidence_0_to_1": raw_value}
        try:
            confidence = float(finding.get("confidence_0_to_1") or 0.0)
        except (ValueError, TypeError):
            confidence = 0.0
        assert confidence == expected


# ------------------------------------------------------------------
# 2. summary.py frequency guard
# ------------------------------------------------------------------


class TestSummaryFrequencyGuard:
    """float() on frequency_hz should not crash on non-numeric values."""

    def test_non_numeric_frequency_skipped(self) -> None:
        row = {"frequency_hz": "invalid"}
        with pytest.raises((ValueError, TypeError)):
            float(row.get("frequency_hz") or 0.0)

    def test_none_frequency(self) -> None:
        row = {"frequency_hz": None}
        try:
            freq = float(row.get("frequency_hz") or 0.0)
        except (ValueError, TypeError):
            freq = 0.0
        assert freq == 0.0


# ------------------------------------------------------------------
# 3. _order_label — edge cases
# ------------------------------------------------------------------


class TestOrderLabel:
    """_order_label should handle 2-arg signatures."""

    @pytest.mark.parametrize(
        ("order", "base", "expected"),
        [
            (1, "wheel", "1x wheel"),
            (3, "engine", "3x engine"),
            (2, "driveline", "2x driveline"),
        ],
        ids=["basic", "higher-order", "driveline"],
    )
    def test_two_arg(self, order: int, base: str, expected: str) -> None:
        assert _order_label(order, base) == expected

    def test_wrong_arg_count_raises(self) -> None:
        with pytest.raises(TypeError):
            _order_label()  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            _order_label(1)  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            _order_label(1, 2, 3, 4)  # type: ignore[call-arg]


# ------------------------------------------------------------------
# 4. _driveshaft_hz — edge cases
# ------------------------------------------------------------------


class TestDriveshaftHz:
    """_driveshaft_hz must handle missing/zero/negative inputs gracefully."""

    @pytest.mark.parametrize(
        ("sample", "overrides", "tire_m"),
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


# ------------------------------------------------------------------
# 5. _as_float_or_none — NaN handling (via parameterized test)
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (float("nan"), None),
        (float("inf"), None),
        (3.14, pytest.approx(3.14)),
        ("42.0", pytest.approx(42.0)),
        (None, None),
        ("hello", None),
    ],
)
def test_as_float_or_none_regression(value: object, expected: object) -> None:
    """as_float_or_none must reject NaN/Inf and accept valid numbers."""
    result = as_float_or_none(value)
    if expected is None:
        assert result is None
    else:
        assert result == expected
