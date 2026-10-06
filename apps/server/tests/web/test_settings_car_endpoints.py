"""Car settings routes over the real car settings service."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.domain.engine_profile import EngineProfile


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


def test_editing_a_reference_makes_only_that_one_user_confirmed(car_client) -> None:
    library_status = {
        "selection_source_status": "exact_row",
        "requires_manual_confirmation": True,
        "tire_dimensions_confidence": "official_exact",
        "final_drive_ratio_confidence": "family_default",
        "current_gear_ratio_confidence": "official_derived",
        "transmission_name": "8-speed automatic",
        "transmission_confidence": "official_exact",
    }
    car = _add(
        car_client,
        name="Library",
        aspects={
            "tire_width_mm": 225.0,
            "tire_aspect_pct": 45.0,
            "rim_in": 17.0,
            "final_drive_ratio": 3.15,
            "current_gear_ratio": 0.67,
        },
        order_reference_status=library_status,
    )["cars"][0]

    edited = car_client.put(
        f"/api/settings/cars/{car['id']}",
        json={"aspects": {"final_drive_ratio": 3.38, "current_gear_ratio": None}},
    ).json()["cars"][0]

    assert edited["aspects"]["final_drive_ratio"] == 3.38
    assert "current_gear_ratio" not in edited["aspects"]
    status = edited["order_reference_status"]
    assert status["final_drive_ratio_confidence"] == "user_confirmed"
    assert status.get("current_gear_ratio_confidence") is None
    assert status["tire_dimensions_confidence"] == "official_exact"
    assert status["transmission_name"] == "8-speed automatic"
    assert status["selection_source_status"] == "manual_entry"
    assert status["requires_manual_confirmation"] is False


def test_library_powertrain_is_kept_on_the_car_and_its_run_snapshot(car_client, fake_state) -> None:
    car = _add(car_client, name="i4 eDrive40", fuel_type="EV")["cars"][0]
    assert car["fuel_type"] == "EV"

    renamed = car_client.put(f"/api/settings/cars/{car['id']}", json={"name": "i4"}).json()
    car_client.put("/api/settings/cars/active", json={"car_id": car["id"]})

    assert renamed["cars"][0]["fuel_type"] == "EV"
    snapshot = fake_state.car_settings.active_car_snapshot()
    assert snapshot is not None and snapshot.fuel_type == "EV"


def test_an_ev_keeps_no_top_gear_so_only_its_reduction_ratio_asks_for_confirmation(
    car_client, fake_state
) -> None:
    """Older library rows gave EVs a made-up top gear of 1.0; an EV car keeps none."""
    tire = {"tire_width_mm": 245.0, "tire_aspect_pct": 45.0, "rim_in": 20.0}
    status = {
        "selection_source_status": "exact_row",
        "requires_manual_confirmation": True,
        "final_drive_ratio_confidence": "official_exact",
        "current_gear_ratio_confidence": "family_default",
    }
    car = _add(
        car_client,
        name="iX xDrive40",
        fuel_type="EV",
        aspects={**tire, "final_drive_ratio": 9.079, "current_gear_ratio": 1.0},
        order_reference_status=status,
    )["cars"][0]
    car_client.put("/api/settings/cars/active", json={"car_id": car["id"]})

    assert car["aspects"]["final_drive_ratio"] == 9.079
    assert "current_gear_ratio" not in car["aspects"]
    assert car["order_reference_status"].get("current_gear_ratio_confidence") is None
    assert car["order_reference_status"]["requires_manual_confirmation"] is False
    snapshot = fake_state.car_settings.active_car_snapshot()
    assert snapshot is not None and "current_gear_ratio" not in snapshot.aspects

    # The reduction ratio is still confirmed by its own confidence.
    weak = car_client.put(
        f"/api/settings/cars/{car['id']}",
        json={
            "order_reference_status": {**status, "final_drive_ratio_confidence": "family_default"}
        },
    ).json()["cars"][0]
    assert weak["order_reference_status"]["requires_manual_confirmation"] is True


def test_drive_layout_is_kept_on_the_car_and_its_run_snapshot(car_client, fake_state) -> None:
    """The layout the wizard sends is saved; the final-drive axle follows from it."""
    car = _add(car_client, name="Golf", drive_layout="FWD")["cars"][0]
    assert (car["drive_layout"], car["final_drive_axle"]) == ("FWD", "front")
    custom = _add(car_client, name="Unknown layout")["cars"][1]
    assert custom.get("drive_layout") is None

    changed = car_client.put(
        f"/api/settings/cars/{custom['id']}", json={"drive_layout": "RWD"}
    ).json()["cars"][1]
    renamed = car_client.put(f"/api/settings/cars/{car['id']}", json={"name": "Golf GTI"}).json()
    car_client.put("/api/settings/cars/active", json={"car_id": car["id"]})

    assert (changed["drive_layout"], changed["final_drive_axle"]) == ("RWD", "rear")
    assert renamed["cars"][0]["drive_layout"] == "FWD"
    snapshot = fake_state.car_settings.active_car_snapshot()
    assert snapshot is not None
    assert (snapshot.drive_layout, snapshot.final_drive_axle) == ("FWD", "front")


def test_a_library_awd_car_keeps_the_axle_of_its_final_drive(car_client) -> None:
    """The axle belongs to the layout: editing the ratio keeps an e-AWD car e-AWD."""
    car = _add(
        car_client, name="225xe", drive_layout="AWD", final_drive_axle="front", fuel_type="PHEV"
    )["cars"][0]
    assert (car["drive_layout"], car["final_drive_axle"]) == ("AWD", "front")

    url = f"/api/settings/cars/{car['id']}"
    edited = car_client.put(url, json={"aspects": {"final_drive_ratio": 4.1}}).json()["cars"][0]
    assert (edited["aspects"]["final_drive_ratio"], edited["final_drive_axle"]) == (4.1, "front")
    cleared = car_client.put(url, json={"aspects": {"final_drive_ratio": None}}).json()["cars"][0]
    assert "final_drive_ratio" not in cleared["aspects"]
    assert cleared["final_drive_axle"] == "front"
    # A new layout drops the library's axle.
    rwd = car_client.put(url, json={"drive_layout": "RWD"}).json()["cars"][0]
    assert (rwd["drive_layout"], rwd["final_drive_axle"]) == ("RWD", "rear")


def test_an_unknown_drive_layout_is_rejected(car_client) -> None:
    response = car_client.post("/api/settings/cars", json={"name": "X", "drive_layout": "4WD"})
    assert response.status_code == 422


def test_engine_profile_is_kept_on_the_car_and_its_run_snapshot(car_client, fake_state) -> None:
    """The engine the wizard sends is saved; an EV keeps none; unknown stays unknown."""
    six = _add(
        car_client, name="Six-cylinder saloon", engine_profile={"layout": "inline", "cylinders": 6}
    )
    car = six["cars"][0]
    assert car["engine_profile"] == {"layout": "inline", "cylinders": 6}
    custom = _add(car_client, name="Unknown engine")["cars"][1]
    assert custom.get("engine_profile") is None
    ev = _add(
        car_client, name="i4", fuel_type="EV", engine_profile={"layout": "inline", "cylinders": 4}
    )["cars"][2]
    assert ev.get("engine_profile") is None

    changed = car_client.put(
        f"/api/settings/cars/{custom['id']}",
        json={"engine_profile": {"layout": "v", "cylinders": 6, "bank_angle_deg": 90}},
    ).json()["cars"][1]
    renamed = car_client.put(
        f"/api/settings/cars/{car['id']}", json={"name": "Six-cylinder estate"}
    ).json()
    car_client.put("/api/settings/cars/active", json={"car_id": car["id"]})

    assert changed["engine_profile"] == {"layout": "v", "cylinders": 6, "bank_angle_deg": 90}
    assert renamed["cars"][0]["engine_profile"] == {"layout": "inline", "cylinders": 6}
    snapshot = fake_state.car_settings.active_car_snapshot()
    assert snapshot is not None
    assert snapshot.engine_profile == EngineProfile("inline", 6)


@pytest.mark.parametrize(
    "engine_profile",
    [
        {"layout": "hemi", "cylinders": 8},
        {"layout": "inline", "cylinders": 0},
        {"layout": "inline", "cylinders": 17},
        {"layout": "inline", "cylinders": 4, "bank_angle_deg": 90},
        {"layout": "rotary", "cylinders": 6},
    ],
)
def test_an_impossible_engine_profile_is_rejected(car_client, engine_profile) -> None:
    response = car_client.post(
        "/api/settings/cars", json={"name": "X", "engine_profile": engine_profile}
    )
    assert response.status_code == 422
