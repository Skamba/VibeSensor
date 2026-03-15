from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

from fastapi import FastAPI, WebSocketDisconnect
from test_support import response_payload as _response_payload

from vibesensor.adapters.http.routes import create_router
from vibesensor.infra.runtime import RuntimeHealthState
from vibesensor.use_cases.diagnostics import summarize_run_data
from vibesensor.use_cases.history.exports import HistoryExportService
from vibesensor.use_cases.history.reports import HistoryReportService
from vibesensor.use_cases.history.runs import HistoryRunService


def make_metadata(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": "run-1",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:00:20Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "language": "en",
    }
    base.update(overrides)
    return base


def sample(i: int) -> dict[str, Any]:
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
            },
        ],
        "vibration_strength_db": 12.0,
        "strength_bucket": "l2",
    }


@dataclass
class FakeHistoryDB:
    metadata: dict[str, Any]
    samples: list[dict[str, Any]]
    analysis: dict[str, Any]
    analysis_completed_at: str | None = "2026-01-01T00:01:00Z"

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if run_id != "run-1":
            return None
        result = {
            "run_id": run_id,
            "status": "complete",
            "metadata": self.metadata,
            "analysis": self.analysis,
        }
        if self.analysis_completed_at is not None:
            result["analysis_completed_at"] = self.analysis_completed_at
        result["sample_count"] = len(self.samples)
        return result

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

    def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
        if run_id != "run-1":
            return False, "not_found"
        return True, None


@dataclass
class FakeWsHub:
    selected_updates: list[str | None] = field(default_factory=list)

    async def add(self, websocket, selected_client_id: str | None) -> None:
        self.selected_updates.append(selected_client_id)

    async def remove(self, websocket) -> None:
        return None

    async def update_selected_client(self, websocket, client_id: str | None) -> None:
        self.selected_updates.append(client_id)


class FakeWs:
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


class FakeState:
    def __init__(self, history_db: FakeHistoryDB, ws_hub: FakeWsHub) -> None:
        self.history_db = history_db
        self.ws_hub = ws_hub
        self.settings_store = type(
            "S",
            (),
            {
                "language": "en",
                "set_language": lambda self, v: v,
                "active_car_snapshot": lambda self: None,
            },
        )()
        self.run_recorder = type(
            "M",
            (),
            {
                "status": lambda self: {},
                "health_snapshot": lambda self: {
                    "write_error": None,
                    "analysis_in_progress": False,
                    "analysis_queue_depth": 0,
                    "analysis_queue_max_depth": 0,
                    "analysis_active_run_id": None,
                    "analysis_started_at": None,
                    "analysis_elapsed_s": None,
                    "analysis_queue_oldest_age_s": None,
                    "analyzing_run_count": 0,
                    "analyzing_oldest_age_s": None,
                    "samples_written": 0,
                    "samples_dropped": 0,
                    "last_completed_run_id": None,
                    "last_completed_run_error": None,
                },
                "persistence": type(
                    "P",
                    (),
                    {
                        "last_write_duration_s": 0.0,
                        "max_write_duration_s": 0.0,
                    },
                )(),
                "last_write_duration_s": 0.0,
                "max_write_duration_s": 0.0,
                "start_recording": lambda self: {},
                "stop_recording": lambda self: {},
            },
        )()
        self.registry = type(
            "R",
            (),
            {
                "snapshot_for_api": lambda self: [],
                "data_loss_snapshot": lambda self: {
                    "tracked_clients": 0,
                    "affected_clients": 0,
                    "frames_dropped": 0,
                    "queue_overflow_drops": 0,
                    "server_queue_drops": 0,
                    "parse_errors": 0,
                },
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
                "intake_stats": lambda self: {
                    "total_ingested_samples": 0,
                    "total_compute_calls": 0,
                    "last_compute_duration_s": 0.0,
                    "last_compute_all_duration_s": 0.0,
                    "last_ingest_duration_s": 0.0,
                },
            },
        )()
        from vibesensor.infra.runtime import ProcessingLoopState

        self.processing_loop_state = ProcessingLoopState()
        self.health_state = RuntimeHealthState()
        self.health_state.mark_ready()
        self.update_manager = MagicMock()
        self.esp_flash_manager = MagicMock()
        self.run_service = HistoryRunService(self.history_db, self.settings_store)
        self.report_service = HistoryReportService(self.history_db, self.settings_store)
        self.export_service = HistoryExportService(self.history_db)


def make_router_and_state(
    language: str = "en",
    sample_count: int = 20,
    *,
    metadata: dict[str, Any] | None = None,
    samples: list[dict[str, Any]] | None = None,
    analysis: dict[str, Any] | None = None,
):
    metadata = metadata or make_metadata(language=language)
    samples = samples or [sample(i) for i in range(sample_count)]
    analysis = analysis or summarize_run_data(
        metadata,
        samples,
        lang=language,
        include_samples=False,
    )
    state = FakeState(FakeHistoryDB(metadata, samples, analysis), FakeWsHub())
    app = FastAPI()
    router = create_router(state)
    app.include_router(router)
    return router, state


def route_endpoint(router, path: str):
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise AssertionError(f"Route not found: {path}")


def route_endpoint_with_method(router, path: str, method: str):
    for route in router.routes:
        if getattr(route, "path", "") != path:
            continue
        if method.upper() in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Route not found: {method.upper()} {path}")


def response_payload(response):
    return _response_payload(response)


def make_status_router(
    *,
    status: str,
    analysis: dict[str, Any] | None,
    include_error_message: bool,
):
    @dataclass
    class StatusDB(FakeHistoryDB):
        run_status: str = "complete"
        run_analysis: dict[str, Any] | None = None

        def get_run(self, run_id: str) -> dict[str, Any] | None:
            if run_id != "run-1":
                return None
            payload = {
                "run_id": run_id,
                "status": self.run_status,
                "analysis": self.run_analysis,
            }
            if include_error_message and self.run_status == "error":
                payload["error_message"] = "Analysis failed"
            return payload

    metadata = {"language": "en"}
    samples = [sample(0)]
    db = StatusDB(metadata, samples, {}, run_status=status, run_analysis=analysis)
    return create_router(FakeState(db, FakeWsHub()))


async def read_streaming_body(response) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, str):
            chunks.append(chunk.encode("utf-8"))
        else:
            chunks.append(chunk)
    return b"".join(chunks)


def read_export_archive(body: bytes) -> tuple[set[str], dict[str, Any], list[dict[str, str]]]:
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        names = set(archive.namelist())
        metadata = json.loads(archive.read("run-1.json").decode("utf-8"))
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
    return names, metadata, rows
