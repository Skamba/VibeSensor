"""Tests for findings module internal helpers: _weighted_percentile, _speed_profile_from_points."""

from __future__ import annotations

import pytest

from vibesensor.analysis.findings import (
    _sensor_intensity_by_location,
    _speed_profile_from_points,
    _weighted_percentile,
)

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

    def test_phase_weights_shorter_than_points_keeps_all_valid_points(self) -> None:
        points = [(80.0, 0.02), (90.0, 0.03), (100.0, 0.09)]
        peak_speed, _band, _label = _speed_profile_from_points(points, phase_weights=[1.0, 1.0])
        assert peak_speed == 100.0

    def test_phase_weights_longer_than_points_ignores_extras(self) -> None:
        points = [(80.0, 0.02), (90.0, 0.09)]
        peak_speed, _band, _label = _speed_profile_from_points(
            points, phase_weights=[1.0, 1.0, 0.1, 0.1]
        )
        assert peak_speed == 90.0

    def test_non_positive_or_invalid_phase_weights_fall_back_to_neutral(self) -> None:
        points = [(80.0, 0.04), (90.0, 0.09)]
        peak_speed, _band, _label = _speed_profile_from_points(
            points, phase_weights=[0.0, float("nan")]
        )
        assert peak_speed == 90.0

    def test_allowed_speed_bins_with_short_phase_weights_still_uses_allowed_points(self) -> None:
        points = [(80.0, 0.02), (95.0, 0.10), (98.0, 0.11)]
        peak_speed, _band, label = _speed_profile_from_points(
            points,
            allowed_speed_bins=["90-100 km/h"],
            phase_weights=[1.0],
        )
        assert peak_speed == 98.0
        assert label == "90-100 km/h"

    def test_empty_allowed_speed_bins_returns_no_profile(self) -> None:
        points = [(80.0, 0.02), (90.0, 0.10)]
        peak_speed, band, label = _speed_profile_from_points(points, allowed_speed_bins=[])
        assert peak_speed is None
        assert band is None
        assert label is None


def test_sensor_counter_deltas_sorted_by_timestamp() -> None:
    samples = [
        {
            "client_name": "front-left",
            "t_s": 10.0,
            "queue_overflow_drops": 9.0,
            "frames_dropped_total": 11.0,
        },
        {
            "client_name": "front-left",
            "t_s": 0.0,
            "queue_overflow_drops": 1.0,
            "frames_dropped_total": 2.0,
        },
        {
            "client_name": "front-left",
            "t_s": 5.0,
            "queue_overflow_drops": 4.0,
            "frames_dropped_total": 7.0,
        },
    ]
    rows = _sensor_intensity_by_location(samples)
    assert len(rows) == 1
    row = rows[0]
    assert row["queue_overflow_drops_delta"] == 8
    assert row["dropped_frames_delta"] == 9


def test_sensor_counter_deltas_without_timestamps_keep_input_order() -> None:
    samples = [
        {"client_name": "front-left", "queue_overflow_drops": 1.0, "frames_dropped_total": 2.0},
        {"client_name": "front-left", "queue_overflow_drops": 4.0, "frames_dropped_total": 7.0},
        {"client_name": "front-left", "queue_overflow_drops": 9.0, "frames_dropped_total": 11.0},
    ]
    rows = _sensor_intensity_by_location(samples)
    assert len(rows) == 1
    row = rows[0]
    assert row["queue_overflow_drops_delta"] == 8
    assert row["dropped_frames_delta"] == 9
