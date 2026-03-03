from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI

from vibesensor.analysis_settings import AnalysisSettingsStore
from vibesensor.api import (
    ActiveCarRequest,
    AnalysisSettingsRequest,
    CarUpsertRequest,
    create_router,
)
from vibesensor.settings_store import SettingsStore


@dataclass
class _State:
    settings_store: SettingsStore
    analysis_settings: AnalysisSettingsStore

    def apply_car_settings(self) -> None:
        aspects = self.settings_store.active_car_aspects()
        if aspects:
            self.analysis_settings.update(aspects)

    def apply_speed_source_settings(self) -> None:
        pass

    def __post_init__(self) -> None:
        self.live_diagnostics = type("D", (), {"reset": lambda self: None})()
        self.metrics_logger = type(
            "M",
            (),
            {
                "status": lambda self: {},
                "start_logging": lambda self: {},
                "stop_logging": lambda self: {},
                "analysis_snapshot": lambda self: ({}, []),
            },
        )()
        self.history_db = type(
            "H",
            (),
            {
                "list_runs": lambda self: [],
                "get_run": lambda self, _run_id: None,
                "iter_run_samples": lambda self, _run_id, batch_size=1000: iter(()),
                "get_active_run_id": lambda self: None,
                "delete_run": lambda self, _run_id: False,
            },
        )()
        self.registry = type(
            "R",
            (),
            {
                "snapshot_for_api": lambda self: [],
                "get": lambda self, _cid: None,
                "set_name": lambda self, cid, name: type(
                    "U",
                    (),
                    {"client_id": cid, "name": name},
                )(),
                "remove_client": lambda self, _cid: True,
            },
        )()
        self.control_plane = type(
            "C",
            (),
            {"send_identify": lambda self, _id, _dur: (False, None)},
        )()
        self.gps_monitor = type(
            "G",
            (),
            {
                "effective_speed_mps": None,
                "override_speed_mps": None,
                "set_speed_override_kmh": lambda self, _v: None,
            },
        )()
        self.ws_hub = type(
            "W",
            (),
            {
                "add": lambda *args, **kwargs: None,
                "remove": lambda *args, **kwargs: None,
                "update_selected_client": lambda *args, **kwargs: None,
            },
        )()
        self.processor = type(
            "P",
            (),
            {
                "debug_spectrum": lambda self, _id: {},
                "raw_samples": lambda self, _id, n_samples=1: {},
            },
        )()


def _route(router, path: str, method: str = "GET"):
    for candidate in router.routes:
        if getattr(candidate, "path", "") == path and method in getattr(
            candidate, "methods", set()
        ):
            return candidate.endpoint
    raise AssertionError(path)


@pytest.mark.asyncio
async def test_analysis_settings_endpoint_updates_active_car_aspects(tmp_path: Path) -> None:
    from vibesensor.history_db import HistoryDB

    db = HistoryDB(tmp_path / "test.db")
    settings_store = SettingsStore(db=db)
    initial = settings_store.add_car({"name": "Primary"})
    settings_store.set_active_car(initial["cars"][0]["id"])
    analysis_settings = AnalysisSettingsStore()
    analysis_settings.update(settings_store.active_car_aspects() or {})
    state = _State(settings_store=settings_store, analysis_settings=analysis_settings)
    app = FastAPI()
    router = create_router(state)
    app.include_router(router)

    set_analysis = _route(router, "/api/analysis-settings", "POST")
    get_cars = _route(router, "/api/settings/cars", "GET")
    set_active = _route(router, "/api/settings/cars/active", "POST")
    add_car = _route(router, "/api/settings/cars", "POST")

    await set_analysis(AnalysisSettingsRequest(tire_width_mm=255.0))
    assert settings_store.active_car_aspects()["tire_width_mm"] == 255.0
    assert analysis_settings.snapshot()["tire_width_mm"] == 255.0

    cars = await add_car(CarUpsertRequest(name="Second", aspects={"tire_width_mm": 225.0}))
    second_id = cars["cars"][1]["id"]
    await set_active(ActiveCarRequest(carId=second_id))
    assert analysis_settings.snapshot()["tire_width_mm"] == 225.0
    current = await get_cars()
    assert current["activeCarId"] == second_id
