"""RuntimeState – thin coordinator over explicit runtime subsystem groups.

``RuntimeState`` no longer constructs subsystems in ``__post_init__``. Runtime
composition lives in ``runtime/composition.py`` and passes in already-wired
subsystems plus a small number of focused service groups.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..analysis_settings import AnalysisSettingsStore
from ..config import AppConfig
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
from .dependencies import (
    RuntimeIngressServices,
    RuntimeOperationsServices,
    RuntimePlatformServices,
)
from .lifecycle import LifecycleManager
from .processing_loop import ProcessingLoop, ProcessingLoopState
from .settings_sync import (
    apply_car_settings as _apply_car_settings,
)
from .settings_sync import (
    apply_speed_source_settings as _apply_speed_source_settings,
)
from .ws_broadcast import WsBroadcastCache, WsBroadcastService


@dataclass(slots=True)
class RuntimeState:
    """Thin coordinator over service groups and already-built subsystems."""

    config: AppConfig
    ingress: RuntimeIngressServices
    operations: RuntimeOperationsServices
    platform: RuntimePlatformServices
    loop_state: ProcessingLoopState
    ws_cache: WsBroadcastCache
    processing_loop: ProcessingLoop
    ws_broadcast: WsBroadcastService
    lifecycle: LifecycleManager

    @property
    def registry(self) -> ClientRegistry:
        return self.ingress.registry

    @registry.setter
    def registry(self, value: ClientRegistry) -> None:
        self.ingress.registry = value

    @property
    def processor(self) -> SignalProcessor:
        return self.ingress.processor

    @processor.setter
    def processor(self, value: SignalProcessor) -> None:
        self.ingress.processor = value

    @property
    def control_plane(self) -> UDPControlPlane:
        return self.ingress.control_plane

    @control_plane.setter
    def control_plane(self, value: UDPControlPlane) -> None:
        self.ingress.control_plane = value

    @property
    def settings_store(self) -> SettingsStore:
        return self.operations.settings_store

    @settings_store.setter
    def settings_store(self, value: SettingsStore) -> None:
        self.operations.settings_store = value

    @property
    def analysis_settings(self) -> AnalysisSettingsStore:
        return self.operations.analysis_settings

    @analysis_settings.setter
    def analysis_settings(self, value: AnalysisSettingsStore) -> None:
        self.operations.analysis_settings = value

    @property
    def gps_monitor(self) -> GPSSpeedMonitor:
        return self.operations.gps_monitor

    @gps_monitor.setter
    def gps_monitor(self, value: GPSSpeedMonitor) -> None:
        self.operations.gps_monitor = value

    @property
    def metrics_logger(self) -> MetricsLogger:
        return self.operations.metrics_logger

    @metrics_logger.setter
    def metrics_logger(self, value: MetricsLogger) -> None:
        self.operations.metrics_logger = value

    @property
    def live_diagnostics(self) -> LiveDiagnosticsEngine:
        return self.operations.live_diagnostics

    @live_diagnostics.setter
    def live_diagnostics(self, value: LiveDiagnosticsEngine) -> None:
        self.operations.live_diagnostics = value

    @property
    def ws_hub(self) -> WebSocketHub:
        return self.platform.ws_hub

    @ws_hub.setter
    def ws_hub(self, value: WebSocketHub) -> None:
        self.platform.ws_hub = value

    @property
    def history_db(self) -> HistoryDB:
        return self.platform.history_db

    @history_db.setter
    def history_db(self, value: HistoryDB) -> None:
        self.platform.history_db = value

    @property
    def update_manager(self) -> UpdateManager:
        return self.platform.update_manager

    @update_manager.setter
    def update_manager(self, value: UpdateManager) -> None:
        self.platform.update_manager = value

    @property
    def esp_flash_manager(self) -> EspFlashManager:
        return self.platform.esp_flash_manager

    @esp_flash_manager.setter
    def esp_flash_manager(self, value: EspFlashManager) -> None:
        self.platform.esp_flash_manager = value

    @property
    def worker_pool(self) -> WorkerPool:
        return self.platform.worker_pool

    @worker_pool.setter
    def worker_pool(self, value: WorkerPool) -> None:
        self.platform.worker_pool = value

    # -- Settings sync (used by settings routes) ---------------------------

    def apply_car_settings(self) -> None:
        """Push active car aspects into the shared AnalysisSettingsStore."""
        _apply_car_settings(self.settings_store, self.analysis_settings)

    def apply_speed_source_settings(self) -> None:
        """Push speed-source settings into GPSSpeedMonitor."""
        _apply_speed_source_settings(self.settings_store, self.gps_monitor)

    # -- Lifecycle delegates -----------------------------------------------

    async def start(self) -> None:
        """Launch UDP receiver, control plane, and background async tasks."""
        await self.lifecycle.start()

    async def stop(self) -> None:
        """Graceful shutdown: cancel tasks, close DB/transport, wait for post-analysis."""
        await self.lifecycle.stop()
