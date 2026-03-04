"""Tests for Cycle 4 (session 3) fixes – a.k.a. cycle-13 in the global sequence.

Covers:
  1. live_diagnostics._combine_amplitude_strength_db — NaN guard
  2. strength_labels.strength_label — NaN guard returns "unknown"
  3. strength_labels.certainty_label — NaN confidence clamped to 0.0
  4. ws_hub.run() — tick-rate drift compensation (source verification)
  5. Tests for previously-untested helpers
"""

from __future__ import annotations

import inspect

import pytest

from vibesensor.analysis.helpers import (
    MEMS_NOISE_FLOOR_G,
    _effective_baseline_floor,
    _validate_required_strength_metrics,
)
from vibesensor.analysis.strength_labels import (
    _select_reason_key,
    certainty_label,
    strength_label,
)
from vibesensor.constants import SILENCE_DB
from vibesensor.live_diagnostics import _combine_amplitude_strength_db
from vibesensor.ws_hub import WebSocketHub

# ------------------------------------------------------------------
# 1. _combine_amplitude_strength_db — NaN guard
# ------------------------------------------------------------------


class TestCombineAmplitudeNanGuard:
    """NaN values in dB list must be skipped, not mapped to 200 dB."""

    @pytest.mark.parametrize(
        "values, expected_silence",
        [
            ([float("nan")], True),
            ([float("inf")], True),
            ([], True),
        ],
        ids=["nan", "inf", "empty"],
    )
    def test_invalid_returns_silence(
        self, values: list[float], expected_silence: bool
    ) -> None:
        assert _combine_amplitude_strength_db(values) == SILENCE_DB

    def test_nan_mixed_with_valid(self) -> None:
        result_clean = _combine_amplitude_strength_db([10.0, 20.0])
        result_with_nan = _combine_amplitude_strength_db([10.0, float("nan"), 20.0])
        assert result_with_nan == result_clean


# ------------------------------------------------------------------
# 2. strength_label — NaN guard
# ------------------------------------------------------------------


class TestStrengthLabelNanGuard:
    """NaN dB value should return 'unknown', not 'negligible'."""

    @pytest.mark.parametrize(
        "db_value",
        [float("nan"), float("inf"), None],
        ids=["nan", "inf", "none"],
    )
    def test_invalid_returns_unknown(self, db_value: object) -> None:
        key, label = strength_label(db_value)
        assert key == "unknown"
        if db_value is not None or isinstance(db_value, float):
            assert "nknown" in label  # "Unknown" or "Onbekend"

    def test_valid_db_returns_band(self) -> None:
        key, _label = strength_label(15.0)
        assert key != "unknown"


# ------------------------------------------------------------------
# 3. certainty_label — NaN confidence guard
# ------------------------------------------------------------------


class TestCertaintyLabelNanGuard:
    """NaN confidence must be clamped to 0, producing 'low' + '0%'."""

    def test_nan_confidence_returns_low(self) -> None:
        level, _label, pct, _reason = certainty_label(
            float("nan"),
            strength_band_key="moderate",
        )
        assert level == "low"
        assert pct == "0%"

    def test_normal_confidence(self) -> None:
        level, _label, pct, _reason = certainty_label(
            0.85,
            strength_band_key="moderate",
        )
        assert level == "high"
        assert pct == "85%"


# ------------------------------------------------------------------
# 4. ws_hub.run() — drift compensation (source verification)
# ------------------------------------------------------------------


class TestWsHubDriftCompensation:
    """run() should subtract elapsed time from sleep to maintain tick rate."""

    def test_run_subtracts_elapsed(self) -> None:
        source = inspect.getsource(WebSocketHub.run)
        assert "loop.time()" in source or "tick_start" in source
        assert "interval - elapsed" in source


# ------------------------------------------------------------------
# 5. _effective_baseline_floor — edge cases
# ------------------------------------------------------------------


class TestEffectiveBaselineFloor:
    """Test the baseline floor helper for edge cases."""

    @pytest.mark.parametrize(
        "baseline, kwargs, expected",
        [
            (None, {}, MEMS_NOISE_FLOOR_G),
            (0.0, {"extra_fallback": 0.005}, MEMS_NOISE_FLOOR_G),
            (-0.5, {}, MEMS_NOISE_FLOOR_G),
            (0.01, {}, 0.01),
        ],
        ids=["none", "zero-clamped", "negative-clamped", "valid"],
    )
    def test_baseline_floor(
        self, baseline: float | None, kwargs: dict, expected: float
    ) -> None:
        result = _effective_baseline_floor(baseline, **kwargs)
        assert result == expected


# ------------------------------------------------------------------
# 6. _validate_required_strength_metrics — edge cases
# ------------------------------------------------------------------


class TestValidateRequiredStrengthMetrics:
    """Test the validation helper for required strength metrics."""

    @pytest.mark.parametrize(
        "samples",
        [
            [],
            [{"vibration_strength_db": 10.0}, {"vibration_strength_db": 20.0}],
        ],
        ids=["empty", "all-valid"],
    )
    def test_valid_no_error(self, samples: list[dict]) -> None:
        _validate_required_strength_metrics(samples)  # should not raise

    def test_all_missing_raises(self) -> None:
        samples = [{"other_field": 1}, {"other_field": 2}]
        with pytest.raises(ValueError, match="vibration_strength_db"):
            _validate_required_strength_metrics(samples)


# ------------------------------------------------------------------
# 7. _select_reason_key — priority ordering
# ------------------------------------------------------------------


class TestSelectReasonKey:
    """Test reason key selection priority ordering."""

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            (
                dict(confidence=0.9, steady_speed=False, weak_spatial=False, sensor_count=4, has_reference_gaps=True),
                "reference_gaps",
            ),
            (
                dict(confidence=0.9, steady_speed=False, weak_spatial=False, sensor_count=1, has_reference_gaps=False),
                "single_sensor",
            ),
            (
                dict(confidence=0.9, steady_speed=False, weak_spatial=False, sensor_count=4, has_reference_gaps=False),
                "strong_order_match",
            ),
            (
                dict(confidence=0.2, steady_speed=False, weak_spatial=False, sensor_count=4, has_reference_gaps=False),
                "weak_order_match",
            ),
        ],
        ids=["reference-gaps", "single-sensor", "strong-match", "weak-match"],
    )
    def test_reason_priority(self, kwargs: dict, expected: str) -> None:
        result = _select_reason_key(
            kwargs["confidence"],
            steady_speed=kwargs["steady_speed"],
            weak_spatial=kwargs["weak_spatial"],
            sensor_count=kwargs["sensor_count"],
            has_reference_gaps=kwargs["has_reference_gaps"],
        )
        assert result == expected
