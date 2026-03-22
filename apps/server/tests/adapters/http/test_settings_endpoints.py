"""Tests for HTTP-specific behavior of the /api/settings/* endpoints."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from test_support import response_payload

from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.shared.types.backend_types import CarConfigPayload, CarsSnapshot


def _make_default_snapshot() -> AnalysisSettingsSnapshot:
    return AnalysisSettingsSnapshot(**AnalysisSettingsSnapshot.DEFAULTS)


def _make_car_payload(
    car_id: str = "car-1",
    name: str = "Test Car",
) -> CarConfigPayload:
    return {
        "id": car_id,
        "name": name,
        "type": "sedan",
        "aspects": {"tire_width_mm": 225.0},
    }


def _make_cars_snapshot(
    cars: list[dict[str, object]] | None = None,
    active_car_id: str | None = "car-1",
) -> CarsSnapshot:
    return CarsSnapshot(
        cars=cars or [_make_car_payload()],
        active_car_id=active_car_id,
    )


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
    for route in router.routes:
        if getattr(route, "path", "") == path:
            methods = getattr(route, "methods", set()) or set()
            if method.upper() in methods:
                return route.endpoint
    return None


@pytest.fixture
def _settings_router(fake_state):
    from vibesensor.adapters.http.settings import create_settings_routes

    fake_state.settings_store.analysis_settings_snapshot.return_value = _make_default_snapshot()
    fake_state.settings_store.get_cars.return_value = _make_cars_snapshot()
    return create_settings_routes(
        fake_state.settings_store,
        fake_state.gps_monitor,
    ), fake_state


class TestNormalizeMacOr400:
    """normalize_mac_or_400 raises HTTP 400 for invalid MAC path parameters."""

    @pytest.mark.asyncio
    async def test_empty_mac_raises_400(self, _settings_router) -> None:
        from vibesensor.adapters.http._helpers import normalize_mac_or_400

        with pytest.raises(HTTPException) as exc_info:
            normalize_mac_or_400("")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_oversized_mac_raises_400(self, _settings_router) -> None:
        from vibesensor.adapters.http._helpers import normalize_mac_or_400

        with pytest.raises(HTTPException) as exc_info:
            normalize_mac_or_400("A" * 65)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_mac_format_raises_400(self, _settings_router) -> None:
        from vibesensor.adapters.http._helpers import normalize_mac_or_400

        with pytest.raises(HTTPException) as exc_info:
            normalize_mac_or_400("not-a-mac-address")
        assert exc_info.value.status_code == 400


class TestDeleteCarEndpoint:
    @pytest.mark.asyncio
    async def test_delete_unknown_car_returns_404(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/cars/{car_id}", "DELETE")
        assert endpoint is not None

        state.settings_store.get_cars.return_value = _make_cars_snapshot(
            cars=[],
            active_car_id=None,
        )

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(car_id="no-such-car")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_known_car_calls_store(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/cars/{car_id}", "DELETE")
        assert endpoint is not None

        state.settings_store.get_cars.return_value = _make_cars_snapshot()
        state.settings_store.delete_car.return_value = _make_cars_snapshot(
            cars=[],
            active_car_id=None,
        )

        result = response_payload(await endpoint(car_id="car-1"))

        state.settings_store.delete_car.assert_called_once_with("car-1")
        assert "cars" in result

    @pytest.mark.asyncio
    async def test_delete_car_business_logic_error_returns_400(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/cars/{car_id}", "DELETE")
        assert endpoint is not None

        state.settings_store.get_cars.return_value = _make_cars_snapshot()
        state.settings_store.delete_car.side_effect = ValueError("cannot delete last car")

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(car_id="car-1")
        assert exc_info.value.status_code == 400


class TestSetActiveCarEndpoint:
    @pytest.mark.asyncio
    async def test_unknown_car_id_raises_404(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/cars/active", "POST")
        assert endpoint is not None

        state.settings_store.set_active_car.side_effect = ValueError("Car not found")

        from vibesensor.shared.types.api_models import ActiveCarRequest

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(req=ActiveCarRequest(car_id="no-such-car"))
        assert exc_info.value.status_code == 404


class TestCarsEndpoint:
    @pytest.mark.asyncio
    async def test_get_cars_response_shape(self, _settings_router) -> None:
        router, _ = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/cars", "GET")
        assert endpoint is not None

        result = response_payload(await endpoint())

        assert result["active_car_id"] == "car-1"
        assert result["cars"][0]["type"] == "sedan"
        assert result["cars"][0]["aspects"]["tire_width_mm"] == 225.0

    @pytest.mark.asyncio
    async def test_add_car_passes_only_non_null_fields(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/cars", "POST")
        assert endpoint is not None

        from vibesensor.shared.types.api_models import CarUpsertRequest

        state.settings_store.add_car.return_value = _make_cars_snapshot(
            cars=[_make_car_payload(), _make_car_payload(car_id="car-2", name="Second")],
        )

        await endpoint(req=CarUpsertRequest(name="Second", variant="Sport"))

        state.settings_store.add_car.assert_called_once_with({"name": "Second", "variant": "Sport"})


class TestSpeedSourceEndpoint:
    @pytest.mark.asyncio
    async def test_update_speed_source_passes_only_non_null_fields(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/speed-source", "POST")
        assert endpoint is not None

        from vibesensor.shared.types.api_models import SpeedSourceRequest

        state.settings_store.update_speed_source.return_value = {
            "speedSource": "manual",
            "manualSpeedKph": 42.0,
            "staleTimeoutS": 15.0,
        }

        await endpoint(req=SpeedSourceRequest(speed_source="manual", manual_speed_kph=42.0))

        state.settings_store.update_speed_source.assert_called_once_with(
            {"speedSource": "manual", "manualSpeedKph": 42.0}
        )

    @pytest.mark.asyncio
    async def test_speed_source_status_response_shape(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/speed-source/status", "GET")
        assert endpoint is not None

        state.gps_monitor.status_snapshot.return_value = _make_speed_source_status_snapshot()

        result = response_payload(await endpoint())

        assert result["speed_source"] == "gps"
        assert result["fix_dimension"] == "3d"


class TestSensorEndpoint:
    @pytest.mark.asyncio
    async def test_update_sensor_passes_normalized_mac_and_non_null_fields(
        self,
        _settings_router,
    ) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/sensors/{mac}", "POST")
        assert endpoint is not None

        from vibesensor.shared.types.api_models import SensorRequest

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


class TestSetAnalysisSettingsEndpoint:
    @pytest.mark.asyncio
    async def test_empty_changes_is_noop(self, _settings_router) -> None:
        """POST /api/settings/analysis with all-None body skips update_active_car_aspects."""
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/analysis", "POST")
        assert endpoint is not None

        from vibesensor.shared.types.api_models import AnalysisSettingsRequest

        result = response_payload(await endpoint(req=AnalysisSettingsRequest()))

        state.settings_store.update_active_car_aspects.assert_not_called()
        assert "tire_width_mm" in result

    @pytest.mark.asyncio
    async def test_valid_changes_calls_update(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/analysis", "POST")
        assert endpoint is not None

        from vibesensor.shared.types.api_models import AnalysisSettingsRequest

        await endpoint(req=AnalysisSettingsRequest(tire_width_mm=265.0))

        state.settings_store.update_active_car_aspects.assert_called_once_with(
            {"tire_width_mm": 265.0}
        )

    @pytest.mark.asyncio
    async def test_get_analysis_settings_response_shape(self, _settings_router) -> None:
        router, _ = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/analysis", "GET")
        assert endpoint is not None

        result = response_payload(await endpoint())

        for key in (
            "tire_width_mm",
            "tire_aspect_pct",
            "rim_in",
            "final_drive_ratio",
            "current_gear_ratio",
        ):
            assert key in result
