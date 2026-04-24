"""Typed vehicle-context snapshot aligned to one analysis-window timestamp."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.shared.types.speed_source_config import ResolvedSpeedSource

__all__ = ["AlignedSpeedContextSnapshot"]


@dataclass(frozen=True, slots=True)
class AlignedSpeedContextSnapshot:
    """Resolved speed/GPS/RPM view for one target monotonic timestamp."""

    selected_speed_source: ResolvedSpeedSource
    resolved_speed_mps: float | None
    resolved_speed_source: ResolvedSpeedSource
    resolved_speed_aligned: bool
    gps_speed_mps: float | None
    gps_speed_aligned: bool
    measured_engine_rpm: float | None
    measured_engine_rpm_source: str | None
    measured_engine_rpm_aligned: bool
