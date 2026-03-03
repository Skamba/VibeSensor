"""Tests for the /api/health endpoint registration."""

from __future__ import annotations

import pytest


def test_health_route_registered():
    """Verify /api/health is registered as a GET route in the API router."""
    from unittest.mock import MagicMock

    from vibesensor.api import create_router

    state = MagicMock()
    router = create_router(state)
    routes = {r.path: r.methods for r in router.routes if hasattr(r, "methods")}
    assert "/api/health" in routes
    assert "GET" in routes["/api/health"]


@pytest.mark.asyncio
async def test_health_endpoint_response_shape():
    """Verify GET /api/health returns status, processing_state, processing_failures."""
    from unittest.mock import MagicMock

    from vibesensor.api import create_router

    state = MagicMock()
    state.processing_state = "ok"
    state.processing_failure_count = 0
    router = create_router(state)

    endpoint = None
    for route in router.routes:
        if getattr(route, "path", "") == "/api/health":
            endpoint = route.endpoint
            break
    assert endpoint is not None

    result = await endpoint()
    assert result["status"] == "ok"
    assert "processing_state" in result
    assert "processing_failures" in result
    assert result["processing_state"] == "ok"
    assert result["processing_failures"] == 0
