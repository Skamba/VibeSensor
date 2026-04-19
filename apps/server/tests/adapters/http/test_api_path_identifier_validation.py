from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
from vibesensor.cli.http_api_schema_export import export_schema
from vibesensor.shared.types.car_config import CarsSnapshot


def _history_test_client() -> tuple[TestClient, MagicMock, MagicMock, MagicMock]:
    from vibesensor.adapters.http.history import create_history_routes

    run_service = MagicMock()
    run_service.get_run = AsyncMock()
    run_service.get_insights = AsyncMock()
    run_service.delete_run = AsyncMock()

    report_service = MagicMock()
    report_service.build_pdf = AsyncMock()

    export_service = MagicMock()
    export_service.build_export = AsyncMock()

    app = FastAPI()
    app.include_router(
        create_history_routes(
            run_service=run_service,
            report_service=report_service,
            export_service=export_service,
        )
    )
    return TestClient(app), run_service, report_service, export_service


def _settings_test_client() -> tuple[TestClient, MagicMock]:
    from vibesensor.adapters.http.settings import create_settings_routes

    settings_store = MagicMock()
    speed_source_service = MagicMock()
    settings_store.get_cars.return_value = CarsSnapshot(
        cars=[
            {
                "id": "car-1",
                "name": "Test Car",
                "type": "sedan",
                "aspects": {"tire_width_mm": 225.0},
            }
        ],
        active_car_id="car-1",
    )
    speed_status_service = MagicMock()
    speed_status_service.status_snapshot.return_value = SpeedSourceStatusSnapshot(
        gps_enabled=True,
        connection_state="connected",
        device="/dev/ttyUSB0",
        fix_mode=3,
        fix_dimension="3d",
        speed_confidence="high",
        epx_m=1.0,
        epy_m=1.0,
        epv_m=1.0,
        last_update_age_s=0.5,
        raw_speed_kmh=48.0,
        effective_speed_kmh=48.0,
        last_error=None,
        reconnect_delay_s=None,
        fallback_active=False,
        speed_source="gps",
        stale_timeout_s=8.0,
    )

    app = FastAPI()
    app.include_router(
        create_settings_routes(
            settings_store,
            settings_store,
            settings_store,
            speed_source_service,
            speed_status_service,
            MagicMock(),
        )
    )
    return TestClient(app), settings_store


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/history/bad%20id"),
        ("GET", "/api/history/bad%20id/insights"),
        ("DELETE", "/api/history/bad%20id"),
        ("GET", "/api/history/bad%20id/report.pdf"),
        ("GET", "/api/history/bad%20id/export"),
    ],
)
def test_history_routes_reject_invalid_run_ids_before_reaching_services(
    method: str,
    path: str,
) -> None:
    client, run_service, report_service, export_service = _history_test_client()

    response = client.request(method, path)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid run identifier"}
    run_service.get_run.assert_not_called()
    run_service.get_insights.assert_not_called()
    run_service.delete_run.assert_not_called()
    report_service.build_pdf.assert_not_called()
    export_service.build_export.assert_not_called()


def test_settings_routes_reject_invalid_car_id_in_active_car_request() -> None:
    client, settings_store = _settings_test_client()

    response = client.put("/api/settings/cars/active", json={"car_id": "bad id"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid car identifier"}
    settings_store.set_active_car.assert_not_called()


@pytest.mark.parametrize(
    ("method", "path", "payload", "store_attr"),
    [
        ("PUT", "/api/settings/cars/bad%20id", {"name": "Updated"}, "update_car"),
        ("DELETE", "/api/settings/cars/bad%20id", None, "delete_car"),
    ],
)
def test_settings_routes_reject_invalid_car_path_ids_before_store_calls(
    method: str,
    path: str,
    payload: dict[str, object] | None,
    store_attr: str,
) -> None:
    client, settings_store = _settings_test_client()

    response = client.request(method, path, json=payload)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid car identifier"}
    settings_store.get_cars.assert_not_called()
    getattr(settings_store, store_attr).assert_not_called()


def test_export_schema_documents_invalid_identifier_responses() -> None:
    schema_dict = json.loads(export_schema())

    history_paths = [
        ("/api/history/{run_id}", "get"),
        ("/api/history/{run_id}", "delete"),
        ("/api/history/{run_id}/insights", "get"),
        ("/api/history/{run_id}/report.pdf", "get"),
        ("/api/history/{run_id}/export", "get"),
    ]
    for path, method in history_paths:
        assert schema_dict["paths"][path][method]["responses"]["400"]["description"] == (
            "Invalid run identifier."
        )

    assert (
        schema_dict["paths"]["/api/settings/cars/active"]["put"]["responses"]["400"]["description"]
        == "Invalid car identifier."
    )
    assert (
        schema_dict["paths"]["/api/settings/cars/{car_id}"]["put"]["responses"]["400"][
            "description"
        ]
        == "Invalid car identifier."
    )
    assert (
        schema_dict["paths"]["/api/settings/cars/{car_id}"]["delete"]["responses"]["400"][
            "description"
        ]
        == "Invalid car identifier or the requested deletion violates current settings constraints."
    )
