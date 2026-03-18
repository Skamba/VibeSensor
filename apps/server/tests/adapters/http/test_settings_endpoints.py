"""Tests for HTTP-specific behavior of the /api/settings/* endpoints."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from test_support import response_payload

from vibesensor.domain import AnalysisSettingsSnapshot


def _make_default_snapshot() -> AnalysisSettingsSnapshot:
    return AnalysisSettingsSnapshot(**AnalysisSettingsSnapshot.DEFAULTS)


def _find_endpoint(router, path: str, method: str = "GET"):
    for route in router.routes:
        if getattr(route, "path", "") == path:
            methods = getattr(route, "methods", set()) or set()
            if method.upper() in methods:
                return route.endpoint
    return None


@pytest.fixture
def _settings_router(fake_state):
    from vibesensor.adapters.http.settings import create_settings_routes

    fake_state.settings_store.analysis_settings_snapshot.return_value = _make_default_snapshot()
    fake_state.settings_store.get_cars.return_value = {
        "cars": [{"id": "car-1", "name": "Test Car"}],
        "activeCar": {"id": "car-1", "name": "Test Car"},
    }
    return create_settings_routes(
        fake_state.settings_store,
        fake_state.gps_monitor,
    ), fake_state


class TestNormalizeMacOr400:
    """normalize_mac_or_400 raises HTTP 400 for invalid MAC path parameters."""

    @pytest.mark.asyncio
    async def test_empty_mac_raises_400(self, _settings_router) -> None:
        from vibesensor.adapters.http._helpers import normalize_mac_or_400

        with pytest.raises(HTTPException) as exc_info:
            normalize_mac_or_400("")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_oversized_mac_raises_400(self, _settings_router) -> None:
        from vibesensor.adapters.http._helpers import normalize_mac_or_400

        with pytest.raises(HTTPException) as exc_info:
            normalize_mac_or_400("A" * 65)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_mac_format_raises_400(self, _settings_router) -> None:
        from vibesensor.adapters.http._helpers import normalize_mac_or_400

        with pytest.raises(HTTPException) as exc_info:
            normalize_mac_or_400("not-a-mac-address")
        assert exc_info.value.status_code == 400


class TestDeleteCarEndpoint:
    @pytest.mark.asyncio
    async def test_delete_unknown_car_returns_404(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/cars/{car_id}", "DELETE")
        assert endpoint is not None

        state.settings_store.get_cars.return_value = {
            "cars": [],
            "activeCar": None,
        }

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(car_id="no-such-car")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_known_car_calls_store(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/cars/{car_id}", "DELETE")
        assert endpoint is not None

        state.settings_store.get_cars.return_value = {
            "cars": [{"id": "car-1", "name": "Test Car"}],
            "activeCar": {"id": "car-1", "name": "Test Car"},
        }
        state.settings_store.delete_car.return_value = {
            "cars": [],
            "activeCarId": None,
        }

        result = response_payload(await endpoint(car_id="car-1"))

        state.settings_store.delete_car.assert_called_once_with("car-1")
        assert "cars" in result

    @pytest.mark.asyncio
    async def test_delete_car_business_logic_error_returns_400(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/cars/{car_id}", "DELETE")
        assert endpoint is not None

        state.settings_store.get_cars.return_value = {
            "cars": [{"id": "car-1", "name": "Test Car"}],
            "activeCar": {"id": "car-1", "name": "Test Car"},
        }
        state.settings_store.delete_car.side_effect = ValueError("cannot delete last car")

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(car_id="car-1")
        assert exc_info.value.status_code == 400


class TestSetActiveCarEndpoint:
    @pytest.mark.asyncio
    async def test_unknown_car_id_raises_404(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/cars/active", "POST")
        assert endpoint is not None

        state.settings_store.set_active_car.side_effect = ValueError("Car not found")

        from vibesensor.shared.types.api_models import ActiveCarRequest

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(req=ActiveCarRequest(carId="no-such-car"))
        assert exc_info.value.status_code == 404


class TestSetAnalysisSettingsEndpoint:
    @pytest.mark.asyncio
    async def test_empty_changes_is_noop(self, _settings_router) -> None:
        """POST /api/settings/analysis with all-None body skips update_active_car_aspects."""
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/analysis", "POST")
        assert endpoint is not None

        from vibesensor.shared.types.api_models import AnalysisSettingsRequest

        result = response_payload(await endpoint(req=AnalysisSettingsRequest()))

        state.settings_store.update_active_car_aspects.assert_not_called()
        assert "tire_width_mm" in result

    @pytest.mark.asyncio
    async def test_valid_changes_calls_update(self, _settings_router) -> None:
        router, state = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/analysis", "POST")
        assert endpoint is not None

        from vibesensor.shared.types.api_models import AnalysisSettingsRequest

        await endpoint(req=AnalysisSettingsRequest(tire_width_mm=265.0))

        state.settings_store.update_active_car_aspects.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_analysis_settings_response_shape(self, _settings_router) -> None:
        router, _ = _settings_router
        endpoint = _find_endpoint(router, "/api/settings/analysis", "GET")
        assert endpoint is not None

        result = response_payload(await endpoint())

        for key in (
            "tire_width_mm",
            "tire_aspect_pct",
            "rim_in",
            "final_drive_ratio",
            "current_gear_ratio",
        ):
            assert key in result
