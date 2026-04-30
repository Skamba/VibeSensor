"""Data models for the update subsystem."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path

from vibesensor.shared.exceptions import ConfigurationError

_SSID_MAX_LEN = 64
_PASSWORD_MAX_LEN = 128
UPDATE_STATUS_LOG_TAIL_LIMIT: int = 50


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


class UpdateTerminalState(enum.StrEnum):
    """Explicit terminal outcome for the most recent update job."""

    success = "success"
    workflow_failed = "workflow_failed"
    cleanup_failed = "cleanup_failed"
    cancelled_cleanly = "cancelled_cleanly"
    cancelled_cleanup_failed = "cancelled_cleanup_failed"
    timeout = "timeout"
    timeout_cleanup_failed = "timeout_cleanup_failed"


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
    terminal_state: UpdateTerminalState | None = None
    runtime: UpdateRuntimeDetails = field(default_factory=lambda: UpdateRuntimeDetails())

    def __post_init__(self) -> None:
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("finished_at must be greater than or equal to started_at")


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
