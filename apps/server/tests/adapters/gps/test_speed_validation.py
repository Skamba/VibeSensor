"""Tests for GPS speed validation policy — independent of transport state."""

from __future__ import annotations

import math

from vibesensor.adapters.gps.speed_validation import (
    DEFAULT_SPEED_VALIDATION_CONFIG,
    SpeedSampleVerdict,
    SpeedValidationConfig,
    evaluate_speed_sample,
    is_speed_plausible,
)


class TestIsSpeedPlausible:
    """Plausibility gate for GPS speed samples."""

    def test_normal_speed_accepted(self) -> None:
        assert is_speed_plausible(30.0) is True

    def test_zero_speed_accepted(self) -> None:
        assert is_speed_plausible(0.0) is True

    def test_max_speed_accepted(self) -> None:
        assert is_speed_plausible(DEFAULT_SPEED_VALIDATION_CONFIG.max_speed_mps) is True

    def test_over_max_rejected(self) -> None:
        assert is_speed_plausible(151.0) is False

    def test_negative_rejected(self) -> None:
        assert is_speed_plausible(-1.0) is False

    def test_nan_rejected(self) -> None:
        assert is_speed_plausible(math.nan) is False

    def test_inf_rejected(self) -> None:
        assert is_speed_plausible(math.inf) is False

    def test_custom_config(self) -> None:
        cfg = SpeedValidationConfig(max_speed_mps=50.0)
        assert is_speed_plausible(60.0, cfg) is False
        assert is_speed_plausible(40.0, cfg) is True


class TestEvaluateSpeedSample:
    """Zero-speed transition confirmation logic."""

    def test_nonzero_speed_always_accepted(self) -> None:
        verdict = evaluate_speed_sample(10.0, prev_speed=50.0, current_streak=2)
        assert verdict == SpeedSampleVerdict(accepted=True, zero_speed_streak=0)

    def test_zero_after_low_speed_accepted_immediately(self) -> None:
        verdict = evaluate_speed_sample(0.0, prev_speed=0.3, current_streak=0)
        assert verdict == SpeedSampleVerdict(accepted=True, zero_speed_streak=0)

    def test_zero_after_high_speed_first_sample_rejected(self) -> None:
        verdict = evaluate_speed_sample(0.0, prev_speed=5.0, current_streak=0)
        assert verdict == SpeedSampleVerdict(accepted=False, zero_speed_streak=1)

    def test_zero_after_high_speed_second_sample_rejected(self) -> None:
        verdict = evaluate_speed_sample(0.0, prev_speed=5.0, current_streak=1)
        assert verdict == SpeedSampleVerdict(accepted=False, zero_speed_streak=2)

    def test_zero_after_high_speed_third_sample_accepted(self) -> None:
        verdict = evaluate_speed_sample(0.0, prev_speed=5.0, current_streak=2)
        assert verdict == SpeedSampleVerdict(accepted=True, zero_speed_streak=3)

    def test_zero_with_none_prev_accepted(self) -> None:
        verdict = evaluate_speed_sample(0.0, prev_speed=None, current_streak=0)
        assert verdict == SpeedSampleVerdict(accepted=True, zero_speed_streak=0)

    def test_zero_with_bool_prev_accepted(self) -> None:
        """Bool values must not be treated as numeric previous speeds."""
        verdict = evaluate_speed_sample(0.0, prev_speed=True, current_streak=0)  # type: ignore[arg-type]
        assert verdict == SpeedSampleVerdict(accepted=True, zero_speed_streak=0)

    def test_custom_confirm_samples(self) -> None:
        cfg = SpeedValidationConfig(zero_confirm_samples=1)
        verdict = evaluate_speed_sample(0.0, prev_speed=5.0, current_streak=0, config=cfg)
        assert verdict == SpeedSampleVerdict(accepted=True, zero_speed_streak=1)

    def test_custom_threshold(self) -> None:
        cfg = SpeedValidationConfig(zero_drop_prev_threshold_mps=10.0)
        # prev_speed=5.0 is below threshold, so zero is accepted immediately
        verdict = evaluate_speed_sample(0.0, prev_speed=5.0, current_streak=0, config=cfg)
        assert verdict == SpeedSampleVerdict(accepted=True, zero_speed_streak=0)
