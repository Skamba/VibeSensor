from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

from fastapi import FastAPI
from test_support.analysis import summarize_mappings
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.analysis.summarize import summarize_sensor_frames
from vibesensor.clock.browser_clock import BrowserClockCorrector
from vibesensor.domain.run_status import RunStatus
from vibesensor.history.exports import HistoryExportService
from vibesensor.history.records import (
    HistoryArtifactAvailability,
    HistoryRunListEntry,
    StoredHistoryRun,
)
from vibesensor.history.run_lifecycle import derive_run_artifact_lifecycle
from vibesensor.history.runs import HistoryRunService
from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.recording.run_metadata import (
    run_metadata_from_mapping,
)
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.recording.sensor_frame_mapping import (
    sensor_frame_from_mapping,
)
from vibesensor.report.pdf import render_report_pdf
from vibesensor.report.service import HistoryReportService, PdfRendererFn
from vibesensor.report.view_model import ReportView
from vibesensor.summary.contracts import AnalysisSummary
from vibesensor.summary.persisted_analysis import PersistedAnalysis
from vibesensor.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.updates.manager import UpdateManager
from vibesensor.web.health_state import RuntimeHealthState
from vibesensor.web.history_services import (
    ProjectedHistoryExportService,
    ProjectedHistoryRunService,
)
from vibesensor.web.router import create_router


