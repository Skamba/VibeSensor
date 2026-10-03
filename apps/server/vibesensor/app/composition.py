"""Composition root: build every runtime service from the loaded config.

``build_runtime()`` is the one place that wires concrete services together.
It returns the services the lifecycle manager starts/stops and the services
the HTTP/WebSocket routes use; both share the same instances.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from vibesensor.app.config_schema import AppConfig
from vibesensor.app.lifecycle import LifecycleRuntime
from vibesensor.dsp.constants import (
    FFT_N,
    FFT_UPDATE_HZ,
    SAMPLE_RATE_HZ,
    SPECTRUM_MAX_HZ,
    SPECTRUM_MIN_HZ,
    WAVEFORM_BUFFER_SECONDS,
    WAVEFORM_DISPLAY_HZ,
)
from vibesensor.history.exports import HistoryExportService
from vibesensor.history.history_db import HistoryDB
from vibesensor.history.runs import HistoryRunService
from vibesensor.hotspot.constants import HOTSPOT_CON_NAME, HOTSPOT_IFNAME
from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.ingest.registry import ClientRegistry
from vibesensor.ingest.sensor_units import ADXL345_SCALE_G_PER_LSB, SENSOR_MODEL
from vibesensor.ingest.udp_control_tx import UDPControlPlane
from vibesensor.live.broadcaster import LiveBroadcaster
from vibesensor.live.processing_loop import ProcessingLoop, ProcessingLoopState
from vibesensor.live.processor import SignalProcessor
from vibesensor.live.ui_constants import UI_HEAVY_PUSH_HZ, UI_PUSH_HZ
from vibesensor.live.ws_payload_projection import LiveWsPayloadProjector
from vibesensor.recording._recorder_types import RunRecorderConfig
from vibesensor.recording.recorder import RunRecorder
from vibesensor.report.service import HistoryReportService
from vibesensor.report.view_model import ReportView
from vibesensor.settings.services import build_settings_services
from vibesensor.speed.gps_speed import GPSSpeedMonitor
from vibesensor.speed.obd.service import ObdService
from vibesensor.speed.source_coordinator import build_speed_source_services
from vibesensor.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.updates.runtime import build_update_manager
from vibesensor.web.health_state import RuntimeHealthState
from vibesensor.web.history_services import (
    ProjectedHistoryExportService,
    ProjectedHistoryRunService,
)
from vibesensor.web.router import WebServices

LOGGER = logging.getLogger(__name__)

RUN_RETENTION_DAYS = 7
"""Terminal runs (and their raw-capture sidecars) older than this are pruned at startup."""


@dataclass(slots=True)
class AppRuntime:
    """Everything ``create_app()`` needs: lifecycle-managed services plus the route services."""

    lifecycle: LifecycleRuntime
    web: WebServices


def _render_report_pdf(view: ReportView) -> bytes:
    """Render a report view to PDF (reportlab is imported on first use)."""
    from vibesensor.report.pdf import render_report_pdf

    return render_report_pdf(view)


def create_history_db(
    config: AppConfig,
    *,
    corruption_reporter: Callable[[str], None] | None = None,
) -> HistoryDB:
    """Open the history DB and run startup recovery plus retention pruning."""
    history = HistoryDB(
        config.logging.history_db_path,
        corruption_reporter=corruption_reporter,
    )
    if history.corruption_detected:
        LOGGER.error(
            "History DB corruption detected at startup; skipping stale-run recovery, "
            "retention pruning, and "
            "continuing with writes disabled until the DB is repaired.",
        )
        return history
    try:
        recovered_runs = history.recover_stale_recording_runs()
    except (sqlite3.Error, OSError):
        LOGGER.error("Failed during early startup DB operations; closing DB.", exc_info=True)
        history.close()
        raise
    if recovered_runs:
        LOGGER.warning("Recovered %d stale recording run(s) on startup", recovered_runs)
    try:
        pruned_runs = history.prune_terminal_runs_older_than_days(
            RUN_RETENTION_DAYS,
        )
    except (sqlite3.Error, OSError):
        LOGGER.warning(
            "Failed to prune terminal runs older than %d day(s) during startup maintenance",
            RUN_RETENTION_DAYS,
            exc_info=True,
        )
    else:
        if pruned_runs:
            LOGGER.info(
                "Pruned %d terminal run(s) older than %d day(s) during startup maintenance",
                pruned_runs,
                RUN_RETENTION_DAYS,
            )
    return history


def build_runtime(config: AppConfig) -> AppRuntime:
    """Construct all services and return the lifecycle and route services."""
    health_state = RuntimeHealthState()
    history = create_history_db(
        config,
        corruption_reporter=health_state.mark_db_corrupted,
    )

    # Speed sources (GPS, OBD) and the selected-source coordination.
    gps_monitor = GPSSpeedMonitor(gps_enabled=config.gps.gps_enabled)
    obd = ObdService()
    speed_services = build_speed_source_services(gps_monitor=gps_monitor, obd=obd)

    settings = build_settings_services(history, speed_control=speed_services.control)

    # Live ingest, processing, broadcast, and recording.
    registry = ClientRegistry(db=history)
    processor = SignalProcessor(
        sample_rate_hz=SAMPLE_RATE_HZ,
        waveform_seconds=WAVEFORM_BUFFER_SECONDS,
        waveform_display_hz=WAVEFORM_DISPLAY_HZ,
        fft_n=FFT_N,
        spectrum_min_hz=SPECTRUM_MIN_HZ,
        spectrum_max_hz=SPECTRUM_MAX_HZ,
        accel_scale_g_per_lsb=ADXL345_SCALE_G_PER_LSB,
    )
    control_plane = UDPControlPlane(
        registry=registry,
        bind_host=config.udp.control_host,
        bind_port=config.udp.control_port,
    )
    processing_loop_state = ProcessingLoopState()
    processing_loop = ProcessingLoop(
        state=processing_loop_state,
        fft_update_hz=FFT_UPDATE_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
        fft_n=FFT_N,
        registry=registry,
        processor=processor,
        control_plane=control_plane,
    )
    ingest_diagnostics = IngestDiagnosticsCollector()
    ws_broadcaster = LiveBroadcaster(
        payload_source=LiveWsPayloadProjector(
            registry=registry,
            processor=processor,
            gps_monitor=speed_services.observation,
            gps_enabled=config.gps.gps_enabled,
            settings_reader=settings.settings_reader,
            speed_source_reader=settings.speed_source_settings,
            sensor_metadata_reader=settings.sensor_settings,
        ),
        ingest_diagnostics=ingest_diagnostics,
        push_hz=UI_PUSH_HZ,
        heavy_push_hz=UI_HEAVY_PUSH_HZ,
    )
    run_recorder = RunRecorder(
        RunRecorderConfig(
            sensor_model=SENSOR_MODEL,
            default_sample_rate_hz=SAMPLE_RATE_HZ,
            fft_window_size_samples=FFT_N,
            accel_scale_g_per_lsb=ADXL345_SCALE_G_PER_LSB,
        ),
        registry=registry,
        gps_monitor=speed_services.observation,
        processor=processor,
        history_db=history,
        settings_reader=settings.settings_reader,
        sensor_metadata_reader=settings.sensor_settings,
        language_reader=settings.ui_preferences,
        ingest_diagnostics=ingest_diagnostics,
    )
    outdated = history.requeue_outdated_analyses()
    if outdated:
        LOGGER.info("Re-analysing %d run(s) stored under an older analysis schema", len(outdated))
    stale_analyzing = history.stale_analyzing_run_ids()
    for stale_run_id in stale_analyzing:
        LOGGER.info("Re-queuing stuck analyzing run %s for re-analysis", stale_run_id)
        run_recorder.post_analysis.schedule(stale_run_id)
    if stale_analyzing:
        LOGGER.info("Re-queued %d stuck analyzing run(s)", len(stale_analyzing))

    update_manager = build_update_manager(
        ap_con_name=HOTSPOT_CON_NAME,
        wifi_ifname=HOTSPOT_IFNAME,
        server_port=config.server.port,
    )
    esp_flash_manager = EspFlashManager()

    lifecycle = LifecycleRuntime(
        health_state=health_state,
        history_db_path=config.logging.history_db_path,
        udp_data_host=config.udp.data_host,
        udp_data_port=config.udp.data_port,
        registry=registry,
        processor=processor,
        ingest_diagnostics=ingest_diagnostics,
        control_plane=control_plane,
        processing_loop=processing_loop,
        ws_broadcaster=ws_broadcaster,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        obd_runner=obd,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
        history_db=history,
    )
    web = WebServices(
        health_state=health_state,
        processing_loop_state=processing_loop_state,
        ingest_diagnostics=ingest_diagnostics,
        registry=registry,
        control_plane=control_plane,
        processor=processor,
        run_recorder=run_recorder,
        ws_broadcaster=ws_broadcaster,
        sensor_metadata_store=settings.sensor_settings,
        car_settings=settings.car_settings,
        analysis_settings=settings.analysis_settings,
        ui_preferences=settings.ui_preferences,
        speed_source_service=settings.speed_source_service,
        speed_status_service=speed_services.observation,
        obd_admin_service=obd,
        run_service=ProjectedHistoryRunService(
            HistoryRunService(history),
            current_car_reader=settings.settings_reader,
        ),
        report_service=HistoryReportService(history, pdf_renderer=_render_report_pdf),
        export_service=ProjectedHistoryExportService(HistoryExportService(history)),
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
    )
    settings.speed_source_service.sync_all()
    return AppRuntime(lifecycle=lifecycle, web=web)
