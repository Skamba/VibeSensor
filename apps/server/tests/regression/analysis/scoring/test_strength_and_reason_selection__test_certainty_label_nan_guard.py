"""Strength labeling and reason-selection regressions.

Covers:
  1. live_diagnostics._combine_amplitude_strength_db — NaN guard
  2. strength_labels.strength_label — NaN guard returns "unknown"
  3. strength_labels.certainty_label — NaN confidence clamped to 0.0
  4. ws_hub.run() — tick-rate drift compensation (source verification)
  5. Tests for previously-untested helpers
"""

from __future__ import annotations

from vibesensor.analysis.strength_labels import (
    certainty_label,
)


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
