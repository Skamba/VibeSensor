from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from vibesensor.adapters.http import create_router
from vibesensor.adapters.http.middleware import install_local_mutation_safety_middleware

_UNSAFE_METHODS = {"DELETE", "PATCH", "POST", "PUT"}


def _test_client() -> TestClient:
    app = FastAPI()
    install_local_mutation_safety_middleware(app)

    @app.get("/state")
    async def read_state() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/state")
    async def mutate_state() -> dict[str, bool]:
        return {"ok": True}

    @app.put("/state")
    async def replace_state() -> dict[str, bool]:
        return {"ok": True}

    @app.patch("/state")
    async def patch_state() -> dict[str, bool]:
        return {"ok": True}

    @app.delete("/state")
    async def delete_state() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app, base_url="http://vibesensor.local")


@pytest.mark.parametrize("method", sorted(_UNSAFE_METHODS))
def test_local_mutation_safety_blocks_cross_origin_browser_mutations(method: str) -> None:
    with _test_client() as client:
        response = client.request(method, "/state", headers={"Origin": "http://evil.local"})

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Mutating local API requests must be same-origin.",
    }


@pytest.mark.parametrize(
    ("header_name", "header_value"),
    [
        ("Origin", "http://vibesensor.local"),
        ("Referer", "http://vibesensor.local/settings"),
    ],
)
def test_local_mutation_safety_allows_same_origin_mutations(
    header_name: str,
    header_value: str,
) -> None:
    with _test_client() as client:
        response = client.post(
            "/state",
            headers={header_name: header_value},
        )

    assert response.status_code == 200


@pytest.mark.parametrize("header_value", ["not a url", "ftp://vibesensor.local"])
def test_local_mutation_safety_rejects_malformed_browser_origin(header_value: str) -> None:
    with _test_client() as client:
        response = client.post("/state", headers={"Origin": header_value})

    assert response.status_code == 403


def test_local_mutation_safety_allows_non_browser_local_clients() -> None:
    with _test_client() as client:
        response = client.post("/state")

    assert response.status_code == 200


def test_local_mutation_safety_allows_cross_origin_read_only_requests() -> None:
    with _test_client() as client:
        response = client.get("/state", headers={"Origin": "http://evil.local"})

    assert response.status_code == 200


def test_all_mutating_http_routes_are_classified_by_method(fake_state) -> None:
    router = create_router(fake_state.router)
    unsafe_routes = {
        (
            next(method for method in sorted(route.methods) if method in _UNSAFE_METHODS),
            route.path,
        )
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.methods is not None
        and route.methods.intersection(_UNSAFE_METHODS)
    }

    assert unsafe_routes == {
        ("DELETE", "/api/clients/{client_id}"),
        ("DELETE", "/api/history/{run_id}"),
        ("DELETE", "/api/settings/cars/{car_id}"),
        ("POST", "/api/clients/{client_id}/identify"),
        ("POST", "/api/clients/{client_id}/location"),
        ("POST", "/api/esp-flash/cancel"),
        ("POST", "/api/esp-flash/start"),
        ("POST", "/api/recording/start"),
        ("POST", "/api/recording/stop"),
        ("POST", "/api/settings/cars"),
        ("POST", "/api/settings/obd/pair"),
        ("POST", "/api/settings/obd/scan"),
        ("POST", "/api/update/cancel"),
        ("POST", "/api/update/start"),
        ("PUT", "/api/settings/analysis"),
        ("PUT", "/api/settings/cars/active"),
        ("PUT", "/api/settings/cars/{car_id}"),
        ("PUT", "/api/settings/language"),
        ("PUT", "/api/settings/speed-source"),
        ("PUT", "/api/settings/speed-unit"),
    }
