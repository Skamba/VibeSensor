"""Tests for the /api/health endpoint registration."""

from __future__ import annotations

import pytest


@pytest.fixture
def _health_router(fake_state):
    """Return ``(router, state)`` for health-endpoint tests."""
    from vibesensor.routes import create_router

    fake_state.loop_state.processing_state = "ok"
    fake_state.loop_state.processing_failure_count = 0
    return create_router(fake_state), fake_state


def _find_endpoint(router, path: str):
    """Return the endpoint callable for *path*, or ``None``."""
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    return None


def test_health_route_registered(_health_router):
    """Verify /api/health is registered as a GET route in the API router."""
    router, _ = _health_router
    routes = {r.path: r.methods for r in router.routes if hasattr(r, "methods")}
    assert "/api/health" in routes
    assert "GET" in routes["/api/health"]


@pytest.mark.asyncio
async def test_health_endpoint_response_shape(_health_router):
    """Verify GET /api/health returns typed degradation, data-loss, and persistence state."""
    router, _ = _health_router
    endpoint = _find_endpoint(router, "/api/health")
    assert endpoint is not None

    result = await endpoint()
    assert result["status"] == "ok"
    assert result["processing_state"] == "ok"
    assert result["processing_failures"] == 0
    assert result["degradation_reasons"] == []
    assert result["data_loss"]["tracked_clients"] == 0
    assert result["persistence"]["write_error"] is None
    assert result["persistence"]["analysis_in_progress"] is False
    assert result["persistence"]["analysis_queue_depth"] == 0
    assert result["persistence"]["analysis_active_run_id"] is None


@pytest.mark.asyncio
async def test_health_endpoint_degrades_for_data_loss_and_persistence_error(_health_router):
    router, state = _health_router
    endpoint = _find_endpoint(router, "/api/health")
    assert endpoint is not None

    state.registry.data_loss_snapshot.return_value = {
        "tracked_clients": 2,
        "affected_clients": 1,
        "frames_dropped": 3,
        "queue_overflow_drops": 0,
        "server_queue_drops": 1,
        "parse_errors": 0,
    }
    state.metrics_logger.health_snapshot.return_value = {
        "write_error": "history append_samples failed",
        "analysis_in_progress": True,
        "analysis_queue_depth": 2,
        "analysis_active_run_id": "run-42",
        "analysis_started_at": 1700000000.0,
        "analysis_elapsed_s": 5.0,
    }
    state.loop_state.processing_state = "degraded"
    state.loop_state.processing_failure_count = 2

    result = await endpoint()

    assert result["status"] == "degraded"
    assert result["degradation_reasons"] == [
        "processing_state:degraded",
        "processing_failures",
        "frames_dropped",
        "server_queue_drops",
        "persistence_write_error",
    ]
    assert result["data_loss"]["affected_clients"] == 1
    assert result["persistence"]["write_error"] == "history append_samples failed"
    assert result["persistence"]["analysis_in_progress"] is True
    assert result["persistence"]["analysis_queue_depth"] == 2
    assert result["persistence"]["analysis_active_run_id"] == "run-42"


@pytest.mark.asyncio
async def test_health_endpoint_validates_through_fastapi_response_field(_health_router):
    """Verify FastAPI can validate the declared /api/health response model."""
    router, _ = _health_router
    route = next(r for r in router.routes if getattr(r, "path", "") == "/api/health")
    payload = await route.endpoint()
    validated, errors = route.response_field.validate(payload, {}, loc=("response",))

    assert errors == []
    assert payload["status"] == "ok"
    assert payload["data_loss"]["tracked_clients"] == 0
    assert payload["persistence"]["analysis_in_progress"] is False
    assert validated.status == "ok"
