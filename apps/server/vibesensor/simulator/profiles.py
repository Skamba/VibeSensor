from __future__ import annotations

from dataclasses import dataclass

from vibesensor.simulator.fault_forces import OrderForce
from vibesensor.simulator.wheel_kinematics import SimCar

DEFAULT_SPEED_KMH = 100.0


@dataclass(frozen=True, slots=True)
class RoadResonance:
    """A structural mode the road excites: wheel hop, a seat, the body, a mirror.

    The road shakes the car with broadband noise, so a mode rings as a
    narrowband hump of noise centred on *hz* (half-power width ``hz / q``), the
    same frequency at every speed. *rms_mg* is its level per axis at
    ``DEFAULT_SPEED_KMH`` on an ISO 8608 class A-B road (``road_roughness`` 1).
    """

    hz: float
    q: float
    rms_mg: tuple[float, float, float]


# Road displacement roughness falls with the square of the spatial frequency
# (ISO 8608), so the acceleration a fixed mode sees grows with the square root
# of the speed; each rougher ISO 8608 class doubles it.
RESONANCE_SPEED_EXPONENT = 0.5

ROAD_RESONANCES: tuple[RoadResonance, ...] = (
    # Wheel hop: the unsprung mass on the tire, damped by the shock absorber
    # (10-15 Hz, damping ratio about 0.2). Mostly vertical.
    RoadResonance(hz=12.0, q=2.5, rms_mg=(3.0, 2.0, 6.0)),
    # The trimmed body's first bending/torsion mode (20-35 Hz, 3-6 % damping).
    RoadResonance(hz=24.0, q=8.0, rms_mg=(1.5, 1.0, 2.5)),
    # Steering column or mirror (30-40 Hz, lightly damped).
    RoadResonance(hz=33.0, q=15.0, rms_mg=(1.0, 1.5, 1.0)),
)
"""A healthy car's road-excited modes, kept modest: a few mg each, well under
the 20-50 mg whole-body level ISO 2631 surveys find on normal roads (see
"Simulated road resonances" in ``docs/testing.md``)."""


# Fault sizes (the basis of each: "Fault amplitudes" in docs/simulator_realism.md).
# A wheel that lost a balancing weight, or was fitted unbalanced: 40 g at the rim.
WHEEL_IMBALANCE_G = 40.0
# A wheel a little out of balance: 15 g at the rim.
WHEEL_MILD_IMBALANCE_G = 15.0
# A propshaft that lost a balance weight: 15 g on its 40 mm tube radius.
PROPSHAFT_IMBALANCE_G = 15.0
PROPSHAFT_RADIUS_M = 0.04
# An inline-4's second-order free force (0.5 kg reciprocating per cylinder,
# 45 mm crank radius, 0.3 crank-to-rod ratio) as an unbalance at E2.
I4_SECOND_ORDER_G = 150.0
CRANK_RADIUS_M = 0.045
# Crankshaft and flywheel balanced four times worse than ISO 21940-11 G6.3.
CRANK_RESIDUAL_G = 20.0
FLYWHEEL_RADIUS_M = 0.1


SIMULATOR_CAR = SimCar.square(285.0, 30.0, 21.0, final_drive_ratio=3.08, top_gear_ratio=0.64)
"""The simulated car, used until the server's active car gives its own tire size and ratios."""


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    # Fixed-frequency tones ``(hz, amps_xyz)``: body resonances and idle shake,
    # the same frequency at every speed.
    tones: tuple[tuple[float, tuple[float, float, float]], ...]
    noise_std: float
    bump_probability: float
    bump_decay: float
    bump_strength: tuple[float, float, float]
    modulation_hz: float
    modulation_depth: float
    # The fault's forces, each turning with its order at the speed the car's
    # wheel kinematics give it (``SimClient.order_tone_hz``); a sensor reads
    # each through the car to its mount (``simulator/fault_forces.py``).
    order_forces: tuple[OrderForce, ...] = ()
    # Road noise grows with speed: the broadband noise is scaled by
    # ``(speed / DEFAULT_SPEED_KMH) ** noise_speed_exponent`` (0: flat).
    noise_speed_exponent: float = 0.0
    # ``(low_kmh, high_kmh, gain)``: a suspension or body resonance the order
    # passes through amplifies its tones by ``gain`` inside that speed band.
    order_resonance_kmh: tuple[float, float, float] | None = None
    # Structural modes the road excites at this sensor, scaled by
    # ``road_roughness`` (each ISO 8608 class rougher doubles it) and the speed.
    road_resonances: tuple[RoadResonance, ...] = ROAD_RESONANCES
    road_roughness: float = 1.0

    def order_resonance_gain(self, speed_kmh: float) -> float:
        """How much ``order_resonance_kmh`` amplifies the order tones at *speed_kmh*."""
        if self.order_resonance_kmh is None:
            return 1.0
        low_kmh, high_kmh, resonance_gain = self.order_resonance_kmh
        return resonance_gain if low_kmh <= speed_kmh <= high_kmh else 1.0

    def resonance_gain(self, speed_kmh: float) -> float:
        """How strongly the road excites the resonances at *speed_kmh* (none at a standstill)."""
        speed_ratio = max(0.0, speed_kmh) / DEFAULT_SPEED_KMH
        return self.road_roughness * float(speed_ratio**RESONANCE_SPEED_EXPONENT)

    def noise_gain(self, speed_kmh: float) -> float:
        """How much the broadband noise grows with *speed_kmh* (1 at ``DEFAULT_SPEED_KMH``)."""
        if not self.noise_speed_exponent:
            return 1.0
        return float((max(0.0, speed_kmh) / DEFAULT_SPEED_KMH) ** self.noise_speed_exponent)


