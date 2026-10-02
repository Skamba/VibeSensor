"""Typed dependency groups for assembling HTTP route bundles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from vibesensor.ingest.client_payloads import ClientSnapshotSource
from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.ingest.registry import ClientRegistry
from vibesensor.live.payload_types import ClientMetrics
from vibesensor.live.processing_loop import ProcessingLoopState
from vibesensor.live.processor import SignalProcessor
from vibesensor.recording.recorder import RunRecorder
from vibesensor.report.service import HistoryReportService
from vibesensor.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.updates.manager import UpdateManager
from vibesensor.web.health_state import RuntimeHealthState

if TYPE_CHECKING:
    from vibesensor.ingest.registry import ClientRecord
    from vibesensor.live.broadcaster import LiveBroadcaster
    from vibesensor.settings.analysis_settings import ActiveCarAnalysisSettingsService
    from vibesensor.settings.car_settings import CarSettingsService
    from vibesensor.settings.sensor_settings import SensorSettingsService
    from vibesensor.settings.ui_preferences import UiPreferencesService
    from vibesensor.speed.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
    from vibesensor.speed.speed_source_config import (
        SpeedSourcePayload,
        SpeedSourceUpdatePayload,
    )
    from vibesensor.speed.speed_status import SpeedSourceStatusSnapshot
    from vibesensor.web.history_services import (
        ProjectedHistoryExportService,
        ProjectedHistoryRunService,
    )


class SettingsSpeedServiceProtocol(Protocol):
    def status_snapshot(self) -> SpeedSourceStatusSnapshot: ...

    def obd_status(self) -> ObdStatusSnapshot: ...


class ObdAdminServiceProtocol(Protocol):
    """Bluetooth OBD admin operations the settings routes are allowed to call.

    Routes get this narrow seam rather than the whole OBD service so they cannot
    reach connection-loop state transitions (``mark_connected`` and friends),
    which belong to the OBD runtime alone.
    """

    def scan_obd_devices(self) -> list[ObdDeviceSnapshot]: ...

    def pair_obd_device(self, mac_address: str) -> ObdDeviceSnapshot: ...

    def refresh_obd_status(self) -> None: ...


class SpeedSourceSettingsServiceProtocol(Protocol):
    def get_speed_source(self) -> SpeedSourcePayload: ...

    def update_speed_source(self, data: SpeedSourceUpdatePayload) -> SpeedSourcePayload: ...


class ClientRegistryProtocol(ClientSnapshotSource, Protocol):
    def get(self, client_id: str) -> ClientRecord | None: ...

    def active_client_ids(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> list[str]: ...

    def set_location(self, client_id: str, location_code: str) -> ClientRecord | None: ...

    def set_name(self, client_id: str, name: str) -> ClientRecord | None: ...

    def clear_name(self, client_id: str) -> ClientRecord | None: ...

    def remove_client(self, client_id: str) -> bool: ...


class ClientProcessorProtocol(Protocol):
    def all_latest_metrics(self, client_ids: list[str]) -> dict[str, ClientMetrics]: ...


class ClientControlPlaneProtocol(Protocol):
    def send_identify(self, client_id: str, duration_ms: int) -> tuple[bool, int | None]: ...


@dataclass(slots=True)
class HealthDeps:
    processing_loop_state: ProcessingLoopState
    health_state: RuntimeHealthState
    processor: SignalProcessor
    registry: ClientRegistry
    run_recorder: RunRecorder
    ingest_diagnostics: IngestDiagnosticsCollector


@dataclass(slots=True)
class LiveDeps:
    registry: ClientRegistryProtocol
    control_plane: ClientControlPlaneProtocol
    sensor_metadata_store: SensorSettingsService
    processor: SignalProcessor
    run_recorder: RunRecorder
    ws_broadcaster: LiveBroadcaster


@dataclass(slots=True)
class SettingsDeps:
    car_settings: CarSettingsService
    analysis_settings: ActiveCarAnalysisSettingsService
    ui_preferences: UiPreferencesService
    speed_source_service: SpeedSourceSettingsServiceProtocol
    speed_status_service: SettingsSpeedServiceProtocol
    obd_admin_service: ObdAdminServiceProtocol


@dataclass(slots=True)
class HistoryDeps:
    run_service: ProjectedHistoryRunService
    report_service: HistoryReportService
    export_service: ProjectedHistoryExportService


@dataclass(slots=True)
class UpdateDeps:
    update_manager: UpdateManager
    esp_flash_manager: EspFlashManager


@dataclass(slots=True)
class RouterDeps:
    health: HealthDeps
    settings: SettingsDeps
    live: LiveDeps
    history: HistoryDeps
    updates: UpdateDeps
