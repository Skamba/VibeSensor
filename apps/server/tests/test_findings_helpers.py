"""Tests for findings module internal helpers: _weighted_percentile, _speed_profile_from_points."""

from __future__ import annotations

import pytest

from vibesensor.report.findings import _speed_profile_from_points, _weighted_percentile

# ---------------------------------------------------------------------------
# _weighted_percentile
# ---------------------------------------------------------------------------


class TestWeightedPercentile:
    def test_empty_returns_none(self) -> None:
        assert _weighted_percentile([], 0.5) is None

    @pytest.mark.smoke
    def test_single_element(self) -> None:
        assert _weighted_percentile([(10.0, 1.0)], 0.5) == 10.0

    def test_median_equal_weights(self) -> None:
        pairs = [(10.0, 1.0), (20.0, 1.0), (30.0, 1.0)]
        result = _weighted_percentile(pairs, 0.5)
        assert result is not None
        assert result == 20.0

    def test_q_zero(self) -> None:
        pairs = [(10.0, 1.0), (20.0, 1.0), (30.0, 1.0)]
        result = _weighted_percentile(pairs, 0.0)
        assert result is not None
        assert result == 10.0

    def test_q_one(self) -> None:
        pairs = [(10.0, 1.0), (20.0, 1.0), (30.0, 1.0)]
        result = _weighted_percentile(pairs, 1.0)
        assert result is not None
        assert result == 30.0

    def test_heavy_weight_pulls_percentile(self) -> None:
        # High weight on 10.0 → median should be pulled toward 10
        pairs = [(10.0, 100.0), (20.0, 1.0), (30.0, 1.0)]
        result = _weighted_percentile(pairs, 0.5)
        assert result is not None
        assert result == 10.0

    def test_zero_weight_entries_ignored(self) -> None:
        pairs = [(10.0, 0.0), (20.0, 1.0), (30.0, 0.0)]
        result = _weighted_percentile(pairs, 0.5)
        assert result == 20.0

    def test_all_zero_weights(self) -> None:
        assert _weighted_percentile([(10.0, 0.0), (20.0, 0.0)], 0.5) is None

    def test_q_clamped_negative(self) -> None:
        result = _weighted_percentile([(10.0, 1.0), (20.0, 1.0)], -0.5)
        assert result == 10.0

    def test_q_clamped_above_one(self) -> None:
        result = _weighted_percentile([(10.0, 1.0), (20.0, 1.0)], 1.5)
        assert result == 20.0

    def test_unsorted_input(self) -> None:
        # Should handle unsorted input correctly (sorts internally)
        pairs = [(30.0, 1.0), (10.0, 1.0), (20.0, 1.0)]
        result = _weighted_percentile(pairs, 0.5)
        assert result == 20.0


# ---------------------------------------------------------------------------
# _speed_profile_from_points
# ---------------------------------------------------------------------------


class TestSpeedProfileFromPoints:
    def test_empty(self) -> None:
        peak_speed, band, label = _speed_profile_from_points([])
        assert peak_speed is None
        assert band is None

    @pytest.mark.smoke
    def test_basic(self) -> None:
        points = [(80.0, 0.06), (90.0, 0.08), (100.0, 0.04)]
        peak_speed, band, label = _speed_profile_from_points(points)
        assert peak_speed is not None
        # Peak speed should be the highest-amplitude speed
        assert peak_speed == 90.0

    def test_zero_speed_filtered(self) -> None:
        points = [(0.0, 0.06), (80.0, 0.08)]
        peak_speed, band, label = _speed_profile_from_points(points)
        assert peak_speed == 80.0

    def test_zero_amp_filtered(self) -> None:
        points = [(80.0, 0.0), (90.0, 0.06)]
        peak_speed, band, label = _speed_profile_from_points(points)
        assert peak_speed == 90.0
