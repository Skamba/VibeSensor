"""Strength labeling and confidence assessment regressions.

Covers:
  1. strength_labels.strength_label — NaN guard returns "unknown"
  2. ConfidenceAssessment.assess — NaN confidence clamped to 0.0
  3. Tests for previously-untested helpers
"""

from __future__ import annotations

import pytest

from vibesensor.analysis._sample_metrics import _effective_baseline_floor
from vibesensor.analysis._validation import _validate_required_strength_metrics
from vibesensor.analysis.constants import MEMS_NOISE_FLOOR_G
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings

# ------------------------------------------------------------------
# 1. strength_label — NaN guard
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# 3. ConfidenceAssessment — NaN confidence guard
# ------------------------------------------------------------------


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
