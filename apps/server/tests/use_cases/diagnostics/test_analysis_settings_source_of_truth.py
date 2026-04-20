from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from test_support import response_payload
from test_support.settings_services import build_settings_services

from tests.conftest import FakeState
from vibesensor.adapters.http import create_router
from vibesensor.adapters.http.models import (
    ActiveCarRequest,
    AnalysisSettingsRequest,
    CarUpsertRequest,
)


def _route(router, path: str, method: str = "GET"):
    for candidate in router.routes:
        if getattr(candidate, "path", "") == path and method in getattr(
            candidate,
            "methods",
            set(),
        ):
            return candidate.endpoint
    raise AssertionError(path)


@pytest.fixture
def _wiring(tmp_path: Path):
    """Provide a wired (state, router) pair with one active car named 'Primary'."""
    from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters

    db = create_history_persistence_adapters(tmp_path / "test.db")
    settings = build_settings_services(db=db.settings_snapshot_repository)
    initial = settings.car_settings.add_car({"name": "Primary"})
    settings.car_settings.set_active_car(initial.cars[0]["id"])
    state = FakeState(
        settings_reader=settings.settings_reader,
        car_settings=settings.car_settings,
        analysis_settings=settings.analysis_settings,
        history_db=db.run_repository,
    )
    app = FastAPI()
    router = create_router(state)
    app.include_router(router)
    return settings, router


@pytest.mark.asyncio
async def test_analysis_settings_endpoint_updates_active_car_aspects(_wiring) -> None:
    settings, router = _wiring

    set_analysis = _route(router, "/api/settings/analysis", "PUT")
    get_cars = _route(router, "/api/settings/cars", "GET")
    set_active = _route(router, "/api/settings/cars/active", "PUT")
    add_car = _route(router, "/api/settings/cars", "POST")

    await set_analysis(AnalysisSettingsRequest(tire_width_mm=255.0))
    assert settings.car_settings.active_car_aspects()["tire_width_mm"] == 255.0
    assert settings.analysis_settings.analysis_settings_snapshot().tire_width_mm == 255.0

    cars = response_payload(
        await add_car(CarUpsertRequest(name="Second", aspects={"tire_width_mm": 225.0})),
    )
    second_id = cars["cars"][1]["id"]
    await set_active(ActiveCarRequest(car_id=second_id))
    assert settings.analysis_settings.analysis_settings_snapshot().tire_width_mm == 225.0
    current = response_payload(await get_cars())
    assert current["active_car_id"] == second_id