# A profile only carries the tones of the source it simulates. Road and body
# profiles are broadband noise plus impacts: a healthy car has no order tones,
# so fault-free sensors and scenarios stay free of wheel/driveshaft/engine orders.
PROFILE_LIBRARY: dict[str, Profile] = {
    "engine_idle": Profile(
        name="engine_idle",
        tones=(
            (13.0, (170.0, 120.0, 250.0)),
            (26.0, (55.0, 40.0, 85.0)),
            (39.0, (30.0, 24.0, 45.0)),
        ),
        noise_std=22.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(18.0, 15.0, 28.0),
        modulation_hz=0.35,
        modulation_depth=0.10,
    ),
    "engine_order": Profile(
        name="engine_order",
        tones=(),
        # An inline-4 without (or with a failed) balance shaft: its pistons'
        # second-order free force, the equivalent of an unbalance turning at
        # twice the crank speed (E2), over the crankshaft's own residual
        # unbalance at E1.
        order_forces=(
            OrderForce("engine_2x", unbalance_g=I4_SECOND_ORDER_G, radius_m=CRANK_RADIUS_M),
            OrderForce("engine_1x", unbalance_g=CRANK_RESIDUAL_G, radius_m=FLYWHEEL_RADIUS_M),
        ),
        noise_std=18.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(16.0, 13.0, 24.0),
        modulation_hz=0.24,
        modulation_depth=0.10,
    ),
    "rough_road": Profile(
        name="rough_road",
        tones=(),
        noise_std=28.0,
        bump_probability=0.012,
        bump_decay=0.92,
        bump_strength=(45.0, 55.0, 80.0),
        modulation_hz=0.45,
        modulation_depth=0.16,
    ),
    "wheel_imbalance": Profile(
        name="wheel_imbalance",
        tones=(),
        order_forces=(OrderForce("wheel_1x", unbalance_g=WHEEL_IMBALANCE_G),),
        noise_std=24.0,
        bump_probability=0.004,
        bump_decay=0.94,
        bump_strength=(30.0, 24.0, 45.0),
        modulation_hz=0.22,
        modulation_depth=0.12,
    ),
    "wheel_mild_imbalance": Profile(
        name="wheel_mild_imbalance",
        tones=(),
        order_forces=(OrderForce("wheel_1x", unbalance_g=WHEEL_MILD_IMBALANCE_G),),
        noise_std=14.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(10.0, 8.0, 14.0),
        modulation_hz=0.18,
        modulation_depth=0.08,
    ),
    "driveshaft_imbalance": Profile(
        name="driveshaft_imbalance",
        tones=(),
        order_forces=(
            OrderForce("shaft_1x", unbalance_g=PROPSHAFT_IMBALANCE_G, radius_m=PROPSHAFT_RADIUS_M),
        ),
        noise_std=20.0,
        bump_probability=0.002,
        bump_decay=0.95,
        bump_strength=(18.0, 15.0, 26.0),
        modulation_hz=0.2,
        modulation_depth=0.10,
    ),
    "rear_body": Profile(
        name="rear_body",
        tones=(),
        noise_std=22.0,
        bump_probability=0.006,
        bump_decay=0.95,
        bump_strength=(30.0, 34.0, 50.0),
        modulation_hz=0.28,
        modulation_depth=0.14,
    ),
}
