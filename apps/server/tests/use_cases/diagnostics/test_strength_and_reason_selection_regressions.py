"""Strength labeling and confidence assessment regressions.

Covers:
  1. strength_labels.strength_label — NaN guard returns "unknown"
  2. ConfidenceAssessment.assess — NaN confidence clamped to 0.0
  3. ws_hub.run() — tick-rate drift compensation (source verification)
  4. Tests for previously-untested helpers
"""

from __future__ import annotations

import pytest

from vibesensor.domain.confidence_assessment import ConfidenceAssessment
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.constants.analysis import MEMS_NOISE_FLOOR_G
from vibesensor.shared.report_presentation import strength_label
from vibesensor.use_cases.diagnostics._sample_metrics import _effective_baseline_floor
from vibesensor.use_cases.diagnostics._validation import _validate_required_strength_metrics

# ------------------------------------------------------------------
# 1. strength_label — NaN guard
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
        assert label == "Unknown"

    def test_valid_db_returns_band(self) -> None:
        key, _label = strength_label(15.0)
        assert key != "unknown"


# ------------------------------------------------------------------
# 3. ConfidenceAssessment — NaN confidence guard
# ------------------------------------------------------------------


class TestConfidenceAssessmentNanGuard:
    """NaN confidence must be clamped to 0, producing CONFIDENCE_LOW + '0%'."""

    def test_nan_confidence_returns_low(self) -> None:
        ca = ConfidenceAssessment.assess(
            float("nan"),
            strength_band_key="moderate",
        )
        assert ca.label_key == "CONFIDENCE_LOW"
        assert ca.pct_text == "0%"

    def test_normal_confidence(self) -> None:
        ca = ConfidenceAssessment.assess(
            0.85,
            strength_band_key="moderate",
        )
        assert ca.label_key == "CONFIDENCE_HIGH"
        assert ca.pct_text == "85%"


# ------------------------------------------------------------------
# 5. _effective_baseline_floor — edge cases
# ------------------------------------------------------------------


class TestEffectiveBaselineFloor:
    """Test the baseline floor helper for edge cases."""

    @pytest.mark.parametrize(
        ("baseline", "kwargs", "expected"),
        [
            (None, {}, MEMS_NOISE_FLOOR_G),
            (0.0, {"extra_fallback": 0.005}, MEMS_NOISE_FLOOR_G),
            (-0.5, {}, MEMS_NOISE_FLOOR_G),
            (0.01, {}, 0.01),
        ],
        ids=["none", "zero-clamped", "negative-clamped", "valid"],
    )
    def test_baseline_floor(self, baseline: float | None, kwargs: dict, expected: float) -> None:
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
        _validate_required_strength_metrics(
            sensor_frames_from_mappings(samples),
        )  # should not raise

    def test_all_missing_raises(self) -> None:
        samples = [{"other_field": 1}, {"other_field": 2}]
        with pytest.raises(ValueError, match="vibration_strength_db"):
            _validate_required_strength_metrics(sensor_frames_from_mappings(samples))
