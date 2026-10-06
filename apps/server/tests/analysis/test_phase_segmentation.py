"""Tests for phase_segmentation internal functions and segment_run_phases."""

from __future__ import annotations

import math
import random

import pytest

from vibesensor.analysis.phase_segmentation import (
    DrivingPhase,
    TimeSpanLookup,
    classify_sample_phase,
    diagnostic_sample_mask,
    segment_run_phases,
    speed_slopes_kmh_s,
)
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings


def _typed(samples: list[dict]) -> list:
    return sensor_frames_from_mappings(samples)


def _drive(
    profile: list[tuple[float, float, float]],
    *,
    step_s: float = 0.25,
    sensors: int = 1,
    gps_hz: float | None = None,
) -> list:
    """Rows every *step_s* through ``(duration_s, start_kmh, end_kmh)`` legs.

    Each moment has one row per sensor (same timestamp). With *gps_hz* the speed
    is held between fixes, as a GPS or OBD-II staircase.
    """
    rows: list[dict] = []
    t_s = 0.0
    for duration_s, start_kmh, end_kmh in profile:
        steps = round(duration_s / step_s)
        for i in range(steps):
            frac = i / steps
            fix_t = t_s + i * step_s
            if gps_hz is not None:
                frac = (int(i * step_s * gps_hz) / gps_hz) / duration_s
            speed = start_kmh + (end_kmh - start_kmh) * frac
            rows.extend({"speed_kmh": speed, "t_s": fix_t} for _ in range(sensors))
        t_s += duration_s
    return _typed(rows)


def _braking_seconds(samples: list) -> float:
    phases, segments = segment_run_phases(samples)
    return sum(seg.end_t_s - seg.start_t_s for seg in segments if seg.phase is DrivingPhase.BRAKING)


# ---------------------------------------------------------------------------
# speed_slopes_kmh_s
# ---------------------------------------------------------------------------


class TestSpeedSlopes:
    @pytest.mark.parametrize(
        ("speeds", "sign"),
        [
            pytest.param([80.0] * 9, 0, id="steady"),
            pytest.param([60.0 + 2.0 * i for i in range(9)], 1, id="accelerating"),
            pytest.param([80.0 - 2.0 * i for i in range(9)], -1, id="decelerating"),
            # At the top of a speed peak the car is not accelerating.
            pytest.param([50.0, 52.0, 54.0, 56.0, 58.0, 56.0, 54.0, 52.0, 50.0], 0, id="peak"),
        ],
    )
    def test_slope_sign_at_centre(self, speeds: list[float], sign: int) -> None:
        series = [(0.5 * i, speed) for i, speed in enumerate(speeds)]
        slope = speed_slopes_kmh_s(series)[4]
        assert slope is not None
        assert slope == pytest.approx(0.0, abs=0.01) if sign == 0 else slope * sign > 0

    def test_too_few_readings_have_no_slope(self) -> None:
        assert speed_slopes_kmh_s([(0.0, 80.0), (0.5, 82.0)]) == [None, None]

    def test_rows_sharing_a_timestamp_still_give_a_slope(self) -> None:
        """Four sensors report at the same moment: the slope is taken over time, not rows."""
        samples = _drive([(10.0, 120.0, 90.0)], sensors=4)
        phases, _segments = segment_run_phases(samples)
        middle = phases[len(phases) // 3 : 2 * len(phases) // 3]
        assert set(middle) == {DrivingPhase.DECELERATION}


# ---------------------------------------------------------------------------
# Braking
# ---------------------------------------------------------------------------


class TestBraking:
    def test_firm_stop_is_braking(self) -> None:
        # 120 -> 40 km/h in 6 s sheds 0.38 g.
        samples = _drive([(10.0, 120.0, 120.0), (6.0, 120.0, 40.0), (10.0, 40.0, 40.0)])
        assert 5.0 <= _braking_seconds(samples) <= 6.5

    def test_coasting_is_not_braking(self) -> None:
        # Lifting off at motorway speed: 120 -> 90 km/h in 10 s is 0.085 g.
        samples = _drive([(10.0, 120.0, 120.0), (10.0, 120.0, 90.0), (10.0, 90.0, 90.0)])
        phases, _segments = segment_run_phases(samples)
        assert DrivingPhase.BRAKING not in phases
        assert DrivingPhase.DECELERATION in phases

    def test_engine_braking_just_under_the_threshold_is_not_braking(self) -> None:
        # 0.18 g sustained (6.4 km/h per second) is still a lift-off in a low gear.
        samples = _drive([(5.0, 90.0, 90.0), (5.0, 90.0, 58.0), (5.0, 58.0, 58.0)])
        assert _braking_seconds(samples) == 0.0

    def test_one_hz_gps_staircase_from_four_sensors_is_braking(self) -> None:
        samples = _drive(
            [(10.0, 110.0, 110.0), (8.0, 110.0, 30.0), (10.0, 30.0, 30.0)],
            sensors=4,
            gps_hz=1.0,
        )
        assert _braking_seconds(samples) >= 6.0

    def test_a_speed_jump_is_not_braking(self) -> None:
        """A reading that drops 25 km/h at once (a GPS glitch) is not a stop."""
        samples = _drive([(10.0, 115.0, 115.0), (10.0, 90.0, 90.0)])
        assert _braking_seconds(samples) == 0.0

    def test_a_short_dab_is_not_braking(self) -> None:
        # 2 s at 0.4 g: shorter than one spectrum.
        samples = _drive([(10.0, 100.0, 100.0), (2.0, 100.0, 72.0), (10.0, 72.0, 72.0)])
        assert _braking_seconds(samples) == 0.0

    def test_braking_below_coast_down_speed_is_a_coast_down(self) -> None:
        samples = _drive([(5.0, 14.0, 14.0), (3.0, 14.0, 4.0), (5.0, 4.0, 4.0)])
        phases, _segments = segment_run_phases(samples)
        assert DrivingPhase.BRAKING not in phases


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

    def test_braking_spell(self) -> None:
        assert classify_sample_phase(80.0, -12.0, braking=True) == DrivingPhase.BRAKING


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


@pytest.mark.parametrize("seed", range(20))
def test_span_lookup_agrees_with_checking_every_span(seed: int) -> None:
    # Sorted, overlapping, nested, touching, empty, reversed and NaN-bounded spans.
    rng = random.Random(seed)
    spans: list[tuple[float, float]] = []
    for _ in range(rng.randint(0, 40)):
        start = rng.choice((rng.uniform(0.0, 100.0), float(rng.randint(0, 100)), math.nan))
        end = rng.choice((start + rng.uniform(-5.0, 20.0), start, math.nan, math.inf))
        spans.append((start, end))
    lookup = TimeSpanLookup(spans)
    times = [None, math.nan, -math.inf, math.inf, *(rng.uniform(-5.0, 125.0) for _ in range(200))]
    times += [bound for span in spans for bound in span]

    for t_s in times:
        expected = t_s is not None and any(start <= t_s <= end for start, end in spans)
        assert lookup(t_s) is expected, (t_s, spans)
