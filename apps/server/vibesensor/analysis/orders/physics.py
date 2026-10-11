"""Rotational-frequency calculators and order-hypothesis catalog.

Pure physics: wheel / driveshaft / engine Hz from speed and vehicle
parameters, plus the hypotheses tested during order analysis: the wheel and
driveshaft orders, and the engine orders the car's engine profile excites.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

import numpy as np
import numpy.typing as npt

from vibesensor.analysis._reference_resolution import effective_engine_rpm, wheel_hz_columns
from vibesensor.analysis.drive_table import DriveTable
from vibesensor.common.units import SECONDS_PER_MINUTE
from vibesensor.domain.engine_profile import EngineProfile, engine_orders
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.locations import wheel_axle
from vibesensor.dsp.order_bands import (
    RIGID_ORDER_PATH_COMPLIANCE,
    WHEEL_ORDER_PATH_COMPLIANCE,
)
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sample_columns import first_seen

# ═══════════════════════════════════════════════════════════════════════════
# Reference frequencies
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ReferenceColumns:
    """Each sample's ``reference_columns`` for the orders of one rotation, as columns.

    Its frequency (NaN where there is none), whether it has one, and its
    source (an index into *source_names*).
    """

    hz: npt.NDArray[np.float64]
    known: npt.NDArray[np.bool_]
    source: npt.NDArray[np.intp]
    source_names: Sequence[str]


def _wheel_hz(
    table: DriveTable,
    context: RunMetadata,
    tire_circumference_m: float | None,
    *,
    own_axle: bool,
) -> npt.NDArray[np.float64]:
    """Each sample's wheel rotational frequency from its speed (NaN where there is none).

    From the car's tires where its order reference has them, else from
    *tire_circumference_m*. With *own_axle*, a wheel sensor's sample turns
    with the tires on its own axle (staggered tires turn the front and rear
    wheels at different rates); any other sensor, and the driveline, take the
    effective tire.
    """
    spec = context.order_reference_spec
    if spec is not None and spec.supports_wheel_reference:
        if not own_axle:
            return wheel_hz_columns(table.speed_kmh, spec.tire_circumference_m)
        circumference_m = np.array(
            [
                spec.tire_setup.axle_tire_circumference_m(wheel_axle(location))
                for location, _name, _client in table.sensors
            ],
            dtype=np.float64,
        )
        return wheel_hz_columns(table.speed_kmh, circumference_m[table.sensor_of])
    if tire_circumference_m is None:
        return np.full(table.size, np.nan)
    return wheel_hz_columns(table.speed_kmh, tire_circumference_m)


def _driveshaft_hz(
    table: DriveTable,
    context: RunMetadata,
    tire_circumference_m: float | None,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.bool_]]:
    """Each sample's driveshaft frequency, and whether it has one.

    From the car's order reference at the sample's own final drive where that
    has the driveline, else from its wheel frequency and the sample's or the
    run's final drive.
    """
    speed = table.speed_kmh
    hz = np.full(table.size, np.nan)
    known = np.zeros(table.size, dtype=np.bool_)
    spec = context.order_reference_spec
    if spec is not None:
        final_drive = np.where(
            table.has_final_drive_ratio, table.final_drive_ratio, spec.final_drive_ratio
        )
        via_spec = (
            table.has_speed & (speed > 0) & spec.supports_wheel_reference & (final_drive > 0.0)
        )
        wheel_hz = wheel_hz_columns(speed, spec.tire_circumference_m)
        with np.errstate(all="ignore"):
            from_spec = wheel_hz * final_drive
        placed = via_spec & ~np.isnan(wheel_hz) & np.isfinite(from_spec)
        hz[placed] = from_spec[placed]
        known[placed] = True
    else:
        via_spec = np.zeros(table.size, dtype=np.bool_)
    context_drive = context.final_drive_ratio
    final_drive = np.where(
        table.has_final_drive_ratio,
        table.final_drive_ratio,
        context_drive if context_drive is not None else np.nan,
    )
    wheel_hz = _wheel_hz(table, context, tire_circumference_m, own_axle=False)
    with np.errstate(all="ignore"):
        from_wheel = wheel_hz * final_drive
    placed = (
        ~via_spec
        & ~np.isnan(wheel_hz)
        & (table.has_final_drive_ratio | (context_drive is not None))
        & ~(final_drive <= 0)
    )
    hz[placed] = from_wheel[placed]
    known[placed] = True
    return hz, known


def _order_label(order: float, base: str) -> str:
    """Return a language-neutral order label like ``'1x wheel'`` or ``'1.5x engine'``."""
    return f"{order:g}x {base}"


# ═══════════════════════════════════════════════════════════════════════════
# Hypothesis catalog
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(slots=True, frozen=True)
class OrderHypothesis:
    key: str
    suspected_source: VibrationSource
    order_label_base: str
    order: float
    # Path compliance factor: models how much the mechanical transmission
    # path between the vibration source and the sensor dampens/broadens
    # the frequency peak.  1.0 = stiff direct coupling (driveshaft), higher
    # values = softer compliant path (wheel through suspension bushings).
    # Used to widen match tolerance and soften error/correlation penalties.
    path_compliance: float = 1.0


def reference_columns(
    order_label_base: str,
    table: DriveTable,
    context: RunMetadata,
    tire_circumference_m: float | None,
) -> ReferenceColumns:
    """Each sample's frequency of the rotation an order of *order_label_base* is a multiple of.

    The same for every order of one rotation (a wheel's T1 to T6), so it is
    worked out once per drive for all of them, with its source.
    """
    if order_label_base == "engine":
        engine = effective_engine_rpm(table, context, tire_circumference_m)
        known = engine.known & ~(engine.rpm <= 0)
        return ReferenceColumns(
            hz=np.where(known, engine.rpm / SECONDS_PER_MINUTE, np.nan),
            known=known,
            source=engine.source_of,
            source_names=engine.sources,
        )
    if order_label_base == "wheel":
        hz = _wheel_hz(table, context, tire_circumference_m, own_axle=True)
        known = ~np.isnan(hz) & table.has_speed & ~(table.speed_kmh <= 0)
        source_name = "speed+tire"
    elif order_label_base == "driveshaft":
        hz, known = _driveshaft_hz(table, context, tire_circumference_m)
        source_name = "speed+tire+final_drive"
    else:
        hz, known = np.full(table.size, np.nan), np.zeros(table.size, dtype=np.bool_)
        source_name = "missing"
    source, source_names = first_seen(
        np.where(known, 0, 1).astype(np.intp), [source_name, "missing"]
    )
    return ReferenceColumns(hz=hz, known=known, source=source, source_names=source_names)


# The road-speed orders, the same for every car. Wheel orders travel through
# tire sidewall -> hub -> knuckle -> control arms -> bushings -> subframe ->
# body -> sensor; each rubber component broadens the peak and reduces tracking
# precision. The driveshaft has a shorter, stiffer path: shaft -> diff ->
# subframe -> body.
_ROAD_HYPOTHESES: tuple[OrderHypothesis, ...] = (
    OrderHypothesis(
        "wheel_1x",
        VibrationSource.WHEEL_TIRE,
        "wheel",
        1,
        path_compliance=WHEEL_ORDER_PATH_COMPLIANCE,
    ),
    OrderHypothesis(
        "wheel_2x",
        VibrationSource.WHEEL_TIRE,
        "wheel",
        2,
        path_compliance=WHEEL_ORDER_PATH_COMPLIANCE,
    ),
    OrderHypothesis(
        "driveshaft_1x",
        VibrationSource.DRIVELINE,
        "driveshaft",
        1,
        path_compliance=RIGID_ORDER_PATH_COMPLIANCE,
    ),
    OrderHypothesis(
        "driveshaft_2x",
        VibrationSource.DRIVELINE,
        "driveshaft",
        2,
        path_compliance=RIGID_ORDER_PATH_COMPLIANCE,
    ),
)


# A tyre's non-uniformity or parking flat spot shakes at the wheel's higher
# orders along with its first (a short flat is a pulse per turn, rich in
# harmonics). They are matched only to tell an engine or driveline order that
# lands on one of them from a fault of its own, never diagnosed.
WHEEL_HARMONIC_HYPOTHESES: tuple[OrderHypothesis, ...] = tuple(
    OrderHypothesis(
        f"wheel_{order}x",
        VibrationSource.WHEEL_TIRE,
        "wheel",
        order,
        path_compliance=WHEEL_ORDER_PATH_COMPLIANCE,
    )
    for order in (3, 4, 5, 6)
)


@cache
def _order_hypotheses(engine_profile: EngineProfile | None = None) -> tuple[OrderHypothesis, ...]:
    """The hypotheses an order analysis tests: the road-speed orders and the engine's.

    The engine orders are the ones *engine_profile* excites (``engine_orders``);
    without a profile E1 and E2. The engine is stiffly mounted on most vehicles.
    """
    return _ROAD_HYPOTHESES + tuple(
        OrderHypothesis(
            order.key,
            VibrationSource.ENGINE,
            "engine",
            order.multiple,
            path_compliance=RIGID_ORDER_PATH_COMPLIANCE,
        )
        for order in engine_orders(engine_profile)
    )
