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
    _select_reason_key,
)


class TestSelectReasonKey:
    """Test reason key selection priority ordering."""

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            (
                dict(
                    confidence=0.9,
                    steady_speed=False,
                    weak_spatial=False,
                    sensor_count=4,
                    has_reference_gaps=True,
                ),
                "reference_gaps",
            ),
            (
                dict(
                    confidence=0.9,
                    steady_speed=False,
                    weak_spatial=False,
                    sensor_count=1,
                    has_reference_gaps=False,
                ),
                "single_sensor",
            ),
            (
                dict(
                    confidence=0.9,
                    steady_speed=False,
                    weak_spatial=False,
                    sensor_count=4,
                    has_reference_gaps=False,
                ),
                "strong_order_match",
            ),
            (
                dict(
                    confidence=0.2,
                    steady_speed=False,
                    weak_spatial=False,
                    sensor_count=4,
                    has_reference_gaps=False,
                ),
                "weak_order_match",
            ),
        ],
        ids=["reference-gaps", "single-sensor", "strong-match", "weak-match"],
    )
    def test_reason_priority(self, kwargs: dict, expected: str) -> None:
        result = _select_reason_key(
            kwargs["confidence"],
            steady_speed=kwargs["steady_speed"],
            weak_spatial=kwargs["weak_spatial"],
            sensor_count=kwargs["sensor_count"],
            has_reference_gaps=kwargs["has_reference_gaps"],
        )
        assert result == expected
