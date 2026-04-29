"""UI preference settings route tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def _preferences_client(fake_state):
    from vibesensor.adapters.http.settings.dependencies import UiPreferencesRouteDeps
    from vibesensor.adapters.http.settings.preferences import create_ui_preferences_routes

    app = FastAPI()
    app.include_router(
        create_ui_preferences_routes(
            UiPreferencesRouteDeps(ui_preferences=fake_state.settings_store),
        )
    )
    with TestClient(app) as client:
        yield client, fake_state


class TestPreferencesEndpoint:
    def test_get_language_returns_current_language(self, _preferences_client) -> None:
        client, state = _preferences_client
        state.settings_store.language = "lt"

        response = client.get("/api/settings/language")

        assert response.status_code == 200
        assert response.json() == {"language": "lt"}

    def test_set_language_maps_invalid_language_to_400(self, _preferences_client) -> None:
        client, state = _preferences_client
        state.settings_store.set_language.side_effect = ValueError("Unsupported language code")

        response = client.put("/api/settings/language", json={"language": "en"})

        assert response.status_code == 400

    def test_get_speed_unit_returns_current_speed_unit(self, _preferences_client) -> None:
        client, state = _preferences_client
        state.settings_store.speed_unit = "mps"

        response = client.get("/api/settings/speed-unit")

        assert response.status_code == 200
        assert response.json() == {"speed_unit": "mps"}

    def test_set_speed_unit_returns_updated_unit(self, _preferences_client) -> None:
        client, state = _preferences_client
        state.settings_store.set_speed_unit.return_value = "mps"

        response = client.put("/api/settings/speed-unit", json={"speed_unit": "mps"})

        assert response.status_code == 200
        state.settings_store.set_speed_unit.assert_called_once_with("mps")
        assert response.json() == {"speed_unit": "mps"}
