"""RuntimeState – top-level runtime assembly."""

from __future__ import annotations

from dataclasses import dataclass

from ..analysis_settings import AnalysisSettingsStore
from ..config import AppConfig
from ..gps_speed import GPSSpeedMonitor
from ..history_db import HistoryDB
from ..history_services.exports import HistoryExportService
from ..history_services.reports import HistoryReportService
from ..history_services.runs import HistoryRunService
from ..metrics_log import RunRecorder
from ..processing import SignalProcessor
from ..registry import ClientRegistry
from ..settings_store import SettingsStore
from ..udp_control_tx import UDPControlPlane
from ..update.esp_flash_manager import EspFlashManager
from ..update.manager import UpdateManager
from ..worker_pool import WorkerPool
from ..ws_hub import WebSocketHub
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
