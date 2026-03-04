"""Tests for the /api/health endpoint registration."""

from __future__ import annotations

import pytest


@pytest.fixture()
def _health_router(fake_state):
    """Return ``(router, state)`` for health-endpoint tests."""
    from vibesensor.api import create_router

    fake_state.processing_state = "ok"
    fake_state.processing_failure_count = 0
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
    """Verify GET /api/health returns status, processing_state, processing_failures."""
    router, _ = _health_router
    endpoint = _find_endpoint(router, "/api/health")
    assert endpoint is not None

    result = await endpoint()
    assert result["status"] == "ok"
    assert result["processing_state"] == "ok"
    assert result["processing_failures"] == 0
