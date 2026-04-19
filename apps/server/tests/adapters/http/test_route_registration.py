"""Smoke test: the assembled router wires key live routes."""

from __future__ import annotations


def test_route_registration_includes_key_live_routes(fake_state) -> None:
    """App registers a representative set of operator-facing live routes."""
    from vibesensor.adapters.http import create_router

    router = create_router(fake_state)
    paths = {route.path for route in router.routes if hasattr(route, "path")}

    assert {
        "/api/health",
        "/api/history",
        "/api/history/{run_id}/report.pdf",
        "/api/update/status",
        "/ws",
    } <= paths
