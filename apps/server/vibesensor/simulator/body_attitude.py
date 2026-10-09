"""What a firmly mounted sensor reads at 0 Hz: gravity and the car's own acceleration.

An accelerometer reads specific force: the car's acceleration minus gravity.
At rest on a level road that is 1 g up; the car's speeding up, braking and
cornering add their acceleration, a grade tilts gravity, and the part the
sensor sits on turns with the car's motion:

- the body (seats, trunk, tunnel, subframe, and the powertrain on its mounts)
  pitches under braking and acceleration and rolls outward in a bend;
- a wheel carrier (knuckle) stays with the road, but a front one turns about
  its steering axis, which leans inboard (kingpin inclination) and rearward
  (caster), so steering tilts it;
- the owner sticks the sensor on at whatever angle the part offers.

A loose fixing's own turning on top of this lives in ``confounders.py``. The
basis of each number is in ``docs/simulator_realism.md`` ("Body attitude").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from vibesensor.common.units import KMH_TO_MPS
from vibesensor.ingest.sensor_units import ADXL345_SCALE_G_PER_LSB
from vibesensor.simulator.road_vibration import SensorMount, mount_for_name

__all__ = ["AttitudeCar", "SensorAttitude", "rotation_about"]

_G_MPS2 = 9.80665
_COUNTS_PER_G = 1.0 / ADXL345_SCALE_G_PER_LSB


@dataclass(frozen=True, slots=True)
class AttitudeCar:
    """A mid-size passenger car's attitude response (see docs/simulator_realism.md)."""

    # Body roll per g sideways: 4.9 and 6.6 deg/g measured on two cars
    # (J. Braz. Soc. Mech. Sci. & Eng. 33(4), 2011, Table 1); the softer one.
    roll_deg_per_g: float = 6.6
    # Body pitch per g fore-aft, from the quarter car's ride rate and load
    # transfer (m g h / L, CG height 0.55 m) without anti-dive geometry.
    pitch_deg_per_g: float = 3.0
    # Extra front-wheel steer per g sideways (same paper, Table 2: 3.9-4.0 deg/g).
    understeer_deg_per_g: float = 4.0
    # Steering axis of a front strut: leaning inboard and rearward at the top.
    kingpin_inclination_deg: float = 13.0
    caster_deg: float = 6.0
    wheelbase_m: float = 2.7
    # Grade changes along a vertical curve: K metres of road per % (AASHTO).
    vertical_curve_m_per_pct: float = 50.0
    # How fast the car's acceleration follows the driver's pedals and the
    # steering (brake pressure build-up, body pitch and roll modes).
    response_s: float = 0.3


def rotation_about(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    """Rotation matrix turning vectors by *angle_rad* about *axis* (right hand)."""
    k = np.asarray(axis, dtype=np.float64)
    k = k / np.linalg.norm(k)
    cross = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    rotation: np.ndarray = (
        np.eye(3) + math.sin(angle_rad) * cross + (1.0 - math.cos(angle_rad)) * (cross @ cross)
    )
    return rotation


_X = np.array([1.0, 0.0, 0.0])
_Y = np.array([0.0, 1.0, 0.0])
_Z = np.array([0.0, 0.0, 1.0])


def _mounting(rng: np.random.Generator) -> np.ndarray:
    """Sensor axes on the part they are stuck to: any heading, up to 30 deg off level."""
    heading = rotation_about(_Z, float(rng.uniform(0.0, 2.0 * math.pi)))
    tilt_axis = heading @ _X
    tilt = rotation_about(tilt_axis, math.radians(float(rng.uniform(0.0, 30.0))))
    mounting: np.ndarray = tilt @ heading
    return mounting


@dataclass(slots=True)
class SensorAttitude:
    """One sensor's 0 Hz reading, frame by frame (the car's state is filtered across frames).

    ``mounting`` holds the sensor's axes (columns) in the frame of the part it
    sits on: car axes x forward, y left, z up.
    """

    mount: SensorMount
    steers: bool
    left: bool
    mounting: np.ndarray
    car: AttitudeCar = AttitudeCar()
    _accel_mps2: float = 0.0
    _lateral_mps2: float = 0.0
    _grade_pct: float | None = None
    _last: np.ndarray | None = field(default=None, repr=False)

    @classmethod
    def for_sensor(cls, name: str, rng: np.random.Generator) -> SensorAttitude:
        """The attitude model for the sensor a name or location code implies."""
        mount, axle_share = mount_for_name(name)
        words = name.strip().lower().replace("_", " ").replace("-", " ").split()
        return cls(
            mount=mount,
            steers=mount is SensorMount.KNUCKLE and axle_share == 0.0,
            left="left" in words,
            mounting=_mounting(rng),
        )

    def frame_counts(
        self,
        *,
        speed_kmh: float,
        accel_mps2: float,
        curvature_1pm: float,
        grade_pct: float,
        samples: int,
        dt: float,
    ) -> np.ndarray:
        """``(samples, 3)`` specific force in the sensor's axes (counts) over one frame.

        It moves linearly from the last frame's end to this frame's, so the
        reading has no steps at frame edges.
        """
        car = self.car
        frame_s = samples * dt
        speed_mps = max(0.0, speed_kmh) * KMH_TO_MPS
        follow = 1.0 - math.exp(-frame_s / car.response_s)
        self._accel_mps2 += (accel_mps2 - self._accel_mps2) * follow
        lateral = speed_mps * speed_mps * curvature_1pm
        self._lateral_mps2 += (lateral - self._lateral_mps2) * follow
        if self._grade_pct is None:
            self._grade_pct = grade_pct
        else:
            step = speed_mps * frame_s / car.vertical_curve_m_per_pct
            self._grade_pct += float(np.clip(grade_pct - self._grade_pct, -step, step))
        end = self._reading(curvature_1pm)
        start = end if self._last is None else self._last
        self._last = end
        ramp = (np.arange(1, samples + 1) / samples)[:, None]
        reading: np.ndarray = start + (end - start) * ramp
        return reading * _COUNTS_PER_G

    def _reading(self, curvature_1pm: float) -> np.ndarray:
        """The specific force (g) at the end of the frame, in the sensor's axes."""
        car = self.car
        assert self._grade_pct is not None
        grade = math.atan(self._grade_pct / 100.0)
        ax_g = self._accel_mps2 / _G_MPS2
        ay_g = self._lateral_mps2 / _G_MPS2
        # Road axes: the car's acceleration plus gravity's reaction, tilted by the grade.
        force = np.array([ax_g + math.sin(grade), ay_g, math.cos(grade)])
        if self.mount is SensorMount.KNUCKLE:
            part = np.eye(3)
            if self.steers:
                steer = math.atan(car.wheelbase_m * curvature_1pm) + math.radians(
                    car.understeer_deg_per_g * ay_g
                )
                inboard = -1.0 if self.left else 1.0
                axis = np.array(
                    [
                        -math.tan(math.radians(car.caster_deg)),
                        inboard * math.tan(math.radians(car.kingpin_inclination_deg)),
                        1.0,
                    ]
                )
                part = rotation_about(axis, steer)
        else:
            # Nose up under acceleration, down under braking; rolled outward in a bend.
            pitch = math.radians(car.pitch_deg_per_g * ax_g)
            roll = math.radians(car.roll_deg_per_g * ay_g)
            part = rotation_about(_X, roll) @ rotation_about(_Y, -pitch)
        axes = part @ self.mounting
        reading: np.ndarray = axes.T @ force
        return reading
