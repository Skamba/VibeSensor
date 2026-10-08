"""How fast the simulated car's wheels, driveshaft and engine turn: the simulator's own physics.

The simulator derives every order tone it injects from this tire and driveline
model, never from the analysis's order math, so a drive can carry what real
cars do and the analysis does not assume: worn or soft tires that roll smaller,
drive and brake slip, and the outer wheels running faster through a bend. The
basis of each parameter is in ``docs/simulator_realism.md`` ("Wheel
kinematics").
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Literal

from vibesensor.common.units import KMH_TO_MPS

__all__ = [
    "CORNERS",
    "DriveState",
    "DrivenAxle",
    "SimCar",
    "SimTire",
]

type DrivenAxle = Literal["front", "rear", "all"]

CORNERS: tuple[str, str, str, str] = ("front-left", "front-right", "rear-left", "rear-right")
"""The wheel corners, in the order ``SimCar.tires`` holds them."""

_G_MPS2 = 9.81
_INCH_M = 0.0254
_KGF_PER_MM_TO_N_PER_M = 9.80665 * 1000.0
_AIR_DENSITY_KG_M3 = 1.2

ETRTO_ROLLING_CIRCUMFERENCE_PER_DIAMETER = 3.05
"""A radial passenger tire at its recommended pressure and normal load rolls
3.05 times its new overall diameter per turn (ETRTO's dynamic rolling
circumference rule), about 3 % short of the free circumference."""

REFERENCE_PRESSURE_KPA = 240.0
"""Cold inflation pressure the tires are set to unless a case says otherwise
(typical door-placard pressure for a mid-size car)."""

_FOOTPRINT_WIDTH_SHARE = 0.75
"""Contact-patch width over section width for a passenger tire (Rhyne's ``W``)."""

_RHYNE_SLOPE = 0.00028
_RHYNE_OFFSET_KGF_PER_MM = 3.45

SLIP_STIFFNESS_PER_LOAD = 19.0
"""Longitudinal slip stiffness over vertical load, per unit slip: the Magic
Formula's B*C*D for a passenger tire on dry asphalt (B 10, C 1.9, D 1)."""

_MAX_SLIP = 0.1
"""Beyond about 10 % slip a tire is past its friction peak; a drive never gets there."""

IN_SERVICE_AXLE_WEAR_MM = (0.0, 5.0)
"""Tread worn off an axle's pair in service: from new (8 mm) to 3 mm left, when
most owners replace them (the legal minimum is 1.6 mm)."""
IN_SERVICE_SIDE_WEAR_MM = 0.5
"""How far the two tires of one axle wear apart (alignment, camber): +/- 0.5 mm."""
IN_SERVICE_PRESSURE_KPA = (-10.0, 10.0)
"""Each tire's pressure off the placard: mean and standard deviation. Surveys
find most cars run their tires somewhat under the placard, a quarter of them
one tire 25 % under (NHTSA Tire Pressure Special Study, DOT HS 809 317, 2001)."""
_IN_SERVICE_PRESSURE_RANGE_KPA = (-60.0, 20.0)


@dataclass(frozen=True, slots=True)
class SimTire:
    """One tire: its size, how much tread is worn off and its pressure."""

    width_mm: float
    aspect_pct: float
    rim_in: float
    # Tread worn off since new (new tread is about 8 mm, the legal minimum 1.6 mm).
    tread_worn_mm: float = 0.0
    pressure_kpa: float = REFERENCE_PRESSURE_KPA

    @property
    def new_diameter_m(self) -> float:
        sidewall_m = self.width_mm * self.aspect_pct / 100.0 / 1000.0
        return self.rim_in * _INCH_M + 2.0 * sidewall_m

    @property
    def rim_radius_m(self) -> float:
        return self.rim_in * _INCH_M / 2.0

    def vertical_stiffness_n_per_m(self, pressure_kpa: float | None = None) -> float:
        """Rhyne's vertical stiffness of a belted radial tire, 0.00028 P sqrt(W D) + 3.45 kgf/mm."""
        pressure = self.pressure_kpa if pressure_kpa is None else pressure_kpa
        footprint_mm = self.width_mm * _FOOTPRINT_WIDTH_SHARE
        kgf_per_mm = (
            _RHYNE_SLOPE * pressure * math.sqrt(footprint_mm * self.new_diameter_m * 1000.0)
            + _RHYNE_OFFSET_KGF_PER_MM
        )
        return kgf_per_mm * _KGF_PER_MM_TO_N_PER_M

    def rolling_radius_m(self, load_n: float, reference_load_n: float) -> float:
        """Rolling radius at *load_n*; ETRTO's at *reference_load_n* and the reference pressure.

        Tread worn off shortens it one for one. Extra deflection (more load,
        less pressure) shortens it by a third of the deflection, the classic
        radial-tire approximation ``r_e = r - delta / 3``.
        """
        etrto_radius_m = (
            ETRTO_ROLLING_CIRCUMFERENCE_PER_DIAMETER * self.new_diameter_m / (2.0 * math.pi)
        )
        deflection_m = load_n / self.vertical_stiffness_n_per_m()
        reference_deflection_m = reference_load_n / self.vertical_stiffness_n_per_m(
            REFERENCE_PRESSURE_KPA
        )
        return (
            etrto_radius_m
            - self.tread_worn_mm / 1000.0
            - (deflection_m - reference_deflection_m) / 3.0
        )


@dataclass(frozen=True, slots=True)
class DriveState:
    """What the car is doing at one instant."""

    speed_kmh: float
    # Longitudinal acceleration (negative while slowing).
    accel_mps2: float = 0.0
    # 1 / turn radius; positive turning left, negative turning right, 0 straight on.
    curvature_1pm: float = 0.0


@dataclass(frozen=True, slots=True)
class SimCar:
    """The simulated car's tires, driveline and the masses that load them.

    Defaults are a mid-size saloon (Gillespie, *Fundamentals of Vehicle
    Dynamics*, ch. 2 and 4): 1600 kg, 55 % on the front axle, centre of
    gravity 0.55 m high, 2.85 m wheelbase, 1.6 m track, CdA 0.65 m²,
    rolling-resistance coefficient 0.012, 70 % of the braking on the front.
    """

    # Front-left, front-right, rear-left, rear-right (``CORNERS``).
    tires: tuple[SimTire, SimTire, SimTire, SimTire]
    final_drive_ratio: float
    top_gear_ratio: float
    driven_axle: DrivenAxle = "rear"
    mass_kg: float = 1600.0
    front_weight_share: float = 0.55
    cg_height_m: float = 0.55
    wheelbase_m: float = 2.85
    track_m: float = 1.6
    drag_area_m2: float = 0.65
    rolling_resistance: float = 0.012
    brake_front_share: float = 0.7

    @classmethod
    def square(
        cls,
        width_mm: float,
        aspect_pct: float,
        rim_in: float,
        final_drive_ratio: float,
        top_gear_ratio: float,
        **kwargs: object,
    ) -> SimCar:
        """A car on four new tires of one size at the reference pressure."""
        tire = SimTire(width_mm, aspect_pct, rim_in)
        return cls(
            tires=(tire, tire, tire, tire),
            final_drive_ratio=final_drive_ratio,
            top_gear_ratio=top_gear_ratio,
            **kwargs,  # type: ignore[arg-type]
        )

    def in_service(self, rng: random.Random) -> SimCar:
        """This car on tires as a car in service has them: worn per axle, pressures a little off.

        Each axle's pair has worn somewhere between new and due for
        replacement, its two tires within a millimetre of each other; each
        tire's pressure sits a little off the placard, mostly under. The four
        wheels then roll on radii up to about 1.5 % apart.
        """
        low, high = IN_SERVICE_AXLE_WEAR_MM
        axle_wear = (rng.uniform(low, high), rng.uniform(low, high))
        mean, spread = IN_SERVICE_PRESSURE_KPA
        floor, ceiling = _IN_SERVICE_PRESSURE_RANGE_KPA
        tires = [
            replace(
                tire,
                tread_worn_mm=max(
                    0.0,
                    axle_wear[index // 2]
                    + rng.uniform(-IN_SERVICE_SIDE_WEAR_MM, IN_SERVICE_SIDE_WEAR_MM),
                ),
                pressure_kpa=tire.pressure_kpa + min(ceiling, max(floor, rng.gauss(mean, spread))),
            )
            for index, tire in enumerate(self.tires)
        ]
        return replace(self, tires=(tires[0], tires[1], tires[2], tires[3]))

    def _static_loads_n(self) -> tuple[float, float, float, float]:
        front = self.mass_kg * _G_MPS2 * self.front_weight_share / 2.0
        rear = self.mass_kg * _G_MPS2 * (1.0 - self.front_weight_share) / 2.0
        return (front, front, rear, rear)

    def corner_loads_n(self, state: DriveState) -> tuple[float, float, float, float]:
        """Each tire's vertical load: static, plus the transfer acceleration and cornering cause."""
        speed_mps = max(0.0, state.speed_kmh) * KMH_TO_MPS
        longitudinal = self.mass_kg * state.accel_mps2 * self.cg_height_m / self.wheelbase_m / 2.0
        lateral_accel = speed_mps**2 * state.curvature_1pm
        lateral = self.mass_kg * lateral_accel * self.cg_height_m / self.track_m
        front_lateral = lateral * self.front_weight_share
        rear_lateral = lateral * (1.0 - self.front_weight_share)
        static = self._static_loads_n()
        # Turning left (positive curvature) loads the right-hand (outer) wheels.
        return (
            static[0] - longitudinal - front_lateral,
            static[1] - longitudinal + front_lateral,
            static[2] + longitudinal - rear_lateral,
            static[3] + longitudinal + rear_lateral,
        )

    def _driven(self) -> tuple[bool, bool, bool, bool]:
        front = self.driven_axle in {"front", "all"}
        rear = self.driven_axle in {"rear", "all"}
        return (front, front, rear, rear)

    def corner_slips(self, state: DriveState) -> tuple[float, float, float, float]:
        """Each tire's longitudinal slip ``(wheel speed - ground speed) / ground speed``.

        The tires push the car along with what its acceleration, aero drag and
        rolling resistance need: the driven wheels share it. A car slowing
        faster than drag alone slows it is braking: every wheel brakes, the
        front ones harder. Slip is that force over the slip stiffness.
        """
        if state.speed_kmh <= 0:
            return (0.0, 0.0, 0.0, 0.0)
        speed_mps = state.speed_kmh * KMH_TO_MPS
        resistance_n = (
            0.5 * _AIR_DENSITY_KG_M3 * self.drag_area_m2 * speed_mps**2
            + self.rolling_resistance * self.mass_kg * _G_MPS2
        )
        tractive_n = self.mass_kg * state.accel_mps2 + resistance_n
        if tractive_n >= 0:
            driven = self._driven()
            shares = tuple(1.0 / sum(driven) if is_driven else 0.0 for is_driven in driven)
        else:
            front = self.brake_front_share / 2.0
            rear = (1.0 - self.brake_front_share) / 2.0
            shares = (front, front, rear, rear)
        loads = self.corner_loads_n(state)
        slips = [
            max(-_MAX_SLIP, min(_MAX_SLIP, tractive_n * share / (SLIP_STIFFNESS_PER_LOAD * load)))
            for share, load in zip(shares, loads, strict=True)
        ]
        return (slips[0], slips[1], slips[2], slips[3])

    def wheel_hz_all(self, state: DriveState) -> tuple[float, float, float, float]:
        """How fast each wheel turns, front-left to rear-right (``CORNERS``)."""
        if state.speed_kmh <= 0:
            return (0.0, 0.0, 0.0, 0.0)
        speed_mps = state.speed_kmh * KMH_TO_MPS
        loads = self.corner_loads_n(state)
        static = self._static_loads_n()
        slips = self.corner_slips(state)
        half_track = self.track_m / 2.0
        # Turning left, the left-hand wheels run the inner, shorter path.
        sides = (-1.0, 1.0, -1.0, 1.0)
        hz = [
            speed_mps
            * (1.0 + side * half_track * state.curvature_1pm)
            * (1.0 + slip)
            / (2.0 * math.pi * tire.rolling_radius_m(load, reference))
            for tire, load, reference, slip, side in zip(
                self.tires, loads, static, slips, sides, strict=True
            )
        ]
        return (hz[0], hz[1], hz[2], hz[3])

    def wheel_hz(self, corner: str | None, state: DriveState) -> float:
        """How fast the wheel at *corner* turns; the four wheels' mean for ``None``."""
        wheels = self.wheel_hz_all(state)
        if corner is None:
            return sum(wheels) / 4.0
        return wheels[CORNERS.index(corner)]

    def shaft_hz(self, state: DriveState) -> float:
        """The driveshaft (final-drive input): the driven wheels' mean times the final drive."""
        wheels = zip(self.wheel_hz_all(state), self._driven(), strict=True)
        driven = [hz for hz, is_driven in wheels if is_driven]
        return sum(driven) / len(driven) * self.final_drive_ratio

    def engine_hz(self, state: DriveState, gear_ratio: float | None = None) -> float:
        """The crankshaft in *gear_ratio* (the top gear when ``None``), clutch engaged."""
        gear = self.top_gear_ratio if gear_ratio is None else gear_ratio
        return self.shaft_hz(state) * gear
