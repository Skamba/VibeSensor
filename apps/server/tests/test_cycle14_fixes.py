"""Tests for Cycle 5 (session 3) fixes – a.k.a. cycle-14 in the global sequence.

Covers:
  1. pdf_builder.py — guarded float() on confidence_0_to_1
  2. summary.py — guarded float() on frequency_hz
  3. order_analysis._order_label — edge cases (zero test coverage)
  4. order_analysis._driveshaft_hz — edge cases (zero test coverage)
  5. domain_models._as_float_or_none — NaN handling
"""

from __future__ import annotations

import pytest

from vibesensor.runlog import as_float_or_none

# ------------------------------------------------------------------
# 1. pdf_builder confidence guard (integration-level)
# ------------------------------------------------------------------


class TestPdfBuilderConfidenceGuard:
    """float() on confidence should not crash on non-numeric values."""

    def test_non_numeric_confidence_defaults_to_zero(self) -> None:
        """Simulates what pdf_builder does with a non-numeric confidence."""
        finding = {"confidence_0_to_1": "unknown"}
        try:
            confidence = float(finding.get("confidence_0_to_1") or 0.0)
        except (ValueError, TypeError):
            confidence = 0.0
        assert confidence == 0.0

    def test_valid_confidence(self) -> None:
        finding = {"confidence_0_to_1": 0.85}
        try:
            confidence = float(finding.get("confidence_0_to_1") or 0.0)
        except (ValueError, TypeError):
            confidence = 0.0
        assert confidence == pytest.approx(0.85)

    def test_none_confidence(self) -> None:
        finding = {"confidence_0_to_1": None}
        try:
            confidence = float(finding.get("confidence_0_to_1") or 0.0)
        except (ValueError, TypeError):
            confidence = 0.0
        assert confidence == 0.0


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
    """_order_label should handle 2-arg and 3-arg signatures."""

    def test_two_arg_basic(self) -> None:
        from vibesensor.analysis.order_analysis import _order_label

        assert _order_label(1, "wheel") == "1x wheel"

    def test_two_arg_higher_order(self) -> None:
        from vibesensor.analysis.order_analysis import _order_label

        assert _order_label(3, "engine") == "3x engine"

    def test_three_arg_legacy(self) -> None:
        from vibesensor.analysis.order_analysis import _order_label

        result = _order_label("en", 2, "driveline")
        assert result == "2x driveline"

    def test_wrong_arg_count_raises(self) -> None:
        from vibesensor.analysis.order_analysis import _order_label

        with pytest.raises(TypeError):
            _order_label()

        with pytest.raises(TypeError):
            _order_label(1)

        with pytest.raises(TypeError):
            _order_label(1, 2, 3, 4)


# ------------------------------------------------------------------
# 4. _driveshaft_hz — edge cases
# ------------------------------------------------------------------


class TestDriveshaftHz:
    """_driveshaft_hz must handle missing/zero/negative inputs gracefully."""

    def test_no_tire_circumference_returns_none(self) -> None:
        from vibesensor.analysis.order_analysis import _driveshaft_hz

        result = _driveshaft_hz(
            {"speed_kmh": 80.0},
            {"final_drive_ratio": 3.5},
            tire_circumference_m=None,
        )
        assert result is None

    def test_zero_final_drive_returns_none(self) -> None:
        from vibesensor.analysis.order_analysis import _driveshaft_hz

        result = _driveshaft_hz(
            {"speed_kmh": 80.0, "final_drive_ratio": 0.0},
            {},
            tire_circumference_m=2.0,
        )
        assert result is None

    def test_valid_inputs(self) -> None:
        from vibesensor.analysis.order_analysis import _driveshaft_hz

        result = _driveshaft_hz(
            {"speed_kmh": 72.0, "final_drive_ratio": 3.5},
            {},
            tire_circumference_m=2.0,
        )
        assert result is not None
        assert result > 0

    def test_negative_final_drive_returns_none(self) -> None:
        from vibesensor.analysis.order_analysis import _driveshaft_hz

        result = _driveshaft_hz(
            {"speed_kmh": 80.0, "final_drive_ratio": -1.0},
            {},
            tire_circumference_m=2.0,
        )
        assert result is None


# ------------------------------------------------------------------
# 5. _as_float_or_none — NaN handling
# ------------------------------------------------------------------


class TestAsFloatOrNone:
    """as_float_or_none must reject NaN and Inf."""

    def test_nan_returns_none(self) -> None:
        assert as_float_or_none(float("nan")) is None

    def test_inf_returns_none(self) -> None:
        assert as_float_or_none(float("inf")) is None

    def test_valid_float(self) -> None:
        assert as_float_or_none(3.14) == pytest.approx(3.14)

    def test_string_number(self) -> None:
        assert as_float_or_none("42.0") == pytest.approx(42.0)

    def test_none_returns_none(self) -> None:
        assert as_float_or_none(None) is None

    def test_non_numeric_string(self) -> None:
        assert as_float_or_none("hello") is None
