"""Speed-source settings route tests."""

from __future__ import annotations

import pytest
from _history_endpoint_helpers import route_endpoint, route_endpoint_with_method
from fastapi import HTTPException
from test_support import response_payload

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


def _find_endpoint(router, path: str, method: str = "GET"):
    if method.upper() == "GET":
        return route_endpoint(router, path)
    return route_endpoint_with_method(router, path, method)


@pytest.fixture
def _speed_source_router(fake_state):
    from vibesensor.adapters.http.settings.dependencies import SpeedSourceRouteDeps
    from vibesensor.adapters.http.settings.speed_source import create_speed_source_routes

    return (
        create_speed_source_routes(
            SpeedSourceRouteDeps(
                speed_source_service=fake_state.speed_source_service,
                speed_status_service=fake_state.gps_monitor,
            ),
        ),
        fake_state,
    )


class TestSpeedSourceEndpoint:
    @pytest.mark.asyncio
    async def test_get_speed_source_response_shape(self, _speed_source_router) -> None:
        router, state = _speed_source_router
        endpoint = _find_endpoint(router, "/api/settings/speed-source", "GET")

        state.speed_source_service.get_speed_source.return_value = {
            "speedSource": "manual",
            "manualSpeedKph": 42.0,
            "staleTimeoutS": 15.0,
            "obdDeviceMac": "001122334455",
            "obdDeviceName": "OBDLink MX+",
        }

        result = response_payload(await endpoint())

        assert result == {
            "speed_source": "manual",
            "manual_speed_kph": 42.0,
            "stale_timeout_s": 15.0,
            "obd_device_mac": "001122334455",
            "obd_device_name": "OBDLink MX+",
        }

    @pytest.mark.asyncio
    async def test_update_speed_source_passes_only_non_null_fields(
        self,
        _speed_source_router,
    ) -> None:
        router, state = _speed_source_router
        endpoint = _find_endpoint(router, "/api/settings/speed-source", "PUT")

        from vibesensor.adapters.http.models import SpeedSourceRequest

        state.speed_source_service.update_speed_source.return_value = {
            "speedSource": "manual",
            "manualSpeedKph": 42.0,
            "staleTimeoutS": 15.0,
        }

        await endpoint(req=SpeedSourceRequest(speed_source="manual", manual_speed_kph=42.0))

        state.speed_source_service.update_speed_source.assert_called_once_with(
            {"speedSource": "manual", "manualSpeedKph": 42.0}
        )

    @pytest.mark.asyncio
    async def test_update_speed_source_maps_invalid_config_to_400(
        self,
        _speed_source_router,
    ) -> None:
        router, state = _speed_source_router
        endpoint = _find_endpoint(router, "/api/settings/speed-source", "PUT")

        from vibesensor.adapters.http.models import SpeedSourceRequest

        state.speed_source_service.update_speed_source.side_effect = ValueError(
            "SpeedSourceConfig with speed_source=MANUAL requires manual_speed_kph"
        )

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(req=SpeedSourceRequest(speed_source="manual"))

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_speed_source_status_response_shape(self, _speed_source_router) -> None:
        router, state = _speed_source_router
        endpoint = _find_endpoint(router, "/api/settings/speed-source/status", "GET")

        state.gps_monitor.status_snapshot.return_value = _make_speed_source_status_snapshot()

        result = response_payload(await endpoint())

        assert result["speed_source"] == "gps"
        assert result["fix_dimension"] == "3d"
