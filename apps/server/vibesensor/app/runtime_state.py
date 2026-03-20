"""App-owned runtime assembly for lifecycle and router dependency bundles.

The lifecycle runtime bag prefers focused shared ports where the existing
protocols already match what downstream consumers need. ``container.py``
remains the concrete composition root that instantiates the real adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.adapters.http.dependencies import RouterDeps
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_loop import ProcessingLoop, ProcessingLoopState
from vibesensor.infra.runtime.ws_broadcast import WsBroadcastService
from vibesensor.infra.workers.worker_pool import WorkerPool
from vibesensor.shared.types.client_tracker import ClientTracker
from vibesensor.shared.types.settings_reader import SettingsReader
from vibesensor.shared.types.signal_source import SignalSource
from vibesensor.use_cases.run import RunRecorder
from vibesensor.use_cases.updates.esp_flash_manager import EspFlashManager
from vibesensor.use_cases.updates.manager import UpdateManager

if TYPE_CHECKING:
    from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
    from vibesensor.adapters.persistence.history_db import HistoryDB
    from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane
    from vibesensor.adapters.websocket.hub import WebSocketHub
    from vibesensor.app.settings import AppConfig


@dataclass(slots=True)
class RuntimeState:
    """Lifecycle-focused runtime dependencies."""

    config: AppConfig
    registry: ClientTracker
    processor: SignalSource
    control_plane: UDPControlPlane
    worker_pool: WorkerPool
    settings_store: SettingsReader
    gps_monitor: GPSSpeedMonitor
    history_db: HistoryDB
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
