"""Shared test fixtures and helpers for the vibesensor test suite.

Plain helper functions / assertion utilities live in
``_test_helpers.py`` so they can be imported unambiguously even when
sub-directory ``conftest.py`` files exist (which shadow this module in
``sys.modules``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from vibesensor.adapters.http.dependencies import (
    HistoryDeps,
    RouterDeps,
    SettingsDeps,
    TelemetryDeps,
    UpdateDeps,
)
from vibesensor.infra.runtime import ProcessingLoopState, RuntimeHealthState
from vibesensor.shared.boundaries.diagnostic_case import project_analysis_summary
from vibesensor.use_cases.history.exports import HistoryExportService
from vibesensor.use_cases.history.reports import HistoryReportService
from vibesensor.use_cases.history.runs import HistoryRunService

# ---------------------------------------------------------------------------
# Shared API test helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeState:
    """Minimal stand-in for router assembly tests.

    Keeps the convenient flat fields used throughout tests while exposing the
    grouped dependency attributes consumed by ``create_router``.
    """

    config: object = field(default_factory=MagicMock)
    registry: object = field(default_factory=MagicMock)
    processor: object = field(default_factory=MagicMock)
    control_plane: object = field(default_factory=MagicMock)
    worker_pool: object = field(default_factory=MagicMock)
    ws_hub: object = field(default_factory=MagicMock)
    gps_monitor: object = field(default_factory=MagicMock)
    run_recorder: object = field(default_factory=MagicMock)
    settings_store: object = field(default_factory=MagicMock)
    history_db: object = field(default_factory=MagicMock)
    update_manager: object = field(default_factory=MagicMock)
    esp_flash_manager: object = field(default_factory=MagicMock)
    processing_loop_state: ProcessingLoopState = field(default_factory=ProcessingLoopState)
    health_state: RuntimeHealthState = field(default_factory=RuntimeHealthState)
    processing_loop: object = field(default_factory=MagicMock)
    ws_broadcast: object = field(default_factory=MagicMock)
    run_service: object | None = None
    report_service: object | None = None
    export_service: object | None = None

    def __post_init__(self) -> None:
        self.health_state.mark_ready()
        if self.run_service is None:
            self.run_service = HistoryRunService(
                self.history_db,
                self.settings_store,
                analysis_projector=project_analysis_summary,
            )
        if self.report_service is None:
            self.report_service = HistoryReportService(
                self.history_db,
                self.settings_store,
                analysis_projector=project_analysis_summary,
                pdf_renderer=lambda _summary, _test_run: b"%PDF-stub",
            )
        if self.export_service is None:
            self.export_service = HistoryExportService(
                self.history_db,
                analysis_projector=project_analysis_summary,
            )

    @property
    def telemetry(self) -> TelemetryDeps:
        return TelemetryDeps(
            processing_loop_state=self.processing_loop_state,
            health_state=self.health_state,
            processor=self.processor,
            registry=self.registry,
            control_plane=self.control_plane,
            run_recorder=self.run_recorder,
            ws_hub=self.ws_hub,
        )

    @property
    def settings(self) -> SettingsDeps:
        return SettingsDeps(
            settings_store=self.settings_store,
            gps_monitor=self.gps_monitor,
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
            telemetry=self.telemetry,
            settings=self.settings,
            history=self.history,
            updates=self.updates,
        )


@pytest.fixture
def fake_state() -> FakeState:
    """Return a fresh ``FakeState`` for each test."""
    state = FakeState()
    state.processor.intake_stats.return_value = {
        "total_ingested_samples": 0,
        "total_compute_calls": 0,
        "last_compute_duration_s": 0.0,
        "last_compute_all_duration_s": 0.0,
        "last_ingest_duration_s": 0.0,
    }
    state.registry.data_loss_snapshot.return_value = {
        "tracked_clients": 0,
        "affected_clients": 0,
        "frames_dropped": 0,
        "queue_overflow_drops": 0,
        "server_queue_drops": 0,
        "parse_errors": 0,
    }
    state.run_recorder.health_snapshot.return_value = {
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
    }
    return state


@pytest.fixture
def route_paths(fake_state: FakeState) -> set[str]:
    """All registered URL paths from the assembled router."""
    from vibesensor.adapters.http import create_router

    router = create_router(fake_state)
    return {r.path for r in router.routes}
