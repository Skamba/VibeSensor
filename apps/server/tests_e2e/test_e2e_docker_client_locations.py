"""Docker E2E tests for client location assignment edge cases."""

from __future__ import annotations

import pytest

from tests_e2e._docker_edge_helpers import (
    _cleanup_clients,
    _simulate,
)
from tests_e2e.e2e_helpers import (
    api_json,
)

pytestmark = pytest.mark.e2e


def test_client_location_invalid_input_matrix(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    _cleanup_clients(base)
    _simulate(e2e_env, duration=2.0, count=2, names="front-left,front-right")
    clients = sorted(api_json(base, "/api/clients")["clients"], key=lambda c: str(c["id"]))
    assert len(clients) >= 2

    c1 = str(clients[0]["id"])
    c2 = str(clients[1]["id"])
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
        _cleanup_clients(base)


def test_location_reassignment_releases_previous_slot(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    _cleanup_clients(base)
    _simulate(e2e_env, duration=2.0, count=2, names="front-left,front-right")
    clients = sorted(api_json(base, "/api/clients")["clients"], key=lambda c: str(c["id"]))
    c1 = str(clients[0]["id"])
    c2 = str(clients[1]["id"])
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
        _cleanup_clients(base)
