"""Data models for the update subsystem."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from vibesensor.shared.exceptions import ConfigurationError
from vibesensor.shared.json_utils import as_float_or_none, as_int_or_none
from vibesensor.shared.types.json_types import JsonObject, is_json_array, is_json_object

_SSID_MAX_LEN = 64
_PASSWORD_MAX_LEN = 128


@dataclass(frozen=True, slots=True)
class UpdateValidationConfig:
    """Runtime prerequisites needed before an update job can proceed."""

    rollback_dir: Path
    min_free_disk_bytes: int


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
    connecting_usb_internet = "connecting_usb_internet"
    checking = "checking"
    downloading = "downloading"
    installing = "installing"
    restoring_hotspot = "restoring_hotspot"
    done = "done"


class UpdateTransport(enum.StrEnum):
    """Network path used by a single OTA update run."""

    wifi = "wifi"
    usb_internet = "usb_internet"


class UpdateExecutionOutcome(enum.StrEnum):
    """Canonical coordinator/workflow result for one update run."""

    aborted = "aborted"
    refresh_only = "refresh_only"
    installed = "installed"


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

    transport: UpdateTransport
    ssid: str | None
    password: str


def validate_update_request(
    ssid: str | None,
    password: str,
    *,
    transport: UpdateTransport = UpdateTransport.wifi,
) -> UpdateRequest:
    """Validate raw SSID/password inputs and return an ``UpdateRequest``.

    Raises :class:`~vibesensor.shared.exceptions.ConfigurationError` when the
    request shape is invalid.
    """
    if password and len(password) > _PASSWORD_MAX_LEN:
        raise ConfigurationError(f"Password must be at most {_PASSWORD_MAX_LEN} characters")
    normalized_ssid = (ssid or "").strip()
    if transport == UpdateTransport.wifi:
        if not normalized_ssid or len(normalized_ssid) > _SSID_MAX_LEN:
            raise ConfigurationError(f"SSID must be 1-{_SSID_MAX_LEN} characters")
        return UpdateRequest(
            transport=transport,
            ssid=normalized_ssid,
            password=password,
        )
    if normalized_ssid:
        raise ConfigurationError("SSID must be empty when transport is usb_internet")
    if password:
        raise ConfigurationError("Password must be empty when transport is usb_internet")
    return UpdateRequest(transport=transport, ssid=None, password="")


@dataclass(frozen=True, slots=True)
class UsbInternetStatus:
    """Current USB-backed upstream detection snapshot for the Pi."""

    detected: bool
    usable: bool
    interface_name: str | None = None
    connection_name: str | None = None
    driver: str | None = None
    ipv4_addresses: tuple[str, ...] = ()
    gateway: str | None = None
    has_default_route: bool = False
    diagnostic: str = ""


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
    transport: str
    started_at: float | None
    finished_at: float | None
    last_success_at: float | None
    phase_started_at: float | None
    phase_elapsed_s: float | None
    updated_at: float | None
    ssid: str | None
    uplink_interface: str | None
    issues: list[UpdateIssuePayload]
    log_tail: list[str]
    exit_code: int | None
    runtime: UpdateRuntimeDetailsPayload


def _require_update_state(value: object) -> UpdateState:
    """Decode a persisted update state or raise for unsupported values."""

    if not isinstance(value, str):
        raise ValueError(f"update state must be a string, got {type(value).__name__}")
    try:
        return UpdateState(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported update state: {value!r}") from exc


def _require_update_phase(value: object) -> UpdatePhase:
    """Decode a persisted update phase or raise for unsupported values."""

    if not isinstance(value, str):
        raise ValueError(f"update phase must be a string, got {type(value).__name__}")
    try:
        return UpdatePhase(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported update phase: {value!r}") from exc


def _require_update_transport(value: object) -> UpdateTransport:
    """Decode a persisted transport or raise for unsupported values."""

    if not isinstance(value, str):
        raise ValueError(f"update transport must be a string, got {type(value).__name__}")
    try:
        return UpdateTransport(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported update transport: {value!r}") from exc


def _coerce_bool(value: object) -> bool:
    """Decode loosely typed persisted booleans used by status payloads."""

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
    transport: UpdateTransport = UpdateTransport.wifi
    started_at: float | None = None
    finished_at: float | None = None
    last_success_at: float | None = None
    phase_started_at: float | None = None
    updated_at: float | None = None
    ssid: str | None = None
    uplink_interface: str | None = None
    issues: list[UpdateIssue] = field(default_factory=list)
    log_tail: list[str] = field(default_factory=list)
    exit_code: int | None = None
    runtime: UpdateRuntimeDetails = field(default_factory=lambda: UpdateRuntimeDetails())

    def __post_init__(self) -> None:
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("finished_at must be greater than or equal to started_at")

    def to_payload(self) -> UpdateJobStatusPayload:
        phase_elapsed_s = None
        if self.state == UpdateState.running and self.phase_started_at is not None:
            phase_elapsed_s = max(0.0, time.time() - self.phase_started_at)
        return {
            "state": self.state.value,
            "phase": self.phase.value,
            "transport": self.transport.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_success_at": self.last_success_at,
            "phase_started_at": self.phase_started_at,
            "phase_elapsed_s": phase_elapsed_s,
            "updated_at": self.updated_at,
            "ssid": self.ssid,
            "uplink_interface": self.uplink_interface,
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
        ssid_raw = data.get("ssid")
        uplink_interface_raw = data.get("uplink_interface")
        return cls(
            state=_require_update_state(data.get("state", UpdateState.idle.value)),
            phase=_require_update_phase(data.get("phase", UpdatePhase.idle.value)),
            transport=_require_update_transport(
                data.get("transport", UpdateTransport.wifi.value),
            ),
            started_at=as_float_or_none(data.get("started_at")),
            finished_at=as_float_or_none(data.get("finished_at")),
            last_success_at=as_float_or_none(data.get("last_success_at")),
            phase_started_at=as_float_or_none(data.get("phase_started_at")),
            updated_at=as_float_or_none(data.get("updated_at")),
            ssid=ssid_raw if isinstance(ssid_raw, str) else None,
            uplink_interface=(
                uplink_interface_raw if isinstance(uplink_interface_raw, str) else None
            ),
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
