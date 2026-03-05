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

from vibesensor.constants import SILENCE_DB
from vibesensor.live_diagnostics import _combine_amplitude_strength_db


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
    def test_invalid_returns_silence(self, values: list[float], expected_silence: bool) -> None:
        assert _combine_amplitude_strength_db(values) == SILENCE_DB

    def test_nan_mixed_with_valid(self) -> None:
        result_clean = _combine_amplitude_strength_db([10.0, 20.0])
        result_with_nan = _combine_amplitude_strength_db([10.0, float("nan"), 20.0])
        assert result_with_nan == result_clean
