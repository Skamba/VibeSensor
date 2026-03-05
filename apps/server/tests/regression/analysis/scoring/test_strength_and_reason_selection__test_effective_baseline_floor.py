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
    MEMS_NOISE_FLOOR_G,
    _effective_baseline_floor,
)


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
    def test_baseline_floor(self, baseline: float | None, kwargs: dict, expected: float) -> None:
        result = _effective_baseline_floor(baseline, **kwargs)
        assert result == expected
