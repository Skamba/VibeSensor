"""Things on a real first drive that can fool a diagnosis or hide a fault.

Each effect acts on what one simulated sensor feels, in ADXL345 counts, from a
physical model with a cited basis (see "Confounders" in
``docs/simulator_realism.md``):

- ``SensorFixing``: the bracket, pad or cable ties the sensor sits on ring as a
  base-excited single-degree-of-freedom system; held too loosely, the housing
  lifts off and rattles (the reading clips at the hold-down level, and every
  landing is an impact spike).
- ``MountSlip``: the housing turns on its fixing, so its reading of gravity
  tilts: it sags while it floats off a rattling fixing, or steps when a pad
  lets go at a corner or a tie slips.
- ``FlatSpot``: a tyre parked overnight keeps a flat where it stood; once per
  turn it presses the wheel like a short bump, with harmonics, and the flat
  creeps back out over the first kilometres as the tyre warms.
- ``AccessoryTone``: a blower or alternator shaking at its own rhythm, which
  no wheel, shaft or engine fault explains.

``SensorConfounders`` holds the effects one sensor gets and their running state
(filter memories, distance driven), so they stay continuous across frames.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import lfilter

from vibesensor.ingest.sensor_units import ADXL345_SCALE_G_PER_LSB
from vibesensor.simulator.body_attitude import rotation_about

__all__ = ["AccessoryTone", "FlatSpot", "MountSlip", "SensorConfounders", "SensorFixing"]

_TWO_PI = 2.0 * math.pi
_G_MPS2 = 9.80665
_COUNTS_PER_G = 1.0 / ADXL345_SCALE_G_PER_LSB
_COUNTS_PER_MG = _COUNTS_PER_G / 1000.0


@dataclass(frozen=True, slots=True)
class MountSlip:
    """How the housing turns on a fixing that has come loose.

    The housing tips about *axis* (sensor axes, through its contact edge).
    While it floats off a rattling fixing (``SensorFixing.rattle_g``) nothing
    holds it against gravity's moment about that edge, so it sags by
    *sag_deg_per_floating_s* for every second it is off the fixing, until it
    hangs in the ties or rests on the part (*max_deg*). *steps* are sudden
    moves, ``(seconds since the sensor started, degrees)``: an adhesive pad
    letting go at one corner, a cable tie slipping.
    """

    axis: tuple[float, float, float] = (1.0, 0.0, 0.0)
    sag_deg_per_floating_s: float = 0.0
    max_deg: float = 20.0
    steps: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class SensorFixing:
    """How the sensor housing is fixed to the car.

    The housing (mass ``m``) on its fixing (stiffness ``k``, damping ratio
    ``damping_ratio``) is a base-excited oscillator: it follows the car below
    ``resonance_hz`` (``sqrt(k/m) / 2 pi``), reads the car's motion up to about
    ``1 / (2 * damping_ratio)`` times as strong at it, and less above it
    (absolute-acceleration transmissibility, Rao, *Mechanical Vibrations*,
    ch. 3.6). A bolted or glued sensor rings far above the band (ISO 5348);
    cable ties or a foam pad bring the ring down into it.

    With *rattle_g*, the fixing holds the housing down only up to that
    acceleration (its preload over the housing's mass, along *rattle_axis*):
    beyond it the housing floats, so the reading clips at ``+/- rattle_g``, and
    it lands with the relative velocity it gained, an impact that rings the
    housing at *impact_hz* for a few milliseconds (Trapp & Chen, *Automotive
    Buzz, Squeak and Rattle*, 2012: rattle starts where the excitation exceeds
    the hold-down).
    """

    resonance_hz: float
    damping_ratio: float
    rattle_g: float | None = None
    rattle_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    impact_hz: float = 250.0
    impact_damping_ratio: float = 0.1


@dataclass(frozen=True, slots=True)
class FlatSpot:
    """A tyre's parking flat spot as its wheel sensor feels it at the start of the drive.

    *t1_mg* is the first wheel order's level per axis (mostly vertical: it is a
    radial force). The flat is a dip about one contact patch long
    (*length_share* of the circumference), so its harmonics fall off slowly
    (a raised-cosine pulse's Fourier series): *harmonics* wheel orders carry it.
    It fades with the distance driven as the rubber and then the nylon cords
    creep back (two exponentials, US 7,377,155 B2), *fast_km* and *slow_km*
    each, *slow_share* of it in the slow one; Tire Rack's guidance is that
    flat-spot vibration is gone after about 15 miles (24 km) at highway speed.
    """

    t1_mg: tuple[float, float, float]
    length_share: float = 0.08
    harmonics: int = 4
    fast_km: float = 2.0
    slow_km: float = 8.0
    slow_share: float = 0.5
    phase_rad: float = 0.0

    def remaining(self, distance_km: float) -> float:
        """Share of the flat still there after *distance_km*."""
        return (1.0 - self.slow_share) * math.exp(-distance_km / self.fast_km) + (
            self.slow_share * math.exp(-distance_km / self.slow_km)
        )

    def harmonic_levels(self) -> tuple[float, ...]:
        """Each wheel order's level relative to the first (1st order: 1)."""

        def coefficient(n: int) -> float:
            x = n * self.length_share
            return float(np.sinc(x) / (1.0 - x * x))

        first = coefficient(1)
        return tuple(coefficient(n) / first for n in range(1, self.harmonics + 1))


@dataclass(frozen=True, slots=True)
class AccessoryTone:
    """Something running in a healthy car that shakes at its own rhythm, felt at one sensor.

    It turns at a fixed speed (*hz*: a blower or fuel-pump motor) or off the
    crank through its pulley (*engine_order*: an alternator), so it is no
    wheel, shaft or engine-order fault. *level_mg* per axis is what the sensor
    feels of the rotor's residual imbalance (``m e w^2`` over the mass it
    shakes, ISO 21940-11 balance grades).
    """

    level_mg: tuple[float, float, float]
    hz: float | None = None
    engine_order: float | None = None
    phase_rad: float = 0.0


def _transmissibility(fixing: SensorFixing, sample_rate_hz: int) -> tuple[np.ndarray, np.ndarray]:
    """Base-to-housing acceleration filter ``(2 z w s + w^2) / (s^2 + 2 z w s + w^2)``,
    by the bilinear transform pre-warped at the resonance so it rings where it should."""
    wn = 2.0 * sample_rate_hz * math.tan(math.pi * fixing.resonance_hz / sample_rate_hz)
    c = 2.0 * sample_rate_hz
    zeta = fixing.damping_ratio
    b_s = (0.0, 2.0 * zeta * wn, wn * wn)
    a_s = (1.0, 2.0 * zeta * wn, wn * wn)
    b = np.array(
        [
            b_s[0] * c * c + b_s[1] * c + b_s[2],
            2.0 * (b_s[2] - b_s[0] * c * c),
            b_s[0] * c * c - b_s[1] * c + b_s[2],
        ]
    )
    a = np.array(
        [
            a_s[0] * c * c + a_s[1] * c + a_s[2],
            2.0 * (a_s[2] - a_s[0] * c * c),
            a_s[0] * c * c - a_s[1] * c + a_s[2],
        ]
    )
    return b / a[0], a / a[0]


def _impact_ring(fixing: SensorFixing, sample_rate_hz: int) -> tuple[np.ndarray, np.ndarray]:
    """A two-pole ring at the housing's contact frequency: a unit-velocity (m/s)
    impulse comes out as a decaying sine peaking at about ``2 pi impact_hz`` m/s^2."""
    w = _TWO_PI * fixing.impact_hz / sample_rate_hz
    r = math.exp(-fixing.impact_damping_ratio * _TWO_PI * fixing.impact_hz / sample_rate_hz)
    gain = _TWO_PI * fixing.impact_hz * math.sin(w) / _G_MPS2 * _COUNTS_PER_G
    return np.array([gain]), np.array([1.0, -2.0 * r * math.cos(w), r * r])


@dataclass(slots=True)
class SensorConfounders:
    """The confounders one sensor gets, with their running state."""

    fixing: SensorFixing | None = None
    slip: MountSlip | None = None
    flat_spot: FlatSpot | None = None
    accessories: tuple[AccessoryTone, ...] = ()
    distance_km: float = 0.0
    flat_spot_angle_rad: float = 0.0
    _accessory_angles: list[float] = field(default_factory=list, repr=False)
    _fixing_state: np.ndarray | None = field(default=None, repr=False)
    _ring_state: np.ndarray | None = field(default=None, repr=False)
    # Whether the housing was floating at the end of the last frame, and the
    # relative velocity (m/s) it has gained so far.
    _floating: bool = field(default=False, repr=False)
    _float_velocity: float = field(default=0.0, repr=False)
    _floating_s: float = field(default=0.0, repr=False)
    # How far the housing has turned on its fixing (deg), and how long (s) the
    # sensor has run.
    tilt_deg: float = 0.0
    elapsed_s: float = 0.0

    def mechanical(
        self, *, wheel_hz: float, engine_hz: float, speed_kmh: float, samples: int, dt: float
    ) -> np.ndarray:
        """What the car adds at this sensor this frame (counts): flat spots and accessories."""
        out = np.zeros((samples, 3), dtype=np.float64)
        frame_s = samples * dt
        if self.accessories:
            out += self._accessories(engine_hz, samples, dt)
        spot = self.flat_spot
        if spot is not None and wheel_hz > 0:
            angle = self.flat_spot_angle_rad + _TWO_PI * wheel_hz * np.arange(samples) * dt
            level = spot.remaining(self.distance_km) * _COUNTS_PER_MG
            axes = np.asarray(spot.t1_mg) * level
            wave = np.zeros(samples)
            for n, rel in enumerate(spot.harmonic_levels(), start=1):
                wave += rel * np.sin(n * (angle + spot.phase_rad))
            out += wave[:, None] * axes[None, :]
            self.flat_spot_angle_rad = (
                self.flat_spot_angle_rad + _TWO_PI * wheel_hz * frame_s
            ) % _TWO_PI
        self.distance_km += max(0.0, speed_kmh) / 3600.0 * frame_s
        return out

    def _accessories(self, engine_hz: float, samples: int, dt: float) -> np.ndarray:
        out = np.zeros((samples, 3), dtype=np.float64)
        if len(self._accessory_angles) != len(self.accessories):
            self._accessory_angles = [tone.phase_rad for tone in self.accessories]
        offsets = np.arange(samples) * dt
        for index, tone in enumerate(self.accessories):
            hz = tone.hz if tone.hz is not None else engine_hz * (tone.engine_order or 0.0)
            angle = self._accessory_angles[index]
            self._accessory_angles[index] = (angle + _TWO_PI * hz * samples * dt) % _TWO_PI
            if hz <= 0:
                continue
            wave = np.sin(angle + _TWO_PI * hz * offsets)
            out += wave[:, None] * (np.asarray(tone.level_mg) * _COUNTS_PER_MG)[None, :]
        return out

    def through_fixing(self, signal: np.ndarray, sample_rate_hz: int) -> np.ndarray:
        """The car's motion at the fixing, as the housing on that fixing reads it (counts)."""
        fixing = self.fixing
        if fixing is None:
            return signal
        b, a = _transmissibility(fixing, sample_rate_hz)
        if self._fixing_state is None:
            self._fixing_state = np.zeros((2, 3))
        filtered, self._fixing_state = lfilter(b, a, signal, axis=0, zi=self._fixing_state)
        housing: np.ndarray = np.asarray(filtered)
        if fixing.rattle_g is None:
            return housing
        return self._rattle(housing, fixing, sample_rate_hz)

    def slipped(self, reading: np.ndarray, sample_rate_hz: int) -> np.ndarray:
        """The housing's whole reading (counts), turned by however far it has slipped so far.

        Call once per frame after ``through_fixing``: the sag of the frame's
        floating time and any step due in it apply from the next frame on.
        """
        frame_s = len(reading) / sample_rate_hz
        start_s, self.elapsed_s = self.elapsed_s, self.elapsed_s + frame_s
        slip = self.slip
        if slip is None:
            return reading
        out = reading
        if self.tilt_deg != 0.0:
            # Row vectors: v @ R is R^T v, the fixed reading in the turned housing's axes.
            out = reading @ rotation_about(np.asarray(slip.axis), math.radians(self.tilt_deg))
        sag = slip.sag_deg_per_floating_s * self._floating_s
        steps = sum(deg for at_s, deg in slip.steps if start_s <= at_s < self.elapsed_s)
        self.tilt_deg = float(np.clip(self.tilt_deg + sag + steps, -slip.max_deg, slip.max_deg))
        self._floating_s = 0.0
        return out

    def _rattle(self, housing: np.ndarray, fixing: SensorFixing, sample_rate_hz: int) -> np.ndarray:
        axis = np.asarray(fixing.rattle_axis, dtype=np.float64)
        axis /= np.linalg.norm(axis)
        along_g = housing @ axis / _COUNTS_PER_G
        hold_g = float(fixing.rattle_g)  # type: ignore[arg-type]
        floating = np.abs(along_g) > hold_g
        self._floating_s += float(np.count_nonzero(floating)) / sample_rate_hz
        # Floating, the housing no longer follows the car past the hold-down.
        clipped = np.clip(along_g, -hold_g, hold_g)
        out = housing + np.outer((clipped - along_g) * _COUNTS_PER_G, axis)
        # It lands at the end of each excursion with the relative velocity the
        # excess acceleration gave it (m/s, signed), and rings.
        gained = np.cumsum((along_g - clipped) * _G_MPS2 / sample_rate_hz)
        before = np.r_[self._floating, floating[:-1]]
        starts = np.flatnonzero(floating & ~before)
        landings = np.flatnonzero(~floating & before)
        impulses = np.zeros(len(along_g))
        for landing in landings:
            earlier = starts[starts < landing]
            if earlier.size:
                start = int(earlier[-1])
                velocity = gained[landing - 1] - (gained[start - 1] if start > 0 else 0.0)
            else:  # floating since the last frame
                velocity = self._float_velocity + gained[landing - 1]
            impulses[landing] = -velocity
        self._floating = bool(floating[-1])
        if self._floating:
            last_start = int(starts[-1]) if starts.size else 0
            carried = self._float_velocity if not starts.size else 0.0
            self._float_velocity = (
                carried + gained[-1] - (gained[last_start - 1] if last_start > 0 else 0.0)
            )
        else:
            self._float_velocity = 0.0
        b, a = _impact_ring(fixing, sample_rate_hz)
        if self._ring_state is None:
            self._ring_state = np.zeros(2)
        ring, self._ring_state = lfilter(b, a, impulses, zi=self._ring_state)
        return out + np.outer(ring, axis)
