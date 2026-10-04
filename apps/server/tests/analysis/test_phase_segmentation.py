"""Tests for phase_segmentation internal functions and segment_run_phases."""

from __future__ import annotations

import pytest

from vibesensor.analysis.phase_segmentation import (
    DrivingPhase,
    _estimate_speed_derivative,
    classify_sample_phase,
    diagnostic_sample_mask,
    segment_run_phases,
)
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings


def _typed(samples: list[dict]) -> list:
    return sensor_frames_from_mappings(samples)


# ---------------------------------------------------------------------------
# _estimate_speed_derivative
# ---------------------------------------------------------------------------


class TestEstimateSpeedDerivative:
    @pytest.mark.parametrize(
        ("speeds", "index", "sign"),
        [
            pytest.param([80.0, 80.0, 80.0, 80.0, 80.0], 2, 0, id="steady-near-zero"),
            pytest.param([60.0, 65.0, 70.0, 75.0, 80.0], 2, 1, id="accelerating"),
            pytest.param([80.0, 75.0, 70.0, 65.0, 60.0], 2, -1, id="decelerating"),
            # Central difference: at the top of a speed peak the car is not accelerating.
            pytest.param([50.0, 54.0, 56.0, 54.0, 50.0], 2, 0, id="speed-peak-is-level"),
            pytest.param([60.0, 70.0, 80.0], 0, 1, id="first-index-forward-difference"),
            pytest.param([60.0, 70.0, 80.0], 2, 1, id="last-index-backward-difference"),
        ],
    )
    def test_derivative_sign(self, speeds: list[float], index: int, sign: int) -> None:
        times = [float(i) for i in range(len(speeds))]
        deriv = _estimate_speed_derivative(speeds, times, index)
        assert deriv is not None
        if sign == 0:
            assert abs(deriv) < 0.01
        else:
            assert deriv * sign > 0

    @pytest.mark.parametrize(
        ("speeds", "times", "index"),
        [
            pytest.param([80.0], [0.0], 5, id="index-past-end"),
            pytest.param([80.0], [0.0], -1, id="negative-index"),
            pytest.param([None, 80.0, None], [0.0, 1.0, 2.0], 1, id="no-valid-neighbors"),
        ],
    )
    def test_derivative_unavailable(
        self, speeds: list[float | None], times: list[float | None], index: int
    ) -> None:
        assert _estimate_speed_derivative(speeds, times, index) is None


# ---------------------------------------------------------------------------
# classify_sample_phase
# ---------------------------------------------------------------------------


class TestClassifySamplePhase:
    @pytest.mark.parametrize(
        ("speed", "deriv", "expected"),
        [
            pytest.param(0.0, 0.0, DrivingPhase.IDLE, id="idle_zero_speed"),
            pytest.param(None, None, DrivingPhase.SPEED_UNKNOWN, id="none_speed_is_unknown"),
            pytest.param(80.0, 0.0, DrivingPhase.CRUISE, id="cruise", marks=pytest.mark.smoke),
            pytest.param(80.0, 5.0, DrivingPhase.ACCELERATION, id="acceleration"),
            pytest.param(80.0, -5.0, DrivingPhase.DECELERATION, id="deceleration"),
            pytest.param(10.0, -5.0, DrivingPhase.COAST_DOWN, id="coast_down_low_speed"),
            pytest.param(80.0, None, DrivingPhase.CRUISE, id="cruise_none_derivative"),
        ],
    )
    def test_classify(
        self,
        speed: float | None,
        deriv: float | None,
        expected: DrivingPhase,
    ) -> None:
        assert classify_sample_phase(speed, deriv) == expected


# ---------------------------------------------------------------------------
# segment_run_phases
# ---------------------------------------------------------------------------


class TestSegmentRunPhases:
    def test_gps_dropout_mid_cruise_interpolated_to_cruise(self) -> None:
        """GPS dropout in the middle of a highway cruise → interpolated to CRUISE, not IDLE."""
        samples = (
            [{"speed_kmh": 120.0, "t_s": float(i)} for i in range(5)]
            + [{"speed_kmh": None, "t_s": float(i)} for i in range(5, 15)]  # 10s GPS dropout
            + [{"speed_kmh": 120.0, "t_s": float(i)} for i in range(15, 20)]
        )
        phases, segments = segment_run_phases(_typed(samples))
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
        phases, _ = segment_run_phases(_typed(samples))
        # Leading unknown-speed samples should be assigned the neighbouring CRUISE phase
        for i in range(3):
            assert phases[i] != DrivingPhase.IDLE


# ---------------------------------------------------------------------------
# _interpolate_speed_unknown
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# diagnostic_sample_mask — GPS dropout inclusion
# ---------------------------------------------------------------------------


class TestDiagnosticSampleMaskGpsDropout:
    def test_idle_still_excluded(self) -> None:
        """IDLE samples should still be excluded by default."""
        phases = [DrivingPhase.IDLE, DrivingPhase.CRUISE, DrivingPhase.IDLE]
        mask = diagnostic_sample_mask(phases)
        assert mask == [False, True, False]


# ---------------------------------------------------------------------------
# phase_summary (integration: DrivingPhaseSegment population)
# ---------------------------------------------------------------------------
