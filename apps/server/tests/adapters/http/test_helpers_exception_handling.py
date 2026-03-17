"""Tests for domain_errors_to_http() exception handling in _helpers.py."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from vibesensor.adapters.http._helpers import domain_errors_to_http
from vibesensor.shared.exceptions import (
    ConfigurationError,
    VibeSensorError,
)


def test_configuration_error_caught_as_vibesensor_error() -> None:
    """ConfigurationError (no longer a ValueError) is caught by the VibeSensorError handler."""
    with pytest.raises(HTTPException) as exc_info:
        with domain_errors_to_http(catch_value_error=400):
            raise ConfigurationError("bad config")
    assert exc_info.value.status_code == 500


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
