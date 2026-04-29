"""Speed-source settings route tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot


def _make_speed_source_status_snapshot() -> SpeedSourceStatusSnapshot:
    return SpeedSourceStatusSnapshot(
        gps_enabled=True,
        connection_state="connected",
        device="/dev/ttyUSB0",
        fix_mode=3,
        fix_dimension="3d",
        speed_confidence="high",
        epx_m=1.2,
        epy_m=1.3,
        epv_m=2.4,
        last_update_age_s=0.5,
        raw_speed_kmh=48.2,
        effective_speed_kmh=48.2,
        last_error=None,
        reconnect_delay_s=None,
        fallback_active=False,
        speed_source="gps",
        stale_timeout_s=8.0,
    )


@pytest.fixture
def _speed_source_client(fake_state):
    from vibesensor.adapters.http.settings.dependencies import SpeedSourceRouteDeps
    from vibesensor.adapters.http.settings.speed_source import create_speed_source_routes

    app = FastAPI()
    app.include_router(
        create_speed_source_routes(
            SpeedSourceRouteDeps(
                speed_source_service=fake_state.speed_source_service,
                speed_status_service=fake_state.gps_monitor,
            ),
        )
    )
    with TestClient(app) as client:
        yield client, fake_state


class TestSpeedSourceEndpoint:
    def test_get_speed_source_response_shape(self, _speed_source_client) -> None:
        client, state = _speed_source_client
        state.speed_source_service.get_speed_source.return_value = {
            "speedSource": "manual",
            "manualSpeedKph": 42.0,
            "staleTimeoutS": 15.0,
            "obdDeviceMac": "001122334455",
            "obdDeviceName": "OBDLink MX+",
        }

        response = client.get("/api/settings/speed-source")

        assert response.status_code == 200
        assert response.json() == {
            "speed_source": "manual",
            "manual_speed_kph": 42.0,
            "stale_timeout_s": 15.0,
            "obd_device_mac": "001122334455",
            "obd_device_name": "OBDLink MX+",
        }

    def test_update_speed_source_passes_only_non_null_fields(
        self,
        _speed_source_client,
    ) -> None:
        client, state = _speed_source_client
        state.speed_source_service.update_speed_source.return_value = {
            "speedSource": "manual",
            "manualSpeedKph": 42.0,
            "staleTimeoutS": 15.0,
        }

        response = client.put(
            "/api/settings/speed-source",
            json={"speed_source": "manual", "manual_speed_kph": 42.0},
        )

        assert response.status_code == 200
        state.speed_source_service.update_speed_source.assert_called_once_with(
            {"speedSource": "manual", "manualSpeedKph": 42.0}
        )

    def test_update_speed_source_maps_invalid_config_to_400(
        self,
        _speed_source_client,
    ) -> None:
        client, state = _speed_source_client
        state.speed_source_service.update_speed_source.side_effect = ValueError(
            "SpeedSourceConfig with speed_source=MANUAL requires manual_speed_kph"
        )

        response = client.put("/api/settings/speed-source", json={"speed_source": "manual"})

        assert response.status_code == 400

    def test_speed_source_status_response_shape(self, _speed_source_client) -> None:
        client, state = _speed_source_client
        state.gps_monitor.status_snapshot.return_value = _make_speed_source_status_snapshot()

        response = client.get("/api/settings/speed-source/status")

        assert response.status_code == 200
        result = response.json()
        assert result["speed_source"] == "gps"
        assert result["fix_dimension"] == "3d"
