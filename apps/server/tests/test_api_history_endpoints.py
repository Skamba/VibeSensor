from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI, WebSocketDisconnect

from vibesensor.api import create_router
from vibesensor.reports import summarize_run_data


def _sample(i: int) -> dict[str, Any]:
    return {
        "record_type": "sample",
        "run_id": "run-1",
        "timestamp_utc": f"2026-01-01T00:00:{i:02d}Z",
        "t_s": float(i),
        "client_id": "aabbccddeeff",
        "client_name": "front-left wheel",
        "speed_kmh": 60.0 + i,
        "accel_x_g": 0.02,
        "accel_y_g": 0.02,
        "accel_z_g": 0.02,
        "dominant_freq_hz": 15.0,
        "dominant_axis": "x",
        "top_peaks": [
            {
                "hz": 15.0,
                "amp": 0.1,
                "vibration_strength_db": 12.0,
                "strength_bucket": "l2",
            }
        ],
        "vibration_strength_db": 12.0,
        "strength_bucket": "l2",
    }


@dataclass
class _FakeHistoryDB:
    metadata: dict[str, Any]
    samples: list[dict[str, Any]]
    analysis: dict[str, Any]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if run_id != "run-1":
            return None
        return {
            "run_id": run_id,
            "status": "complete",
            "metadata": self.metadata,
            "analysis": self.analysis,
        }

    def iter_run_samples(self, run_id: str, batch_size: int = 1000):
        if run_id != "run-1":
            return
        for start in range(0, len(self.samples), batch_size):
            yield self.samples[start : start + batch_size]

    def get_run_samples(self, run_id: str) -> list[dict[str, Any]]:
        if run_id != "run-1":
            return []
        return list(self.samples)

    def list_runs(self) -> list[dict[str, Any]]:
        return []

    def get_active_run_id(self) -> str | None:
        return None

    def delete_run(self, run_id: str) -> bool:
        return False


@dataclass
class _FakeWsHub:
    selected_updates: list[str | None] = field(default_factory=list)

    async def add(self, websocket, selected_client_id: str | None) -> None:
        self.selected_updates.append(selected_client_id)

    async def remove(self, websocket) -> None:
        return None

    async def update_selected_client(self, websocket, client_id: str | None) -> None:
        self.selected_updates.append(client_id)


class _FakeWs:
    def __init__(self, messages: list[str], selected_query: str | None = None) -> None:
        self.query_params = {}
        if selected_query is not None:
            self.query_params["client_id"] = selected_query
        self._messages = list(messages)

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
        if not self._messages:
            raise WebSocketDisconnect()
        return self._messages.pop(0)


