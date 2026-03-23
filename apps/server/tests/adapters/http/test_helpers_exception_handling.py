"""Tests for domain_errors_to_http() exception handling in _helpers.py."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from vibesensor.adapters.http._helpers import domain_errors_to_http
from vibesensor.shared.exceptions import (
    ConfigurationError,
    ProtocolError,
    UpdateError,
    VibeSensorError,
)


def test_configuration_error_caught_as_vibesensor_error() -> None:
    """ConfigurationError maps to HTTP 400."""
    with pytest.raises(HTTPException) as exc_info:
        with domain_errors_to_http(catch_value_error=400):
            raise ConfigurationError("bad config")
    assert exc_info.value.status_code == 400


def test_protocol_error_maps_to_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        with domain_errors_to_http():
            raise ProtocolError("bad packet")
    assert exc_info.value.status_code == 400


def test_update_error_conflict_maps_to_409() -> None:
    with pytest.raises(HTTPException) as exc_info:
        with domain_errors_to_http():
            raise UpdateError("busy", status="conflict")
    assert exc_info.value.status_code == 409


def test_plain_value_error_still_caught() -> None:
    """A plain ValueError is still caught by the except ValueError fallback."""
    with pytest.raises(HTTPException) as exc_info:
        with domain_errors_to_http(catch_value_error=400):
            raise ValueError("not a number")
    assert exc_info.value.status_code == 400


def test_plain_runtime_error_still_caught() -> None:
    """A plain RuntimeError is still caught by the except RuntimeError fallback."""
    with pytest.raises(HTTPException) as exc_info:
        with domain_errors_to_http(catch_runtime_error=503):
            raise RuntimeError("service down")
    assert exc_info.value.status_code == 503


def test_vibesensor_error_base_caught() -> None:
    """VibeSensorError (base) is caught and mapped to HTTP 500."""
    with pytest.raises(HTTPException) as exc_info:
        with domain_errors_to_http():
            raise VibeSensorError("generic domain error")
    assert exc_info.value.status_code == 500
