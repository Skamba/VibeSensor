"""Reference-resolution helpers for diagnostics order analysis."""

from __future__ import annotations

from vibesensor.domain import OrderReferenceSpec
from vibesensor.shared.constants.units import KMH_TO_MPS, SECONDS_PER_MINUTE
from vibesensor.shared.types.run_schema import RunMetadata

from ._metadata import current_gear_ratio, effective_order_reference_spec, final_drive_ratio
from ._types import Sample


def _tire_reference_from_context(context: RunMetadata) -> tuple[float | None, str | None]:
    """Return the wheel reference circumference and the metadata source name."""
    spec = _order_reference_spec_from_context(context)
    if spec is not None and spec.supports_wheel_reference:
        return spec.tire_circumference_m, "order_reference_spec"

    direct = context.tire_circumference_m
    if direct is not None and direct > 0:
        return direct, "diagnostics_context.tire_circumference_m"
    return None, None


def _order_reference_spec_from_context(
    context: RunMetadata,
    sample: Sample | None = None,
) -> OrderReferenceSpec | None:
    """Return the effective order-reference spec for one optional sample override."""
    return effective_order_reference_spec(context, sample)


def _effective_engine_rpm(
    sample: Sample,
    context: RunMetadata,
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    """Resolve measured or inferred engine rpm plus the source label."""
    measured = sample.engine_rpm
    if measured is not None and measured > 0:
        return measured, sample.engine_rpm_source or "measured"

    speed_kmh = sample.speed_kmh
    spec = _order_reference_spec_from_context(context, sample)
    if (
        speed_kmh is not None
        and speed_kmh > 0
        and spec is not None
        and spec.supports_engine_reference
    ):
        rpm = spec.engine_rpm_from_speed_kmh(speed_kmh)
        if rpm is not None and rpm > 0:
            return rpm, "estimated_from_speed_and_ratios"

    drive_ratio = (
        sample.final_drive_ratio
        if sample.final_drive_ratio is not None
        else final_drive_ratio(context)
    )
    gear_val = sample.gear
    gear_ratio = gear_val if gear_val is not None else current_gear_ratio(context)
    if (
        speed_kmh is None
        or speed_kmh <= 0
        or tire_circumference_m is None
        or tire_circumference_m <= 0
        or drive_ratio is None
        or drive_ratio <= 0
        or gear_ratio is None
        or gear_ratio <= 0
    ):
        return None, "missing"

    whz = speed_kmh * KMH_TO_MPS / tire_circumference_m
    rpm = whz * drive_ratio * gear_ratio * SECONDS_PER_MINUTE
    return float(rpm), "estimated_from_speed_and_ratios"
