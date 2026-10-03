"""Car settings routes over the real car settings service."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def car_client(fake_state):
    from vibesensor.web.settings.cars import create_car_settings_routes

    app = FastAPI()
    app.include_router(create_car_settings_routes(car_settings=fake_state.car_settings))
    with TestClient(app) as client:
        yield client


def _add(client: TestClient, **body: object) -> dict:
    response = client.post("/api/settings/cars", json=body)
    assert response.status_code == 200
    return response.json()


def test_add_update_activate_and_list_cars(car_client) -> None:
    first = _add(car_client, name="First", aspects={"tire_width_mm": 225.0})["cars"][0]
    second = _add(car_client, name="Second", variant="Sport")["cars"][1]

    updated = car_client.put(f"/api/settings/cars/{first['id']}", json={"name": "Renamed"})
    assert updated.status_code == 200
    activated = car_client.put("/api/settings/cars/active", json={"car_id": second["id"]})
    assert activated.status_code == 200

    listed = car_client.get("/api/settings/cars").json()
    assert listed["active_car_id"] == second["id"]
    by_id = {car["id"]: car for car in listed["cars"]}
    assert by_id[first["id"]]["name"] == "Renamed"
    assert by_id[first["id"]]["aspects"]["tire_width_mm"] == 225.0
    assert by_id[second["id"]]["variant"] == "Sport"


def test_activating_an_unknown_car_is_404(car_client) -> None:
    _add(car_client, name="Only")

    response = car_client.put("/api/settings/cars/active", json={"car_id": "no-such-car"})

    assert response.status_code == 404


def test_deleting_an_unknown_car_is_404(car_client) -> None:
    assert car_client.delete("/api/settings/cars/no-such-car").status_code == 404


def test_deleting_the_last_car_is_refused_but_others_can_go(car_client) -> None:
    first = _add(car_client, name="First")["cars"][0]
    assert car_client.delete(f"/api/settings/cars/{first['id']}").status_code == 400

    second = _add(car_client, name="Second")["cars"][1]
    response = car_client.delete(f"/api/settings/cars/{second['id']}")

    assert response.status_code == 200
    assert [car["id"] for car in response.json()["cars"]] == [first["id"]]
