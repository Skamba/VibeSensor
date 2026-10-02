"""Docker E2E tests for client location assignment edge cases."""

from __future__ import annotations

import pytest

from tests_e2e._docker_edge_helpers import _simulate
from tests_e2e.e2e_helpers import (
    api_json,
    registered_client_ids,
    remove_all_clients,
    sim_client_ids,
)

pytestmark = pytest.mark.e2e


def _register_two_sim_clients(e2e_env: dict[str, str]) -> tuple[str, str]:
    base = e2e_env["base_url"]
    remove_all_clients(base)
    _simulate(e2e_env, duration=2.0, count=2, names="front-left,front-right")
    c1, c2 = sim_client_ids(2)
    assert registered_client_ids(base) >= {c1, c2}
    return c1, c2


def test_client_location_invalid_input_matrix(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    c1, c2 = _register_two_sim_clients(e2e_env)
    try:
        api_json(
            base,
            "/api/clients/not-a-client/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
            expected_status=400,
        )
        api_json(
            base,
            "/api/clients/025a000000ff/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
            expected_status=404,
        )
        api_json(
            base,
            f"/api/clients/{c1}/location",
            method="POST",
            body={"location_code": "nowhere"},
            expected_status=400,
        )

        api_json(
            base,
            f"/api/clients/{c1}/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
        )
        api_json(
            base,
            f"/api/clients/{c2}/location",
            method="POST",
            body={"location_code": "front_right_wheel"},
        )
        api_json(
            base,
            f"/api/clients/{c2}/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
            expected_status=409,
        )
    finally:
        remove_all_clients(base)


def test_location_reassignment_releases_previous_slot(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    c1, c2 = _register_two_sim_clients(e2e_env)
    try:
        api_json(
            base,
            f"/api/clients/{c1}/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
        )
        api_json(
            base,
            f"/api/clients/{c2}/location",
            method="POST",
            body={"location_code": "front_right_wheel"},
        )
        api_json(
            base,
            f"/api/clients/{c1}/location",
            method="POST",
            body={"location_code": "rear_left_wheel"},
        )
        moved = api_json(
            base,
            f"/api/clients/{c2}/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
        )
        assert moved["location_code"] == "front_left_wheel"

        clients_after_move = {
            str(client["id"]): client["location_code"]
            for client in api_json(base, "/api/clients")["clients"]
        }
        assert clients_after_move[c1] == "rear_left_wheel"
        assert clients_after_move[c2] == "front_left_wheel"
    finally:
        remove_all_clients(base)
