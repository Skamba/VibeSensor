"""Typed dependency groups for assembling HTTP route groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.infra.config.settings_store import SettingsStore
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_loop import ProcessingLoopState
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.use_cases.history.exports import HistoryExportService
from vibesensor.use_cases.history.reports import HistoryReportService
from vibesensor.use_cases.history.runs import HistoryRunService
from vibesensor.use_cases.run import RunRecorder
from vibesensor.use_cases.updates.esp_flash_manager import EspFlashManager
from vibesensor.use_cases.updates.manager import UpdateManager

if TYPE_CHECKING:
    from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
    from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane
    from vibesensor.adapters.websocket.hub import WebSocketHub


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
    gps_monitor: GPSSpeedMonitor


@dataclass(slots=True)
class HistoryDeps:
    run_service: HistoryRunService
    report_service: HistoryReportService
    export_service: HistoryExportService


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
