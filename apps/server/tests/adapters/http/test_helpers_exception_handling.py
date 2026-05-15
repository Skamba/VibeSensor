"""Tests for the HTTP route error boundary."""

from __future__ import annotations

from collections.abc import Callable

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


@pytest.mark.parametrize(
    ("error_factory", "expected_status_code"),
    [
        (lambda: ConfigurationError("bad config"), 400),
        (lambda: ProtocolError("bad packet"), 400),
        (lambda: UpdateError("busy", status="conflict"), 409),
        (lambda: ServiceUnavailableError("service down"), 503),
        (lambda: VibeSensorError("generic domain error"), 500),
        (lambda: OperationalError("operational failure"), 500),
    ],
    ids=[
        "configuration-error",
        "protocol-error",
        "update-conflict",
        "service-unavailable",
        "vibesensor-base",
        "operational-base",
    ],
)
def test_route_error_boundary_maps_known_errors(
    error_factory: Callable[[], Exception],
    expected_status_code: int,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        with route_errors_to_http():
            raise error_factory()

    assert exc_info.value.status_code == expected_status_code


def test_value_error_handling_stays_explicit_at_route_boundary() -> None:
    with pytest.raises(ValueError, match="not a number"):
        with route_errors_to_http():
            raise ValueError("not a number")

    exc = http_exception_for_value_error(ValueError("not a number"), status_code=400)
    assert exc.status_code == 400
    assert exc.detail == "not a number"


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
