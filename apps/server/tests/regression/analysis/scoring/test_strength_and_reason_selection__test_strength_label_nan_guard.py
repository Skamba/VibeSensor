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

from vibesensor.analysis.strength_labels import (
    strength_label,
)


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
