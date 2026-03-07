"""RuntimeState – thin coordinator holding service references and subsystems.

``RuntimeState`` is the composition root: it holds service references that
routes need and creates focused subsystem objects that own actual behavior.

Subsystems (created automatically in ``__post_init__``):
- ``processing_loop``: async tick loop + failure tracking
- ``ws_broadcast``: WebSocket payload assembly + caching
- ``lifecycle``: server start / graceful stop
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    """Thin coordinator: holds service refs used by routes and subsystem objects.

    Subsystems (created in ``__post_init__``):

    - ``processing_loop``: async tick loop + failure tracking
    - ``ws_broadcast``: WebSocket payload assembly + caching
    - ``lifecycle``: server start / graceful stop
    """

    # -- Service references (used by routes) --------------------------------

    config: AppConfig
    registry: ClientRegistry
    processor: SignalProcessor
    control_plane: UDPControlPlane
    ws_hub: WebSocketHub
    gps_monitor: GPSSpeedMonitor
    analysis_settings: AnalysisSettingsStore
    metrics_logger: MetricsLogger
    live_diagnostics: LiveDiagnosticsEngine
    settings_store: SettingsStore
    history_db: HistoryDB
    update_manager: UpdateManager
    esp_flash_manager: EspFlashManager
    worker_pool: WorkerPool

    # -- Shared mutable state (routes + subsystems access these) ------------

    loop_state: ProcessingLoopState = field(default_factory=ProcessingLoopState)
    ws_cache: WsBroadcastCache = field(default_factory=WsBroadcastCache)

    # -- Subsystems (created in __post_init__) ------------------------------

    processing_loop: ProcessingLoop = field(init=False)
    ws_broadcast: WsBroadcastService = field(init=False)
    lifecycle: LifecycleManager = field(init=False)

    def __post_init__(self) -> None:
        self.processing_loop = ProcessingLoop(
            state=self.loop_state,
            fft_update_hz=self.config.processing.fft_update_hz,
            sample_rate_hz=self.config.processing.sample_rate_hz,
            fft_n=self.config.processing.fft_n,
            registry=self.registry,
            processor=self.processor,
            control_plane=self.control_plane,
        )
        self.ws_broadcast = WsBroadcastService(
            cache=self.ws_cache,
            ui_push_hz=self.config.processing.ui_push_hz,
            ui_heavy_push_hz=self.config.processing.ui_heavy_push_hz,
            registry=self.registry,
            processor=self.processor,
            gps_monitor=self.gps_monitor,
            analysis_settings=self.analysis_settings,
            metrics_logger=self.metrics_logger,
            live_diagnostics=self.live_diagnostics,
            settings_store=self.settings_store,
        )
        self.lifecycle = LifecycleManager(
            config=self.config,
            registry=self.registry,
            processor=self.processor,
            control_plane=self.control_plane,
            ws_hub=self.ws_hub,
            gps_monitor=self.gps_monitor,
            metrics_logger=self.metrics_logger,
            update_manager=self.update_manager,
            esp_flash_manager=self.esp_flash_manager,
            history_db=self.history_db,
            worker_pool=self.worker_pool,
            processing_loop=self.processing_loop,
            ws_broadcast=self.ws_broadcast,
        )

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
