"""RuntimeState – top-level runtime assembly."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.adapters.udp.control_tx import UDPControlPlane
from vibesensor.adapters.websocket.hub import WebSocketHub
from vibesensor.app.settings import AppConfig
from vibesensor.infra.config.analysis_settings import AnalysisSettingsStore
from vibesensor.infra.config.settings_store import SettingsStore
from vibesensor.infra.metrics import RunRecorder
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.infra.workers.worker_pool import WorkerPool
from vibesensor.use_cases.history.exports import HistoryExportService
from vibesensor.use_cases.history.reports import HistoryReportService
from vibesensor.use_cases.history.runs import HistoryRunService
from vibesensor.use_cases.updates.esp_flash_manager import EspFlashManager
from vibesensor.use_cases.updates.manager import UpdateManager

from .health_state import RuntimeHealthState
from .processing_loop import ProcessingLoop, ProcessingLoopState
from .ws_broadcast import WsBroadcastService


@dataclass(slots=True)
class RuntimeState:
    """Top-level runtime with flat field access."""

    config: AppConfig
    # ingress
    registry: ClientRegistry
    processor: SignalProcessor
    control_plane: UDPControlPlane
    worker_pool: WorkerPool
    # settings
    settings_store: SettingsStore
    analysis_settings: AnalysisSettingsStore
    gps_monitor: GPSSpeedMonitor
    # persistence
    history_db: HistoryDB
    run_service: HistoryRunService
    report_service: HistoryReportService
    export_service: HistoryExportService
    # processing
    processing_loop_state: ProcessingLoopState
    health_state: RuntimeHealthState
    processing_loop: ProcessingLoop
    # websocket
    ws_hub: WebSocketHub
    ws_broadcast: WsBroadcastService
    # top-level
    run_recorder: RunRecorder
    update_manager: UpdateManager
    esp_flash_manager: EspFlashManager
