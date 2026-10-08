"""Road-excited vibration at a sensor: an ISO 8608 road through a quarter car.

The road's height under a wheel is a random profile whose displacement PSD
falls as ``n^-2`` (ISO 8608), so its vertical *velocity* at speed ``v`` is
white with one-sided PSD ``4 pi^2 n0^2 Gd(n0) v``. The tyre's contact patch
smooths wavelengths shorter than itself (a first-order low-pass at
``0.44 v / contact length``), and a quarter car (sprung and unsprung mass,
suspension spring and damper, tyre spring) turns that input into the
acceleration of the wheel knuckle (wheel hop near 12 Hz, falling above) and of
the body (the ride mode near 1.2 Hz, little above 10 Hz). Engine and gearbox
sensors sit on rubber mounts that ring near 10 Hz on top of the body motion.

Sources and the reasoning behind each number: ``docs/simulator_realism.md``.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from enum import Enum

import numpy as np
from scipy.signal import cont2discrete, lfilter, ss2tf

from vibesensor.simulator.road_surface import ISO8608_N0_CYCLES_PER_M, RoadSurface

__all__ = [
    "QuarterCar",
    "RoadVibration",
    "SensorMount",
    "mount_for_name",
]

_G_MPS2 = 9.80665
_KMH_TO_MPS = 1.0 / 3.6


@dataclass(frozen=True, slots=True)
class QuarterCar:
    """One corner of a mid-size passenger car (about 1.5 t)."""

    sprung_kg: float = 330.0
    unsprung_kg: float = 40.0
    # Ride rate for a 1.2 Hz body mode on a 200 kN/m tyre.
    suspension_n_per_m: float = 20_700.0
    # 0.3 of critical damping on the body mode (0.26 on wheel hop).
    damper_ns_per_m: float = 1_570.0
    tyre_n_per_m: float = 200_000.0
    contact_length_m: float = 0.15
    wheelbase_m: float = 2.7


class SensorMount(Enum):
    """Where on the car a sensor sits, as the road reaches it."""

    # The wheel carrier (knuckle, strut base): unsprung, on the tyre spring.
    KNUCKLE = "knuckle"
    # Body structure: subframe, tunnel, seat rails, trunk floor.
    BODY = "body"
    # Engine or gearbox on its rubber mounts.
    POWERTRAIN = "powertrain"


# Where along the car a mount meets the road: 0 the front axle, 1 the rear.
_AXLE_SHARE = {"front": 0.0, "middle": 0.5, "rear": 1.0}

_BODY_WORDS = ("seat", "trunk", "tunnel", "driveshaft", "subframe", "cabin", "body")
_POWERTRAIN_WORDS = ("engine", "gearbox", "transmission")

# Vertical dominates; fore-aft and lateral carry a fraction of it (x, y, z).
_AXIS_SHARE = np.asarray((0.5, 0.35, 1.0))

# Engine/gearbox bounce on its mounts: 6-12 Hz, rubber damping 5-15 %.
_POWERTRAIN_MOUNT_HZ = 10.0
_POWERTRAIN_MOUNT_DAMPING = 0.1


def mount_for_name(name: str) -> tuple[SensorMount, float]:
    """The mount and axle share (0 front, 1 rear) a sensor's name or location code implies.

    A corner (``front-left``, ``rear_right_wheel``, ``VS-12 front left``) is a
    knuckle; seats, trunk, tunnel and subframe are body; engine and gearbox
    are powertrain. Anything else is body, mid-car.
    """
    normalized = name.strip().lower().replace("_", " ").replace("-", " ")
    words = normalized.split()
    axle = "front" if "front" in words else "rear" if "rear" in words else None
    side = "left" in words or "right" in words
    if any(word in normalized for word in _POWERTRAIN_WORDS):
        return SensorMount.POWERTRAIN, _AXLE_SHARE["front"]
    if any(word in normalized for word in _BODY_WORDS) or axle is None or not side:
        if "trunk" in normalized:
            axle = "rear"
        elif "subframe" in normalized and axle is None:
            axle = "front"
        return SensorMount.BODY, _AXLE_SHARE[axle or "middle"]
    return SensorMount.KNUCKLE, _AXLE_SHARE[axle]


@functools.cache
def _quarter_car_filter(
    car: QuarterCar, sample_rate_hz: int, unsprung: bool
) -> tuple[np.ndarray, np.ndarray]:
    """Discrete transfer function from road velocity (m/s) to sensor acceleration (m/s^2).

    States: suspension deflection, body velocity, tyre deflection, wheel
    velocity. The road velocity is held over each sample (zero-order hold),
    which is exact for the piecewise-constant input the generator feeds it.
    """
    ms, mu = car.sprung_kg, car.unsprung_kg
    ks, cs, kt = car.suspension_n_per_m, car.damper_ns_per_m, car.tyre_n_per_m
    a = np.array(
        [
            [0.0, 1.0, 0.0, -1.0],
            [-ks / ms, -cs / ms, 0.0, cs / ms],
            [0.0, 0.0, 0.0, 1.0],
            [ks / mu, cs / mu, -kt / mu, -cs / mu],
        ]
    )
    b = np.array([[0.0], [0.0], [-1.0], [0.0]])
    c = a[[3 if unsprung else 1], :]
    d = np.zeros((1, 1))
    ad, bd, cd, dd, _dt = cont2discrete((a, b, c, d), 1.0 / sample_rate_hz, method="zoh")
    num, den = ss2tf(ad, bd, cd, dd)
    return np.asarray(num[0], dtype=np.float64), np.asarray(den, dtype=np.float64)


@functools.cache
def _mount_filter(sample_rate_hz: int) -> tuple[np.ndarray, np.ndarray]:
    """Base-excitation transmissibility of an engine/gearbox on its rubber mounts."""
    wn = 2.0 * np.pi * _POWERTRAIN_MOUNT_HZ
    zeta = _POWERTRAIN_MOUNT_DAMPING
    a = np.array([[0.0, 1.0], [-(wn**2), -2.0 * zeta * wn]])
    b = np.array([[0.0], [1.0]])
    # Output: mass acceleration = wn^2 (base - x) + 2 zeta wn (base' - x') in
    # relative coordinates; in absolute form the transfer is
    # (2 zeta wn s + wn^2) / (s^2 + 2 zeta wn s + wn^2).
    c = np.array([[wn**2, 2.0 * zeta * wn]])
    d = np.zeros((1, 1))
    ad, bd, cd, dd, _dt = cont2discrete((a, b, c, d), 1.0 / sample_rate_hz, method="bilinear")
    num, den = ss2tf(ad, bd, cd, dd)
    return np.asarray(num[0], dtype=np.float64), np.asarray(den, dtype=np.float64)


@dataclass(slots=True)
class RoadVibration:
    """The road's vibration at one sensor, frame by frame (stateful filters)."""

    mount: SensorMount
    axle_share: float
    sample_rate_hz: int
    rng: np.random.Generator
    car: QuarterCar = QuarterCar()
    _contact_state: np.ndarray | None = None
    _car_state: np.ndarray | None = None
    _mount_state: np.ndarray | None = None

    def frame_mg(self, road: RoadSurface, start_m: float, speed_kmh: float, n: int) -> np.ndarray:
        """``(n, 3)`` acceleration (mg) for a frame whose first sample is at *start_m*.

        *start_m* is the front axle's distance along *road*; this sensor meets
        the road ``axle_share * wheelbase`` behind it.
        """
        fs = float(self.sample_rate_hz)
        speed_mps = max(0.0, speed_kmh) * _KMH_TO_MPS
        position_m = start_m - self.axle_share * self.car.wheelbase_m
        # Road velocity: white, one-sided PSD 4 pi^2 n0^2 Gd(n0) v, held per sample.
        gd = road.gd_n0_m3(position_m)
        psd = 4.0 * np.pi**2 * ISO8608_N0_CYCLES_PER_M**2 * gd * speed_mps
        road_velocity = self.rng.normal(0.0, np.sqrt(psd * fs / 2.0), size=(n, 3))
        road_velocity *= _AXIS_SHARE
        if speed_mps > 0.0:
            road_velocity += self._impact_velocity(road, position_m, speed_mps, n)[:, None]
            road_velocity = self._contact_patch(road_velocity, speed_mps)
        num, den = _quarter_car_filter(
            self.car, self.sample_rate_hz, self.mount is SensorMount.KNUCKLE
        )
        if self._car_state is None:
            self._car_state = np.zeros((den.size - 1, 3))
        accel, self._car_state = lfilter(num, den, road_velocity, axis=0, zi=self._car_state)
        if self.mount is SensorMount.POWERTRAIN:
            mount_num, mount_den = _mount_filter(self.sample_rate_hz)
            if self._mount_state is None:
                self._mount_state = np.zeros((mount_den.size - 1, 3))
            accel, self._mount_state = lfilter(
                mount_num, mount_den, accel, axis=0, zi=self._mount_state
            )
        return np.asarray(accel, dtype=np.float64) * (1000.0 / _G_MPS2)

    def _impact_velocity(
        self, road: RoadSurface, position_m: float, speed_mps: float, n: int
    ) -> np.ndarray:
        """Vertical road velocity of the frame's impacts, as each sample's mean (m/s).

        Differencing the dip's height at the sample edges keeps the full depth
        however short the dip is against a sample.
        """
        dt = 1.0 / self.sample_rate_hz
        end_m = position_m + speed_mps * n * dt
        impacts = road.impacts_between(position_m, end_m)
        out = np.zeros(n)
        if not impacts:
            return out
        edges_m = position_m + speed_mps * dt * np.arange(n + 1)
        for impact in impacts:
            out += np.diff(impact.displacement_m(edges_m)) / dt
        return out

    def _contact_patch(self, road_velocity: np.ndarray, speed_mps: float) -> np.ndarray:
        """Low-pass the road under the tyre: wavelengths shorter than the patch average out."""
        cutoff_hz = 0.44 * speed_mps / self.car.contact_length_m
        pole = float(np.exp(-2.0 * np.pi * cutoff_hz / self.sample_rate_hz))
        if self._contact_state is None:
            self._contact_state = np.zeros((1, 3))
        smoothed, self._contact_state = lfilter(
            [1.0 - pole], [1.0, -pole], road_velocity, axis=0, zi=self._contact_state
        )
        return np.asarray(smoothed)
