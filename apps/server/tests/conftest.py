"""Shared test fixtures and helpers for the vibesensor test suite.

Plain helper functions / assertion utilities live in dedicated
``_*_test_helpers.py`` modules so they can be imported unambiguously even
when sub-directory ``conftest.py`` files exist (which shadow this module in
``sys.modules``).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, create_autospec

import pytest

from vibesensor.clock.browser_clock import BrowserClockCorrector
from vibesensor.history.exports import HistoryExportService
from vibesensor.history.history_db import HistoryDB
from vibesensor.history.runs import HistoryRunService
from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.ingest.registry import ClientRegistry
from vibesensor.ingest.udp_control_tx import UDPControlPlane
from vibesensor.live.broadcaster import LiveBroadcaster
from vibesensor.live.processing_loop import ProcessingLoopState
from vibesensor.live.processor import SignalProcessor
from vibesensor.recording.recorder import RunRecorder
from vibesensor.recording.status_reporting import RunRecorderStatusSnapshot
from vibesensor.report.service import HistoryReportService
from vibesensor.settings.services import SettingsServices, build_settings_services
from vibesensor.speed.gps_speed import GPSSpeedMonitor
from vibesensor.speed.speed_status import SpeedSourceStatusSnapshot
from vibesensor.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.updates.firmware.esp_flash_types import EspFlashStatus
from vibesensor.updates.manager import UpdateManager
from vibesensor.updates.models import UpdateJobStatus, UsbInternetStatus
from vibesensor.web.health_state import RuntimeHealthState
from vibesensor.web.history_services import (
    ProjectedHistoryExportService,
    ProjectedHistoryRunService,
)


@pytest.fixture(autouse=True, scope="session")
def _isolate_git_environment() -> Iterator[None]:
    """Drop inherited ``GIT_*`` variables so tests that run git use their own repos.

    Under a git hook or ``git rebase -x``, variables such as ``GIT_DIR`` point at the
    developer's repository, and a test's ``git -C <tmp>`` would modify it instead.
    """
    with pytest.MonkeyPatch.context() as mp:
        for name in [key for key in os.environ if key.startswith("GIT_")]:
            mp.delenv(name)
        yield


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
    manager.bundled_firmware_version.return_value = ""
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
    processor.recent_buffer_overflow_drops.return_value = 0
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
    registry.recent_data_loss_snapshot.return_value = {
        "window_s": 60,
        "frame_loss_clients": 0,
        "frames_dropped": 0,
        "expected_frames_dropped": 0,
        "queue_overflow_drops": 0,
        "server_queue_drops": 0,
        "parse_errors": 0,
    }
    return registry


def _control_plane_mock() -> UDPControlPlane:
    control_plane = create_autospec(UDPControlPlane, instance=True, spec_set=True)
    control_plane.send_identify.return_value = (False, None)
    return control_plane


def _ws_broadcaster_mock() -> LiveBroadcaster:
    return create_autospec(LiveBroadcaster, instance=True, spec_set=True)


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


@dataclass
class FakeState:
    """Router-assembly state: spec'd runtime mocks plus real in-memory settings services.

    Its attribute names match ``vibesensor.web.router.WebServices`` so it can be
    passed straight to ``create_router``. Settings routes run against the real
    services from ``build_settings_services()``; pass ``settings=`` to share
    them with the test, or override a single service by keyword.
    """

    registry: ClientRegistry = field(default_factory=_registry_mock)
    processor: SignalProcessor = field(default_factory=_processor_mock)
    control_plane: UDPControlPlane = field(default_factory=_control_plane_mock)
    ws_broadcaster: LiveBroadcaster = field(default_factory=_ws_broadcaster_mock)
    gps_monitor: GPSSpeedMonitor = field(default_factory=_gps_monitor_mock)
    run_recorder: RunRecorder = field(default_factory=_run_recorder_mock)
    settings: SettingsServices = field(default_factory=build_settings_services)
    settings_reader: object | None = None
    car_settings: object | None = None
    analysis_settings: object | None = None
    sensor_metadata_store: object | None = None
    ui_preferences: object | None = None
    speed_source_service: object | None = None
    history_db: object = field(default_factory=lambda: create_autospec(HistoryDB, instance=True))
    update_manager: UpdateManager = field(default_factory=_update_manager_mock)
    esp_flash_manager: EspFlashManager = field(default_factory=_esp_flash_manager_mock)
    processing_loop_state: ProcessingLoopState = field(default_factory=ProcessingLoopState)
    health_state: RuntimeHealthState = field(default_factory=RuntimeHealthState)
    ingest_diagnostics: IngestDiagnosticsCollector = field(
        default_factory=IngestDiagnosticsCollector
    )
    run_service: object | None = None
    report_service: object | None = None
    export_service: object | None = None
    # Sync state "unknown": the router-assembly state never steps the host clock.
    browser_clock: BrowserClockCorrector = field(
        default_factory=lambda: BrowserClockCorrector(
            recording=lambda: False, synchronized=lambda: None
        )
    )

    def __post_init__(self) -> None:
        self.health_state.mark_ready()
        if self.settings_reader is None:
            self.settings_reader = self.settings.settings_reader
        if self.car_settings is None:
            self.car_settings = self.settings.car_settings
        if self.analysis_settings is None:
            self.analysis_settings = self.settings.analysis_settings
        if self.sensor_metadata_store is None:
            self.sensor_metadata_store = self.settings.sensor_settings
        if self.ui_preferences is None:
            self.ui_preferences = self.settings.ui_preferences
        if self.speed_source_service is None:
            self.speed_source_service = self.settings.speed_source_service
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
    def speed_status_service(self) -> GPSSpeedMonitor:
        return self.gps_monitor

    @property
    def obd_admin_service(self) -> GPSSpeedMonitor:
        return self.gps_monitor


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
