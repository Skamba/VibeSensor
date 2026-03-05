"""Strength labeling and reason-selection regressions.

Covers:
  1. live_diagnostics._combine_amplitude_strength_db — NaN guard
  2. strength_labels.strength_label — NaN guard returns "unknown"
  3. strength_labels.certainty_label — NaN confidence clamped to 0.0
  4. ws_hub.run() — tick-rate drift compensation (source verification)
  5. Tests for previously-untested helpers
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.helpers import (
    _validate_required_strength_metrics,
)


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
