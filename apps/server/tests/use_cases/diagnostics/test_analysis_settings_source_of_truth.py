from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from test_support import response_payload

from tests.conftest import FakeState
from vibesensor.adapters.http import create_router
from vibesensor.infra.config.analysis_settings import AnalysisSettingsStore
from vibesensor.infra.config.settings_store import SettingsStore
from vibesensor.shared.types.api_models import (
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
    from vibesensor.adapters.persistence.history_db import HistoryDB

    db = HistoryDB(tmp_path / "test.db")
    analysis_settings = AnalysisSettingsStore()
    settings_store = SettingsStore(db=db, analysis_settings=analysis_settings)
    initial = settings_store.add_car({"name": "Primary"})
    settings_store.set_active_car(initial["cars"][0]["id"])
    state = FakeState(
        settings_store=settings_store,
        analysis_settings=analysis_settings,
        history_db=db,
    )
    app = FastAPI()
    router = create_router(state)
    app.include_router(router)
    return state, router


@pytest.mark.asyncio
async def test_analysis_settings_endpoint_updates_active_car_aspects(_wiring) -> None:
    state, router = _wiring
    settings_store = state.settings_store
    analysis_settings = state.analysis_settings

    set_analysis = _route(router, "/api/settings/analysis", "POST")
    get_cars = _route(router, "/api/settings/cars", "GET")
    set_active = _route(router, "/api/settings/cars/active", "POST")
    add_car = _route(router, "/api/settings/cars", "POST")

    await set_analysis(AnalysisSettingsRequest(tire_width_mm=255.0))
    assert settings_store.active_car_aspects()["tire_width_mm"] == 255.0
    assert analysis_settings.snapshot()["tire_width_mm"] == 255.0

    cars = response_payload(
        await add_car(CarUpsertRequest(name="Second", aspects={"tire_width_mm": 225.0})),
    )
    second_id = cars["cars"][1]["id"]
    await set_active(ActiveCarRequest(carId=second_id))
    assert analysis_settings.snapshot()["tire_width_mm"] == 225.0
    current = response_payload(await get_cars())
    assert current["activeCarId"] == second_id
