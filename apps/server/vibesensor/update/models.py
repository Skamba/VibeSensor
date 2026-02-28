"""Data models for the update subsystem."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class UpdateState(enum.StrEnum):
    idle = "idle"
    running = "running"
    success = "success"
    failed = "failed"


class UpdatePhase(enum.StrEnum):
    idle = "idle"
    validating = "validating"
    stopping_hotspot = "stopping_hotspot"
    connecting_wifi = "connecting_wifi"
    checking = "checking"
    downloading = "downloading"
    installing = "installing"
    restoring_hotspot = "restoring_hotspot"
    done = "done"


@dataclass
class UpdateIssue:
    phase: str
    message: str
    detail: str = ""


@dataclass
class UpdateJobStatus:
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
            "log_tail": self.log_tail[-50:],
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
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            last_success_at=data.get("last_success_at"),
            ssid=str(data.get("ssid", "")),
            issues=issues,
            log_tail=list(data.get("log_tail") or []),
            exit_code=data.get("exit_code"),
            runtime=dict(data.get("runtime") or {}),
        )
