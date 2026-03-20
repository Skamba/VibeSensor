"""Smoke test: the assembled router wires a minimum number of routes."""

from __future__ import annotations


def test_route_registration_floor(fake_state) -> None:
    """App registers a minimum number of routes, catching broken wiring."""
    from vibesensor.adapters.http import create_router

    router = create_router(fake_state)
    routes = [r for r in router.routes if hasattr(r, "path")]
    assert len(routes) >= 20, f"Expected ≥20 routes, got {len(routes)}"
