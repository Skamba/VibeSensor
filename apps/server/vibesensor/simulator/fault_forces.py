"""How hard a fault's force shakes each simulated sensor.

A fault turns with an order and pulls with a force. An unbalanced mass ``m``
at radius ``r`` pulls with ``m r w^2`` (ISO 21940-11), so with the square of
the speed; a shape fault (a tyre's radial force variation, a brake disc's
thickness variation, an engine's firing pulses) pulls with a force its shape
or load fixes, the same at every speed. A sensor reads that force through the
structure between them:

- a wheel's force shakes its own knuckle through the quarter car (the
  unsprung mass on the tyre and suspension: wheel hop near 12 Hz vertically,
  the wheel's fore-aft mode near 17 Hz) and the body through the suspension;
- a propshaft's or an engine's force reaches the body through rubber mounts;
  a sensor on the engine or gearbox rides on the shaking powertrain itself;
- whatever reaches the body reaches a knuckle through its control arms
  (fore-aft and sideways) and suspension (vertically), and an engine or
  gearbox sensor through the powertrain's mounts.

The basis of each number is in ``docs/simulator_realism.md`` ("Fault
amplitudes").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from vibesensor.simulator.road_vibration import QuarterCar, SensorMount

__all__ = ["OrderForce", "order_force_mg"]

_G_MPS2 = 9.80665
_QUARTER_CAR = QuarterCar()

# The wheel's fore-aft mode: the unsprung mass on the suspension's
# longitudinal compliance, 15-20 Hz in a rolling car, damped by the bushings'
# rubber and the tyre's slip.
_FORE_AFT_HZ = 17.0
_FORE_AFT_DAMPING = 0.15
# Engine and gearbox (about 200 kg) on rubber mounts ringing at 6-12 Hz with
# 5-15 % damping; the differential and propshaft bearings sit on rubber of
# the same class.
_POWERTRAIN_KG = 200.0
_MOUNT_HZ = 10.0
_MOUNT_DAMPING = 0.1
# How a stiff point of the body (a mount's or bearing's attachment) moves
# under a force there: like a mass of about 50 kg below 100 Hz.
_BODY_POINT_KG = 50.0
# A sensor fixed a little off square (about 10 degrees) reads a fifth of the
# strongest axis on the others.
_MISALIGNMENT = 0.2

# (fore-aft, lateral, vertical) share of each source's force.
_WHEEL_PLANE = (1.0, 0.0, 1.0)
_SHAFT_PLANE = (0.0, 1.0, 1.0)
_VERTICAL = (0.0, 0.0, 1.0)


@dataclass(frozen=True, slots=True)
class OrderForce:
    """A force turning with the order ``order_key``, ``multiple`` times per turn.

    ``order_key`` is a simulator order (``wheel_1x``, ``shaft_1x``,
    ``engine_1x``, ...; a wheel order may name its wheel,
    ``wheel_1x@front-left``). The force is an unbalance of ``unbalance_g`` at
    ``radius_m`` (``None``: the wheel's rim flange, where balancing weights
    go) plus ``force_n`` of fixed amplitude. ``direction`` is its share along
    (fore-aft, lateral, vertical); ``None`` takes the source's own: a wheel's
    force turns in the wheel's plane, a propshaft's across the shaft, an
    engine's free force is vertical.
    """

    order_key: str
    multiple: float = 1.0
    unbalance_g: float = 0.0
    radius_m: float | None = None
    force_n: float = 0.0
    direction: tuple[float, float, float] | None = None

    def scaled(self, gain: float, multiple_scale: float = 1.0) -> OrderForce:
        """This force times *gain*, at *multiple_scale* times its rate."""
        return replace(
            self,
            multiple=self.multiple * multiple_scale,
            unbalance_g=self.unbalance_g * gain,
            force_n=self.force_n * gain,
        )

    def newtons(self, hz: float, rim_radius_m: float) -> float:
        """The force's amplitude when it turns at *hz*."""
        radius_m = rim_radius_m if self.radius_m is None else self.radius_m
        unbalance_kgm = self.unbalance_g / 1000.0 * radius_m
        return unbalance_kgm * (2.0 * math.pi * hz) ** 2 + self.force_n


