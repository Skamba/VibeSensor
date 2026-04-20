"""App-owned runtime assembly for lifecycle and router dependency bundles.

The lifecycle runtime bag prefers focused shared ports where the existing
protocols already match what downstream consumers need. ``container.py``
remains the concrete composition root that instantiates the real adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.adapters.http.dependencies import RouterDeps
from vibesensor.app.config_schema import AppConfig
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_loop import ProcessingLoop
from vibesensor.infra.runtime.processing_state import ProcessingLoopState
from vibesensor.infra.runtime.ws_broadcast import WsBroadcastService
from vibesensor.infra.workers.worker_pool import WorkerPool
from vibesensor.shared.ports import ClientTracker, SettingsReader, SignalSource
from vibesensor.use_cases.run import RunRecorder
from vibesensor.use_cases.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.use_cases.updates.manager import UpdateManager

if TYPE_CHECKING:
    from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
    from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane
    from vibesensor.adapters.websocket.hub import WebSocketHub
    from vibesensor.infra.runtime.lifecycle import LifecycleHistoryDb, LifecycleObdRunner


@dataclass(slots=True)
class RuntimeState:
    """Lifecycle-focused runtime dependencies."""

    config: AppConfig
    registry: ClientTracker
    processor: SignalSource
    control_plane: UDPControlPlane
    worker_pool: WorkerPool
    settings_reader: SettingsReader
    gps_monitor: GPSSpeedMonitor
    obd_runner: LifecycleObdRunner
    history_db: LifecycleHistoryDb
    processing_loop_state: ProcessingLoopState
    health_state: RuntimeHealthState
    processing_loop: ProcessingLoop
    ws_hub: WebSocketHub
    ws_broadcast: WsBroadcastService
    run_recorder: RunRecorder
    update_manager: UpdateManager
    esp_flash_manager: EspFlashManager


@dataclass(slots=True)
class AppRuntime:
    """Top-level app runtime bundle used by bootstrap and CLI entrypoints."""

    lifecycle: RuntimeState
    router: RouterDeps

    @property
    def config(self) -> AppConfig:
        return self.lifecycle.config
