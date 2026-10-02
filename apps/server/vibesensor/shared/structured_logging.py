"""Structured logging: JSON file formatter, readable console formatter, request ids.

Both formatters are plain ``logging.Formatter`` subclasses. Fields passed via
``extra=log_extra(event=..., ...)`` are emitted as top-level JSON keys in the
file log and as ``key=value`` pairs on the console. The JSON fields are
``timestamp`` (UTC ISO-8601), ``level``, ``logger``, ``message``, ``event``
(defaults to the message), ``request_id`` (when bound), ``exception`` (when
present), and any extra fields.
"""

from __future__ import annotations

import json
import logging
import string
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

REQUEST_ID_HEADER = "X-Request-ID"

_REQUEST_ID: ContextVar[str | None] = ContextVar("vibesensor_request_id", default=None)
_ALLOWED_REQUEST_ID_CHARS = frozenset(string.ascii_letters + string.digits + "-._:/")
_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_LOG_BACKUP_COUNT = 3
_HANDLER_MARKER = "_vibesensor_log_handler"
_STANDARD_RECORD_FIELDS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def _timestamp(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _record_fields(record: logging.LogRecord) -> dict[str, object]:
    """Return the ``extra`` fields of *record* plus the bound request id."""
    fields = {
        key: value
        for key, value in vars(record).items()
        if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
    }
    if "request_id" not in fields and (request_id := current_request_id()) is not None:
        fields["request_id"] = request_id
    return fields


class StructuredLogFormatter(logging.Formatter):
    """Render one JSON object per log record for the application log file."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload: dict[str, object] = {
            "timestamp": _timestamp(record),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": message,
            **_record_fields(record),
        }
        payload.setdefault("event", message)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)


class ConsoleLogFormatter(logging.Formatter):
    """Render ``<timestamp> [level] message [logger] key=value ...`` lines.

    Tracebacks are plain text (no frame locals) so formatting stays cheap on
    the event loop.
    """

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        fields = _record_fields(record)
        if fields.get("event") == message:
            fields.pop("event")
        line = f"{_timestamp(record)} [{record.levelname.lower():<8}] {message} [{record.name}]"
        if fields:
            line += " " + " ".join(f"{key}={value!r}" for key, value in sorted(fields.items()))
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            line += "\n" + self.formatStack(record.stack_info)
        return line


def _mark_handler(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _HANDLER_MARKER, True)
    return handler


def _managed_handlers(root_logger: logging.Logger) -> list[logging.Handler]:
    return [handler for handler in root_logger.handlers if getattr(handler, _HANDLER_MARKER, False)]


def _replace_managed_handlers(root_logger: logging.Logger, handlers: list[logging.Handler]) -> None:
    for handler in _managed_handlers(root_logger):
        root_logger.removeHandler(handler)
        handler.close()
    for handler in handlers:
        root_logger.addHandler(_mark_handler(handler))


def _build_console_handler() -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(ConsoleLogFormatter())
    return handler


def configure_logging(log_path: Path | None) -> None:
    """Install the console handler and, when *log_path* is set, the JSON file handler."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    handlers: list[logging.Handler] = [_build_console_handler()]
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=_LOG_MAX_BYTES,
                backupCount=_LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(StructuredLogFormatter())
            handlers.append(file_handler)
        except OSError:
            _replace_managed_handlers(root_logger, handlers)
            logging.getLogger(__name__).warning(
                "Failed to set up file logging at %s",
                log_path,
                exc_info=True,
                extra=log_extra(
                    event="file_logging_setup_failed",
                    log_path=str(log_path),
                ),
            )
            return

    _replace_managed_handlers(root_logger, handlers)
    if log_path is not None:
        logging.getLogger(__name__).info(
            "File logging enabled: %s",
            log_path,
            extra=log_extra(
                event="file_logging_enabled",
                log_path=str(log_path),
            ),
        )


def current_request_id() -> str | None:
    """Return the currently bound request identifier, if any."""
    return _REQUEST_ID.get()


def normalize_request_id(raw_value: str | None) -> str:
    """Sanitize a request-id header value or generate a new opaque fallback."""
    if raw_value is None:
        return uuid4().hex
    candidate = "".join(ch for ch in raw_value.strip() if ch in _ALLOWED_REQUEST_ID_CHARS)[:64]
    return candidate or uuid4().hex


def bind_request_id(raw_value: str | None) -> tuple[str, Token[str | None]]:
    """Normalize and bind a request id to the current context."""
    request_id = normalize_request_id(raw_value)
    return request_id, _REQUEST_ID.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request-id context using *token*."""
    _REQUEST_ID.reset(token)


def log_extra(**fields: object) -> dict[str, object]:
    """Build ``logging`` extra fields, automatically attaching the bound request id."""
    extra = dict(fields)
    request_id = current_request_id()
    if request_id is not None:
        extra["request_id"] = request_id
    return extra
