"""Tests for Cycle 4 (session 3) fixes – a.k.a. cycle-13 in the global sequence.

Covers:
  1. live_diagnostics._combine_amplitude_strength_db — NaN guard
  2. strength_labels.strength_label — NaN guard returns "unknown"
  3. strength_labels.certainty_label — NaN confidence clamped to 0.0
  4. ws_hub.run() — tick-rate drift compensation (source verification)
  5. Tests for previously-untested helpers
"""

from __future__ import annotations

import pytest

# ------------------------------------------------------------------
# 1. _combine_amplitude_strength_db — NaN guard
# ------------------------------------------------------------------

class TestCombineAmplitudeNanGuard:
    """NaN values in dB list must be skipped, not mapped to 200 dB."""

    def test_nan_skipped_returns_silence(self) -> None:
        from vibesensor.constants import SILENCE_DB
        from vibesensor.live_diagnostics import _combine_amplitude_strength_db

        result = _combine_amplitude_strength_db([float("nan")])
        assert result == SILENCE_DB

    def test_nan_mixed_with_valid(self) -> None:
        from vibesensor.live_diagnostics import _combine_amplitude_strength_db

        result_clean = _combine_amplitude_strength_db([10.0, 20.0])
        result_with_nan = _combine_amplitude_strength_db([10.0, float("nan"), 20.0])
        # With NaN skipped, should get same as clean
        assert result_with_nan == result_clean

    def test_inf_skipped(self) -> None:
        from vibesensor.constants import SILENCE_DB
        from vibesensor.live_diagnostics import _combine_amplitude_strength_db

        result = _combine_amplitude_strength_db([float("inf")])
        assert result == SILENCE_DB

    def test_empty_returns_silence(self) -> None:
        from vibesensor.constants import SILENCE_DB
        from vibesensor.live_diagnostics import _combine_amplitude_strength_db

        assert _combine_amplitude_strength_db([]) == SILENCE_DB


# ------------------------------------------------------------------
# 2. strength_label — NaN guard
# ------------------------------------------------------------------

class TestStrengthLabelNanGuard:
    """NaN dB value should return 'unknown', not 'negligible'."""

    def test_nan_returns_unknown(self) -> None:
        from vibesensor.analysis.strength_labels import strength_label

        key, label = strength_label(float("nan"))
        assert key == "unknown"
        assert "nknown" in label  # "Unknown" or "Onbekend"

    def test_inf_returns_unknown(self) -> None:
        from vibesensor.analysis.strength_labels import strength_label

        key, label = strength_label(float("inf"))
        assert key == "unknown"

    def test_none_returns_unknown(self) -> None:
        from vibesensor.analysis.strength_labels import strength_label

        key, label = strength_label(None)
        assert key == "unknown"

    def test_valid_db_returns_band(self) -> None:
        from vibesensor.analysis.strength_labels import strength_label

        key, label = strength_label(15.0)
        assert key != "unknown"


# ------------------------------------------------------------------
# 3. certainty_label — NaN confidence guard
# ------------------------------------------------------------------

class TestCertaintyLabelNanGuard:
    """NaN confidence must be clamped to 0, producing 'low' + '0%'."""

    def test_nan_confidence_returns_low(self) -> None:
        from vibesensor.analysis.strength_labels import certainty_label

        level, label, pct, reason = certainty_label(
            float("nan"),
            strength_band_key="moderate",
        )
        assert level == "low"
        assert pct == "0%"

    def test_normal_confidence(self) -> None:
        from vibesensor.analysis.strength_labels import certainty_label

        level, label, pct, reason = certainty_label(
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
        import inspect

        from vibesensor.ws_hub import WebSocketHub

        source = inspect.getsource(WebSocketHub.run)
        # Verify the drift-compensation pattern exists
        assert "loop.time()" in source or "tick_start" in source
        assert "interval - elapsed" in source


# ------------------------------------------------------------------
# 5. _effective_baseline_floor — edge cases
# ------------------------------------------------------------------

class TestEffectiveBaselineFloor:
    """Test the baseline floor helper for edge cases."""

    def test_both_none_returns_mems_floor(self) -> None:
        from vibesensor.analysis.helpers import MEMS_NOISE_FLOOR_G, _effective_baseline_floor

        result = _effective_baseline_floor(None)
        assert result == MEMS_NOISE_FLOOR_G

    def test_zero_baseline_uses_fallback(self) -> None:
        from vibesensor.analysis.helpers import MEMS_NOISE_FLOOR_G, _effective_baseline_floor

        result = _effective_baseline_floor(0.0, extra_fallback=0.005)
        assert result >= MEMS_NOISE_FLOOR_G

    def test_negative_clamped(self) -> None:
        from vibesensor.analysis.helpers import MEMS_NOISE_FLOOR_G, _effective_baseline_floor

        result = _effective_baseline_floor(-0.5)
        assert result == MEMS_NOISE_FLOOR_G

    def test_valid_baseline_used(self) -> None:
        from vibesensor.analysis.helpers import _effective_baseline_floor

        result = _effective_baseline_floor(0.01)
        assert result == 0.01


# ------------------------------------------------------------------
# 6. _validate_required_strength_metrics — edge cases
# ------------------------------------------------------------------

class TestValidateRequiredStrengthMetrics:
    """Test the validation helper for required strength metrics."""

    def test_empty_list_no_error(self) -> None:
        from vibesensor.analysis.helpers import _validate_required_strength_metrics

        _validate_required_strength_metrics([])  # should not raise

    def test_all_valid_no_error(self) -> None:
        from vibesensor.analysis.helpers import _validate_required_strength_metrics

        samples = [{"vibration_strength_db": 10.0}, {"vibration_strength_db": 20.0}]
        _validate_required_strength_metrics(samples)  # should not raise

    def test_all_missing_raises(self) -> None:
        from vibesensor.analysis.helpers import _validate_required_strength_metrics

        samples = [{"other_field": 1}, {"other_field": 2}]
        with pytest.raises(ValueError, match="vibration_strength_db"):
            _validate_required_strength_metrics(samples)


# ------------------------------------------------------------------
# 7. _select_reason_key — priority ordering
# ------------------------------------------------------------------

class TestSelectReasonKey:
    """Test reason key selection priority ordering."""

    def test_reference_gaps_takes_priority(self) -> None:
        from vibesensor.analysis.strength_labels import _select_reason_key

        result = _select_reason_key(
            0.9,
            steady_speed=False,
            weak_spatial=False,
            sensor_count=4,
            has_reference_gaps=True,
        )
        assert result == "reference_gaps"

    def test_single_sensor_second_priority(self) -> None:
        from vibesensor.analysis.strength_labels import _select_reason_key

        result = _select_reason_key(
            0.9,
            steady_speed=False,
            weak_spatial=False,
            sensor_count=1,
            has_reference_gaps=False,
        )
        assert result == "single_sensor"

    def test_high_confidence_strong_match(self) -> None:
        from vibesensor.analysis.strength_labels import _select_reason_key

        result = _select_reason_key(
            0.9,
            steady_speed=False,
            weak_spatial=False,
            sensor_count=4,
            has_reference_gaps=False,
        )
        assert result == "strong_order_match"

    def test_low_confidence(self) -> None:
        from vibesensor.analysis.strength_labels import _select_reason_key

        result = _select_reason_key(
            0.2,
            steady_speed=False,
            weak_spatial=False,
            sensor_count=4,
            has_reference_gaps=False,
        )
        assert result == "weak_order_match"
