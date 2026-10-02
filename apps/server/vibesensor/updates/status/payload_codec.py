"""msgspec codecs and the persistent JSON state store for updater status."""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
import time
from pathlib import Path

import msgspec

from vibesensor.common.json_types import (
    JsonObject,
    is_json_object,
)
from vibesensor.common.process_settings import (
    DEFAULT_UPDATE_STATE_PATH,
    load_update_env_settings,
)
from vibesensor.updates.models import (
    UPDATE_STATUS_LOG_TAIL_LIMIT,
    UpdateJobStatus,
    UpdatePhase,
    UpdateState,
    UpdateTerminalState,
    UpdateTransport,
)

__all__ = [
    "DEFAULT_STATE_PATH",
    "UpdateIssuePayload",
    "UpdateJobStatusPayload",
    "UpdateRuntimeDetailsPayload",
    "UpdateStateStore",
    "update_status_from_builtins",
    "update_status_from_json",
    "update_status_to_builtins",
    "update_status_to_json",
    "update_status_to_payload",
]

LOGGER = logging.getLogger(__name__)

DEFAULT_STATE_PATH = str(DEFAULT_UPDATE_STATE_PATH)


class UpdateIssuePayload(msgspec.Struct, kw_only=True, frozen=True):
    """Wire contract for a single updater issue entry."""

    phase: str = ""
    message: str = ""
    detail: str = ""


class UpdateRuntimeDetailsPayload(msgspec.Struct, kw_only=True, frozen=True):
    """Wire contract for updater runtime/build verification details."""

    version: str = ""
    commit: str = ""
    ui_source_hash: str = ""
    static_assets_hash: str = ""
    static_build_source_hash: str = ""
    static_build_commit: str = ""
    assets_verified: bool = False
    has_packaged_static: bool = False


class UpdateJobStatusPayload(msgspec.Struct, kw_only=True):
    """Wire contract for persisted and HTTP-exposed updater status."""

    state: UpdateState = UpdateState.idle
    phase: UpdatePhase = UpdatePhase.idle
    transport: UpdateTransport = UpdateTransport.wifi
    started_at: float | None = None
    finished_at: float | None = None
    last_success_at: float | None = None
    phase_started_at: float | None = None
    phase_elapsed_s: float | None = None
    updated_at: float | None = None
    ssid: str | None = None
    uplink_interface: str | None = None
    issues: list[UpdateIssuePayload] = msgspec.field(default_factory=list)
    log_tail: list[str] = msgspec.field(default_factory=list)
    exit_code: int | None = None
    terminal_state: UpdateTerminalState | None = None
    runtime: UpdateRuntimeDetailsPayload = msgspec.field(
        default_factory=UpdateRuntimeDetailsPayload
    )


def update_status_to_payload(
    status: UpdateJobStatus,
    *,
    now_s: float | None = None,
) -> UpdateJobStatusPayload:
    """Convert a domain updater status into the shared msgspec payload struct."""

    payload = msgspec.convert(
        status,
        type=UpdateJobStatusPayload,
        from_attributes=True,
        strict=False,
    )
    payload.log_tail = payload.log_tail[-UPDATE_STATUS_LOG_TAIL_LIMIT:]
    payload.phase_elapsed_s = _phase_elapsed_s(status, now_s=now_s)
    return payload


def update_status_to_builtins(
    status: UpdateJobStatus,
    *,
    now_s: float | None = None,
) -> JsonObject:
    """Convert a domain updater status into JSON-safe builtins for Pydantic/HTTP."""

    builtins = msgspec.to_builtins(update_status_to_payload(status, now_s=now_s))
    if not is_json_object(builtins):
        raise TypeError("msgspec updater status payload must encode to a JSON object")
    return builtins


def update_status_to_json(
    status: UpdateJobStatus,
    *,
    now_s: float | None = None,
) -> bytes:
    """Encode a domain updater status as persisted JSON bytes."""

    return msgspec.json.encode(update_status_to_payload(status, now_s=now_s)) + b"\n"


def update_status_from_builtins(data: object) -> UpdateJobStatus:
    """Decode a JSON-like updater status object into the domain status model."""

    return _status_from_payload(_convert_status_payload_object(data))


def update_status_from_json(raw: bytes | str) -> UpdateJobStatus:
    """Decode persisted updater status JSON into the domain status model."""

    payload = msgspec.json.decode(raw, type=UpdateJobStatusPayload)
    return _status_from_payload(payload)


def _status_from_payload(payload: UpdateJobStatusPayload) -> UpdateJobStatus:
    payload.log_tail = payload.log_tail[-UPDATE_STATUS_LOG_TAIL_LIMIT:]
    return msgspec.convert(
        payload,
        type=UpdateJobStatus,
        from_attributes=True,
        strict=False,
    )


def _convert_status_payload_object(data: object) -> UpdateJobStatusPayload:
    return msgspec.convert(data, type=UpdateJobStatusPayload, strict=True)


def _phase_elapsed_s(status: UpdateJobStatus, *, now_s: float | None) -> float | None:
    if status.state != UpdateState.running or status.phase_started_at is None:
        return None
    return max(0.0, (time.time() if now_s is None else now_s) - status.phase_started_at)


class UpdateStateStore:
    """Load / save :class:`UpdateJobStatus` to a JSON file.

    Writes are atomic (write-to-temp + ``os.replace``) so a crash mid-write
    never corrupts the file. Reads tolerate missing or malformed JSON and
    return ``None`` with a logged warning.
    """

    __slots__ = ("_path",)

    def __init__(self, path: str | Path | None = None) -> None:
        if path is not None:
            self._path = Path(path).expanduser()
        else:
            self._path = load_update_env_settings().update_state_path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> UpdateJobStatus | None:
        """Load persisted status. Returns ``None`` if missing or corrupt."""
        if not self._path.is_file():
            return None
        try:
            return update_status_from_json(self._path.read_bytes())
        except (msgspec.DecodeError, msgspec.ValidationError, ValueError, TypeError) as exc:
            LOGGER.warning("Corrupt update state file %s: %s", self._path, exc)
            return None
        except OSError as exc:
            LOGGER.warning("Cannot read update state file %s: %s", self._path, exc)
            return None

    def save(self, status: UpdateJobStatus) -> None:
        """Persist *status* atomically (temp-file + ``os.replace``)."""
        payload = update_status_to_json(status)
        tmp: str | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent),
                prefix=".update_status_",
                suffix=".tmp",
            )
            try:
                os.write(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            Path(tmp).replace(self._path)
        except OSError as exc:
            LOGGER.warning("Failed to persist update state to %s: %s", self._path, exc)
            if tmp is not None:
                with contextlib.suppress(OSError):
                    Path(tmp).unlink()
