"""How the car's attitude turns a firm sensor's 0 Hz reading (the bench sees only the sum)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from vibesensor.simulator.body_attitude import AttitudeCar, SensorAttitude

_FS = 800
_FRAME = 200
_G = 9.80665


def _settled_g(
    name: str, *, speed_kmh: float = 50.0, accel_mps2: float = 0.0, curvature_1pm: float = 0.0
) -> np.ndarray:
    """The reading (g) once the car has settled into a state, with the sensor fixed level."""
    attitude = SensorAttitude.for_sensor(name, np.random.default_rng(0))
    attitude.mounting = np.eye(3)
    for _ in range(40):
        counts = attitude.frame_counts(
            speed_kmh=speed_kmh,
            accel_mps2=accel_mps2,
            curvature_1pm=curvature_1pm,
            grade_pct=0.0,
            samples=_FRAME,
            dt=1.0 / _FS,
        )
    return counts[-1] / np.linalg.norm(counts[-1])


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    return math.degrees(math.acos(float(np.clip(a @ b, -1.0, 1.0))))


def test_braking_pitches_the_body_but_not_the_wheel_carrier() -> None:
    braking = -0.4 * _G
    trunk = _settled_g("trunk", accel_mps2=braking)
    knuckle = _settled_g("rear_left_wheel", accel_mps2=braking)

    # The knuckle stays with the road: it reads the deceleration and gravity alone.
    assert _angle_deg(knuckle, np.array([0.0, 0.0, 1.0])) == pytest.approx(
        math.degrees(math.atan(0.4)), abs=0.05
    )
    # The body dives on its springs on top of that, by its pitch gradient.
    pitch_deg = AttitudeCar().pitch_deg_per_g * 0.4
    assert _angle_deg(trunk, knuckle) == pytest.approx(pitch_deg, abs=0.05)


def test_steering_tilts_a_front_wheel_carrier_about_its_kingpin_but_not_a_rear_one() -> None:
    # At a crawl on full-ish lock (10 m radius) the car barely accelerates sideways.
    front = _settled_g("front_left_wheel", speed_kmh=0.0, curvature_1pm=0.1)
    rear = _settled_g("rear_left_wheel", speed_kmh=0.0, curvature_1pm=0.1)
    up = np.array([0.0, 0.0, 1.0])

    assert _angle_deg(rear, up) < 0.01
    # A 15 deg steer about an axis leaning 14 deg from vertical tilts the carrier ~3.7 deg.
    assert 3.0 < _angle_deg(front, up) < 4.5
