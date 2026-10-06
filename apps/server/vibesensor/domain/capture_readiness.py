"""Backend-owned live pre-record capture readiness state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "CaptureCapabilities",
    "CaptureReadiness",
    "CaptureReadinessCheck",
    "CaptureReadinessDetailValue",
    "CaptureReadinessPolicy",
    "DrivelineCapability",
    "EngineCapability",
    "WheelCapability",
]

type CaptureReadinessDetailValue = int | float | str
type WheelCapability = Literal["ok", "missing_tire", "manual_speed"]
type DrivelineCapability = Literal[
    "ok", "estimated_final_drive", "missing_final_drive", "missing_tire", "manual_speed"
]
type EngineCapability = Literal[
    "measured",
    "estimated_top_gear",
    "hybrid_estimated",
    "estimated_ratios",
    "missing_tire",
    "missing_final_drive",
    "missing_top_gear",
    "missing_ratios",
    "manual_speed",
    "not_applicable",
]


@dataclass(frozen=True, slots=True)
class CaptureReadinessCheck:
    """One checklist item inside the live capture-readiness evaluation."""

    check_key: str
    state: Literal["pass", "warn", "fail"]
    reason_key: str | None = None
    details: tuple[tuple[str, CaptureReadinessDetailValue], ...] = ()

    @property
    def failed(self) -> bool:
        return self.state == "fail"

    @property
    def warning(self) -> bool:
        return self.state == "warn"

    @property
    def details_dict(self) -> dict[str, CaptureReadinessDetailValue]:
        return dict(self.details)


@dataclass(frozen=True, slots=True)
class CaptureCapabilities:
    """Which order families the run can test (never blocks capture).

    Mirrors the post-run source checks: ``wheel`` needs the tire size,
    ``driveline`` also the final drive (``estimated_final_drive`` when it is a
    weak library value), and ``engine`` is ``measured`` with fresh OBD-II RPM,
    else estimated from speed assuming top gear (``estimated_ratios`` when the
    final drive or top gear is a weak library value). Without OBD-II, a missing
    reference is named: ``missing_tire`` first, then ``missing_final_drive``,
    ``missing_top_gear``, or ``missing_ratios`` for both. A typed-in speed makes
    every family ``manual_speed``: order matching then holds only at that speed.
    An EV's engine is ``not_applicable`` (its motor is the driveline order); a
    plug-in hybrid's estimated engine check is ``hybrid_estimated``, because the
    engine may be off while it drives electrically.
    """

    wheel: WheelCapability
    driveline: DrivelineCapability
    engine: EngineCapability


@dataclass(frozen=True, slots=True)
class CaptureReadiness:
    """Full readiness result used by the recording status surface."""

    is_ready: bool
    checks: tuple[CaptureReadinessCheck, ...] = ()
    capabilities: CaptureCapabilities | None = None
    """``None`` without an active car."""


@dataclass(frozen=True, slots=True)
class CaptureReadinessPolicy:
    """Thresholds and source rules for live capture-readiness evaluation."""

    min_ready_speed_kmh: float = 20.0
    max_speed_age_s: float = 2.0
    max_obd_rpm_age_s: float = 1.0
    stable_speed_dwell_s: float = 8.0
    integrity_quiet_period_s: float = 10.0
    low_sensor_count_warn_threshold: int = 3
    live_speed_sources: tuple[str, ...] = field(default_factory=lambda: ("gps", "obd2"))
