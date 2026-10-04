"""Analysis settings routes over the real active-car analysis settings."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot


@pytest.fixture
def analysis_client(fake_state):
    from vibesensor.web.settings.analysis import create_analysis_settings_routes

    created = fake_state.car_settings.add_car({"name": "Active"})
    fake_state.car_settings.set_active_car(created.cars[0]["id"])
    app = FastAPI()
    app.include_router(
        create_analysis_settings_routes(analysis_settings=fake_state.analysis_settings)
    )
    with TestClient(app) as client:
        yield client


def test_get_returns_the_active_car_settings(analysis_client) -> None:
    result = analysis_client.get("/api/settings/analysis").json()

    for key, default in AnalysisSettingsSnapshot.DEFAULTS.items():
        assert result[key] == pytest.approx(default), key
    # Tire size and ratios have no defaults: a new car leaves them unknown.
    for key in ("tire_width_mm", "rim_in", "final_drive_ratio", "current_gear_ratio"):
        assert result[key] is None, key


def test_put_updates_only_the_sent_settings(analysis_client) -> None:
    response = analysis_client.put("/api/settings/analysis", json={"tire_width_mm": 265.0})

    assert response.status_code == 200
    stored = analysis_client.get("/api/settings/analysis").json()
    assert stored["tire_width_mm"] == 265.0
    assert stored["rim_in"] is None


def test_empty_put_changes_nothing(analysis_client) -> None:
    before = analysis_client.get("/api/settings/analysis").json()

    response = analysis_client.put("/api/settings/analysis", json={})

    assert response.status_code == 200
    assert response.json() == before


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"tire_deflection_factor": 0.84}, id="deflection-below-0.85"),
        pytest.param({"tire_deflection_factor": 1.01}, id="deflection-above-1"),
    ],
)
def test_out_of_range_request_values_are_rejected(analysis_client, body: dict) -> None:
    assert analysis_client.put("/api/settings/analysis", json=body).status_code == 422
