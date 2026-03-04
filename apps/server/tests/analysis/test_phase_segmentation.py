"""Tests for phase_segmentation internal functions and segment_run_phases."""

from __future__ import annotations

import pytest

from vibesensor.analysis.phase_segmentation import (
    DrivingPhase,
    _estimate_speed_derivative,
    _interpolate_speed_unknown,
    classify_sample_phase,
    diagnostic_sample_mask,
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
# classify_sample_phase
# ---------------------------------------------------------------------------


class TestClassifySamplePhase:
    def test_idle_zero_speed(self) -> None:
        assert classify_sample_phase(0.0, 0.0) == DrivingPhase.IDLE

    def test_idle_none_speed(self) -> None:
        # None speed → SPEED_UNKNOWN (not IDLE), see issue #287
        assert classify_sample_phase(None, None) == DrivingPhase.SPEED_UNKNOWN

    @pytest.mark.smoke
    def test_cruise(self) -> None:
        assert classify_sample_phase(80.0, 0.0) == DrivingPhase.CRUISE

    def test_acceleration(self) -> None:
        assert classify_sample_phase(80.0, 5.0) == DrivingPhase.ACCELERATION

    def test_deceleration(self) -> None:
        assert classify_sample_phase(80.0, -5.0) == DrivingPhase.DECELERATION

    def test_coast_down_low_speed(self) -> None:
        # Low speed + deceleration → coast_down
        assert classify_sample_phase(10.0, -5.0) == DrivingPhase.COAST_DOWN

    def test_cruise_with_none_derivative(self) -> None:
        # No derivative info → defaults to cruise if speed is above idle threshold
        assert classify_sample_phase(80.0, None) == DrivingPhase.CRUISE


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

    def test_gps_dropout_mid_cruise_interpolated_to_cruise(self) -> None:
        """GPS dropout in the middle of a highway cruise → interpolated to CRUISE, not IDLE."""
        samples = (
            [{"speed_kmh": 120.0, "t_s": float(i)} for i in range(5)]
            + [{"speed_kmh": None, "t_s": float(i)} for i in range(5, 15)]  # 10s GPS dropout
            + [{"speed_kmh": 120.0, "t_s": float(i)} for i in range(15, 20)]
        )
        phases, segments = segment_run_phases(samples)
        assert len(phases) == 20
        # All dropout samples should be interpolated to CRUISE (surrounded by CRUISE)
        for i in range(5, 15):
            assert phases[i] != DrivingPhase.IDLE, (
                f"Sample {i} should not be IDLE during GPS dropout"
            )
            assert phases[i] == DrivingPhase.CRUISE, f"Sample {i} should be CRUISE (interpolated)"
        # No IDLE segments at all
        assert all(seg.phase != DrivingPhase.IDLE for seg in segments)

    def test_gps_dropout_at_run_start_with_cruise_after(self) -> None:
        """GPS dropout at run start followed by cruise → interpolated to neighbour phase."""
        samples = [{"speed_kmh": None, "t_s": float(i)} for i in range(3)] + [
            {"speed_kmh": 80.0, "t_s": float(i)} for i in range(3, 10)
        ]
        phases, _ = segment_run_phases(samples)
        # Leading unknown-speed samples should be assigned the neighbouring CRUISE phase
        for i in range(3):
            assert phases[i] != DrivingPhase.IDLE

    def test_gps_dropout_at_run_end_with_cruise_before(self) -> None:
        """GPS dropout at run end preceded by cruise → interpolated to neighbour phase."""
        samples = [{"speed_kmh": 80.0, "t_s": float(i)} for i in range(7)] + [
            {"speed_kmh": None, "t_s": float(i)} for i in range(7, 10)
        ]
        phases, _ = segment_run_phases(samples)
        # Trailing unknown-speed samples should keep the moving phase
        for i in range(7, 10):
            assert phases[i] != DrivingPhase.IDLE

    def test_gps_dropout_between_idle_stays_speed_unknown(self) -> None:
        """GPS dropout surrounded by IDLE stays SPEED_UNKNOWN (not misclassified as IDLE)."""
        samples = (
            [{"speed_kmh": 0.0, "t_s": float(i)} for i in range(3)]
            + [{"speed_kmh": None, "t_s": float(i)} for i in range(3, 6)]
            + [{"speed_kmh": 0.0, "t_s": float(i)} for i in range(6, 10)]
        )
        phases, _ = segment_run_phases(samples)
        # Surrounded by IDLE → stays SPEED_UNKNOWN (not interpolated to a moving phase)
        for i in range(3, 6):
            assert phases[i] == DrivingPhase.SPEED_UNKNOWN

    def test_all_none_speeds(self) -> None:
        """All samples have None speed → all SPEED_UNKNOWN."""
        samples = [{"speed_kmh": None, "t_s": float(i)} for i in range(5)]
        phases, _ = segment_run_phases(samples)
        assert all(p == DrivingPhase.SPEED_UNKNOWN for p in phases)


# ---------------------------------------------------------------------------
# _interpolate_speed_unknown
# ---------------------------------------------------------------------------


class TestInterpolateSpeedUnknown:
    def test_gap_between_cruise_becomes_cruise(self) -> None:
        phases = [
            DrivingPhase.CRUISE,
            DrivingPhase.SPEED_UNKNOWN,
            DrivingPhase.SPEED_UNKNOWN,
            DrivingPhase.CRUISE,
        ]
        _interpolate_speed_unknown(phases)
        assert phases == [DrivingPhase.CRUISE] * 4

    def test_gap_between_different_moving_phases_becomes_cruise(self) -> None:
        phases = [DrivingPhase.ACCELERATION, DrivingPhase.SPEED_UNKNOWN, DrivingPhase.DECELERATION]
        _interpolate_speed_unknown(phases)
        assert phases[1] == DrivingPhase.CRUISE

    def test_gap_between_idle_stays_unknown(self) -> None:
        phases = [DrivingPhase.IDLE, DrivingPhase.SPEED_UNKNOWN, DrivingPhase.IDLE]
        _interpolate_speed_unknown(phases)
        assert phases[1] == DrivingPhase.SPEED_UNKNOWN

    def test_gap_at_start_with_moving_after(self) -> None:
        phases = [DrivingPhase.SPEED_UNKNOWN, DrivingPhase.SPEED_UNKNOWN, DrivingPhase.CRUISE]
        _interpolate_speed_unknown(phases)
        assert phases[0] == DrivingPhase.CRUISE
        assert phases[1] == DrivingPhase.CRUISE

    def test_gap_at_end_with_moving_before(self) -> None:
        phases = [DrivingPhase.ACCELERATION, DrivingPhase.SPEED_UNKNOWN]
        _interpolate_speed_unknown(phases)
        assert phases[1] == DrivingPhase.ACCELERATION

    def test_empty_list(self) -> None:
        phases: list[DrivingPhase] = []
        _interpolate_speed_unknown(phases)
        assert phases == []

    def test_no_unknowns(self) -> None:
        phases = [DrivingPhase.CRUISE, DrivingPhase.IDLE, DrivingPhase.CRUISE]
        _interpolate_speed_unknown(phases)
        assert phases == [DrivingPhase.CRUISE, DrivingPhase.IDLE, DrivingPhase.CRUISE]


# ---------------------------------------------------------------------------
# diagnostic_sample_mask — GPS dropout inclusion
# ---------------------------------------------------------------------------


class TestDiagnosticSampleMaskGpsDropout:
    def test_speed_unknown_not_excluded(self) -> None:
        """SPEED_UNKNOWN samples must NOT be excluded from diagnostics (issue #287)."""
        phases = [
            DrivingPhase.CRUISE,
            DrivingPhase.SPEED_UNKNOWN,
            DrivingPhase.SPEED_UNKNOWN,
            DrivingPhase.CRUISE,
        ]
        mask = diagnostic_sample_mask(phases)
        # All should be included
        assert mask == [True, True, True, True]

    def test_idle_still_excluded(self) -> None:
        """IDLE samples should still be excluded by default."""
        phases = [DrivingPhase.IDLE, DrivingPhase.CRUISE, DrivingPhase.IDLE]
        mask = diagnostic_sample_mask(phases)
        assert mask == [False, True, False]

    def test_gps_dropout_highway_run_preserves_diagnostic_data(self) -> None:
        """Simulate a highway run with a 10s GPS dropout — all data preserved for analysis."""
        phases = (
            [DrivingPhase.CRUISE] * 50
            + [DrivingPhase.SPEED_UNKNOWN] * 10  # GPS dropout
            + [DrivingPhase.CRUISE] * 50
        )
        mask = diagnostic_sample_mask(phases)
        # All 110 samples should be included (nothing is IDLE)
        assert all(mask)
        assert sum(mask) == 110
