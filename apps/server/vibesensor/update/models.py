"""Data models for the update subsystem."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import TypedDict, TypeGuard

from ..json_types import JsonObject, is_json_array, is_json_object


class UpdateIssuePayload(TypedDict):
    phase: str
    message: str
    detail: str


class UpdateJobStatusPayload(TypedDict):
    state: str
    phase: str
    started_at: float | None
    finished_at: float | None
    last_success_at: float | None
    phase_started_at: float | None
    phase_elapsed_s: float | None
    updated_at: float | None
    ssid: str
    issues: list[UpdateIssuePayload]
    log_tail: list[str]
    exit_code: int | None
    runtime: JsonObject


def _is_number_like(value: object) -> TypeGuard[int | float | str]:
    """Return True for scalar shapes worth attempting numeric coercion on."""
    return isinstance(value, (int, float, str))


def _to_float_or_none(value: object) -> float | None:
    """Coerce *value* to float, returning None for null / unconvertible input."""
    if value is None:
        return None
    if not _is_number_like(value):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int_or_none(value: object) -> int | None:
    """Coerce *value* to int, returning None for null / unconvertible input."""
    if value is None:
        return None


def _coerce_update_state(value: object) -> "UpdateState":
    if not isinstance(value, str):
        return UpdateState.idle
    try:
        return UpdateState(value)
    except ValueError:
        return UpdateState.idle


def _coerce_update_phase(value: object) -> "UpdatePhase":
    if not isinstance(value, str):
        return UpdatePhase.idle
    try:
        return UpdatePhase(value)
    except ValueError:
        return UpdatePhase.idle
    if not _is_number_like(value):
        return None
    try:
        return int(value)
    except ValueError:
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


@dataclass(frozen=True, slots=True)
class UpdateRequest:
    """Immutable request parameters for a single update run."""

    ssid: str
    password: str


@dataclass(slots=True)
class UpdateJobStatus:
    """Full status snapshot of the current or most-recent OTA update job."""

    state: UpdateState = UpdateState.idle
    phase: UpdatePhase = UpdatePhase.idle
    started_at: float | None = None
    finished_at: float | None = None
    last_success_at: float | None = None
    phase_started_at: float | None = None
    updated_at: float | None = None
    ssid: str = ""
    issues: list[UpdateIssue] = field(default_factory=list)
    log_tail: list[str] = field(default_factory=list)
    exit_code: int | None = None
    runtime: JsonObject = field(default_factory=dict)

    def to_dict(self) -> UpdateJobStatusPayload:
        phase_elapsed_s = None
        if self.state == UpdateState.running and self.phase_started_at is not None:
            phase_elapsed_s = max(0.0, time.time() - self.phase_started_at)
        return {
            "state": self.state.value,
            "phase": self.phase.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_success_at": self.last_success_at,
            "phase_started_at": self.phase_started_at,
            "phase_elapsed_s": phase_elapsed_s,
            "updated_at": self.updated_at,
            "ssid": self.ssid,
            "issues": [
                {"phase": i.phase, "message": i.message, "detail": i.detail} for i in self.issues
            ],
            "log_tail": self.log_tail[-_LOG_TAIL_LIMIT:],
            "exit_code": self.exit_code,
            "runtime": self.runtime,
        }

    @classmethod
    def from_dict(cls, data: JsonObject) -> UpdateJobStatus:
        """Reconstruct from a serialised dict (e.g. loaded from disk)."""
        issues_raw = data.get("issues")
        issues = []
        if is_json_array(issues_raw):
            for issue_raw in issues_raw:
                if not is_json_object(issue_raw):
                    continue
                issues.append(
                    UpdateIssue(
                        phase=str(issue_raw.get("phase", "")),
                        message=str(issue_raw.get("message", "")),
                        detail=str(issue_raw.get("detail", "")),
                    )
                )
        log_tail_raw = data.get("log_tail")
        log_tail = (
            [str(line) for line in log_tail_raw[-_LOG_TAIL_LIMIT:]]
            if is_json_array(log_tail_raw)
            else []
        )
        runtime_raw = data.get("runtime")
        return cls(
            state=_coerce_update_state(data.get("state", "idle")),
            phase=_coerce_update_phase(data.get("phase", "idle")),
            started_at=_to_float_or_none(data.get("started_at")),
            finished_at=_to_float_or_none(data.get("finished_at")),
            last_success_at=_to_float_or_none(data.get("last_success_at")),
            phase_started_at=_to_float_or_none(data.get("phase_started_at")),
            updated_at=_to_float_or_none(data.get("updated_at")),
            ssid=str(data.get("ssid") or ""),
            issues=issues,
            log_tail=log_tail,
            exit_code=_to_int_or_none(data.get("exit_code")),
            runtime=runtime_raw if is_json_object(runtime_raw) else {},
        )
