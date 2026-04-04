"""Tests for the HTTP route error boundary."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from vibesensor.adapters.http.error_boundary import (
    http_exception_for_value_error,
    http_status_for_analysis_not_ready_error,
    route_errors_to_http,
)
from vibesensor.shared.exceptions import (
    AnalysisNotReadyError,
    ConfigurationError,
    ProtocolError,
    UpdateError,
    VibeSensorError,
)
from vibesensor.shared.operational_errors import OperationalError, ServiceUnavailableError


def test_configuration_error_caught_as_vibesensor_error() -> None:
    """ConfigurationError maps to HTTP 400."""
    with pytest.raises(HTTPException) as exc_info:
        with route_errors_to_http():
            raise ConfigurationError("bad config")
    assert exc_info.value.status_code == 400


def test_protocol_error_maps_to_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        with route_errors_to_http():
            raise ProtocolError("bad packet")
    assert exc_info.value.status_code == 400


def test_update_error_conflict_maps_to_409() -> None:
    with pytest.raises(HTTPException) as exc_info:
        with route_errors_to_http():
            raise UpdateError("busy", status="conflict")
    assert exc_info.value.status_code == 409


def test_plain_value_error_propagates_past_route_boundary() -> None:
    """A plain ValueError must be handled explicitly by the route that owns it."""
    with pytest.raises(ValueError, match="not a number"):
        with route_errors_to_http():
            raise ValueError("not a number")


def test_http_exception_for_value_error_maps_explicit_request_failures() -> None:
    exc = http_exception_for_value_error(ValueError("not a number"), status_code=400)
    assert exc.status_code == 400
    assert exc.detail == "not a number"


def test_service_unavailable_error_maps_to_503() -> None:
    with pytest.raises(HTTPException) as exc_info:
        with route_errors_to_http():
            raise ServiceUnavailableError("service down")
    assert exc_info.value.status_code == 503


def test_vibesensor_error_base_caught() -> None:
    """VibeSensorError (base) is caught and mapped to HTTP 500."""
    with pytest.raises(HTTPException) as exc_info:
        with route_errors_to_http():
            raise VibeSensorError("generic domain error")
    assert exc_info.value.status_code == 500


def test_operational_error_base_maps_to_500() -> None:
    with pytest.raises(HTTPException) as exc_info:
        with route_errors_to_http():
            raise OperationalError("operational failure")
    assert exc_info.value.status_code == 500


@pytest.mark.parametrize(
    ("status", "expected_status_code"),
    [
        ("in_progress", 409),
        ("active", 409),
        ("error", 422),
        ("unavailable", 422),
        ("unexpected", 500),
    ],
)
def test_analysis_not_ready_status_mapping_is_explicit(
    status: str,
    expected_status_code: int,
) -> None:
    assert (
        http_status_for_analysis_not_ready_error(
            AnalysisNotReadyError("analysis unavailable", status=status),
        )
        == expected_status_code
    )
