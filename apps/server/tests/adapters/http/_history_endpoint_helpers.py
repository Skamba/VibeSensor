from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any, cast
from unittest.mock import MagicMock

from fastapi import FastAPI, WebSocketDisconnect
from test_support import response_payload as _response_payload
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.analysis_summary import summarize_run_data
from vibesensor.adapters.history import ProjectedHistoryExportService, ProjectedHistoryRunService
from vibesensor.adapters.http import create_router
from vibesensor.adapters.http.dependencies import (
    HealthDeps,
    HistoryDeps,
    LiveDeps,
    RouterDeps,
    SettingsDeps,
    UpdateDeps,
)
from vibesensor.adapters.pdf.pdf_engine import build_prepared_report_pdf
from vibesensor.domain import RunStatus
from vibesensor.infra.runtime import RuntimeHealthState
from vibesensor.shared.boundaries.runs.metadata import (
    run_metadata_from_mapping,
    run_metadata_to_json_object,
)
from vibesensor.shared.boundaries.sensor_frames import (
    sensor_frame_from_mapping,
    sensor_frame_to_json_object,
)
from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.history_records import HistoryRunListEntry, StoredHistoryRun
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.use_cases.history.exports import HistoryExportService
from vibesensor.use_cases.history.reports import HistoryReportService, PdfRendererFn
from vibesensor.use_cases.history.runs import HistoryRunService


def _real_pdf_renderer(prepared: object) -> bytes:
    """Default test renderer wiring the real adapter pipeline."""
    from vibesensor.shared.boundaries.reporting import PreparedReportInput

    assert isinstance(prepared, PreparedReportInput)
    return build_prepared_report_pdf(prepared)


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


def _coerce_metadata(metadata: dict[str, Any] | RunMetadata) -> RunMetadata:
    return metadata if isinstance(metadata, RunMetadata) else run_metadata_from_mapping(metadata)


def _coerce_analysis(
    metadata: RunMetadata,
    samples: list[dict[str, Any] | SensorFrame],
    analysis: dict[str, Any] | AnalysisSummary | PersistedAnalysis,
) -> PersistedAnalysis:
    if isinstance(analysis, PersistedAnalysis):
        return analysis
    if {"findings", "top_causes", "warnings"}.issubset(analysis):
        return make_persisted_analysis(cast(AnalysisSummary, analysis))
    baseline = summarize_run_data(
        run_metadata_to_json_object(metadata),
        [
            sensor_frame_to_json_object(row) if isinstance(row, SensorFrame) else row
            for row in samples
        ],
        lang=metadata.language or "en",
        include_samples=False,
    )
    baseline.update(analysis)
    return make_persisted_analysis(cast(AnalysisSummary, baseline))


