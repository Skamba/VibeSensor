"""Rotational-frequency calculators and order-hypothesis catalog.

Pure physics: wheel / driveshaft / engine Hz from speed and vehicle
parameters, plus the static table of hypotheses tested during order analysis.
"""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain import OrderReferenceSpec, VibrationSource
from vibesensor.shared.constants.units import KMH_TO_MPS, SECONDS_PER_MINUTE
from vibesensor.use_cases.diagnostics._context import DiagnosticsContext
from vibesensor.use_cases.diagnostics._reference_resolution import (
    _effective_engine_rpm,
    _order_reference_spec_from_context,
)
from vibesensor.use_cases.diagnostics._types import (
    AnalysisSampleInput,
    Sample,
    ensure_analysis_sample,
)

# ═══════════════════════════════════════════════════════════════════════════
# Hz helpers
# ═══════════════════════════════════════════════════════════════════════════


def _wheel_hz(
    sample: AnalysisSampleInput,
    tire_circumference_m: float | None,
    context: DiagnosticsContext | None = None,
    order_reference_spec: OrderReferenceSpec | None = None,
) -> float | None:
    typed_sample = ensure_analysis_sample(sample)
    speed_kmh = typed_sample.speed_kmh
    if speed_kmh is None or speed_kmh <= 0:
        return None
    spec = order_reference_spec
    if spec is None and context is not None:
        spec = _order_reference_spec_from_context(context, typed_sample)
    if spec is not None and spec.supports_wheel_reference:
        return spec.wheel_hz_from_speed_kmh(speed_kmh)
    if tire_circumference_m is None or tire_circumference_m <= 0:
        return None
    return float(speed_kmh * KMH_TO_MPS / tire_circumference_m)


def _driveshaft_hz(
    sample: AnalysisSampleInput,
    context: DiagnosticsContext,
    tire_circumference_m: float | None,
) -> float | None:
    typed_sample = ensure_analysis_sample(sample)
    speed_kmh = typed_sample.speed_kmh
    spec = _order_reference_spec_from_context(context, typed_sample)
    if (
        speed_kmh is not None
        and speed_kmh > 0
        and spec is not None
        and spec.supports_driveshaft_reference
    ):
        return spec.driveshaft_hz_from_speed_kmh(speed_kmh)
    whz = _wheel_hz(
        typed_sample,
        tire_circumference_m,
        context,
        order_reference_spec=spec,
    )
    fd = (
        typed_sample.final_drive_ratio
        if typed_sample.final_drive_ratio is not None
        else context.final_drive_ratio
    )
    if whz is None or fd is None or fd <= 0:
        return None
    return float(whz * fd)


def _engine_hz(
    sample: AnalysisSampleInput,
    context: DiagnosticsContext,
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    rpm, src = _effective_engine_rpm(
        ensure_analysis_sample(sample),
        context,
        tire_circumference_m,
    )
    if rpm is None or rpm <= 0:
        return None, src
    return float(rpm / SECONDS_PER_MINUTE), src


def _order_label(order: int, base: str) -> str:
    """Return a language-neutral order label like ``'1x wheel'``."""
    return f"{order}x {base}"


# ═══════════════════════════════════════════════════════════════════════════
# Hypothesis catalog
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(slots=True, frozen=True)
class OrderHypothesis:
    key: str
    suspected_source: VibrationSource
    order_label_base: str
    order: int
    # Path compliance factor: models how much the mechanical transmission
    # path between the vibration source and the sensor dampens/broadens
    # the frequency peak.  1.0 = stiff direct coupling (driveshaft), higher
    # values = softer compliant path (wheel through suspension bushings).
    # Used to widen match tolerance and soften error/correlation penalties.
    path_compliance: float = 1.0

    def predicted_hz(
        self,
        sample: Sample,
        context: DiagnosticsContext,
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


# Pre-built hypothesis objects – avoids re-creating 6 frozen dataclass
# instances on every call.  The thin wrapper function below is kept so that
# test monkeypatches (which replace the callable) keep working.
_ORDER_HYPOTHESES: tuple[OrderHypothesis, ...] = (
    # Wheel orders travel through tire sidewall → hub → knuckle → control
    # arms → bushings → subframe → body → sensor.  Each rubber component
    # broadens the peak and reduces tracking precision.
    OrderHypothesis("wheel_1x", VibrationSource.WHEEL_TIRE, "wheel", 1, path_compliance=1.5),
    OrderHypothesis("wheel_2x", VibrationSource.WHEEL_TIRE, "wheel", 2, path_compliance=1.5),
    # Driveshaft has a shorter, stiffer path: shaft → diff → subframe → body.
    OrderHypothesis(
        "driveshaft_1x",
        VibrationSource.DRIVELINE,
        "driveshaft",
        1,
        path_compliance=1.0,
    ),
    OrderHypothesis(
        "driveshaft_2x",
        VibrationSource.DRIVELINE,
        "driveshaft",
        2,
        path_compliance=1.0,
    ),
    # Engine is stiffly mounted on most vehicles.
    OrderHypothesis("engine_1x", VibrationSource.ENGINE, "engine", 1, path_compliance=1.0),
    OrderHypothesis("engine_2x", VibrationSource.ENGINE, "engine", 2, path_compliance=1.0),
)


def _order_hypotheses() -> tuple[OrderHypothesis, ...]:
    return _ORDER_HYPOTHESES
