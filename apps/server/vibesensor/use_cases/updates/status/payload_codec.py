"""msgspec codecs for updater status persistence and HTTP payloads."""

from __future__ import annotations

import time

import msgspec

from vibesensor.shared.types.json_types import (
    JsonObject,
    is_json_object,
)
from vibesensor.use_cases.updates.models import (
    UPDATE_STATUS_LOG_TAIL_LIMIT,
    UpdateJobStatus,
    UpdatePhase,
    UpdateState,
    UpdateTransport,
)

__all__ = [
    "UpdateIssuePayload",
    "UpdateJobStatusPayload",
    "UpdateRuntimeDetailsPayload",
    "update_status_from_builtins",
    "update_status_from_json",
    "update_status_to_builtins",
    "update_status_to_json",
    "update_status_to_payload",
]


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
