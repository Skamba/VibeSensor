"""The simulated car's wheel speeds against the sources its physics comes from."""

from __future__ import annotations

import math
import random
from dataclasses import replace

import pytest

from vibesensor.simulator.wheel_kinematics import DriveState, SimCar, SimTire

_CAR = SimCar.square(225.0, 45.0, 18.0, final_drive_ratio=3.2, top_gear_ratio=0.7)
_NO_SLIP = DriveState(1.0)


def _ground_hz(car: SimCar, speed_kmh: float) -> float:
    """Turns per second of a new tire at its ETRTO rolling circumference."""
    diameter_m = car.tires[0].new_diameter_m
    return speed_kmh / 3.6 / (3.05 * diameter_m)


def test_new_tires_roll_at_the_etrto_circumference_and_wear_or_soft_ones_turn_faster() -> None:
    cruise = DriveState(100.0)
    # Cruising, the rear (driven) wheels slip a fraction of a percent; the front roll freely.
    assert _CAR.wheel_hz("front-left", cruise) == pytest.approx(_ground_hz(_CAR, 100.0), rel=1e-3)
    rear_slip = _CAR.wheel_hz("rear-left", cruise) / _ground_hz(_CAR, 100.0) - 1.0
    assert 0.001 < rear_slip < 0.006

    new = _CAR.tires[0]
    worn = replace(new, tread_worn_mm=6.0)
    soft = replace(new, pressure_kpa=170.0)
    car = replace(_CAR, tires=(new, worn, soft, new), driven_axle="all")
    front_left, front_right, rear_left, _ = car.wheel_hz_all(cruise)
    # 6 mm of tread off a 0.32 m radius: about 1.9 % faster.
    assert front_right / front_left - 1.0 == pytest.approx(6.0 / 1000 / 0.3184, rel=0.05)
    # 70 kPa under pressure: a few millimetres more deflection, a few tenths of a percent.
    rear_left_new = _CAR.wheel_hz("rear-left", cruise)
    assert 0.001 < rear_left / rear_left_new - 1.0 < 0.01


@pytest.mark.parametrize(
    ("driven_axle", "driven", "free"),
    [("front", "front-left", "rear-left"), ("rear", "rear-left", "front-left")],
)
def test_pulling_hard_slips_only_the_driven_wheels_and_braking_slips_every_wheel_back(
    driven_axle: str, driven: str, free: str
) -> None:
    car = replace(_CAR, driven_axle=driven_axle)
    ground = _ground_hz(car, 80.0)
    pulling = DriveState(80.0, accel_mps2=3.0)
    # 0.3 g on one axle of a 1.6 t car: a few percent of slip (Magic Formula stiffness).
    assert 0.02 < car.wheel_hz(driven, pulling) / ground - 1.0 < 0.06
    assert abs(car.wheel_hz(free, pulling) / ground - 1.0) < 0.003
    braking = DriveState(80.0, accel_mps2=-4.0)
    front, _, rear, _ = car.wheel_hz_all(braking)
    assert front / ground - 1.0 < rear / ground - 1.0 < -0.005
    # The driveshaft turns with the driven wheels' mean times the final drive.
    assert car.shaft_hz(pulling) == pytest.approx(car.wheel_hz(driven, pulling) * 3.2)


def test_through_a_bend_the_outer_wheels_run_faster_by_half_the_track_over_the_radius() -> None:
    radius_m = 150.0
    left_turn = DriveState(60.0, curvature_1pm=1.0 / radius_m)
    front_left, front_right, rear_left, rear_right = _CAR.wheel_hz_all(left_turn)
    straight = _CAR.wheel_hz_all(DriveState(60.0))
    spread = _CAR.track_m / 2.0 / radius_m
    # On top of the path, the load the bend moves outwards squats the outer
    # tires a little and lifts the inner ones: a few tenths of a percent more.
    assert front_left / straight[0] - 1.0 == pytest.approx(-spread, abs=0.003)
    assert front_right / straight[1] - 1.0 == pytest.approx(spread, abs=0.003)
    assert front_right / front_left - 1.0 > 2.0 * spread
    assert rear_right > rear_left
    right_turn = _CAR.wheel_hz_all(DriveState(60.0, curvature_1pm=-1.0 / radius_m))
    assert right_turn[0] > right_turn[1]
    assert math.isclose(sum(_CAR.wheel_hz_all(left_turn)), sum(straight), rel_tol=0.003)


def test_a_staggered_car_turns_its_narrower_taller_axle_slower() -> None:
    front = SimTire(245.0, 40.0, 19.0)
    rear = SimTire(275.0, 35.0, 19.0)
    car = replace(_CAR, tires=(front, front, rear, rear))
    front_hz, _, rear_hz, _ = car.wheel_hz_all(_NO_SLIP)
    diameters = rear.new_diameter_m / front.new_diameter_m
    assert front_hz / rear_hz == pytest.approx(diameters, rel=0.003)


def test_cars_in_service_roll_their_four_wheels_up_to_about_one_and_a_half_percent_apart() -> None:
    reference = _CAR.wheel_hz("front-left", _NO_SLIP)
    spreads = []
    for seed in range(200):
        wheels = _CAR.in_service(random.Random(seed)).wheel_hz_all(_NO_SLIP)
        # Worn tires are smaller: every wheel turns at least as fast as a new one.
        assert min(wheels) > reference * 0.995
        spreads.append(max(wheels) / min(wheels) - 1.0)
    spreads.sort()
    assert 0.001 < spreads[10] and spreads[-10] < 0.02
    assert spreads[100] > 0.003
