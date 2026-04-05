"""Car settings route tests."""

from __future__ import annotations

import pytest
from _history_endpoint_helpers import route_endpoint, route_endpoint_with_method
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from test_support import response_payload

from vibesensor.shared.types.car_config import CarConfigPayload, CarsSnapshot


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


def _find_endpoint(router, path: str, method: str = "GET"):
    if method.upper() == "GET":
        return route_endpoint(router, path)
    return route_endpoint_with_method(router, path, method)


@pytest.fixture
def _car_router(fake_state):
    from vibesensor.adapters.http.settings.cars import create_car_settings_routes
    from vibesensor.adapters.http.settings.dependencies import CarSettingsRouteDeps

    fake_state.settings_store.get_cars.return_value = _make_cars_snapshot()
    return (
        create_car_settings_routes(
            CarSettingsRouteDeps(car_settings=fake_state.settings_store),
        ),
        fake_state,
    )


class TestDeleteCarEndpoint:
    @pytest.mark.asyncio
    async def test_delete_unknown_car_returns_404(self, _car_router) -> None:
        router, state = _car_router
        endpoint = _find_endpoint(router, "/api/settings/cars/{car_id}", "DELETE")

        state.settings_store.get_cars.return_value = _make_cars_snapshot(
            cars=[],
            active_car_id=None,
        )

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(car_id="no-such-car")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_known_car_calls_store(self, _car_router) -> None:
        router, state = _car_router
        endpoint = _find_endpoint(router, "/api/settings/cars/{car_id}", "DELETE")

        state.settings_store.get_cars.return_value = _make_cars_snapshot()
        state.settings_store.delete_car.return_value = _make_cars_snapshot(
            cars=[],
            active_car_id=None,
        )

        result = response_payload(await endpoint(car_id="car-1"))

        state.settings_store.delete_car.assert_called_once_with("car-1")
        assert "cars" in result

    @pytest.mark.asyncio
    async def test_delete_car_business_logic_error_returns_400(self, _car_router) -> None:
        router, state = _car_router
        endpoint = _find_endpoint(router, "/api/settings/cars/{car_id}", "DELETE")

        state.settings_store.get_cars.return_value = _make_cars_snapshot()
        state.settings_store.delete_car.side_effect = ValueError("cannot delete last car")

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(car_id="car-1")
        assert exc_info.value.status_code == 400


class TestSetActiveCarEndpoint:
    @pytest.mark.asyncio
    async def test_unknown_car_id_raises_404(self, _car_router) -> None:
        router, state = _car_router
        endpoint = _find_endpoint(router, "/api/settings/cars/active", "PUT")

        state.settings_store.set_active_car.side_effect = ValueError("Car not found")

        from vibesensor.adapters.http.models import ActiveCarRequest

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(req=ActiveCarRequest(car_id="no-such-car"))
        assert exc_info.value.status_code == 404

    def test_static_put_route_wins_over_dynamic_car_id_route(self, _car_router) -> None:
        router, state = _car_router
        app = FastAPI()
        app.include_router(router)

        state.settings_store.set_active_car.return_value = _make_cars_snapshot(
            active_car_id="car-1"
        )

        with TestClient(app) as client:
            response = client.put("/api/settings/cars/active", json={"car_id": "car-1"})

        assert response.status_code == 200
        state.settings_store.set_active_car.assert_called_once_with("car-1")
        state.settings_store.update_car.assert_not_called()


class TestCarsEndpoint:
    @pytest.mark.asyncio
    async def test_get_cars_response_shape(self, _car_router) -> None:
        router, _ = _car_router
        endpoint = _find_endpoint(router, "/api/settings/cars", "GET")

        result = response_payload(await endpoint())

        assert result["active_car_id"] == "car-1"
        assert result["cars"][0]["type"] == "sedan"
        assert result["cars"][0]["aspects"]["tire_width_mm"] == 225.0

    @pytest.mark.asyncio
    async def test_add_car_passes_only_non_null_fields(self, _car_router) -> None:
        router, state = _car_router
        endpoint = _find_endpoint(router, "/api/settings/cars", "POST")

        from vibesensor.adapters.http.models import CarUpsertRequest

        state.settings_store.add_car.return_value = _make_cars_snapshot(
            cars=[_make_car_payload(), _make_car_payload(car_id="car-2", name="Second")],
        )

        await endpoint(req=CarUpsertRequest(name="Second", variant="Sport"))

        state.settings_store.add_car.assert_called_once_with({"name": "Second", "variant": "Sport"})

    @pytest.mark.asyncio
    async def test_update_car_passes_only_non_null_fields(self, _car_router) -> None:
        router, state = _car_router
        endpoint = _find_endpoint(router, "/api/settings/cars/{car_id}", "PUT")

        from vibesensor.adapters.http.models import CarUpsertRequest

        state.settings_store.update_car.return_value = _make_cars_snapshot()

        await endpoint(car_id="car-1", req=CarUpsertRequest(name="Updated", variant="GT"))

        state.settings_store.update_car.assert_called_once_with(
            "car-1",
            {"name": "Updated", "variant": "GT"},
        )
