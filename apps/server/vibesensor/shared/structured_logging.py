from __future__ import annotations

import json
import logging
import string
from contextvars import ContextVar, Token
from uuid import uuid4

REQUEST_ID_HEADER = "X-Request-ID"

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

_REQUEST_ID: ContextVar[str | None] = ContextVar("vibesensor_request_id", default=None)
_ALLOWED_REQUEST_ID_CHARS = frozenset(string.ascii_letters + string.digits + "-._:/")
_STANDARD_LOG_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def current_request_id() -> str | None:
    return _REQUEST_ID.get()


def normalize_request_id(raw_value: str | None) -> str:
    if raw_value is None:
        return uuid4().hex
    candidate = "".join(ch for ch in raw_value.strip() if ch in _ALLOWED_REQUEST_ID_CHARS)[:64]
    return candidate or uuid4().hex


def bind_request_id(raw_value: str | None) -> tuple[str, Token[str | None]]:
    request_id = normalize_request_id(raw_value)
    return request_id, _REQUEST_ID.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _REQUEST_ID.reset(token)


def log_extra(**fields: object) -> dict[str, object]:
    extra = dict(fields)
    request_id = current_request_id()
    if request_id is not None:
        extra["request_id"] = request_id
    return extra


def _json_compatible(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {str(key): _json_compatible(inner) for key, inner in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_json_compatible(item) for item in value]
    return str(value)


class StructuredLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, JsonValue] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_FIELDS:
                continue
            payload[key] = _json_compatible(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)
