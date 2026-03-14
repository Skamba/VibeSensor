"""Unit tests for under-tested helpers in vibesensor.analysis.helpers.

Covers:
- _amplitude_weighted_speed_window (dominant-bin speed finder)

The weak-spatial threshold rule now lives on LocationHotspot and is
tested in the domain value-object suite.
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.helpers import _amplitude_weighted_speed_window

# ---------------------------------------------------------------------------
# _amplitude_weighted_speed_window
# ---------------------------------------------------------------------------


class TestAmplitudeWeightedSpeedWindow:
    """Dominant amplitude-weighted speed bin finder."""

    def test_empty_inputs_return_none_tuple(self) -> None:
        """No data → (None, None), not an error."""
        result = _amplitude_weighted_speed_window([], [])
        assert result == (None, None)

    def test_all_zero_speeds_return_none_tuple(self) -> None:
        """Zero/negative speeds are invalid and should be skipped entirely."""
        result = _amplitude_weighted_speed_window([0.0, -5.0], [1.0, 2.0])
        assert result == (None, None)

    def test_all_zero_amplitudes_return_none_tuple(self) -> None:
        """Zero amplitude observations carry no weight and must be skipped."""
        result = _amplitude_weighted_speed_window([50.0, 60.0], [0.0, 0.0])
        assert result == (None, None)

    def test_finds_dominant_bin(self) -> None:
        """Heavy observations in 50-60 km/h bin should win."""
        # 3 observations near 55 km/h with large amplitude vs 1 near 80 km/h
        speeds = [52.0, 54.0, 57.0, 82.0]
        amps = [10.0, 10.0, 10.0, 5.0]
        low, high = _amplitude_weighted_speed_window(speeds, amps)
        assert low is not None and high is not None
        assert low == pytest.approx(50.0)
        assert high == pytest.approx(60.0)

    def test_bin_width_is_ten_kmh(self) -> None:
        """Result window should always span exactly 10 km/h."""
        speeds = [75.0, 76.0]
        amps = [1.0, 1.0]
        low, high = _amplitude_weighted_speed_window(speeds, amps)
        assert low is not None and high is not None
        assert high - low == pytest.approx(10.0)

    def test_high_amplitude_single_point_wins(self) -> None:
        """A single observation with high amplitude should dominate."""
        speeds = [30.0, 90.0]
        amps = [1.0, 100.0]
        low, high = _amplitude_weighted_speed_window(speeds, amps)
        assert low is not None
        assert low == pytest.approx(90.0)
        assert high == pytest.approx(100.0)
