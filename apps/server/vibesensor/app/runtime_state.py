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
from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector
from vibesensor.shared.ports import ClientTracker, SettingsReader, SignalSource
from vibesensor.use_cases.run import RunRecorder
from vibesensor.use_cases.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.use_cases.updates.manager import UpdateManager

if TYPE_CHECKING:
    from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
    from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane
    from vibesensor.adapters.websocket.hub import WebSocketHub
    from vibesensor.infra.runtime.lifecycle import (
        LifecycleHistoryDb,
        LifecycleObdRunner,
        LifecycleRuntime,
    )


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
    ingest_diagnostics: IngestDiagnosticsCollector
    processing_loop: ProcessingLoop
    ws_hub: WebSocketHub
    ws_broadcast: WsBroadcastService
    run_recorder: RunRecorder
    update_manager: UpdateManager
    esp_flash_manager: EspFlashManager

    def lifecycle_runtime(self) -> LifecycleRuntime:
        """Project the lifecycle-owned dependency bag for LifecycleManager."""

        from vibesensor.infra.runtime.lifecycle import LifecycleRuntime

        return LifecycleRuntime(
            health_state=self.health_state,
            history_db_path=self.config.logging.history_db_path,
            udp_data_host=self.config.udp.data_host,
            udp_data_port=self.config.udp.data_port,
            udp_data_queue_maxsize=self.config.udp.data_queue_maxsize,
            gpsd_host=self.config.gps.gpsd_host,
            gpsd_port=self.config.gps.gpsd_port,
            shutdown_analysis_timeout_s=self.config.logging.shutdown_analysis_timeout_s,
            registry=self.registry,
            processor=self.processor,
            ingest_diagnostics=self.ingest_diagnostics,
            control_plane=self.control_plane,
            processing_loop=self.processing_loop,
            ws_hub=self.ws_hub,
            ws_broadcast=self.ws_broadcast,
            run_recorder=self.run_recorder,
            gps_monitor=self.gps_monitor,
            obd_runner=self.obd_runner,
            update_manager=self.update_manager,
            esp_flash_manager=self.esp_flash_manager,
            worker_pool=self.worker_pool,
            history_db=self.history_db,
        )


@dataclass(slots=True)
class AppRuntime:
    """Top-level app runtime bundle used by bootstrap and CLI entrypoints."""

    lifecycle: RuntimeState
    router: RouterDeps

    @property
    def config(self) -> AppConfig:
        return self.lifecycle.config
