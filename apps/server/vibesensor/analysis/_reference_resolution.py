"""Reference-resolution helpers for diagnostics order analysis."""

from __future__ import annotations

from vibesensor.analysis._types import Sample
from vibesensor.common.units import SECONDS_PER_MINUTE
from vibesensor.domain.order_reference import OrderReferenceSpec, wheel_hz_from_speed_kmh
from vibesensor.recording.run_schema import RunMetadata

# Engine RPM derived from vehicle speed, tire size and gear ratios: it moves in
# lockstep with the wheels, so it cannot tell an engine order from a wheel order.
ESTIMATED_RPM_SOURCE = "estimated_from_speed_and_ratios"
ENGINE_OFF_RPM_SOURCE = "engine_off"
_NOT_MEASURED_RPM_SOURCES = frozenset({"", ESTIMATED_RPM_SOURCE, "missing", "context_unaligned"})


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
    return context.order_reference_spec_for(sample)


def _effective_engine_rpm(
    sample: Sample,
    context: RunMetadata,
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    """Resolve measured or inferred engine rpm plus the source label."""
    measured = sample.engine_rpm
    if measured is not None and measured > 0:
        return measured, sample.engine_rpm_source or "measured"
    if measured is not None and sample.engine_rpm_source not in _NOT_MEASURED_RPM_SOURCES:
        # A measured 0 rpm: the engine is off (a hybrid driving electrically, or
        # stop-start), so there is no engine order to estimate from speed.
        return None, ENGINE_OFF_RPM_SOURCE

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
            return rpm, ESTIMATED_RPM_SOURCE

    drive_ratio = (
        sample.final_drive_ratio
        if sample.final_drive_ratio is not None
        else context.final_drive_ratio
    )
    gear_val = sample.gear
    gear_ratio = gear_val if gear_val is not None else context.current_gear_ratio
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

    whz = wheel_hz_from_speed_kmh(speed_kmh, tire_circumference_m)
    if whz is None:
        return None, "missing"
    rpm = whz * drive_ratio * gear_ratio * SECONDS_PER_MINUTE
    return float(rpm), ESTIMATED_RPM_SOURCE
