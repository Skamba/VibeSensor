"""Shared test fixtures and helpers for the vibesensor test suite.

Plain helper functions / assertion utilities live in dedicated
``_*_test_helpers.py`` modules so they can be imported unambiguously even
when sub-directory ``conftest.py`` files exist (which shadow this module in
``sys.modules``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
from vibesensor.adapters.history import (
    ProjectedHistoryExportService,
    ProjectedHistoryRunService,
)
from vibesensor.adapters.http.dependencies import (
    HealthDeps,
    HistoryDeps,
    LiveDeps,
    RouterDeps,
    SettingsDeps,
    UpdateDeps,
)
from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane
from vibesensor.adapters.websocket.hub import WebSocketHub
from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.runtime import ProcessingLoopState, RuntimeHealthState
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector
from vibesensor.shared.types.car_config import CarsSnapshot
from vibesensor.use_cases.history.exports import HistoryExportService
from vibesensor.use_cases.history.reports import HistoryReportService
from vibesensor.use_cases.history.runs import HistoryRunService
from vibesensor.use_cases.run import RunRecorder
from vibesensor.use_cases.run.status_reporting import RunRecorderStatusSnapshot
from vibesensor.use_cases.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.use_cases.updates.firmware.esp_flash_types import EspFlashStatus
from vibesensor.use_cases.updates.manager import UpdateManager
from vibesensor.use_cases.updates.models import UpdateJobStatus, UsbInternetStatus

# ---------------------------------------------------------------------------
# Shared API test helpers
# ---------------------------------------------------------------------------


def _update_manager_mock() -> UpdateManager:
    manager = create_autospec(UpdateManager, instance=True, spec_set=True)
    manager.status = UpdateJobStatus()
    manager.cancel.return_value = False
    manager.get_usb_internet_status = AsyncMock(
        return_value=UsbInternetStatus(
            detected=False,
            usable=False,
            diagnostic="No USB network interface is currently detected.",
        )
    )
    return manager


def _esp_flash_manager_mock() -> EspFlashManager:
    manager = create_autospec(EspFlashManager, instance=True, spec_set=True)
    manager.status = EspFlashStatus()
    manager.list_ports = AsyncMock(return_value=[])
    manager.start.return_value = 1
    manager.logs_since.return_value = {"from_index": 0, "next_index": 0, "lines": []}
    manager.cancel.return_value = False
    manager.history.return_value = []
    return manager


def _run_recorder_mock() -> RunRecorder:
    recorder = create_autospec(RunRecorder, instance=True, spec_set=True)
    idle_status = RunRecorderStatusSnapshot(
        enabled=False,
        run_id=None,
        write_error=None,
        analysis_in_progress=False,
        samples_written=0,
        samples_dropped=0,
        last_completed_run_id=None,
        last_completed_run_error=None,
    )
    recorder.status.return_value = idle_status
    recorder.start_recording.return_value = idle_status
    recorder.stop_recording.return_value = idle_status
    return recorder


def _processor_mock() -> SignalProcessor:
    processor = create_autospec(SignalProcessor, instance=True, spec_set=True)
    processor.intake_stats.return_value = {
        "total_ingested_samples": 0,
        "total_compute_calls": 0,
        "last_compute_duration_s": 0.0,
        "last_compute_all_duration_s": 0.0,
        "last_ingest_duration_s": 0.0,
    }
    processor.buffer_overflow_drops.return_value = 0
    processor.all_latest_metrics.return_value = {}
    return processor


def _registry_mock() -> ClientRegistry:
    registry = create_autospec(ClientRegistry, instance=True, spec_set=True)
    registry.active_client_ids.return_value = []
    registry.get.return_value = None
    registry.remove_client.return_value = False
    registry.data_loss_snapshot.return_value = {
        "tracked_clients": 0,
        "affected_clients": 0,
        "frames_dropped": 0,
        "queue_overflow_drops": 0,
        "server_queue_drops": 0,
        "parse_errors": 0,
    }
    return registry


def _control_plane_mock() -> UDPControlPlane:
    control_plane = create_autospec(UDPControlPlane, instance=True, spec_set=True)
    control_plane.send_identify.return_value = (False, None)
    return control_plane


def _ws_hub_mock() -> WebSocketHub:
    ws_hub = create_autospec(WebSocketHub, instance=True, spec_set=True)
    ws_hub.add = AsyncMock(return_value=None)
    ws_hub.update_selected_client = AsyncMock(return_value=None)
    ws_hub.remove = AsyncMock(return_value=None)
    return ws_hub


def _gps_monitor_mock() -> GPSSpeedMonitor:
    gps_monitor = create_autospec(GPSSpeedMonitor, instance=True, spec_set=True)
    gps_monitor.status_snapshot.return_value = SpeedSourceStatusSnapshot(
        gps_enabled=False,
        connection_state="disconnected",
        device=None,
        fix_mode=0,
        fix_dimension="none",
        speed_confidence="none",
        epx_m=None,
        epy_m=None,
        epv_m=None,
        last_update_age_s=None,
        raw_speed_kmh=None,
        effective_speed_kmh=None,
        last_error=None,
        reconnect_delay_s=None,
        fallback_active=False,
        speed_source="manual",
        stale_timeout_s=8.0,
    )
    return gps_monitor


def _default_cars_snapshot() -> CarsSnapshot:
    return CarsSnapshot(
        cars=[
            {
                "id": "car-1",
                "name": "Test Car",
                "type": "sedan",
                "aspects": {"tire_width_mm": 225.0},
            }
        ],
        active_car_id="car-1",
    )


def _settings_store_mock() -> MagicMock:
    store = MagicMock()
    store.analysis_settings_snapshot.return_value = AnalysisSettingsSnapshot(
        **AnalysisSettingsSnapshot.DEFAULTS
    )
    store.get_cars.return_value = _default_cars_snapshot()
    store.get_speed_source.return_value = {
        "speedSource": "manual",
        "manualSpeedKph": 0.0,
        "staleTimeoutS": 8.0,
    }
    store.get_sensors.return_value = {}
    store.active_car_snapshot.return_value = None
    store.add_car.return_value = _default_cars_snapshot()
    store.update_car.return_value = _default_cars_snapshot()
    store.delete_car.return_value = _default_cars_snapshot()
    store.set_active_car.return_value = _default_cars_snapshot()
    store.update_active_car_aspects.return_value = {}
    store.set_sensor.return_value = {}
    store.remove_sensor.return_value = True
    store.update_speed_source.return_value = {
        "speedSource": "manual",
        "manualSpeedKph": 0.0,
        "staleTimeoutS": 8.0,
    }
    store.set_language.return_value = "en"
    store.language = "en"
    store.set_speed_unit.return_value = "kmh"
    store.speed_unit = "kmh"
    return store


def _speed_source_service_mock() -> MagicMock:
    service = MagicMock()
    service.get_speed_source.return_value = {
        "speedSource": "manual",
        "manualSpeedKph": 0.0,
        "staleTimeoutS": 8.0,
    }
    service.update_speed_source.return_value = {
        "speedSource": "manual",
        "manualSpeedKph": 0.0,
        "staleTimeoutS": 8.0,
    }
    return service


@dataclass
class FakeState:
    """Minimal stand-in for router assembly tests.

    Keeps the convenient flat fields used throughout tests while exposing the
    grouped dependency attributes consumed by ``create_router``.
    """

    config: object = field(default_factory=MagicMock)
    registry: ClientRegistry = field(default_factory=_registry_mock)
    processor: SignalProcessor = field(default_factory=_processor_mock)
    control_plane: UDPControlPlane = field(default_factory=_control_plane_mock)
    worker_pool: object = field(default_factory=MagicMock)
    ws_hub: WebSocketHub = field(default_factory=_ws_hub_mock)
    gps_monitor: GPSSpeedMonitor = field(default_factory=_gps_monitor_mock)
    run_recorder: RunRecorder = field(default_factory=_run_recorder_mock)
    settings_store: MagicMock = field(default_factory=_settings_store_mock)
    settings_reader: object | None = None
    car_settings: object | None = None
    analysis_settings: object | None = None
    sensor_metadata_store: object | None = None
    ui_preferences: object | None = None
    speed_source_service: MagicMock = field(default_factory=_speed_source_service_mock)
    history_db: object = field(default_factory=MagicMock)
    update_manager: UpdateManager = field(default_factory=_update_manager_mock)
    esp_flash_manager: EspFlashManager = field(default_factory=_esp_flash_manager_mock)
    processing_loop_state: ProcessingLoopState = field(default_factory=ProcessingLoopState)
    health_state: RuntimeHealthState = field(default_factory=RuntimeHealthState)
    ingest_diagnostics: IngestDiagnosticsCollector = field(
        default_factory=IngestDiagnosticsCollector
    )
    processing_loop: object = field(default_factory=MagicMock)
    ws_broadcast: object = field(default_factory=MagicMock)
    run_service: object | None = None
    report_service: object | None = None
    export_service: object | None = None

    def __post_init__(self) -> None:
        self.health_state.mark_ready()
        if self.settings_reader is None:
            self.settings_reader = self.settings_store
        if self.car_settings is None:
            self.car_settings = self.settings_store
        if self.analysis_settings is None:
            self.analysis_settings = self.settings_store
        if self.sensor_metadata_store is None:
            self.sensor_metadata_store = self.settings_store
        if self.ui_preferences is None:
            self.ui_preferences = self.settings_store
        # Keep router assembly tests focused on dependency wiring rather than
        # bespoke history/export service setup in each caller.
        if self.run_service is None:
            self.run_service = ProjectedHistoryRunService(
                HistoryRunService(
                    self.history_db,
                ),
                current_car_reader=self.settings_reader,
            )
        if self.report_service is None:
            self.report_service = HistoryReportService(
                self.history_db,
                pdf_renderer=lambda _prepared: b"%PDF-stub",
            )
        if self.export_service is None:
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
            sensor_metadata_store=self.sensor_metadata_store,
            processor=self.processor,
            run_recorder=self.run_recorder,
            ws_hub=self.ws_hub,
        )

    @property
    def settings(self) -> SettingsDeps:
        return SettingsDeps(
            car_settings=self.car_settings,
            analysis_settings=self.analysis_settings,
            ui_preferences=self.ui_preferences,
            speed_source_service=self.speed_source_service,
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


@pytest.fixture
def fake_state() -> FakeState:
    """Return a fresh ``FakeState`` for each test."""
    state = FakeState()
    # Health endpoints read a dedicated recorder health payload, not status().
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
