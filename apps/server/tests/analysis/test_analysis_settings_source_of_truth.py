from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from vibesensor.analysis_settings import AnalysisSettingsStore
from vibesensor.api_models import ActiveCarRequest, AnalysisSettingsRequest, CarUpsertRequest
from vibesensor.routes import create_router
from vibesensor.settings_store import SettingsStore


def _noop(*_args, **_kwargs):  # noqa: ANN202
    return None


@dataclass
class _State:
    settings_store: SettingsStore
    analysis_settings: AnalysisSettingsStore

    live_diagnostics: object = field(init=False)
    metrics_logger: object = field(init=False)
    history_db: object = field(init=False)
    registry: object = field(init=False)
    control_plane: object = field(init=False)
    gps_monitor: object = field(init=False)
    ws_hub: object = field(init=False)
    processor: object = field(init=False)
    loop_state: object = field(init=False)
    update_manager: object = field(init=False)
    esp_flash_manager: object = field(init=False)

    def apply_car_settings(self) -> None:
        aspects = self.settings_store.active_car_aspects()
        if aspects:
            self.analysis_settings.update(aspects)

    def apply_speed_source_settings(self) -> None:
        pass

    def __post_init__(self) -> None:
        from vibesensor.runtime import ProcessingLoopState

        self.loop_state = ProcessingLoopState()
        self.update_manager = None
        self.esp_flash_manager = None
        self.live_diagnostics = SimpleNamespace(reset=_noop)
        self.metrics_logger = SimpleNamespace(
            status=dict,
            start_logging=_noop,
            stop_logging=_noop,
            analysis_snapshot=lambda: ({}, []),
        )
        self.history_db = SimpleNamespace(
            list_runs=list,
            get_run=_noop,
            iter_run_samples=lambda *_a, **_kw: iter(()),
            get_active_run_id=_noop,
            delete_run=lambda _id: False,
        )
        self.registry = SimpleNamespace(
            snapshot_for_api=list,
            get=_noop,
            set_name=lambda cid, name: SimpleNamespace(client_id=cid, name=name),
            remove_client=lambda _cid: True,
        )
        self.control_plane = SimpleNamespace(
            send_identify=lambda _id, _dur: (False, None),
        )
        self.gps_monitor = SimpleNamespace(
            effective_speed_mps=None,
            override_speed_mps=None,
            set_speed_override_kmh=_noop,
        )
        self.ws_hub = SimpleNamespace(
            add=_noop,
            remove=_noop,
            update_selected_client=_noop,
        )
        self.processor = SimpleNamespace(
            debug_spectrum=lambda _id: {},
            raw_samples=lambda _id, n_samples=1: {},
            intake_stats=lambda: {},
        )


def _route(router, path: str, method: str = "GET"):
    for candidate in router.routes:
        if getattr(candidate, "path", "") == path and method in getattr(
            candidate, "methods", set()
        ):
            return candidate.endpoint
    raise AssertionError(path)


@pytest.fixture
def _wiring(tmp_path: Path):
    """Provide a wired (state, router) pair with one active car named 'Primary'."""
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
    return state, router


@pytest.mark.asyncio
async def test_analysis_settings_endpoint_updates_active_car_aspects(_wiring) -> None:
    state, router = _wiring
    settings_store = state.settings_store
    analysis_settings = state.analysis_settings

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
