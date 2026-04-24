"""Typed dependency groups for assembling HTTP route bundles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from vibesensor.adapters.http.models import (
    DeleteHistoryRunResponse,
    HistoryInsightsResponse,
    HistoryListEntryResponse,
    HistoryRunResponse,
)
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_state import ProcessingLoopState
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.shared.boundaries.clients import ClientSnapshotSource
from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector
from vibesensor.shared.ports import (
    AnalysisSettingsStore,
    CarSettingsStore,
    SensorMetadataStore,
    TrackedClient,
    UiPreferencesStore,
)
from vibesensor.shared.types.payload_types import ClientMetrics
from vibesensor.use_cases.history.exports import HistoryExportDownload
from vibesensor.use_cases.history.reports import HistoryReportPdf
from vibesensor.use_cases.run import RunRecorder
from vibesensor.use_cases.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.use_cases.updates.manager import UpdateManager

if TYPE_CHECKING:
    from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
    from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
    from vibesensor.adapters.websocket.hub import WebSocketHub
    from vibesensor.shared.types.speed_source_config import (
        SpeedSourcePayload,
        SpeedSourceUpdatePayload,
    )


class HistoryRunServiceProtocol(Protocol):
    async def list_runs(self) -> list[HistoryListEntryResponse]: ...

    async def get_run(self, run_id: str) -> HistoryRunResponse: ...

    async def get_insights(
        self,
        run_id: str,
        requested_lang: str | None = None,
    ) -> HistoryInsightsResponse | None: ...

    async def delete_run(self, run_id: str) -> DeleteHistoryRunResponse: ...


class HistoryReportServiceProtocol(Protocol):
    async def build_pdf(self, run_id: str, requested_lang: str | None) -> HistoryReportPdf: ...


class HistoryExportServiceProtocol(Protocol):
    async def build_export(self, run_id: str) -> HistoryExportDownload: ...


class SettingsSpeedServiceProtocol(Protocol):
    def status_snapshot(self) -> SpeedSourceStatusSnapshot: ...

    def obd_status(self) -> ObdStatusSnapshot: ...


class ObdAdminServiceProtocol(Protocol):
    def scan_obd_devices(self, *, timeout_s: int = ...) -> list[ObdDeviceSnapshot]: ...

    def pair_obd_device(self, mac_address: str) -> ObdDeviceSnapshot: ...

    def refresh_obd_status(self) -> None: ...


class SpeedSourceSettingsServiceProtocol(Protocol):
    def get_speed_source(self) -> SpeedSourcePayload: ...

    def update_speed_source(self, data: SpeedSourceUpdatePayload) -> SpeedSourcePayload: ...


class ClientRegistryProtocol(ClientSnapshotSource, Protocol):
    def get(self, client_id: str) -> TrackedClient | None: ...

    def active_client_ids(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> list[str]: ...

    def set_location(self, client_id: str, location_code: str) -> TrackedClient | None: ...

    def set_name(self, client_id: str, name: str) -> TrackedClient | None: ...

    def clear_name(self, client_id: str) -> TrackedClient | None: ...

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
    sensor_metadata_store: SensorMetadataStore
    processor: SignalProcessor
    run_recorder: RunRecorder
    ws_hub: WebSocketHub


@dataclass(slots=True)
class SettingsDeps:
    car_settings: CarSettingsStore
    analysis_settings: AnalysisSettingsStore
    ui_preferences: UiPreferencesStore
    speed_source_service: SpeedSourceSettingsServiceProtocol
    speed_status_service: SettingsSpeedServiceProtocol
    obd_admin_service: ObdAdminServiceProtocol


@dataclass(slots=True)
class HistoryDeps:
    run_service: HistoryRunServiceProtocol
    report_service: HistoryReportServiceProtocol
    export_service: HistoryExportServiceProtocol


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
