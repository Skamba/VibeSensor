from __future__ import annotations

import logging
from typing import cast

from vibesensor.sensor_units import get_accel_scale_g_per_lsb

from ..analysis_settings import AnalysisSettingsStore
from ..config import AppConfig
from ..constants import (
    FFT_N,
    FFT_UPDATE_HZ,
    SPECTRUM_MAX_HZ,
    SPECTRUM_MIN_HZ,
    UI_HEAVY_PUSH_HZ,
    UI_PUSH_HZ,
    WAVEFORM_DISPLAY_HZ,
)
from ..esp_flash_manager import EspFlashManager
from ..gps_speed import GPSSpeedMonitor
from ..history_db import HistoryDB
from ..history_services.exports import HistoryExportService
from ..history_services.reports import HistoryReportService
from ..history_services.runs import HistoryRunService
from ..metrics_log import MetricsLogger, MetricsLoggerConfig
from ..processing import SignalProcessor
from ..registry import ClientRegistry
from ..settings_store import SettingsStore
from ..udp_control_tx import UDPControlPlane
from ..update.manager import UpdateManager
from ..worker_pool import WorkerPool
from ..ws_hub import WebSocketHub
from .health_state import RuntimeHealthState
from .lifecycle import LifecycleManager
from .processing_loop import ProcessingLoop, ProcessingLoopState
from .state import RuntimeState
from .ws_broadcast import WsBroadcastCache, WsBroadcastService

LOGGER = logging.getLogger(__name__)


def resolve_accel_scale_g_per_lsb(config: AppConfig) -> float:
    return cast(
        "float",
        (
            config.processing.accel_scale_g_per_lsb
            if config.processing.accel_scale_g_per_lsb is not None
            else get_accel_scale_g_per_lsb(config.logging.sensor_model)
        ),
    )


def create_history_db(config: AppConfig) -> HistoryDB:
    """Create and initialise the HistoryDB, recovering any stale runs."""
    history_db = HistoryDB(config.logging.history_db_path)
    try:
        recovered_runs = history_db.recover_stale_recording_runs()
    except Exception:
        LOGGER.error("Failed during early startup DB operations; closing DB.", exc_info=True)
        history_db.close()
        raise
    if recovered_runs:
        LOGGER.warning("Recovered %d stale recording run(s) on startup", recovered_runs)
    return history_db


def build_runtime(config: AppConfig) -> RuntimeState:
    """Construct all services and return a wired RuntimeState."""
    accel_scale_g_per_lsb = resolve_accel_scale_g_per_lsb(config)

    # DB + settings
    history_db = create_history_db(config)
    settings_store = SettingsStore(db=history_db)
    analysis_settings = AnalysisSettingsStore()
    gps_monitor = GPSSpeedMonitor(gps_enabled=config.gps.gps_enabled)

    # persistence services
    run_service = HistoryRunService(history_db, settings_store)
    report_service = HistoryReportService(history_db, settings_store)
    export_service = HistoryExportService(history_db)

    # ingress
    registry = ClientRegistry(
        db=history_db,
        stale_ttl_seconds=config.processing.client_ttl_seconds,
    )
    worker_pool = WorkerPool(max_workers=4, thread_name_prefix="vibesensor-fft")
    processor = SignalProcessor(
        sample_rate_hz=config.processing.sample_rate_hz,
        waveform_seconds=config.processing.waveform_seconds,
        waveform_display_hz=WAVEFORM_DISPLAY_HZ,
        fft_n=FFT_N,
        spectrum_min_hz=SPECTRUM_MIN_HZ,
        spectrum_max_hz=SPECTRUM_MAX_HZ,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        worker_pool=worker_pool,
    )
    control_plane = UDPControlPlane(
        registry=registry,
        bind_host=config.udp.control_host,
        bind_port=config.udp.control_port,
    )

    # processing loop
    processing_loop_state = ProcessingLoopState()
    health_state = RuntimeHealthState()
    processing_loop = ProcessingLoop(
        state=processing_loop_state,
        fft_update_hz=FFT_UPDATE_HZ,
        sample_rate_hz=config.processing.sample_rate_hz,
        fft_n=FFT_N,
        registry=registry,
        processor=processor,
        control_plane=control_plane,
    )

    # websocket
    ws_cache = WsBroadcastCache()
    ws_hub = WebSocketHub()
    ws_broadcast = WsBroadcastService(
        cache=ws_cache,
        ui_push_hz=UI_PUSH_HZ,
        ui_heavy_push_hz=UI_HEAVY_PUSH_HZ,
        registry=registry,
        processor=processor,
        gps_monitor=gps_monitor,
        analysis_settings=analysis_settings,
        settings_store=settings_store,
    )

    # metrics logger
    metrics_logger = MetricsLogger(
        MetricsLoggerConfig(
            enabled=config.logging.log_metrics,
            metrics_log_hz=config.logging.metrics_log_hz,
            no_data_timeout_s=config.logging.no_data_timeout_s,
            sensor_model=config.logging.sensor_model,
            default_sample_rate_hz=config.processing.sample_rate_hz,
            fft_window_size_samples=FFT_N,
            fft_window_type="hann",
            peak_picker_method="canonical_strength_metrics_module",
            accel_scale_g_per_lsb=accel_scale_g_per_lsb,
            persist_history_db=config.logging.persist_history_db,
        ),
        registry=registry,
        gps_monitor=gps_monitor,
        processor=processor,
        analysis_settings=analysis_settings,
        history_db=history_db,
        settings_store=settings_store,
        language_provider=lambda: settings_store.language,
    )

    # requeue stale analysis runs
    stale_analyzing = history_db.stale_analyzing_run_ids()
    for stale_run_id in stale_analyzing:
        LOGGER.info("Re-queuing stuck analyzing run %s for re-analysis", stale_run_id)
        metrics_logger.schedule_post_analysis(stale_run_id)
    if stale_analyzing:
        LOGGER.info("Re-queued %d stuck analyzing run(s)", len(stale_analyzing))

    # update manager
    update_manager = UpdateManager(
        ap_con_name=config.ap.con_name,
        wifi_ifname=config.ap.ifname,
        rollback_dir=str(config.update.rollback_dir),
    )

    runtime = RuntimeState(
        config=config,
        registry=registry,
        processor=processor,
        control_plane=control_plane,
        worker_pool=worker_pool,
        settings_store=settings_store,
        analysis_settings=analysis_settings,
        gps_monitor=gps_monitor,
        history_db=history_db,
        run_service=run_service,
        report_service=report_service,
        export_service=export_service,
        processing_loop_state=processing_loop_state,
        health_state=health_state,
        processing_loop=processing_loop,
        ws_hub=ws_hub,
        ws_broadcast=ws_broadcast,
        metrics_logger=metrics_logger,
        update_manager=update_manager,
        esp_flash_manager=EspFlashManager(),
    )
    runtime.lifecycle = LifecycleManager(runtime=runtime)
    runtime.apply_car_settings()
    runtime.apply_speed_source_settings()
    return runtime
