"""Data models for the update subsystem."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from vibesensor.shared.json_utils import as_float_or_none, as_int_or_none
from vibesensor.shared.types.json_types import JsonObject, is_json_array, is_json_object


@dataclass(frozen=True, slots=True)
class UpdateValidationConfig:
    rollback_dir: Path
    min_free_disk_bytes: int


def _coerce_update_state(value: object) -> UpdateState:
    if not isinstance(value, str):
        return UpdateState.idle
    try:
        return UpdateState(value)
    except ValueError:
        return UpdateState.idle


def _coerce_update_phase(value: object) -> UpdatePhase:
    if not isinstance(value, str):
        return UpdatePhase.idle
    try:
        return UpdatePhase(value)
    except ValueError:
        return UpdatePhase.idle


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


class UpdateIssuePayload(TypedDict):
    phase: str
    message: str
    detail: str


class UpdateRuntimeDetailsPayload(TypedDict):
    version: str
    commit: str
    ui_source_hash: str
    static_assets_hash: str
    static_build_source_hash: str
    static_build_commit: str
    assets_verified: bool
    has_packaged_static: bool


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
    runtime: UpdateRuntimeDetailsPayload


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"1", "true", "yes", "on"}
    return False


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
    runtime: UpdateRuntimeDetails = field(default_factory=lambda: UpdateRuntimeDetails())

    def to_payload(self) -> UpdateJobStatusPayload:
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
            "runtime": self.runtime.to_payload(),
        }

    @classmethod
    def from_payload(cls, data: JsonObject) -> UpdateJobStatus:
        """Reconstruct from a serialized payload (e.g. loaded from disk)."""
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
                    ),
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
            started_at=as_float_or_none(data.get("started_at")),
            finished_at=as_float_or_none(data.get("finished_at")),
            last_success_at=as_float_or_none(data.get("last_success_at")),
            phase_started_at=as_float_or_none(data.get("phase_started_at")),
            updated_at=as_float_or_none(data.get("updated_at")),
            ssid=str(data.get("ssid") or ""),
            issues=issues,
            log_tail=log_tail,
            exit_code=as_int_or_none(data.get("exit_code")),
            runtime=UpdateRuntimeDetails.from_payload(runtime_raw),
        )


@dataclass(frozen=True, slots=True)
class UpdateRuntimeDetails:
    """Runtime/build metadata tracked during update lifecycle and exposed over HTTP."""

    version: str = ""
    commit: str = ""
    ui_source_hash: str = ""
    static_assets_hash: str = ""
    static_build_source_hash: str = ""
    static_build_commit: str = ""
    assets_verified: bool = False
    has_packaged_static: bool = False

    def to_payload(self) -> UpdateRuntimeDetailsPayload:
        return {
            "version": self.version,
            "commit": self.commit,
            "ui_source_hash": self.ui_source_hash,
            "static_assets_hash": self.static_assets_hash,
            "static_build_source_hash": self.static_build_source_hash,
            "static_build_commit": self.static_build_commit,
            "assets_verified": self.assets_verified,
            "has_packaged_static": self.has_packaged_static,
        }

    @classmethod
    def from_payload(cls, data: object) -> UpdateRuntimeDetails:
        if not is_json_object(data):
            return cls()
        return cls(
            version=str(data.get("version") or ""),
            commit=str(data.get("commit") or ""),
            ui_source_hash=str(data.get("ui_source_hash") or ""),
            static_assets_hash=str(data.get("static_assets_hash") or ""),
            static_build_source_hash=str(data.get("static_build_source_hash") or ""),
            static_build_commit=str(data.get("static_build_commit") or ""),
            assets_verified=_coerce_bool(data.get("assets_verified")),
            has_packaged_static=_coerce_bool(data.get("has_packaged_static")),
        )
