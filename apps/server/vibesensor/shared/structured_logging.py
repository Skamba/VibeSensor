"""Structured logging helpers for request context and structlog-backed rendering."""

from __future__ import annotations

import json
import logging
import string
from contextvars import ContextVar, Token
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

import structlog

REQUEST_ID_HEADER = "X-Request-ID"

_REQUEST_ID: ContextVar[str | None] = ContextVar("vibesensor_request_id", default=None)
_ALLOWED_REQUEST_ID_CHARS = frozenset(string.ascii_letters + string.digits + "-._:/")
_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_LOG_BACKUP_COUNT = 3
_HANDLER_MARKER = "_vibesensor_structlog_handler"


def _add_request_id(
    _logger: logging.Logger | None,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    if "request_id" not in event_dict:
        request_id = current_request_id()
        if request_id is not None:
            event_dict["request_id"] = request_id
    return event_dict


def _json_dumps(payload: object, **_: object) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _foreign_pre_chain() -> list[structlog.typing.Processor]:
    return [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        _add_request_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
    ]


def _add_message_field(
    _logger: logging.Logger | None,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    event_dict.setdefault("message", str(event_dict.get("event", "")))
    return event_dict


def _shared_formatter_processors(
    renderer: structlog.typing.Processor,
    *,
    format_exceptions: bool = True,
) -> list[structlog.typing.Processor]:
    processors: list[structlog.typing.Processor] = [
        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
        _add_message_field,
        structlog.processors.StackInfoRenderer(),
    ]
    if format_exceptions:
        processors.append(structlog.processors.format_exc_info)
    processors.append(renderer)
    return processors


def _configure_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            _add_request_id,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            structlog.stdlib.render_to_log_kwargs,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


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
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=_foreign_pre_chain(),
            processors=_shared_formatter_processors(
                structlog.dev.ConsoleRenderer(colors=False),
                format_exceptions=False,
            ),
        )
    )
    return handler


class StructuredLogFormatter(structlog.stdlib.ProcessorFormatter):
    def __init__(self) -> None:
        super().__init__(
            foreign_pre_chain=_foreign_pre_chain(),
            processors=_shared_formatter_processors(
                structlog.processors.JSONRenderer(serializer=_json_dumps),
            ),
        )


def configure_logging(log_path: Path | None) -> None:
    """Install the canonical structlog-backed backend logging handlers."""
    _configure_structlog()
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
