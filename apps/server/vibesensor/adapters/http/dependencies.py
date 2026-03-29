"""Typed dependency groups for assembling HTTP route groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from vibesensor.adapters.http.models import (
    DeleteHistoryRunResponse,
    HistoryInsightsResponse,
    HistoryListEntryResponse,
    HistoryRunResponse,
)
from vibesensor.infra.config.settings_store import SettingsStore
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_loop import ProcessingLoopState
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.use_cases.history.exports import HistoryExportDownload
from vibesensor.use_cases.history.reports import HistoryReportPdf
from vibesensor.use_cases.run import RunRecorder
from vibesensor.use_cases.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.use_cases.updates.manager import UpdateManager

if TYPE_CHECKING:
    from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
    from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
    from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane
    from vibesensor.adapters.websocket.hub import WebSocketHub


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

    def scan_obd_devices(self, *, timeout_s: int = ...) -> list[ObdDeviceSnapshot]: ...

    def pair_obd_device(self, mac_address: str) -> ObdDeviceSnapshot: ...

    def obd_status(self) -> ObdStatusSnapshot: ...


@dataclass(slots=True)
class TelemetryDeps:
    processing_loop_state: ProcessingLoopState
    health_state: RuntimeHealthState
    processor: SignalProcessor
    registry: ClientRegistry
    control_plane: UDPControlPlane
    run_recorder: RunRecorder
    ws_hub: WebSocketHub


@dataclass(slots=True)
class SettingsDeps:
    settings_store: SettingsStore
    gps_monitor: SettingsSpeedServiceProtocol


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
    telemetry: TelemetryDeps
    settings: SettingsDeps
    history: HistoryDeps
    updates: UpdateDeps