@dataclass
class FakeHistoryDB:
    metadata: dict[str, Any] | RunMetadata
    samples: list[dict[str, Any] | SensorFrame]
    analysis: dict[str, Any] | AnalysisSummary | PersistedAnalysis
    analysis_completed_at: str | None = "2026-01-01T00:01:00Z"

    async def aget_run(self, run_id: str) -> StoredHistoryRun | None:
        if run_id != "run-1":
            return None
        metadata = _coerce_metadata(self.metadata)
        return StoredHistoryRun(
            run_id=run_id,
            status=RunStatus.COMPLETE,
            start_time_utc=metadata.start_time_utc,
            end_time_utc=metadata.end_time_utc,
            metadata=metadata,
            analysis=_coerce_analysis(metadata, self.samples, self.analysis),
            created_at=metadata.start_time_utc,
            sample_count=len(self.samples),
            analysis_completed_at=self.analysis_completed_at,
        )

    async def aiter_run_samples(self, run_id: str, batch_size: int = 1000, *, stride: int = 1):
        if run_id != "run-1":
            return
        rows = [
            row if isinstance(row, SensorFrame) else sensor_frame_from_mapping(row)
            for row in self.samples
        ]
        for start in range(0, len(rows), batch_size):
            yield rows[start : start + batch_size]

    async def aget_run_samples(self, run_id: str) -> list[SensorFrame]:
        if run_id != "run-1":
            return []
        return [
            row if isinstance(row, SensorFrame) else sensor_frame_from_mapping(row)
            for row in self.samples
        ]

    async def alist_runs(self, limit: int = 500) -> list[HistoryRunListEntry]:
        metadata = _coerce_metadata(self.metadata)
        return [
            HistoryRunListEntry(
                run_id=metadata.run_id or "run-1",
                status=RunStatus.COMPLETE,
                start_time_utc=metadata.start_time_utc,
                end_time_utc=metadata.end_time_utc,
                created_at=metadata.start_time_utc,
                sample_count=len(self.samples),
                car_name=metadata.car_name,
            )
        ]

    async def aget_active_run_id(self) -> str | None:
        return None

    async def adelete_run(self, run_id: str) -> bool:
        return False

    async def adelete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
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
    def __init__(
        self,
        history_db: FakeHistoryDB,
        ws_hub: FakeWsHub,
        *,
        pdf_renderer: PdfRendererFn = _real_pdf_renderer,
    ) -> None:
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
                "client_snapshots": (
                    lambda self, now=None, now_mono=None, metrics_by_client=None: []
                ),
                "active_client_ids": lambda self, now=None, stale_after_s=None: [],
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
        self.processor = type(
            "P",
            (),
            {
                "intake_stats": lambda self: {
                    "total_ingested_samples": 0,
                    "total_compute_calls": 0,
                    "last_compute_duration_s": 0.0,
                    "last_compute_all_duration_s": 0.0,
                    "last_ingest_duration_s": 0.0,
                },
                "buffer_overflow_drops": lambda self: 0,
            },
        )()
        from vibesensor.infra.runtime import ProcessingLoopState

        self.processing_loop_state = ProcessingLoopState()
        self.health_state = RuntimeHealthState()
        self.ingest_diagnostics = IngestDiagnosticsCollector()
        self.health_state.mark_ready()
        self.update_manager = MagicMock()
        self.esp_flash_manager = MagicMock()
        self.run_service = ProjectedHistoryRunService(
            HistoryRunService(
                self.history_db,
            ),
            current_car_reader=self.settings_store,
        )
        self.report_service = HistoryReportService(
            self.history_db,
            pdf_renderer=pdf_renderer,
        )
        self.export_service = ProjectedHistoryExportService(
            HistoryExportService(
                self.history_db,
            )
        )

    @property
    def health(self) -> HealthDeps:
        return HealthDeps(
            processing_loop_state=self.processing_loop_state,
            health_state=self.health_state,
            processor=self.processor,
            registry=self.registry,
            run_recorder=self.run_recorder,
            ingest_diagnostics=self.ingest_diagnostics,
        )

    @property
    def live(self) -> LiveDeps:
        return LiveDeps(
            registry=self.registry,
            control_plane=self.control_plane,
            sensor_metadata_store=self.settings_store,
            processor=self.processor,
            run_recorder=self.run_recorder,
            ws_hub=self.ws_hub,
        )

    @property
    def settings(self) -> SettingsDeps:
        return SettingsDeps(
            car_settings=self.settings_store,
            analysis_settings=self.settings_store,
            ui_preferences=self.settings_store,
            speed_source_service=self.settings_store,
            speed_status_service=self.gps_monitor,
            obd_admin_service=self.gps_monitor,
        )

    @property
    def history(self) -> HistoryDeps:
        return HistoryDeps(
            run_service=self.run_service,
            report_service=self.report_service,
            export_service=self.export_service,
        )

    @property
    def updates(self) -> UpdateDeps:
        return UpdateDeps(
            update_manager=self.update_manager,
            esp_flash_manager=self.esp_flash_manager,
        )

    @property
    def router(self) -> RouterDeps:
        return RouterDeps(
            health=self.health,
            settings=self.settings,
            live=self.live,
            history=self.history,
            updates=self.updates,
        )


def make_router_and_state(
    language: str = "en",
    sample_count: int = 20,
    *,
    metadata: dict[str, Any] | None = None,
    samples: list[dict[str, Any]] | None = None,
    analysis: dict[str, Any] | None = None,
    pdf_renderer: PdfRendererFn = _real_pdf_renderer,
):
    metadata = metadata or make_metadata(language=language)
    samples = samples or [sample(i) for i in range(sample_count)]
    analysis = analysis or summarize_run_data(
        metadata,
        samples,
        lang=language,
        include_samples=False,
    )
    state = FakeState(
        FakeHistoryDB(metadata, samples, analysis), FakeWsHub(), pdf_renderer=pdf_renderer
    )
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

        async def aget_run(self, run_id: str) -> StoredHistoryRun | None:
            if run_id != "run-1":
                return None
            metadata = _coerce_metadata(self.metadata)
            invalid_analysis = self.run_analysis is not None and not {
                "findings",
                "top_causes",
                "warnings",
            }.issubset(self.run_analysis)
            return StoredHistoryRun(
                run_id=run_id,
                status=RunStatus(self.run_status),
                start_time_utc=metadata.start_time_utc,
                end_time_utc=metadata.end_time_utc,
                metadata=metadata,
                analysis=(
                    None
                    if self.run_analysis is None or invalid_analysis
                    else make_persisted_analysis(cast(dict[str, object], self.run_analysis))
                ),
                analysis_corrupt=invalid_analysis,
                error_message=(
                    "Analysis failed"
                    if include_error_message and self.run_status == "error"
                    else None
                ),
                created_at=metadata.start_time_utc,
                sample_count=len(self.samples),
                analysis_completed_at=self.analysis_completed_at,
            )

    metadata = make_metadata(language="en")
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
