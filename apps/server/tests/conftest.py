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

from vibesensor.history_services.exports import HistoryExportService
from vibesensor.history_services.reports import HistoryReportService
from vibesensor.history_services.runs import HistoryRunDeleteService, HistoryRunQueryService
from vibesensor.runtime import ProcessingLoopState, RuntimeHealthState
from vibesensor.runtime.subsystems import (
    RuntimeIngressSubsystem,
    RuntimePersistenceSubsystem,
    RuntimeProcessingSubsystem,
    RuntimeRecordingSubsystem,
    RuntimeSettingsSubsystem,
    RuntimeUpdateSubsystem,
    RuntimeWebsocketSubsystem,
)
from vibesensor.runtime.ws_broadcast import WsBroadcastCache

# ---------------------------------------------------------------------------
# Shared API test helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeState:
    """Minimal stand-in for RuntimeState used by ``create_router``.

    Uses the actual production subsystem dataclass types so that shape
    drift between test fixtures and production code is caught at
    construction time rather than via obscure test failures.
    """

    config: object = field(default_factory=MagicMock)
    registry: object = field(default_factory=MagicMock)
    processor: object = field(default_factory=MagicMock)
    control_plane: object = field(default_factory=MagicMock)
    ws_hub: object = field(default_factory=MagicMock)
    gps_monitor: object = field(default_factory=MagicMock)
    analysis_settings: object = field(default_factory=MagicMock)
    metrics_logger: object = field(default_factory=MagicMock)
    settings_store: object = field(default_factory=MagicMock)
    history_db: object = field(default_factory=MagicMock)
    update_manager: object = field(default_factory=MagicMock)
    esp_flash_manager: object = field(default_factory=MagicMock)
    loop_state: ProcessingLoopState = field(default_factory=ProcessingLoopState)
    health_state: RuntimeHealthState = field(default_factory=RuntimeHealthState)
    apply_car_settings: object = field(default_factory=MagicMock)
    apply_speed_source_settings: object = field(default_factory=MagicMock)

    def __post_init__(self) -> None:
        self.health_state.mark_ready()
        self.ingress = RuntimeIngressSubsystem(
            registry=self.registry,  # type: ignore[arg-type]
            processor=self.processor,  # type: ignore[arg-type]
            control_plane=self.control_plane,  # type: ignore[arg-type]
            worker_pool=MagicMock(),
        )
        self.settings = RuntimeSettingsSubsystem(
            settings_store=self.settings_store,  # type: ignore[arg-type]
            gps_monitor=self.gps_monitor,  # type: ignore[arg-type]
            analysis_settings=self.analysis_settings,  # type: ignore[arg-type]
        )
        self.recording = RuntimeRecordingSubsystem(
            metrics_logger=self.metrics_logger,  # type: ignore[arg-type]
        )
        self.persistence = RuntimePersistenceSubsystem(
            history_db=self.history_db,  # type: ignore[arg-type]
            query_service=HistoryRunQueryService(self.history_db, self.settings_store),
            delete_service=HistoryRunDeleteService(self.history_db, self.settings_store),
            report_service=HistoryReportService(self.history_db, self.settings_store),
            export_service=HistoryExportService(self.history_db),
        )
        self.websocket = RuntimeWebsocketSubsystem(
            hub=self.ws_hub,  # type: ignore[arg-type]
            cache=WsBroadcastCache(),
            broadcast=MagicMock(),
        )
        self.updates = RuntimeUpdateSubsystem(
            update_manager=self.update_manager,  # type: ignore[arg-type]
            esp_flash_manager=self.esp_flash_manager,  # type: ignore[arg-type]
        )
        self.processing = RuntimeProcessingSubsystem(
            state=self.loop_state,
            health_state=self.health_state,
            loop=MagicMock(),
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
    state.metrics_logger.health_snapshot.return_value = {
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
    from vibesensor.routes import create_router

    router = create_router(fake_state)  # type: ignore[arg-type]
    return {r.path for r in router.routes}
