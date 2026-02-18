"""Tests for the /api/health endpoint registration."""

from __future__ import annotations


def test_health_route_registered():
    """Verify /api/health is registered as a GET route in the API router."""
    from unittest.mock import MagicMock

    from vibesensor.api import create_router

    state = MagicMock()
    router = create_router(state)
    routes = {r.path: r.methods for r in router.routes if hasattr(r, "methods")}
    assert "/api/health" in routes
    assert "GET" in routes["/api/health"]
