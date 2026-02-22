"""Tests for phase_segmentation internal functions and segment_run_phases."""

from __future__ import annotations

import pytest

from vibesensor.report.phase_segmentation import (
    DrivingPhase,
    _classify_sample_phase,
    _estimate_speed_derivative,
    segment_run_phases,
)

# ---------------------------------------------------------------------------
# _estimate_speed_derivative
# ---------------------------------------------------------------------------


class TestEstimateSpeedDerivative:
    def test_steady_speed_derivative_near_zero(self) -> None:
        speeds = [80.0, 80.0, 80.0, 80.0, 80.0]
        times = [0.0, 1.0, 2.0, 3.0, 4.0]
        deriv = _estimate_speed_derivative(speeds, times, 2)
        assert deriv is not None
        assert abs(deriv) < 0.01

    def test_accelerating(self) -> None:
        speeds = [60.0, 65.0, 70.0, 75.0, 80.0]
        times = [0.0, 1.0, 2.0, 3.0, 4.0]
        deriv = _estimate_speed_derivative(speeds, times, 2)
        assert deriv is not None
        assert deriv > 0

    def test_decelerating(self) -> None:
        speeds = [80.0, 75.0, 70.0, 65.0, 60.0]
        times = [0.0, 1.0, 2.0, 3.0, 4.0]
        deriv = _estimate_speed_derivative(speeds, times, 2)
        assert deriv is not None
        assert deriv < 0

    def test_out_of_range_index(self) -> None:
        assert _estimate_speed_derivative([80.0], [0.0], 5) is None
        assert _estimate_speed_derivative([80.0], [0.0], -1) is None

    def test_none_speed_at_neighbors(self) -> None:
        speeds: list[float | None] = [None, 80.0, None]
        times: list[float | None] = [0.0, 1.0, 2.0]
        deriv = _estimate_speed_derivative(speeds, times, 1)
        # No valid neighbors → None
        assert deriv is None

    def test_boundary_index_zero(self) -> None:
        speeds = [60.0, 70.0, 80.0]
        times = [0.0, 1.0, 2.0]
        deriv = _estimate_speed_derivative(speeds, times, 0)
        assert deriv is not None  # one-sided (forward) should work

    def test_boundary_last_index(self) -> None:
        speeds = [60.0, 70.0, 80.0]
        times = [0.0, 1.0, 2.0]
        deriv = _estimate_speed_derivative(speeds, times, 2)
        assert deriv is not None


# ---------------------------------------------------------------------------
# _classify_sample_phase
# ---------------------------------------------------------------------------


class TestClassifySamplePhase:
    def test_idle_zero_speed(self) -> None:
        assert _classify_sample_phase(0.0, 0.0) == DrivingPhase.IDLE

    def test_idle_none_speed(self) -> None:
        assert _classify_sample_phase(None, None) == DrivingPhase.IDLE

    @pytest.mark.smoke
    def test_cruise(self) -> None:
        assert _classify_sample_phase(80.0, 0.0) == DrivingPhase.CRUISE

    def test_acceleration(self) -> None:
        assert _classify_sample_phase(80.0, 5.0) == DrivingPhase.ACCELERATION

    def test_deceleration(self) -> None:
        assert _classify_sample_phase(80.0, -5.0) == DrivingPhase.DECELERATION

    def test_coast_down_low_speed(self) -> None:
        # Low speed + deceleration → coast_down
        assert _classify_sample_phase(10.0, -5.0) == DrivingPhase.COAST_DOWN

    def test_cruise_with_none_derivative(self) -> None:
        # No derivative info → defaults to cruise if speed is above idle threshold
        assert _classify_sample_phase(80.0, None) == DrivingPhase.CRUISE


# ---------------------------------------------------------------------------
# segment_run_phases
# ---------------------------------------------------------------------------


class TestSegmentRunPhases:
    def test_empty_samples(self) -> None:
        phases, segments = segment_run_phases([])
        assert phases == []
        assert segments == []

    def test_single_sample(self) -> None:
        samples = [{"speed_kmh": 80.0, "t_s": 0.0}]
        phases, segments = segment_run_phases(samples)
        assert len(phases) == 1
        assert len(segments) == 1
        assert segments[0].phase == DrivingPhase.CRUISE

    def test_idle_to_cruise_transition(self) -> None:
        samples = [{"speed_kmh": 0.0, "t_s": float(i)} for i in range(5)] + [
            {"speed_kmh": 80.0, "t_s": float(i)} for i in range(5, 10)
        ]
        phases, segments = segment_run_phases(samples)
        assert len(phases) == 10
        # Should have at least idle and cruise segments
        segment_phases = {seg.phase for seg in segments}
        assert DrivingPhase.IDLE in segment_phases

    def test_all_samples_same_phase(self) -> None:
        samples = [{"speed_kmh": 80.0, "t_s": float(i)} for i in range(20)]
        phases, segments = segment_run_phases(samples)
        assert all(p == DrivingPhase.CRUISE for p in phases)
        assert len(segments) == 1
