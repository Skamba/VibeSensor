"""Analysis settings route tests."""

from __future__ import annotations

import pytest
from _history_endpoint_helpers import route_endpoint, route_endpoint_with_method
from test_support import response_payload

from vibesensor.domain import AnalysisSettingsSnapshot


def _make_default_snapshot() -> AnalysisSettingsSnapshot:
    return AnalysisSettingsSnapshot(**AnalysisSettingsSnapshot.DEFAULTS)


def _find_endpoint(router, path: str, method: str = "GET"):
    if method.upper() == "GET":
        return route_endpoint(router, path)
    return route_endpoint_with_method(router, path, method)


@pytest.fixture
def _analysis_router(fake_state):
    from vibesensor.adapters.http.settings.analysis import create_analysis_settings_routes
    from vibesensor.adapters.http.settings.dependencies import AnalysisSettingsRouteDeps

    fake_state.settings_store.analysis_settings_snapshot.return_value = _make_default_snapshot()
    return (
        create_analysis_settings_routes(
            AnalysisSettingsRouteDeps(analysis_settings=fake_state.settings_store),
        ),
        fake_state,
    )


class TestSetAnalysisSettingsEndpoint:
    @pytest.mark.asyncio
    async def test_empty_changes_is_noop(self, _analysis_router) -> None:
        """PUT /api/settings/analysis with all-None body skips update_active_car_aspects."""

        router, state = _analysis_router
        endpoint = _find_endpoint(router, "/api/settings/analysis", "PUT")

        from vibesensor.adapters.http.models import AnalysisSettingsRequest

        result = response_payload(await endpoint(req=AnalysisSettingsRequest()))

        state.settings_store.update_active_car_aspects.assert_not_called()
        assert "tire_width_mm" in result

    @pytest.mark.asyncio
    async def test_valid_changes_calls_update(self, _analysis_router) -> None:
        router, state = _analysis_router
        endpoint = _find_endpoint(router, "/api/settings/analysis", "PUT")

        from vibesensor.adapters.http.models import AnalysisSettingsRequest

        await endpoint(req=AnalysisSettingsRequest(tire_width_mm=265.0))

        state.settings_store.update_active_car_aspects.assert_called_once_with(
            {"tire_width_mm": 265.0}
        )

    @pytest.mark.asyncio
    async def test_get_analysis_settings_response_shape(self, _analysis_router) -> None:
        router, _ = _analysis_router
        endpoint = _find_endpoint(router, "/api/settings/analysis", "GET")

        result = response_payload(await endpoint())

        for key in (
            "tire_width_mm",
            "tire_aspect_pct",
            "rim_in",
            "final_drive_ratio",
            "current_gear_ratio",
        ):
            assert key in result