def order_force_mg(
    force: OrderForce, hz: float, mount: SensorMount, rim_radius_m: float
) -> tuple[float, float, float]:
    """The fore-aft, lateral and vertical tone (mg) *force* at *hz* gives a sensor on *mount*."""
    if hz <= 0.0:
        return (0.0, 0.0, 0.0)
    base = force.order_key.partition("@")[0]
    newtons = force.newtons(hz, rim_radius_m)
    if base.startswith("wheel_"):
        direction = force.direction or _WHEEL_PLANE
        if mount is SensorMount.KNUCKLE:
            per_n = (_fore_aft_knuckle(hz), 0.0, _vertical(hz, unsprung=True))
        else:
            body = (_fore_aft_body(hz), 0.0, _vertical(hz, unsprung=False))
            per_n = _from_body(body, hz, mount)
    else:
        engine = not base.startswith("shaft_")
        direction = force.direction or (_VERTICAL if engine else _SHAFT_PLANE)
        if engine and mount is SensorMount.POWERTRAIN:
            per_n = (_on_powertrain(hz),) * 3
        else:
            per_n = _from_body((_isolated(hz) / _BODY_POINT_KG,) * 3, hz, mount)
    accel = [newtons * share * gain for share, gain in zip(direction, per_n, strict=True)]
    strongest = max(accel)
    return tuple(  # type: ignore[return-value]
        max(axis, _MISALIGNMENT * strongest) / _G_MPS2 * 1000.0 for axis in accel
    )


def _vertical(hz: float, *, unsprung: bool) -> float:
    """Vertical acceleration (m/s^2 per N on the unsprung mass) of the unsprung or sprung mass."""
    car = _QUARTER_CAR
    w = 2.0 * math.pi * hz
    link = car.suspension_n_per_m + 1j * w * car.damper_ns_per_m
    wheel = car.tyre_n_per_m + link - car.unsprung_kg * w * w
    body = link - car.sprung_kg * w * w
    det = wheel * body - link * link
    return w * w * abs((body if unsprung else link) / det)


def _fore_aft_link(hz: float) -> tuple[complex, complex]:
    """The fore-aft bushing's dynamic stiffness and the knuckle's on it (N/m)."""
    w = 2.0 * math.pi * hz
    wn = 2.0 * math.pi * _FORE_AFT_HZ
    mass = _QUARTER_CAR.unsprung_kg
    link = mass * wn * wn + 1j * w * 2.0 * _FORE_AFT_DAMPING * mass * wn
    return link, link - mass * w * w


def _fore_aft_knuckle(hz: float) -> float:
    w = 2.0 * math.pi * hz
    return w * w / abs(_fore_aft_link(hz)[1])


def _fore_aft_body(hz: float) -> float:
    """Body fore-aft acceleration per N: what the bushing passes on, over the sprung mass."""
    link, knuckle = _fore_aft_link(hz)
    return abs(link / knuckle) / _QUARTER_CAR.sprung_kg


def _transmissibility(hz: float, natural_hz: float, damping: float) -> float:
    """Single-degree-of-freedom force (or base) transmissibility."""
    ratio = hz / natural_hz
    damped = (2.0 * damping * ratio) ** 2
    return math.sqrt((1.0 + damped) / ((1.0 - ratio * ratio) ** 2 + damped))


def _isolated(hz: float) -> float:
    """Share of a powertrain or propshaft force its rubber mounts pass to the body."""
    return _transmissibility(hz, _MOUNT_HZ, _MOUNT_DAMPING)


def _on_powertrain(hz: float) -> float:
    """Acceleration (m/s^2 per N) of the powertrain on its mounts under a force inside it."""
    ratio = hz / _MOUNT_HZ
    dynamic = complex(1.0 - ratio * ratio, 2.0 * _MOUNT_DAMPING * ratio)
    return ratio * ratio / (_POWERTRAIN_KG * abs(dynamic))


def _from_body(
    body: tuple[float, float, float], hz: float, mount: SensorMount
) -> tuple[float, float, float]:
    """What a sensor on *mount* reads of body motion *body*.

    The powertrain follows it through its mounts. A knuckle hangs on control
    arms whose bushings are stiff fore-aft and sideways, so it follows the
    body (subframe) there; vertically it rides on the tyre and only the
    suspension spring and damper drive it.
    """
    if mount is SensorMount.BODY:
        return body
    if mount is SensorMount.POWERTRAIN:
        gain = _isolated(hz)
        return (body[0] * gain, body[1] * gain, body[2] * gain)
    car = _QUARTER_CAR
    w = 2.0 * math.pi * hz
    link = car.suspension_n_per_m + 1j * w * car.damper_ns_per_m
    vertical = abs(link / (car.tyre_n_per_m + link - car.unsprung_kg * w * w))
    return (body[0], body[1], body[2] * vertical)
