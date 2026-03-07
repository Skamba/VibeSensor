from __future__ import annotations

from dataclasses import dataclass

from ..analysis_settings import AnalysisSettingsStore
from ..esp_flash_manager import EspFlashManager
from ..gps_speed import GPSSpeedMonitor
from ..history_db import HistoryDB
from ..live_diagnostics.engine import LiveDiagnosticsEngine
from ..metrics_log import MetricsLogger
from ..processing import SignalProcessor
from ..registry import ClientRegistry
from ..settings_store import SettingsStore
from ..udp_control_tx import UDPControlPlane
from ..update.manager import UpdateManager
from ..worker_pool import WorkerPool
from ..ws_hub import WebSocketHub
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
class RuntimeDiagnosticsSubsystem:
    metrics_logger: MetricsLogger
    live_diagnostics: LiveDiagnosticsEngine


@dataclass(slots=True)
class RuntimePersistenceSubsystem:
    history_db: HistoryDB


@dataclass(slots=True)
class RuntimeUpdateSubsystem:
    update_manager: UpdateManager
    esp_flash_manager: EspFlashManager


@dataclass(slots=True)
class RuntimeProcessingSubsystem:
    state: ProcessingLoopState
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
    diagnostics: RuntimeDiagnosticsSubsystem
    persistence: RuntimePersistenceSubsystem
    updates: RuntimeUpdateSubsystem
    processing: RuntimeProcessingSubsystem
    websocket: RuntimeWebsocketSubsystem
