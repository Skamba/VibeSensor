"""Sensor settings route tests."""

from __future__ import annotations

import pytest
from _history_endpoint_helpers import route_endpoint, route_endpoint_with_method
from fastapi import HTTPException


def _find_endpoint(router, path: str, method: str = "GET"):
    if method.upper() == "GET":
        return route_endpoint(router, path)
    return route_endpoint_with_method(router, path, method)


@pytest.fixture
def _sensor_router(fake_state):
    from vibesensor.adapters.http.settings.dependencies import SensorSettingsRouteDeps
    from vibesensor.adapters.http.settings.sensors import create_sensor_settings_routes

    return (
        create_sensor_settings_routes(
            SensorSettingsRouteDeps(sensor_metadata_store=fake_state.settings_store),
        ),
        fake_state,
    )


class TestSensorEndpoint:
    @pytest.mark.asyncio
    async def test_update_sensor_passes_normalized_mac_and_non_null_fields(
        self,
        _sensor_router,
    ) -> None:
        router, state = _sensor_router
        endpoint = _find_endpoint(router, "/api/settings/sensors/{mac}", "POST")

        from vibesensor.adapters.http.models import SensorRequest

        normalized_mac = "aabbccddeeff"
        state.settings_store.get_sensors.return_value = {
            normalized_mac: {"name": "Wheel sensor", "location_code": "front_left"}
        }

        await endpoint(
            mac="AA:BB:CC:DD:EE:FF",
            req=SensorRequest(name="Wheel sensor", location_code="front_left"),
        )

        state.settings_store.set_sensor.assert_called_once_with(
            normalized_mac,
            {"name": "Wheel sensor", "location_code": "front_left"},
        )

    @pytest.mark.asyncio
    async def test_update_sensor_maps_duplicate_location_to_409(self, _sensor_router) -> None:
        router, state = _sensor_router
        endpoint = _find_endpoint(router, "/api/settings/sensors/{mac}", "POST")

        from vibesensor.adapters.http.models import SensorRequest

        state.settings_store.set_sensor.side_effect = ValueError(
            "Location 'front_left' already assigned to Rear Left",
        )

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(
                mac="AA:BB:CC:DD:EE:FF",
                req=SensorRequest(name="Wheel sensor", location_code="front_left"),
            )

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_unknown_sensor_returns_404(self, _sensor_router) -> None:
        router, state = _sensor_router
        endpoint = _find_endpoint(router, "/api/settings/sensors/{mac}", "DELETE")

        state.settings_store.remove_sensor.return_value = False

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(mac="AA:BB:CC:DD:EE:FF")

        assert exc_info.value.status_code == 404
