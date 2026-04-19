"""msgspec codecs for updater status persistence and HTTP payloads."""

from __future__ import annotations

import time

import msgspec

from vibesensor.shared.types.json_types import JsonObject, is_json_array, is_json_object
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

    try:
        payload = msgspec.json.decode(raw, type=UpdateJobStatusPayload)
    except msgspec.ValidationError:
        payload = _convert_status_payload_object(msgspec.json.decode(raw))
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
    try:
        return msgspec.convert(data, type=UpdateJobStatusPayload, strict=False)
    except msgspec.ValidationError:
        if not is_json_object(data):
            raise
        # Legacy persisted updater status files allowed loose nested values.
        normalized = dict(data)
        normalized["issues"] = _normalize_legacy_issues(data.get("issues"))
        normalized["log_tail"] = _normalize_legacy_log_tail(data.get("log_tail"))
        normalized["runtime"] = _normalize_legacy_runtime(data.get("runtime"))
        normalized["ssid"] = data.get("ssid") if isinstance(data.get("ssid"), str) else None
        normalized["uplink_interface"] = (
            data.get("uplink_interface") if isinstance(data.get("uplink_interface"), str) else None
        )
        return msgspec.convert(normalized, type=UpdateJobStatusPayload, strict=False)


def _normalize_legacy_issues(value: object) -> list[JsonObject]:
    if not is_json_array(value):
        return []
    issues: list[JsonObject] = []
    for issue in value:
        if not is_json_object(issue):
            continue
        issues.append(
            {
                "phase": str(issue.get("phase", "")),
                "message": str(issue.get("message", "")),
                "detail": str(issue.get("detail", "")),
            }
        )
    return issues


def _normalize_legacy_log_tail(value: object) -> list[str]:
    if not is_json_array(value):
        return []
    return [str(line) for line in value[-UPDATE_STATUS_LOG_TAIL_LIMIT:]]


def _normalize_legacy_runtime(value: object) -> JsonObject:
    if not is_json_object(value):
        return {}
    return {
        "version": _legacy_text(value.get("version")),
        "commit": _legacy_text(value.get("commit")),
        "ui_source_hash": _legacy_text(value.get("ui_source_hash")),
        "static_assets_hash": _legacy_text(value.get("static_assets_hash")),
        "static_build_source_hash": _legacy_text(value.get("static_build_source_hash")),
        "static_build_commit": _legacy_text(value.get("static_build_commit")),
        "assets_verified": _coerce_legacy_bool(value.get("assets_verified")),
        "has_packaged_static": _coerce_legacy_bool(value.get("has_packaged_static")),
    }


def _legacy_text(value: object) -> str:
    return "" if value is None else str(value)


def _coerce_legacy_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _phase_elapsed_s(status: UpdateJobStatus, *, now_s: float | None) -> float | None:
    if status.state != UpdateState.running or status.phase_started_at is None:
        return None
    return max(0.0, (time.time() if now_s is None else now_s) - status.phase_started_at)
