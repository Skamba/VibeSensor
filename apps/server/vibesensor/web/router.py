"""Assemble every HTTP/WebSocket route from the runtime services that back it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import APIRouter

from vibesensor.web.car_library import create_car_library_routes
from vibesensor.web.clients import create_client_routes
from vibesensor.web.health import create_health_routes
from vibesensor.web.history import create_history_routes
from vibesensor.web.recording import create_recording_routes
from vibesensor.web.settings.analysis import create_analysis_settings_routes
from vibesensor.web.settings.cars import create_car_settings_routes
from vibesensor.web.settings.obd import create_obd_admin_routes
from vibesensor.web.settings.preferences import create_ui_preferences_routes
from vibesensor.web.settings.speed_source import create_speed_source_routes
from vibesensor.web.updates import create_update_routes
from vibesensor.web.websocket import create_websocket_routes

if TYPE_CHECKING:
    from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
    from vibesensor.ingest.registry import ClientRegistry
    from vibesensor.ingest.udp_control_tx import UDPControlPlane
    from vibesensor.live.broadcaster import LiveBroadcaster
    from vibesensor.live.processing_loop import ProcessingLoopState
    from vibesensor.live.processor import SignalProcessor
    from vibesensor.recording.recorder import RunRecorder
    from vibesensor.report.service import HistoryReportService
    from vibesensor.settings.analysis_settings import ActiveCarAnalysisSettingsService
    from vibesensor.settings.car_settings import CarSettingsService
    from vibesensor.settings.sensor_settings import SensorSettingsService
    from vibesensor.settings.speed_source_runtime import SpeedSourceSettingsService
    from vibesensor.settings.ui_preferences import UiPreferencesService
    from vibesensor.speed.obd.service import ObdService
    from vibesensor.speed.source_coordinator import SpeedSourceObservationService
    from vibesensor.updates.firmware.esp_flash_manager import EspFlashManager
    from vibesensor.updates.manager import UpdateManager
    from vibesensor.web.health_state import RuntimeHealthState
    from vibesensor.web.history_services import (
        ProjectedHistoryExportService,
        ProjectedHistoryRunService,
    )

__all__ = ["WebServices", "create_router"]


@dataclass(slots=True)
class WebServices:
    """The runtime services the HTTP/WebSocket routes use, built by ``app.composition``."""

    health_state: RuntimeHealthState
    processing_loop_state: ProcessingLoopState
    ingest_diagnostics: IngestDiagnosticsCollector
    registry: ClientRegistry
    control_plane: UDPControlPlane
    processor: SignalProcessor
    run_recorder: RunRecorder
    ws_broadcaster: LiveBroadcaster
    sensor_metadata_store: SensorSettingsService
    car_settings: CarSettingsService
    analysis_settings: ActiveCarAnalysisSettingsService
    ui_preferences: UiPreferencesService
    speed_source_service: SpeedSourceSettingsService
    speed_status_service: SpeedSourceObservationService
    obd_admin_service: ObdService
    run_service: ProjectedHistoryRunService
    report_service: HistoryReportService
    export_service: ProjectedHistoryExportService
    update_manager: UpdateManager
    esp_flash_manager: EspFlashManager


def create_router(services: WebServices) -> APIRouter:
    """Build the application router: health, settings, live, history, and update routes."""
    s = services
    router = APIRouter()
    router.include_router(
        create_health_routes(
            s.processing_loop_state,
            s.health_state,
            s.processor,
            s.registry,
            s.run_recorder,
            s.ingest_diagnostics,
        ),
    )
    router.include_router(create_car_settings_routes(s.car_settings))
    router.include_router(
        create_speed_source_routes(s.speed_source_service, s.speed_status_service),
    )
    router.include_router(
        create_obd_admin_routes(
            s.speed_source_service,
            s.speed_status_service,
            s.obd_admin_service,
        ),
    )
    router.include_router(create_ui_preferences_routes(s.ui_preferences))
    router.include_router(create_analysis_settings_routes(s.analysis_settings))
    router.include_router(create_car_library_routes())
    router.include_router(
        create_client_routes(
            s.registry,
            s.control_plane,
            s.sensor_metadata_store,
            s.processor,
        ),
    )
    router.include_router(create_recording_routes(s.run_recorder))
    router.include_router(create_websocket_routes(s.ws_broadcaster))
    router.include_router(
        create_history_routes(
            run_service=s.run_service,
            report_service=s.report_service,
            export_service=s.export_service,
        ),
    )
    router.include_router(create_update_routes(s.update_manager, s.esp_flash_manager))
    return router
