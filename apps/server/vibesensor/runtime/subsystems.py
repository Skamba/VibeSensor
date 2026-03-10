from __future__ import annotations

from dataclasses import dataclass

from ..analysis_settings import AnalysisSettingsStore
from ..esp_flash_manager import EspFlashManager
from ..gps_speed import GPSSpeedMonitor
from ..history_db import HistoryDB
from ..history_services.exports import HistoryExportService
from ..history_services.reports import HistoryReportService
from ..history_services.runs import HistoryRunDeleteService, HistoryRunQueryService
from ..metrics_log import MetricsLogger
from ..processing import SignalProcessor
from ..registry import ClientRegistry
from ..settings_store import SettingsStore
from ..udp_control_tx import UDPControlPlane
from ..update.manager import UpdateManager
from ..worker_pool import WorkerPool
from ..ws_hub import WebSocketHub
from .health_state import RuntimeHealthState
from .processing_loop import ProcessingLoop, ProcessingLoopState
from .settings_sync import apply_car_settings, apply_speed_source_settings
from .ws_broadcast import WsBroadcastCache, WsBroadcastService


@dataclass(slots=True)
class RuntimeIngressSubsystem:
    registry: ClientRegistry
    processor: SignalProcessor
    control_plane: UDPControlPlane
    worker_pool: WorkerPool


@dataclass(slots=True)
class RuntimeSettingsSubsystem:
    settings_store: SettingsStore
    analysis_settings: AnalysisSettingsStore
    gps_monitor: GPSSpeedMonitor

    def apply_car_settings(self) -> None:
        apply_car_settings(self.settings_store, self.analysis_settings)

    def apply_speed_source_settings(self) -> None:
        apply_speed_source_settings(self.settings_store, self.gps_monitor)


@dataclass(slots=True)
class RuntimeRecordingSubsystem:
    metrics_logger: MetricsLogger


@dataclass(slots=True)
class RuntimePersistenceSubsystem:
    history_db: HistoryDB
    query_service: HistoryRunQueryService
    delete_service: HistoryRunDeleteService
    report_service: HistoryReportService
    export_service: HistoryExportService


@dataclass(slots=True)
class RuntimeUpdateSubsystem:
    update_manager: UpdateManager
    esp_flash_manager: EspFlashManager


@dataclass(slots=True)
class RuntimeProcessingSubsystem:
    state: ProcessingLoopState
    health_state: RuntimeHealthState
    loop: ProcessingLoop


@dataclass(slots=True)
class RuntimeWebsocketSubsystem:
    hub: WebSocketHub
    cache: WsBroadcastCache
    broadcast: WsBroadcastService


@dataclass(slots=True)
class RuntimeRouteServices:
    ingress: RuntimeIngressSubsystem
    settings: RuntimeSettingsSubsystem
    recording: RuntimeRecordingSubsystem
    persistence: RuntimePersistenceSubsystem
    updates: RuntimeUpdateSubsystem
    processing: RuntimeProcessingSubsystem
    websocket: RuntimeWebsocketSubsystem
