"""OS connectivity probes on the hotspot are redirected to the UI (captive portal)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.web.middleware import install_captive_portal_middleware


def _client() -> TestClient:
    app = FastAPI()
    install_captive_portal_middleware(app)

    @app.get("/{path:path}")
    async def ui(path: str) -> dict[str, str]:
        return {"served": path}

    return TestClient(app, base_url="http://10.4.0.1", follow_redirects=False)


@pytest.mark.parametrize(
    ("method", "host", "path"),
    [
        pytest.param("GET", "connectivitycheck.gstatic.com", "/generate_204", id="android"),
        pytest.param("GET", "clients3.google.com", "/generate_204", id="android-legacy"),
        pytest.param("GET", "captive.apple.com", "/hotspot-detect.html", id="apple"),
        pytest.param("GET", "www.msftconnecttest.com", "/connecttest.txt", id="windows"),
        pytest.param("HEAD", "WWW.MSFTNCSI.COM.", "/ncsi.txt", id="windows-ncsi-case-dot"),
        pytest.param("GET", "detectportal.firefox.com:80", "/canonical.html", id="firefox-port"),
        pytest.param("GET", "nmcheck.gnome.org", "/check_network_status.txt", id="gnome"),
    ],
)
def test_connectivity_probe_redirects_to_the_ui(method: str, host: str, path: str) -> None:
    with _client() as client:
        response = client.request(method, path, headers={"Host": host})

    assert response.status_code == 302
    assert response.headers["location"] == "http://10.4.0.1/"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "host",
    ["10.4.0.1", "localhost:8000", "vibesensor.local", "www.google.com", "notcaptive.apple.com"],
)
def test_ui_and_other_hosts_pass_through(host: str) -> None:
    with _client() as client:
        response = client.get("/generate_204", headers={"Host": host})

    assert response.status_code == 200
    assert response.json() == {"served": "generate_204"}
