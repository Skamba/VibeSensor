"""Reference-resolution helpers for diagnostics order analysis."""

from __future__ import annotations

from vibesensor.domain import OrderReferenceSpec
from vibesensor.shared.constants.units import KMH_TO_MPS, SECONDS_PER_MINUTE

from ._context import DiagnosticsContext
from ._types import AnalysisSampleInput, Sample, ensure_analysis_sample


def _tire_reference_from_context(context: DiagnosticsContext) -> tuple[float | None, str | None]:
    """Return the wheel reference circumference and the metadata source name."""
    spec = _order_reference_spec_from_context(context)
    if spec is not None and spec.supports_wheel_reference:
        return spec.tire_circumference_m, "order_reference_spec"

    direct = context.tire_circumference_m
    if direct is not None and direct > 0:
        return direct, "diagnostics_context.tire_circumference_m"
    return None, None


def _order_reference_spec_from_context(
    context: DiagnosticsContext,
    sample: Sample | None = None,
) -> OrderReferenceSpec | None:
    """Return the effective order-reference spec for one optional sample override."""
    return context.effective_order_reference_spec(sample)


def _effective_engine_rpm(
    sample: AnalysisSampleInput,
    context: DiagnosticsContext,
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    """Resolve measured or inferred engine rpm plus the source label."""
    typed_sample = ensure_analysis_sample(sample)
    measured = typed_sample.engine_rpm
    if measured is not None and measured > 0:
        return measured, typed_sample.engine_rpm_source or "measured"

    estimated_in_sample = typed_sample.engine_rpm_estimated
    if estimated_in_sample is not None and estimated_in_sample > 0:
        return estimated_in_sample, "estimated_from_speed_and_ratios"

    speed_kmh = typed_sample.speed_kmh
    spec = _order_reference_spec_from_context(context, typed_sample)
    if (
        speed_kmh is not None
        and speed_kmh > 0
        and spec is not None
        and spec.supports_engine_reference
    ):
        rpm = spec.engine_rpm_from_speed_kmh(speed_kmh)
        if rpm is not None and rpm > 0:
            return rpm, "estimated_from_speed_and_ratios"

    final_drive_ratio = (
        typed_sample.final_drive_ratio
        if typed_sample.final_drive_ratio is not None
        else context.final_drive_ratio
    )
    gear_val = typed_sample.gear
    gear_ratio = gear_val if gear_val is not None else context.current_gear_ratio
    if (
        speed_kmh is None
        or speed_kmh <= 0
        or tire_circumference_m is None
        or tire_circumference_m <= 0
        or final_drive_ratio is None
        or final_drive_ratio <= 0
        or gear_ratio is None
        or gear_ratio <= 0
    ):
        return None, "missing"

    whz = speed_kmh * KMH_TO_MPS / tire_circumference_m
    rpm = whz * final_drive_ratio * gear_ratio * SECONDS_PER_MINUTE
    return float(rpm), "estimated_from_speed_and_ratios"
