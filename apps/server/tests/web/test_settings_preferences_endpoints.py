"""UI preference settings routes over the real preferences service."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def _preferences_client(fake_state):
    from vibesensor.web.settings.preferences import create_ui_preferences_routes

    app = FastAPI()
    app.include_router(create_ui_preferences_routes(ui_preferences=fake_state.ui_preferences))
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    ("path", "field", "default", "updated"),
    [
        ("/api/settings/language", "language", "en", "nl"),
        ("/api/settings/speed-unit", "speed_unit", "kmh", "mps"),
    ],
)
def test_preference_round_trips_through_get_and_put(
    _preferences_client, path: str, field: str, default: str, updated: str
) -> None:
    client = _preferences_client

    assert client.get(path).json() == {field: default}
    response = client.put(path, json={field: updated})

    assert response.status_code == 200
    assert response.json() == {field: updated}
    assert client.get(path).json() == {field: updated}


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/settings/language", {"language": "xx"}),
        ("/api/settings/speed-unit", {"speed_unit": "furlongs"}),
    ],
)
def test_unsupported_preference_values_are_rejected(
    _preferences_client, path: str, body: dict[str, str]
) -> None:
    response = _preferences_client.put(path, json=body)

    assert response.status_code == 422
