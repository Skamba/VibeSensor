"""Docker E2E tests for car CRUD edge cases."""

from __future__ import annotations

import pytest

from tests_e2e.e2e_helpers import api_json

pytestmark = pytest.mark.e2e
def test_car_crud_edge_cases_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    cars_before = api_json(base, "/api/settings/cars")
    original_active_raw = cars_before.get("active_car_id")
    original_active = str(original_active_raw) if isinstance(original_active_raw, str) else None

    api_json(
        base,
        "/api/settings/cars",
        method="POST",
        body={
            "name": "Edge A",
            "type": "sedan",
            "aspects": {"tire_width_mm": 255, "tire_aspect_pct": 40, "rim_in": 19},
        },
    )
    car_b = api_json(
        base,
        "/api/settings/cars",
        method="POST",
        body={
            "name": "Edge B",
            "type": "sedan",
            "aspects": {"tire_width_mm": 265, "tire_aspect_pct": 35, "rim_in": 20},
        },
    )
    ids_after = {str(c["id"]) for c in car_b["cars"]}
    ids_before = {str(c["id"]) for c in cars_before["cars"]}
    created_ids = sorted(ids_after - ids_before)
    assert len(created_ids) == 2

    try:
        api_json(
            base,
            "/api/settings/cars/active",
            method="PUT",
            body={"car_id": "missing-car"},
            expected_status=404,
        )

        active_target = created_ids[0]
        api_json(base, "/api/settings/cars/active", method="PUT", body={"car_id": active_target})
        api_json(base, f"/api/settings/cars/{active_target}", method="DELETE")
        after_delete = api_json(base, "/api/settings/cars")
        assert after_delete["active_car_id"] != active_target

        while len(api_json(base, "/api/settings/cars")["cars"]) > 1:
            snapshot = api_json(base, "/api/settings/cars")
            active = str(snapshot["active_car_id"])
            victim = next(str(c["id"]) for c in snapshot["cars"] if str(c["id"]) != active)
            api_json(base, f"/api/settings/cars/{victim}", method="DELETE")
        lone = api_json(base, "/api/settings/cars")
        lone_car_id = str(lone["cars"][0]["id"])
        api_json(base, f"/api/settings/cars/{lone_car_id}", method="DELETE", expected_status=400)
        final_state = api_json(base, "/api/settings/cars")
        assert len(final_state["cars"]) == 1
        assert final_state["active_car_id"] == lone_car_id
    finally:
        current = api_json(base, "/api/settings/cars")
        remaining_ids = {str(c["id"]) for c in current["cars"]}
        for car_id in sorted(remaining_ids):
            if car_id != original_active:
                api_json(
                    base,
                    f"/api/settings/cars/{car_id}",
                    method="DELETE",
                    expected_status=(200, 400, 404),
                )
        if original_active is not None:
            api_json(
                base,
                "/api/settings/cars/active",
                method="PUT",
                body={"car_id": original_active},
                expected_status=(200, 404),
            )
