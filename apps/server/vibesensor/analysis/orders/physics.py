"""Rotational-frequency calculators and order-hypothesis catalog.

Pure physics: wheel / driveshaft / engine Hz from speed and vehicle
parameters, plus the hypotheses tested during order analysis: the wheel and
driveshaft orders, and the engine orders the car's engine profile excites.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from vibesensor.analysis._reference_resolution import (
    _effective_engine_rpm,
    _order_reference_spec_from_context,
)
from vibesensor.analysis._types import Sample
from vibesensor.common.units import SECONDS_PER_MINUTE
from vibesensor.domain.engine_profile import EngineProfile, engine_orders
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.order_reference import OrderReferenceSpec, wheel_hz_from_speed_kmh
from vibesensor.dsp.order_bands import (
    RIGID_ORDER_PATH_COMPLIANCE,
    WHEEL_ORDER_PATH_COMPLIANCE,
)
from vibesensor.recording.run_schema import RunMetadata

# ═══════════════════════════════════════════════════════════════════════════
# Hz helpers
# ═══════════════════════════════════════════════════════════════════════════


def _wheel_hz(
    sample: Sample,
    tire_circumference_m: float | None,
    context: RunMetadata | None = None,
    order_reference_spec: OrderReferenceSpec | None = None,
) -> float | None:
    """Return wheel rotational frequency from speed plus optional reference data."""
    speed_kmh = sample.speed_kmh
    if speed_kmh is None or speed_kmh <= 0:
        return None
    spec = order_reference_spec
    if spec is None and context is not None:
        spec = _order_reference_spec_from_context(context, sample)
    if spec is not None and spec.supports_wheel_reference:
        return spec.wheel_hz_from_speed_kmh(speed_kmh)
    if tire_circumference_m is None:
        return None
    return wheel_hz_from_speed_kmh(speed_kmh, tire_circumference_m)


def _driveshaft_hz(
    sample: Sample,
    context: RunMetadata,
    tire_circumference_m: float | None,
) -> float | None:
    """Return driveshaft frequency from the best available wheel/final-drive inputs."""
    speed_kmh = sample.speed_kmh
    spec = _order_reference_spec_from_context(context, sample)
    if (
        speed_kmh is not None
        and speed_kmh > 0
        and spec is not None
        and spec.supports_driveshaft_reference
    ):
        return spec.driveshaft_hz_from_speed_kmh(speed_kmh)
    whz = _wheel_hz(
        sample,
        tire_circumference_m,
        context,
        order_reference_spec=spec,
    )
    fd = (
        sample.final_drive_ratio
        if sample.final_drive_ratio is not None
        else context.final_drive_ratio
    )
    if whz is None or fd is None or fd <= 0:
        return None
    return float(whz * fd)


def _engine_hz(
    sample: Sample,
    context: RunMetadata,
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    """Return engine rotational frequency plus the source label used to derive it."""
    rpm, src = _effective_engine_rpm(
        sample,
        context,
        tire_circumference_m,
    )
    if rpm is None or rpm <= 0:
        return None, src
    return float(rpm / SECONDS_PER_MINUTE), src


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

    def predicted_hz(
        self,
        sample: Sample,
        context: RunMetadata,
        tire_circumference_m: float | None,
    ) -> tuple[float | None, str]:
        if self.order_label_base == "wheel":
            base = _wheel_hz(sample, tire_circumference_m, context)
            return (base * self.order, "speed+tire") if base is not None else (None, "missing")
        if self.order_label_base == "driveshaft":
            base = _driveshaft_hz(sample, context, tire_circumference_m)
            if base is None:
                return None, "missing"
            return base * self.order, "speed+tire+final_drive"
        if self.order_label_base == "engine":
            base, src = _engine_hz(sample, context, tire_circumference_m)
            return (base * self.order, src) if base is not None else (None, src)
        return None, "missing"


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
