"""Data models for the update subsystem."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


def _to_float_or_none(value: Any) -> float | None:
    """Coerce *value* to float, returning None for null / unconvertible input."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int_or_none(value: Any) -> int | None:
    """Coerce *value* to int, returning None for null / unconvertible input."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class UpdateState(enum.StrEnum):
    """Top-level state of an OTA software update job."""

    idle = "idle"
    running = "running"
    success = "success"
    failed = "failed"


class UpdatePhase(enum.StrEnum):
    """Granular phase within an OTA update job."""

    idle = "idle"
    validating = "validating"
    stopping_hotspot = "stopping_hotspot"
    connecting_wifi = "connecting_wifi"
    checking = "checking"
    downloading = "downloading"
    installing = "installing"
    restoring_hotspot = "restoring_hotspot"
    done = "done"


_LOG_TAIL_LIMIT: int = 50


@dataclass(frozen=True, slots=True)
class UpdateIssue:
    """An issue (warning or error) raised during a specific update phase."""

    phase: str
    message: str
    detail: str = ""


@dataclass(slots=True)
class UpdateJobStatus:
    """Full status snapshot of the current or most-recent OTA update job."""

    state: UpdateState = UpdateState.idle
    phase: UpdatePhase = UpdatePhase.idle
    started_at: float | None = None
    finished_at: float | None = None
    last_success_at: float | None = None
    ssid: str = ""
    issues: list[UpdateIssue] = field(default_factory=list)
    log_tail: list[str] = field(default_factory=list)
    exit_code: int | None = None
    runtime: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "phase": self.phase.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_success_at": self.last_success_at,
            "ssid": self.ssid,
            "issues": [
                {"phase": i.phase, "message": i.message, "detail": i.detail} for i in self.issues
            ],
            "log_tail": self.log_tail[-_LOG_TAIL_LIMIT:],
            "exit_code": self.exit_code,
            "runtime": self.runtime,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UpdateJobStatus:
        """Reconstruct from a serialised dict (e.g. loaded from disk)."""
        issues = [
            UpdateIssue(
                phase=str(i.get("phase", "")),
                message=str(i.get("message", "")),
                detail=str(i.get("detail", "")),
            )
            for i in (data.get("issues") or [])
        ]
        return cls(
            state=UpdateState(data.get("state", "idle")),
            phase=UpdatePhase(data.get("phase", "idle")),
            started_at=_to_float_or_none(data.get("started_at")),
            finished_at=_to_float_or_none(data.get("finished_at")),
            last_success_at=_to_float_or_none(data.get("last_success_at")),
            ssid=str(data.get("ssid") or ""),
            issues=issues,
            log_tail=list(data.get("log_tail") or [])[-_LOG_TAIL_LIMIT:],
            exit_code=_to_int_or_none(data.get("exit_code")),
            runtime=dict(data.get("runtime") or {}),
        )
