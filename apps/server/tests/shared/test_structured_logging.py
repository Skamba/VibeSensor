"""Tests for shared structured logging helpers."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from vibesensor.shared.structured_logging import (
    StructuredLogFormatter,
    bind_request_id,
    configure_logging,
    log_extra,
    normalize_request_id,
    reset_request_id,
)


def test_formatter_serializes_extra_fields_to_json() -> None:
    formatter = StructuredLogFormatter()
    record = logging.makeLogRecord(
        {
            "name": "vibesensor.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "settings_change",
        }
    )
    record.event = "settings_change"
    record.request_id = "req-123"
    record.before = {"language": "en"}
    record.after = {"language": "nl"}

    payload = json.loads(formatter.format(record))

    assert payload["message"] == "settings_change"
    assert payload["logger"] == "vibesensor.test"
    assert payload["event"] == "settings_change"
    assert payload["request_id"] == "req-123"
    assert payload["before"] == {"language": "en"}
    assert payload["after"] == {"language": "nl"}


def test_log_extra_includes_bound_request_id() -> None:
    request_id, token = bind_request_id("  client/request-42 \n")
    try:
        extra = log_extra(event="http_request")
    finally:
        reset_request_id(token)

    assert request_id == "client/request-42"
    assert extra["request_id"] == "client/request-42"


def test_normalize_request_id_falls_back_when_header_is_invalid() -> None:
    request_id = normalize_request_id(" \n\t ")
    assert request_id


def test_configure_logging_preserves_non_managed_root_handlers(tmp_path: Path) -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    probe_handler = logging.NullHandler()
    root_logger.addHandler(probe_handler)
    try:
        configure_logging(tmp_path / "app.log")
        assert probe_handler in root_logger.handlers

        configure_logging(None)
        assert probe_handler in root_logger.handlers
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            if handler is not probe_handler:
                handler.close()
        for handler in original_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(original_level)


def test_configure_logging_writes_structured_json_file(tmp_path: Path) -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    log_path = tmp_path / "app.log"
    try:
        configure_logging(log_path)
        request_id, token = bind_request_id("req-structured")
        try:
            logging.getLogger("vibesensor.test").info(
                "settings_change",
                extra=log_extra(
                    event="settings_change",
                    before={"language": "en"},
                    after={"language": "nl"},
                ),
            )
        finally:
            reset_request_id(token)

        for handler in root_logger.handlers:
            handler.flush()

        payload = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert payload["message"] == "settings_change"
        assert payload["event"] == "settings_change"
        assert payload["request_id"] == request_id
        assert payload["logger"] == "vibesensor.test"
        assert payload["before"] == {"language": "en"}
        assert payload["after"] == {"language": "nl"}
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()
        for handler in original_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(original_level)
