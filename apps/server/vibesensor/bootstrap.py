"""Service construction and wiring.

Builds all runtime services from an ``AppConfig`` and returns a fully
wired ``RuntimeState`` ready for ``start()``.
"""

from __future__ import annotations

import logging

from vibesensor_core.sensor_units import get_accel_scale_g_per_lsb

from .analysis_settings import AnalysisSettingsStore
from .config import AppConfig
from .esp_flash_manager import EspFlashManager
from .gps_speed import GPSSpeedMonitor
from .history_db import HistoryDB
from .live_diagnostics.engine import LiveDiagnosticsEngine
from .metrics_log import MetricsLogger, MetricsLoggerConfig
from .processing import SignalProcessor
from .registry import ClientRegistry
from .runtime import RuntimeState
from .settings_store import SettingsStore
from .udp_control_tx import UDPControlPlane
from .update.manager import UpdateManager
from .worker_pool import WorkerPool
from .ws_hub import WebSocketHub

LOGGER = logging.getLogger(__name__)


def build_services(config: AppConfig) -> RuntimeState:
    """Construct all services and return a wired RuntimeState."""
    history_db = HistoryDB(config.logging.history_db_path)
    try:
        recovered_runs = history_db.recover_stale_recording_runs()
    except Exception:
        LOGGER.error("Failed during early startup DB operations; closing DB.", exc_info=True)
        history_db.close()
        raise
    if recovered_runs:
        LOGGER.warning("Recovered %d stale recording run(s) on startup", recovered_runs)

    registry = ClientRegistry(
        db=history_db,
        stale_ttl_seconds=config.processing.client_ttl_seconds,
    )
    accel_scale_g_per_lsb = (
        config.processing.accel_scale_g_per_lsb
        if config.processing.accel_scale_g_per_lsb is not None
        else get_accel_scale_g_per_lsb(config.logging.sensor_model)
    )
    worker_pool = WorkerPool(max_workers=4, thread_name_prefix="vibesensor-fft")
    processor = SignalProcessor(
        sample_rate_hz=config.processing.sample_rate_hz,
        waveform_seconds=config.processing.waveform_seconds,
        waveform_display_hz=config.processing.waveform_display_hz,
        fft_n=config.processing.fft_n,
        spectrum_min_hz=config.processing.spectrum_min_hz,
        spectrum_max_hz=config.processing.spectrum_max_hz,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        worker_pool=worker_pool,
    )
    ws_hub = WebSocketHub()
    control_plane = UDPControlPlane(
        registry=registry,
        bind_host=config.udp.control_host,
        bind_port=config.udp.control_port,
    )
    gps_monitor = GPSSpeedMonitor(gps_enabled=config.gps.gps_enabled)
    analysis_settings = AnalysisSettingsStore()
    settings_store = SettingsStore(db=history_db)
    metrics_logger = MetricsLogger(
        MetricsLoggerConfig(
            enabled=config.logging.log_metrics,
            log_path=config.logging.metrics_log_path,
            metrics_log_hz=config.logging.metrics_log_hz,
            no_data_timeout_s=config.logging.no_data_timeout_s,
            sensor_model=config.logging.sensor_model,
            default_sample_rate_hz=config.processing.sample_rate_hz,
            fft_window_size_samples=config.processing.fft_n,
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
        language_provider=lambda: settings_store.language,
    )

    # Re-queue runs stuck in 'analyzing' state (e.g. after a crash)
    stale_analyzing = history_db.stale_analyzing_run_ids()
    for stale_run_id in stale_analyzing:
        LOGGER.info("Re-queuing stuck analyzing run %s for re-analysis", stale_run_id)
        metrics_logger.schedule_post_analysis(stale_run_id)
    if stale_analyzing:
        LOGGER.info("Re-queued %d stuck analyzing run(s)", len(stale_analyzing))

    live_diagnostics = LiveDiagnosticsEngine()
    update_manager = UpdateManager(
        ap_con_name=config.ap.con_name,
        wifi_ifname=config.ap.ifname,
        rollback_dir=str(config.update.rollback_dir),
        server_repo=config.update.server_repo,
    )
    esp_flash_manager = EspFlashManager()

    runtime = RuntimeState(
        config=config,
        registry=registry,
        processor=processor,
        control_plane=control_plane,
        ws_hub=ws_hub,
        gps_monitor=gps_monitor,
        analysis_settings=analysis_settings,
        metrics_logger=metrics_logger,
        live_diagnostics=live_diagnostics,
        settings_store=settings_store,
        history_db=history_db,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
        worker_pool=worker_pool,
    )
    # Sync initial settings into analysis store and GPS monitor
    runtime.apply_car_settings()
    runtime.apply_speed_source_settings()

    return runtime
