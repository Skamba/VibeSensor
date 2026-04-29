"""Analysis settings route tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.domain import AnalysisSettingsSnapshot


def _make_default_snapshot() -> AnalysisSettingsSnapshot:
    return AnalysisSettingsSnapshot(**AnalysisSettingsSnapshot.DEFAULTS)


@pytest.fixture
def _analysis_client(fake_state):
    from vibesensor.adapters.http.settings.analysis import create_analysis_settings_routes
    from vibesensor.adapters.http.settings.dependencies import AnalysisSettingsRouteDeps

    fake_state.settings_store.analysis_settings_snapshot.return_value = _make_default_snapshot()
    app = FastAPI()
    app.include_router(
        create_analysis_settings_routes(
            AnalysisSettingsRouteDeps(analysis_settings=fake_state.settings_store),
        )
    )
    with TestClient(app) as client:
        yield client, fake_state


class TestSetAnalysisSettingsEndpoint:
    def test_empty_changes_is_noop(self, _analysis_client) -> None:
        """PUT /api/settings/analysis with all-None body skips update_active_car_aspects."""

        client, state = _analysis_client

        response = client.put("/api/settings/analysis", json={})

        assert response.status_code == 200
        state.settings_store.update_active_car_aspects.assert_not_called()
        assert "tire_width_mm" in response.json()

    def test_valid_changes_calls_update(self, _analysis_client) -> None:
        client, state = _analysis_client

        response = client.put("/api/settings/analysis", json={"tire_width_mm": 265.0})

        assert response.status_code == 200
        state.settings_store.update_active_car_aspects.assert_called_once_with(
            {"tire_width_mm": 265.0}
        )

    def test_get_analysis_settings_response_shape(self, _analysis_client) -> None:
        client, _ = _analysis_client

        response = client.get("/api/settings/analysis")

        assert response.status_code == 200
        result = response.json()
        for key in (
            "tire_width_mm",
            "tire_aspect_pct",
            "rim_in",
            "final_drive_ratio",
            "current_gear_ratio",
        ):
            assert key in result
