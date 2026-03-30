"""Backend-owned live pre-record capture readiness state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["CaptureReadiness", "CaptureReadinessCheck", "CaptureReadinessDetailValue"]

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
