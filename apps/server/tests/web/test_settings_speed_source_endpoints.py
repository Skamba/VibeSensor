"""Speed-source settings route tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.speed.speed_status import SpeedSourceStatusSnapshot


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
    from vibesensor.web.settings.speed_source import create_speed_source_routes

    app = FastAPI()
    app.include_router(
        create_speed_source_routes(
            speed_source_service=fake_state.speed_source_service,
            speed_status_service=fake_state.gps_monitor,
        )
    )
    with TestClient(app) as client:
        yield client, fake_state


class TestSpeedSourceEndpoint:
    def test_put_then_get_round_trips_the_saved_config(self, _speed_source_client) -> None:
        client, _state = _speed_source_client

        response = client.put(
            "/api/settings/speed-source",
            json={
                "speed_source": "manual",
                "manual_speed_kph": 42.0,
                "stale_timeout_s": 15.0,
            },
        )

        assert response.status_code == 200
        expected = {
            "speed_source": "manual",
            "manual_speed_kph": 42.0,
            "stale_timeout_s": 15.0,
            "obd_device_mac": None,
            "obd_device_name": None,
        }
        assert response.json() == expected
        assert client.get("/api/settings/speed-source").json() == expected

    def test_partial_update_keeps_the_fields_it_omits(self, _speed_source_client) -> None:
        client, _state = _speed_source_client
        client.put(
            "/api/settings/speed-source",
            json={"speed_source": "gps", "manual_speed_kph": 42.0, "stale_timeout_s": 15.0},
        )

        response = client.put("/api/settings/speed-source", json={"stale_timeout_s": 20.0})

        assert response.status_code == 200
        assert response.json()["manual_speed_kph"] == 42.0
        assert response.json()["stale_timeout_s"] == 20.0

    def test_manual_source_without_a_manual_speed_is_rejected(
        self,
        _speed_source_client,
    ) -> None:
        client, _state = _speed_source_client

        response = client.put("/api/settings/speed-source", json={"speed_source": "manual"})

        assert response.status_code == 400
        assert client.get("/api/settings/speed-source").json()["speed_source"] == "gps"

    def test_speed_source_status_response_shape(self, _speed_source_client) -> None:
        client, state = _speed_source_client
        state.gps_monitor.status_snapshot.return_value = _make_speed_source_status_snapshot()

        response = client.get("/api/settings/speed-source/status")

        assert response.status_code == 200
        result = response.json()
        assert result["speed_source"] == "gps"
        assert result["fix_dimension"] == "3d"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"manual_speed_kph": 500.1}, id="manual-speed-above-500"),
        pytest.param({"manual_speed_kph": -1}, id="negative-manual-speed"),
        pytest.param({"stale_timeout_s": 2.9}, id="stale-timeout-below-3"),
        pytest.param({"stale_timeout_s": 120.1}, id="stale-timeout-above-120"),
    ],
)
def test_out_of_range_speed_source_values_are_rejected(_speed_source_client, body) -> None:
    client, _state = _speed_source_client

    assert client.put("/api/settings/speed-source", json=body).status_code == 422
