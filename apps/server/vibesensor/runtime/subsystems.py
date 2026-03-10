from __future__ import annotations

from dataclasses import dataclass

from ..analysis_settings import AnalysisSettingsStore
from ..gps_speed import GPSSpeedMonitor
from ..history_db import HistoryDB
from ..history_services.exports import HistoryExportService
from ..history_services.reports import HistoryReportService
from ..history_services.runs import HistoryRunDeleteService, HistoryRunQueryService
from ..processing import SignalProcessor
from ..registry import ClientRegistry
from ..settings_store import SettingsStore
from ..udp_control_tx import UDPControlPlane
from ..worker_pool import WorkerPool
from ..ws_hub import WebSocketHub
from .health_state import RuntimeHealthState
from .processing_loop import ProcessingLoop, ProcessingLoopState
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
        aspects = self.settings_store.active_car_aspects()
        if aspects:
            self.analysis_settings.update(aspects)

    def apply_speed_source_settings(self) -> None:
        ss = self.settings_store.get_speed_source()
        self.gps_monitor.set_manual_source_selected(ss["speedSource"] == "manual")
        if ss["manualSpeedKph"] is not None:
            self.gps_monitor.set_speed_override_kmh(ss["manualSpeedKph"])
        else:
            self.gps_monitor.set_speed_override_kmh(None)
        self.gps_monitor.set_fallback_settings(
            stale_timeout_s=ss.get("staleTimeoutS"),
            fallback_mode=ss.get("fallbackMode"),
        )


@dataclass(slots=True)
class RuntimePersistenceSubsystem:
    history_db: HistoryDB
    query_service: HistoryRunQueryService
    delete_service: HistoryRunDeleteService
    report_service: HistoryReportService
    export_service: HistoryExportService


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