def _real_pdf_renderer(view: ReportView) -> bytes:
    """Default test renderer: the real ReportLab renderer."""
    return render_report_pdf(view)


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
    baseline = summarize_sensor_frames(
        metadata,
        [
            row if isinstance(row, SensorFrame) else sensor_frame_from_mapping(row)
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

    @staticmethod
    def _artifact_availability_from_lifecycle(
        raw_capture: str,
    ) -> HistoryArtifactAvailability:
        return HistoryArtifactAvailability(
            raw_capture="available" if raw_capture == "ready" else raw_capture,
        )

    def get_run(self, run_id: str) -> StoredHistoryRun | None:
        if run_id != "run-1":
            return None
        metadata = _coerce_metadata(self.metadata)
        lifecycle = derive_run_artifact_lifecycle(
            status=RunStatus.COMPLETE,
            has_raw_capture_manifest=False,
            raw_capture_artifacts_present=False,
            raw_capture_finalize=metadata.raw_capture_finalize,
            has_analysis=True,
            analysis_corrupt=False,
        )
        artifact_availability = self._artifact_availability_from_lifecycle(
            lifecycle.raw_capture,
        )
        return StoredHistoryRun(
            run_id=run_id,
            status=RunStatus.COMPLETE,
            start_time_utc=metadata.start_time_utc,
            end_time_utc=metadata.end_time_utc,
            metadata=metadata,
            lifecycle=lifecycle,
            raw_capture_finalize=metadata.raw_capture_finalize,
            artifact_availability=artifact_availability,
            analysis=_coerce_analysis(metadata, self.samples, self.analysis),
            created_at=metadata.start_time_utc,
            sample_count=len(self.samples),
            analysis_completed_at=self.analysis_completed_at,
        )

    def iter_run_samples(self, run_id: str, batch_size: int = 1000, *, stride: int = 1):
        if run_id != "run-1":
            return
        rows = [
            row if isinstance(row, SensorFrame) else sensor_frame_from_mapping(row)
            for row in self.samples
        ]
        for start in range(0, len(rows), batch_size):
            yield rows[start : start + batch_size]

    def get_run_samples(self, run_id: str) -> list[SensorFrame]:
        if run_id != "run-1":
            return []
        return [
            row if isinstance(row, SensorFrame) else sensor_frame_from_mapping(row)
            for row in self.samples
        ]

    def list_runs(self, limit: int = 500) -> list[HistoryRunListEntry]:
        metadata = _coerce_metadata(self.metadata)
        lifecycle = derive_run_artifact_lifecycle(
            status=RunStatus.COMPLETE,
            has_raw_capture_manifest=False,
            raw_capture_artifacts_present=False,
            raw_capture_finalize=metadata.raw_capture_finalize,
            has_analysis=True,
            analysis_corrupt=False,
        )
        artifact_availability = self._artifact_availability_from_lifecycle(
            lifecycle.raw_capture,
        )
        return [
            HistoryRunListEntry(
                run_id=metadata.run_id or "run-1",
                status=RunStatus.COMPLETE,
                start_time_utc=metadata.start_time_utc,
                end_time_utc=metadata.end_time_utc,
                created_at=metadata.start_time_utc,
                sample_count=len(self.samples),
                car_name=metadata.car_name,
                lifecycle=lifecycle,
                artifact_availability=artifact_availability,
                raw_capture_finalize=metadata.raw_capture_finalize,
            )
        ]

    def get_active_run_id(self) -> str | None:
        return None

    def delete_run(self, run_id: str) -> bool:
        return False

    def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
        if run_id != "run-1":
            return False, "not_found"
        return True, None


@dataclass
class FakeLiveWs:
    selected_updates: list[str | None] = field(default_factory=list)

    def add(self, websocket, selected_client_id: str | None, *, on_drop) -> None:
        self.selected_updates.append(selected_client_id)

    def remove(self, websocket) -> None:
        return None

    def select(self, websocket, client_id: str | None) -> None:
        self.selected_updates.append(client_id)


class FakeState:
    def __init__(
        self,
        history_db: FakeHistoryDB,
        ws_broadcaster: FakeLiveWs,
        *,
        pdf_renderer: PdfRendererFn = _real_pdf_renderer,
    ) -> None:
        self.history_db = history_db
        self.ws_broadcaster = ws_broadcaster
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
        from vibesensor.live.processing_loop import ProcessingLoopState

        self.processing_loop_state = ProcessingLoopState()
        self.health_state = RuntimeHealthState()
        self.ingest_diagnostics = IngestDiagnosticsCollector()
        self.health_state.mark_ready()
        self.update_manager = create_autospec(UpdateManager, instance=True)
        self.esp_flash_manager = create_autospec(EspFlashManager, instance=True)
        self.browser_clock = create_autospec(BrowserClockCorrector, instance=True)
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

    # Route-service names (see ``vibesensor.web.router.WebServices``).
    @property
    def sensor_metadata_store(self) -> MagicMock:
        return self.settings_store

    @property
    def car_settings(self) -> MagicMock:
        return self.settings_store

    @property
    def analysis_settings(self) -> MagicMock:
        return self.settings_store

    @property
    def ui_preferences(self) -> MagicMock:
        return self.settings_store

    @property
    def speed_source_service(self) -> MagicMock:
        return self.settings_store

    @property
    def speed_status_service(self) -> object:
        return self.gps_monitor

    @property
    def obd_admin_service(self) -> object:
        return self.gps_monitor


def make_app_from_state(state: FakeState) -> FastAPI:
    app = FastAPI()
    app.include_router(create_router(state))
    return app


def _build_app_router_and_state(
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
    analysis = analysis or summarize_mappings(
        metadata,
        samples,
        lang=language,
        include_samples=False,
    )
    state = FakeState(
        FakeHistoryDB(metadata, samples, analysis), FakeLiveWs(), pdf_renderer=pdf_renderer
    )
    app = FastAPI()
    router = create_router(state)
    app.include_router(router)
    return app, router, state


def make_app_and_state(
    language: str = "en",
    sample_count: int = 20,
    *,
    metadata: dict[str, Any] | None = None,
    samples: list[dict[str, Any]] | None = None,
    analysis: dict[str, Any] | None = None,
    pdf_renderer: PdfRendererFn = _real_pdf_renderer,
):
    app, _router, state = _build_app_router_and_state(
        language=language,
        sample_count=sample_count,
        metadata=metadata,
        samples=samples,
        analysis=analysis,
        pdf_renderer=pdf_renderer,
    )
    return app, state


def make_status_app(
    *,
    status: str,
    analysis: dict[str, Any] | None,
    include_error_message: bool,
):
    @dataclass
    class StatusDB(FakeHistoryDB):
        run_status: str = "complete"
        run_analysis: dict[str, Any] | None = None

        def get_run(self, run_id: str) -> StoredHistoryRun | None:
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
    app = FastAPI()
    app.include_router(create_router(FakeState(db, FakeLiveWs())))
    return app


def read_export_archive(body: bytes) -> tuple[set[str], dict[str, Any], list[dict[str, str]]]:
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        names = set(archive.namelist())
        metadata = json.loads(archive.read("run-1.json").decode("utf-8"))
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
    return names, metadata, rows
