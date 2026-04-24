"""Runtime smoke checks for critical HTTP route wiring."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vibesensor.adapters.http import create_router
from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector


@pytest.mark.smoke
def test_smoke_health_route_registered() -> None:
    state = MagicMock()
    placeholder = MagicMock()
    state.health = SimpleNamespace(
        health_state=placeholder,
        processing_loop_state=placeholder,
        processor=placeholder,
        registry=placeholder,
        run_recorder=placeholder,
        ingest_diagnostics=IngestDiagnosticsCollector(),
    )
    state.live = SimpleNamespace(
        control_plane=placeholder,
        processor=placeholder,
        registry=placeholder,
        run_recorder=placeholder,
        sensor_metadata_store=placeholder,
        ws_hub=placeholder,
    )
    state.settings = SimpleNamespace(
        car_settings=placeholder,
        analysis_settings=placeholder,
        sensor_metadata_store=placeholder,
        ui_preferences=placeholder,
        speed_source_service=placeholder,
        speed_status_service=placeholder,
        obd_admin_service=placeholder,
    )
    state.history = SimpleNamespace(
        export_service=placeholder,
        report_service=placeholder,
        run_service=placeholder,
    )
    state.updates = SimpleNamespace(
        esp_flash_manager=placeholder,
        update_manager=placeholder,
    )
    router = create_router(state)
    routes = {route.path: route.methods for route in router.routes if hasattr(route, "methods")}
    assert "/api/health" in routes, "Missing /api/health route"
    assert "GET" in routes["/api/health"], "/api/health must support GET"
