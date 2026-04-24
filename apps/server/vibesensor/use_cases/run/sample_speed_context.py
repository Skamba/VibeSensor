"""Speed and engine-reference resolution for live sample construction."""

from __future__ import annotations

from typing import NamedTuple

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.constants.units import MPS_TO_KMH
from vibesensor.shared.order_reference_settings import order_reference_spec_from_snapshot
from vibesensor.shared.types.aligned_speed_context import AlignedSpeedContextSnapshot

__all__ = ["SpeedContext", "resolve_speed_context", "resolve_speed_context_snapshot"]


_SPEED_SOURCE_MAP = {
    "manual": "manual",
    "gps": "gps",
    "obd2": "obd2",
    "fallback_manual": "fallback_manual",
    "none": "none",
}


class SpeedContext(NamedTuple):
    """Named result of :func:`resolve_speed_context`."""

    speed_kmh: float | None
    gps_speed_kmh: float | None
    speed_source: str
    engine_rpm: float | None
    engine_rpm_source: str


def resolve_speed_context(
    *,
    gps_speed_mps: float | None,
    resolved_speed_mps: float | None,
    resolved_speed_source: str,
    analysis_settings_snapshot: AnalysisSettingsSnapshot,
    measured_engine_rpm: float | None = None,
    measured_engine_rpm_source: str | None = None,
) -> SpeedContext:
    """Resolve a concrete speed snapshot into sample-record values."""

    order_reference_spec = order_reference_spec_from_snapshot(analysis_settings_snapshot)
    gps_speed_kmh = (
        (float(gps_speed_mps) * MPS_TO_KMH) if isinstance(gps_speed_mps, NUMERIC_TYPES) else None
    )
    speed_kmh = (
        (float(resolved_speed_mps) * MPS_TO_KMH)
        if isinstance(resolved_speed_mps, NUMERIC_TYPES)
        else None
    )
    speed_source = _SPEED_SOURCE_MAP.get(resolved_speed_source, "none")
    engine_rpm_estimated = None
    if speed_kmh is not None and order_reference_spec is not None:
        engine_rpm_estimated = order_reference_spec.engine_rpm_from_speed_kmh(speed_kmh)
    measured_rpm = (
        float(measured_engine_rpm)
        if (
            isinstance(measured_engine_rpm, NUMERIC_TYPES)
            and not isinstance(measured_engine_rpm, bool)
        )
        else None
    )
    if measured_rpm is not None:
        engine_rpm = measured_rpm
        engine_rpm_source = str(measured_engine_rpm_source or "obd2")
    elif engine_rpm_estimated is not None:
        engine_rpm = engine_rpm_estimated
        engine_rpm_source = "estimated_from_speed_and_ratios"
    else:
        engine_rpm = None
        engine_rpm_source = "missing"

    return SpeedContext(
        speed_kmh=speed_kmh,
        gps_speed_kmh=gps_speed_kmh,
        speed_source=speed_source,
        engine_rpm=engine_rpm,
        engine_rpm_source=engine_rpm_source,
    )


def resolve_speed_context_snapshot(
    *,
    snapshot: AlignedSpeedContextSnapshot,
    analysis_settings_snapshot: AnalysisSettingsSnapshot,
) -> SpeedContext:
    """Resolve one analysis-window-aligned vehicle-context snapshot."""

    order_reference_spec = order_reference_spec_from_snapshot(analysis_settings_snapshot)
    gps_speed_kmh = (
        (float(snapshot.gps_speed_mps) * MPS_TO_KMH)
        if snapshot.gps_speed_aligned and isinstance(snapshot.gps_speed_mps, NUMERIC_TYPES)
        else None
    )
    speed_kmh = (
        (float(snapshot.resolved_speed_mps) * MPS_TO_KMH)
        if snapshot.resolved_speed_aligned
        and isinstance(snapshot.resolved_speed_mps, NUMERIC_TYPES)
        and not isinstance(snapshot.resolved_speed_mps, bool)
        else None
    )
    if speed_kmh is not None:
        speed_source = _SPEED_SOURCE_MAP.get(snapshot.resolved_speed_source, "none")
    elif snapshot.selected_speed_source in {"gps", "obd2"}:
        speed_source = f"{snapshot.selected_speed_source}_unaligned"
    else:
        speed_source = _SPEED_SOURCE_MAP.get(snapshot.resolved_speed_source, "none")

    engine_rpm_estimated = None
    if speed_kmh is not None and order_reference_spec is not None:
        engine_rpm_estimated = order_reference_spec.engine_rpm_from_speed_kmh(speed_kmh)
    measured_rpm = (
        float(snapshot.measured_engine_rpm)
        if (
            snapshot.measured_engine_rpm_aligned
            and isinstance(snapshot.measured_engine_rpm, NUMERIC_TYPES)
            and not isinstance(snapshot.measured_engine_rpm, bool)
        )
        else None
    )
    if measured_rpm is not None:
        engine_rpm = measured_rpm
        engine_rpm_source = str(snapshot.measured_engine_rpm_source or "obd2")
    elif engine_rpm_estimated is not None:
        engine_rpm = engine_rpm_estimated
        engine_rpm_source = "estimated_from_speed_and_ratios"
    elif speed_source.endswith("_unaligned"):
        engine_rpm = None
        engine_rpm_source = "context_unaligned"
    else:
        engine_rpm = None
        engine_rpm_source = "missing"

    return SpeedContext(
        speed_kmh=speed_kmh,
        gps_speed_kmh=gps_speed_kmh,
        speed_source=speed_source,
        engine_rpm=engine_rpm,
        engine_rpm_source=engine_rpm_source,
    )
