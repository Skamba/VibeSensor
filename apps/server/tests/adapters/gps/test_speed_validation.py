"""Tests for GPS speed validation policy — independent of transport state."""

from __future__ import annotations

import math

import pytest

from vibesensor.adapters.gps.speed_validation import (
    DEFAULT_SPEED_VALIDATION_CONFIG,
    SpeedSampleVerdict,
    SpeedValidationConfig,
    evaluate_speed_sample,
    is_speed_plausible,
)


class TestIsSpeedPlausible:
    """Plausibility gate for GPS speed samples."""

    @pytest.mark.parametrize(
        ("speed_mps", "expected"),
        [
            (30.0, True),
            (0.0, True),
            (DEFAULT_SPEED_VALIDATION_CONFIG.max_speed_mps, True),
            (151.0, False),
            (-1.0, False),
            (math.nan, False),
            (math.inf, False),
        ],
        ids=[
            "normal-speed-accepted",
            "zero-speed-accepted",
            "max-speed-accepted",
            "over-max-rejected",
            "negative-rejected",
            "nan-rejected",
            "inf-rejected",
        ],
    )
    def test_default_plausibility_contract(self, speed_mps: float, expected: bool) -> None:
        assert is_speed_plausible(speed_mps) is expected

    def test_custom_config(self) -> None:
        cfg = SpeedValidationConfig(max_speed_mps=50.0)
        assert is_speed_plausible(60.0, cfg) is False
        assert is_speed_plausible(40.0, cfg) is True


class TestEvaluateSpeedSample:
    """Zero-speed transition confirmation logic."""

    @pytest.mark.parametrize(
        ("speed_mps", "prev_speed", "current_streak", "expected"),
        [
            (
                10.0,
                50.0,
                2,
                SpeedSampleVerdict(accepted=True, zero_speed_streak=0),
            ),
            (
                0.0,
                0.3,
                0,
                SpeedSampleVerdict(accepted=True, zero_speed_streak=0),
            ),
            (
                0.0,
                5.0,
                0,
                SpeedSampleVerdict(accepted=False, zero_speed_streak=1),
            ),
            (
                0.0,
                5.0,
                1,
                SpeedSampleVerdict(accepted=False, zero_speed_streak=2),
            ),
            (
                0.0,
                5.0,
                2,
                SpeedSampleVerdict(accepted=True, zero_speed_streak=3),
            ),
            (
                0.0,
                None,
                0,
                SpeedSampleVerdict(accepted=True, zero_speed_streak=0),
            ),
            (
                0.0,
                True,
                0,
                SpeedSampleVerdict(accepted=True, zero_speed_streak=0),
            ),
        ],
        ids=[
            "nonzero-always-accepted",
            "zero-after-low-speed-accepted-immediately",
            "zero-after-high-speed-first-sample-rejected",
            "zero-after-high-speed-second-sample-rejected",
            "zero-after-high-speed-third-sample-accepted",
            "zero-with-no-previous-speed-accepted",
            "bool-previous-speed-is-not-numeric",
        ],
    )
    def test_default_zero_transition_contract(
        self,
        speed_mps: float,
        prev_speed: float | None | bool,
        current_streak: int,
        expected: SpeedSampleVerdict,
    ) -> None:
        verdict = evaluate_speed_sample(speed_mps, prev_speed, current_streak)  # type: ignore[arg-type]
        assert verdict == expected

    @pytest.mark.parametrize(
        ("config", "expected"),
        [
            (
                SpeedValidationConfig(zero_confirm_samples=1),
                SpeedSampleVerdict(accepted=True, zero_speed_streak=1),
            ),
            (
                SpeedValidationConfig(zero_drop_prev_threshold_mps=10.0),
                SpeedSampleVerdict(accepted=True, zero_speed_streak=0),
            ),
        ],
        ids=["custom-confirm-samples", "custom-previous-speed-threshold"],
    )
    def test_custom_zero_transition_config(
        self, config: SpeedValidationConfig, expected: SpeedSampleVerdict
    ) -> None:
        verdict = evaluate_speed_sample(0.0, prev_speed=5.0, current_streak=0, config=config)
        assert verdict == expected
