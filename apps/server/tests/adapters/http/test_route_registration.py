"""Smoke test: the assembled router wires key runtime routes."""

from __future__ import annotations


def test_assembled_router_registers_key_runtime_routes(fake_state) -> None:
    """One route-table contract keeps endpoint smoke coverage out of behavior tests."""
    from vibesensor.adapters.http import create_router

    router = create_router(fake_state)
    routes = {
        (route.path, method)
        for route in router.routes
        for method in (getattr(route, "methods", None) or {"WEBSOCKET"})
    }

    assert {
        ("/api/health", "GET"),
        ("/api/settings/language", "GET"),
        ("/api/settings/language", "PUT"),
        ("/api/clients", "GET"),
        ("/api/recording/status", "GET"),
        ("/ws", "WEBSOCKET"),
        ("/api/history", "GET"),
        ("/api/history/{run_id}/report.pdf", "GET"),
        ("/api/update/status", "GET"),
        ("/api/update/internet-status", "GET"),
        ("/api/update/start", "POST"),
        ("/api/update/cancel", "POST"),
    } <= routes
