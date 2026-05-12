"""Smoke tests for key endpoints on the assembled HTTP router."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_assembled_router_serves_core_runtime_endpoints(fake_state) -> None:
    from vibesensor.adapters.http import create_router

    app = FastAPI()
    app.include_router(create_router(fake_state))

    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/settings/language").json() == {"language": "en"}
        assert client.put("/api/settings/language", json={"language": "nl"}).json() == {
            "language": "en",
        }
        assert client.get("/api/clients").json() == {"clients": []}
        assert client.get("/api/recording/status").json()["enabled"] is False
        assert client.get("/api/update/status").json()["state"] == "idle"
        assert client.get("/api/update/internet-status").json()["usable"] is False
        assert client.post("/api/update/cancel").json() == {"cancelled": False}