class _FakeState:
    def __init__(self, history_db: _FakeHistoryDB, ws_hub: _FakeWsHub) -> None:
        self.history_db = history_db
        self.ws_hub = ws_hub
        self.settings_store = type("S", (), {"language": "en", "set_language": lambda self, v: v})()
        self.live_diagnostics = type("D", (), {"reset": lambda self: None})()
        self.metrics_logger = type(
            "M",
            (),
            {
                "status": lambda self: {},
                "start_logging": lambda self: {},
                "stop_logging": lambda self: {},
            },
        )()
        self.registry = type(
            "R",
            (),
            {
                "snapshot_for_api": lambda self: [],
                "get": lambda self, _cid: None,
                "set_name": lambda self, cid, name: type(
                    "U", (), {"client_id": cid, "name": name}
                )(),
                "remove_client": lambda self, _cid: True,
            },
        )()
        self.control_plane = type(
            "C", (), {"send_identify": lambda self, _id, _dur: (False, None)}
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
        self.analysis_settings = type(
            "A",
            (),
            {"snapshot": lambda self: {}, "update": lambda self, payload: payload},
        )()
        self.processor = type(
            "P",
            (),
            {
                "debug_spectrum": lambda self, _id: {},
                "raw_samples": lambda self, _id, n_samples=1: {},
            },
        )()


def _make_router_and_state(language: str = "en", sample_count: int = 20):
    metadata = {
        "run_id": "run-1",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:00:20Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "language": language,
    }
    samples = [_sample(i) for i in range(sample_count)]
    analysis = summarize_run_data(metadata, samples, lang=language, include_samples=False)
    state = _FakeState(_FakeHistoryDB(metadata, samples, analysis), _FakeWsHub())
    app = FastAPI()
    router = create_router(state)
    app.include_router(router)
    return router, state


def _route_endpoint(router, path: str):
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise AssertionError(f"Route not found: {path}")


@pytest.mark.asyncio
async def test_history_insights_respects_lang_query() -> None:
    router, _ = _make_router_and_state(language="en")
    endpoint = _route_endpoint(router, "/api/history/{run_id}/insights")
    en = await endpoint("run-1", "en")
    nl = await endpoint("run-1", "nl")
    assert en["lang"] == "en"
    assert nl["lang"] == "nl"
    assert en["most_likely_origin"] != nl["most_likely_origin"]


@pytest.mark.asyncio
async def test_report_pdf_respects_lang_query() -> None:
    router, _ = _make_router_and_state(language="en")
    endpoint = _route_endpoint(router, "/api/history/{run_id}/report.pdf")
    en = await endpoint("run-1", "en")
    nl = await endpoint("run-1", "nl")
    assert en.body.startswith(b"%PDF")
    assert nl.body.startswith(b"%PDF")
    assert en.body != nl.body


@pytest.mark.asyncio
async def test_history_export_streams_zip_with_json_and_csv() -> None:
    router, _ = _make_router_and_state(language="en", sample_count=1000)
    endpoint = _route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    with zipfile.ZipFile(io.BytesIO(response.body), "r") as archive:
        names = set(archive.namelist())
        assert names == {"run-1.json", "run-1_raw.csv"}
        metadata = json.loads(archive.read("run-1.json").decode("utf-8"))
        assert metadata["run_id"] == "run-1"
        assert metadata["sample_count"] == 1000
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
        assert len(rows) == 1000


@pytest.mark.asyncio
async def test_ws_selected_client_id_validation() -> None:
    router, state = _make_router_and_state(language="en")
    endpoint = _route_endpoint(router, "/ws")
    ws = _FakeWs(
        messages=[
            json.dumps({"client_id": "not-a-mac"}),
            json.dumps({"client_id": "aa:bb:cc:dd:ee:ff"}),
        ],
        selected_query="ZZZZZZZZZZZZ",
    )
    await endpoint(ws)
    assert None in state.ws_hub.selected_updates
    assert "aabbccddeeff" in state.ws_hub.selected_updates


@pytest.mark.asyncio
async def test_history_insights_lang_sampling_is_bounded() -> None:
    router, _ = _make_router_and_state(language="en", sample_count=30_000)
    endpoint = _route_endpoint(router, "/api/history/{run_id}/insights")
    payload = await endpoint("run-1", "en")
    sampling = payload.get("sampling", {})
    assert sampling.get("analyzed_samples", 0) <= 12_000
    assert sampling.get("total_samples") == 30_000


@pytest.mark.asyncio
async def test_delete_active_run_returns_409() -> None:
    """DELETE /api/history/{run_id} returns 409 when run is active."""

    @dataclass
    class _ActiveDB(_FakeHistoryDB):
        def get_active_run_id(self) -> str | None:
            return "run-1"

    metadata = {
        "run_id": "run-1",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:00:20Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "language": "en",
    }
    samples = [_sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    db = _ActiveDB(metadata, samples, analysis)
    state = _FakeState(db, _FakeWsHub())
    app = FastAPI()
    router = create_router(state)
    app.include_router(router)

    # Find the DELETE endpoint specifically
    delete_endpoint = None
    for route in router.routes:
        if getattr(route, "path", "") == "/api/history/{run_id}":
            if "DELETE" in getattr(route, "methods", set()):
                delete_endpoint = route.endpoint
                break
    assert delete_endpoint is not None

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await delete_endpoint("run-1")
    assert exc_info.value.status_code == 409
