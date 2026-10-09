from __future__ import annotations

from dataclasses import dataclass

from vibesensor.simulator.fault_forces import OrderForce
from vibesensor.simulator.wheel_kinematics import SimCar

DEFAULT_SPEED_KMH = 100.0
# An unbalanced mass m at radius r turning at w pulls with F = m r w^2, and w
# follows the road speed, so a wheel's or propshaft's unbalance shakes with the
# square of the speed (ISO 21940-11 / ISO 1940-1).
UNBALANCE_SPEED_EXPONENT = 2.0


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
    # Order-locked tones as ``(order_key, multiple, amps_xyz)``: ``order_key``
    # names the order (``wheel_1x``, ``wheel_2x``, ``shaft_1x``, ``engine_1x``,
    # ``engine_2x``; a wheel order may name its wheel, ``wheel_1x@front-left``)
    # and the tone turns at the speed the car's wheel kinematics give it
    # (``SimClient.order_tone_hz``).
    order_tones: tuple[tuple[str, float, tuple[float, float, float]], ...] = ()
    # Speed at which the order tones' amplitudes are ``amps_xyz``; ``None``
    # means the profile has only absolute tones (e.g. engine_idle, rough_road).
    reference_speed_kmh: float | None = None
    # Road noise grows with speed: the broadband noise is scaled by
    # ``(speed / DEFAULT_SPEED_KMH) ** noise_speed_exponent`` (0: flat).
    noise_speed_exponent: float = 0.0
    # An unbalanced mass shakes harder the faster it turns: order-tone
    # amplitudes are scaled by ``(speed / reference_speed) ** order_speed_exponent``
    # (0: the same amplitude at every speed).
    order_speed_exponent: float = 0.0
    # Order tones sized as the fault's forces instead, each turning with its
    # order like ``order_tones``; a sensor reads each through the car to its
    # mount (``simulator/fault_forces.py``). The accuracy benchmark plays these
    # with VIBESENSOR_BENCH_FAULT_AMPLITUDES=physical ("Fault amplitudes" in
    # docs/simulator_realism.md).
    order_forces: tuple[OrderForce, ...] = ()
    # ``(low_kmh, high_kmh, gain)``: a suspension or body resonance the order
    # passes through amplifies its tones (and forces) by ``gain`` inside that
    # speed band.
    order_resonance_kmh: tuple[float, float, float] | None = None
    # Structural modes the road excites at this sensor, scaled by
    # ``road_roughness`` (each ISO 8608 class rougher doubles it) and the speed.
    road_resonances: tuple[RoadResonance, ...] = ROAD_RESONANCES
    road_roughness: float = 1.0

    def order_amplitude_gain(self, speed_kmh: float) -> float:
        """How much the order tones are amplified at *speed_kmh* (1 at the reference speed)."""
        gain = self.order_resonance_gain(speed_kmh)
        if self.order_speed_exponent and self.reference_speed_kmh:
            gain *= (max(0.0, speed_kmh) / self.reference_speed_kmh) ** self.order_speed_exponent
        return gain

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
        # A 4-stroke 4-cylinder fires twice per crank revolution, so its
        # load-dependent vibration is dominated by the 2nd engine order (E2).
        order_tones=(
            ("engine_2x", 1.0, (185.0, 128.0, 248.0)),
            ("engine_1x", 1.0, (62.0, 46.0, 92.0)),
        ),
        noise_std=18.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(16.0, 13.0, 24.0),
        modulation_hz=0.24,
        modulation_depth=0.10,
        reference_speed_kmh=DEFAULT_SPEED_KMH,
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
        order_tones=(
            ("wheel_1x", 1.0, (220.0, 125.0, 170.0)),
            ("wheel_2x", 1.0, (80.0, 52.0, 72.0)),
        ),
        noise_std=24.0,
        bump_probability=0.004,
        bump_decay=0.94,
        bump_strength=(30.0, 24.0, 45.0),
        modulation_hz=0.22,
        modulation_depth=0.12,
        reference_speed_kmh=DEFAULT_SPEED_KMH,
        order_speed_exponent=UNBALANCE_SPEED_EXPONENT,
    ),
    "wheel_mild_imbalance": Profile(
        name="wheel_mild_imbalance",
        tones=(),
        order_tones=(
            ("wheel_1x", 1.0, (105.0, 62.0, 80.0)),
            ("wheel_2x", 1.0, (28.0, 18.0, 24.0)),
        ),
        noise_std=14.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(10.0, 8.0, 14.0),
        modulation_hz=0.18,
        modulation_depth=0.08,
        reference_speed_kmh=DEFAULT_SPEED_KMH,
        order_speed_exponent=UNBALANCE_SPEED_EXPONENT,
    ),
    "driveshaft_imbalance": Profile(
        name="driveshaft_imbalance",
        tones=(),
        order_tones=(
            ("shaft_1x", 1.0, (150.0, 120.0, 190.0)),
            ("shaft_1x", 2.0, (45.0, 36.0, 60.0)),
        ),
        noise_std=20.0,
        bump_probability=0.002,
        bump_decay=0.95,
        bump_strength=(18.0, 15.0, 26.0),
        modulation_hz=0.2,
        modulation_depth=0.10,
        reference_speed_kmh=DEFAULT_SPEED_KMH,
        order_speed_exponent=UNBALANCE_SPEED_EXPONENT,
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
