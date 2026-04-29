"""Car settings route tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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


@pytest.fixture
def _car_client(fake_state):
    from vibesensor.adapters.http.settings.cars import create_car_settings_routes
    from vibesensor.adapters.http.settings.dependencies import CarSettingsRouteDeps

    fake_state.settings_store.get_cars.return_value = _make_cars_snapshot()
    app = FastAPI()
    app.include_router(
        create_car_settings_routes(
            CarSettingsRouteDeps(car_settings=fake_state.settings_store),
        )
    )
    with TestClient(app) as client:
        yield client, fake_state


class TestDeleteCarEndpoint:
    def test_delete_unknown_car_returns_404(self, _car_client) -> None:
        client, state = _car_client
        state.settings_store.get_cars.return_value = _make_cars_snapshot(
            cars=[],
            active_car_id=None,
        )

        response = client.delete("/api/settings/cars/no-such-car")

        assert response.status_code == 404

    def test_delete_known_car_calls_store(self, _car_client) -> None:
        client, state = _car_client
        state.settings_store.get_cars.return_value = _make_cars_snapshot()
        state.settings_store.delete_car.return_value = _make_cars_snapshot(
            cars=[],
            active_car_id=None,
        )

        response = client.delete("/api/settings/cars/car-1")

        assert response.status_code == 200
        state.settings_store.delete_car.assert_called_once_with("car-1")
        assert "cars" in response.json()

    def test_delete_car_business_logic_error_returns_400(self, _car_client) -> None:
        client, state = _car_client
        state.settings_store.get_cars.return_value = _make_cars_snapshot()
        state.settings_store.delete_car.side_effect = ValueError("cannot delete last car")

        response = client.delete("/api/settings/cars/car-1")

        assert response.status_code == 400


class TestSetActiveCarEndpoint:
    def test_unknown_car_id_raises_404(self, _car_client) -> None:
        client, state = _car_client
        state.settings_store.set_active_car.side_effect = ValueError("Car not found")

        response = client.put("/api/settings/cars/active", json={"car_id": "no-such-car"})

        assert response.status_code == 404

    def test_static_put_route_wins_over_dynamic_car_id_route(self, _car_client) -> None:
        client, state = _car_client
        state.settings_store.set_active_car.return_value = _make_cars_snapshot(
            active_car_id="car-1"
        )

        response = client.put("/api/settings/cars/active", json={"car_id": "car-1"})

        assert response.status_code == 200
        state.settings_store.set_active_car.assert_called_once_with("car-1")
        state.settings_store.update_car.assert_not_called()


class TestCarsEndpoint:
    def test_get_cars_response_shape(self, _car_client) -> None:
        client, _ = _car_client

        response = client.get("/api/settings/cars")

        assert response.status_code == 200
        result = response.json()
        assert result["active_car_id"] == "car-1"
        assert result["cars"][0]["type"] == "sedan"
        assert result["cars"][0]["aspects"]["tire_width_mm"] == 225.0

    def test_add_car_passes_only_non_null_fields(self, _car_client) -> None:
        client, state = _car_client
        state.settings_store.add_car.return_value = _make_cars_snapshot(
            cars=[_make_car_payload(), _make_car_payload(car_id="car-2", name="Second")],
        )

        response = client.post("/api/settings/cars", json={"name": "Second", "variant": "Sport"})

        assert response.status_code == 200
        state.settings_store.add_car.assert_called_once_with({"name": "Second", "variant": "Sport"})

    def test_update_car_passes_only_non_null_fields(self, _car_client) -> None:
        client, state = _car_client
        state.settings_store.update_car.return_value = _make_cars_snapshot()

        response = client.put(
            "/api/settings/cars/car-1",
            json={"name": "Updated", "variant": "GT"},
        )

        assert response.status_code == 200
        state.settings_store.update_car.assert_called_once_with(
            "car-1",
            {"name": "Updated", "variant": "GT"},
        )
