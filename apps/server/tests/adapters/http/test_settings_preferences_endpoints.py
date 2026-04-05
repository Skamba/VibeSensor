"""UI preference settings route tests."""

from __future__ import annotations

import pytest
from _history_endpoint_helpers import route_endpoint, route_endpoint_with_method
from fastapi import HTTPException
from test_support import response_payload


def _find_endpoint(router, path: str, method: str = "GET"):
    if method.upper() == "GET":
        return route_endpoint(router, path)
    return route_endpoint_with_method(router, path, method)


@pytest.fixture
def _preferences_router(fake_state):
    from vibesensor.adapters.http.settings.dependencies import UiPreferencesRouteDeps
    from vibesensor.adapters.http.settings.preferences import create_ui_preferences_routes

    return (
        create_ui_preferences_routes(
            UiPreferencesRouteDeps(ui_preferences=fake_state.settings_store),
        ),
        fake_state,
    )


class TestPreferencesEndpoint:
    @pytest.mark.asyncio
    async def test_get_language_returns_current_language(self, _preferences_router) -> None:
        router, state = _preferences_router
        endpoint = _find_endpoint(router, "/api/settings/language", "GET")

        state.settings_store.language = "lt"

        result = response_payload(await endpoint())

        assert result == {"language": "lt"}

    @pytest.mark.asyncio
    async def test_set_language_maps_invalid_language_to_400(self, _preferences_router) -> None:
        router, state = _preferences_router
        endpoint = _find_endpoint(router, "/api/settings/language", "PUT")

        from vibesensor.adapters.http.models import LanguageRequest

        state.settings_store.set_language.side_effect = ValueError("Unsupported language code")

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(req=LanguageRequest(language="en"))

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_speed_unit_returns_current_speed_unit(self, _preferences_router) -> None:
        router, state = _preferences_router
        endpoint = _find_endpoint(router, "/api/settings/speed-unit", "GET")

        state.settings_store.speed_unit = "mps"

        result = response_payload(await endpoint())

        assert result == {"speed_unit": "mps"}

    @pytest.mark.asyncio
    async def test_set_speed_unit_returns_updated_unit(self, _preferences_router) -> None:
        router, state = _preferences_router
        endpoint = _find_endpoint(router, "/api/settings/speed-unit", "PUT")

        from vibesensor.adapters.http.models import SpeedUnitRequest

        state.settings_store.set_speed_unit.return_value = "mps"

        result = response_payload(await endpoint(req=SpeedUnitRequest(speed_unit="mps")))

        state.settings_store.set_speed_unit.assert_called_once_with("mps")
        assert result == {"speed_unit": "mps"}
