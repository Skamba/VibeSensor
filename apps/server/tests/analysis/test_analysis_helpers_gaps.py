"""Unit tests for under-tested helpers in vibesensor.analysis.helpers.

Covers:
- weak_spatial_dominance_threshold (adaptive dominance ratio)
- _amplitude_weighted_speed_window (dominant-bin speed finder)

Neither function had a direct unit test; they were only exercised
indirectly through the full analysis pipeline.
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.helpers import (
    WEAK_SPATIAL_DOMINANCE_THRESHOLD,
    _amplitude_weighted_speed_window,
    weak_spatial_dominance_threshold,
)

# ---------------------------------------------------------------------------
# weak_spatial_dominance_threshold
# ---------------------------------------------------------------------------


class TestWeakSpatialDominanceThreshold:
    """Adaptive dominance threshold for weak spatial separation."""

    def test_returns_baseline_for_none(self) -> None:
        """None location count falls back to the global baseline constant."""
        result = weak_spatial_dominance_threshold(None)
        assert result == WEAK_SPATIAL_DOMINANCE_THRESHOLD

    def test_returns_baseline_for_two_locations(self) -> None:
        """Two locations is the canonical baseline case — no extra scaling."""
        result = weak_spatial_dominance_threshold(2)
        assert result == pytest.approx(WEAK_SPATIAL_DOMINANCE_THRESHOLD)

    def test_scales_up_per_additional_location(self) -> None:
        """Each extra sensor beyond 2 adds 10% of the baseline."""
        baseline = WEAK_SPATIAL_DOMINANCE_THRESHOLD
        result_3 = weak_spatial_dominance_threshold(3)
        result_4 = weak_spatial_dominance_threshold(4)
        assert result_3 == pytest.approx(baseline * 1.1, rel=1e-6)
        assert result_4 == pytest.approx(baseline * 1.2, rel=1e-6)

    def test_clamps_to_minimum_of_two_for_one_or_zero(self) -> None:
        """Fewer than 2 sensors are clamped to 2 to avoid under-threshold."""
        result_one = weak_spatial_dominance_threshold(1)
        result_zero = weak_spatial_dominance_threshold(0)
        baseline = WEAK_SPATIAL_DOMINANCE_THRESHOLD
        assert result_one == pytest.approx(baseline)
        assert result_zero == pytest.approx(baseline)

    def test_monotonically_increasing_with_location_count(self) -> None:
        """More sensors → higher threshold (stricter spatial separation)."""
        thresholds = [weak_spatial_dominance_threshold(n) for n in range(2, 8)]
        for low, high in zip(thresholds, thresholds[1:], strict=False):
            assert high > low, f"Expected monotonic increase but {high} <= {low}"


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
