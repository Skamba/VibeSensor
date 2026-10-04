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


def test_ratios_are_optional_and_a_null_ratio_clears_the_stored_one(car_client) -> None:
    tire = {"tire_width_mm": 225.0, "tire_aspect_pct": 45.0, "rim_in": 17.0}
    car = _add(
        car_client,
        name="Tire only",
        aspects={**tire, "final_drive_ratio": None, "current_gear_ratio": None},
    )["cars"][0]
    assert "final_drive_ratio" not in car["aspects"]
    assert "current_gear_ratio" not in car["aspects"]

    status = {
        "selection_source_status": "exact_row",
        "requires_manual_confirmation": False,
        "final_drive_ratio_confidence": "official_exact",
        "current_gear_ratio_confidence": "official_exact",
    }
    filled = car_client.put(
        f"/api/settings/cars/{car['id']}",
        json={
            "aspects": {"final_drive_ratio": 3.2, "current_gear_ratio": 0.8},
            "order_reference_status": status,
        },
    ).json()["cars"][0]
    assert filled["aspects"]["final_drive_ratio"] == 3.2

    cleared = car_client.put(
        f"/api/settings/cars/{car['id']}",
        json={"aspects": {"final_drive_ratio": None}, "order_reference_status": status},
    ).json()["cars"][0]

    assert "final_drive_ratio" not in cleared["aspects"]
    assert cleared["aspects"]["current_gear_ratio"] == 0.8
    assert cleared["aspects"]["tire_width_mm"] == 225.0
    assert cleared["order_reference_status"].get("final_drive_ratio_confidence") is None
    assert cleared["order_reference_status"]["current_gear_ratio_confidence"] == ("official_exact")
