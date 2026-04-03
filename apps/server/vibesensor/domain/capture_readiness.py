"""Backend-owned live pre-record capture readiness state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "CaptureReadiness",
    "CaptureReadinessCheck",
    "CaptureReadinessDetailValue",
    "CaptureReadinessPolicy",
]

type CaptureReadinessDetailValue = int | float | str


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
class CaptureReadiness:
    """Full readiness result used by the recording status surface."""

    is_ready: bool
    checks: tuple[CaptureReadinessCheck, ...] = ()

    @property
    def failed_checks(self) -> tuple[CaptureReadinessCheck, ...]:
        return tuple(check for check in self.checks if check.failed)

    @property
    def warning_checks(self) -> tuple[CaptureReadinessCheck, ...]:
        return tuple(check for check in self.checks if check.warning)


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
