"""Tests for shared structured logging helpers."""

from __future__ import annotations

import json
import logging

from vibesensor.shared.structured_logging import (
    StructuredLogFormatter,
    bind_request_id,
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
