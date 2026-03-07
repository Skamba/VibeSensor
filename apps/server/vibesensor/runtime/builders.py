from __future__ import annotations

import logging
from typing import cast

from vibesensor_core.sensor_units import get_accel_scale_g_per_lsb

from ..analysis_settings import AnalysisSettingsStore
from ..config import AppConfig
from ..esp_flash_manager import EspFlashManager
from ..gps_speed import GPSSpeedMonitor
from ..history_db import HistoryDB
from ..live_diagnostics.engine import LiveDiagnosticsEngine
from ..metrics_log import MetricsLogger, MetricsLoggerConfig
from ..processing import SignalProcessor
from ..registry import ClientRegistry
from ..settings_store import SettingsStore
from ..udp_control_tx import UDPControlPlane
from ..update.manager import UpdateManager
from ..worker_pool import WorkerPool
from ..ws_hub import WebSocketHub
from .lifecycle import LifecycleManager
from .processing_loop import ProcessingLoop, ProcessingLoopState
from .subsystems import (
    RuntimeDiagnosticsSubsystem,
    RuntimeIngressSubsystem,
    RuntimePersistenceSubsystem,
    RuntimeProcessingSubsystem,
    RuntimeRouteServices,
    RuntimeSettingsSubsystem,
    RuntimeUpdateSubsystem,
    RuntimeWebsocketSubsystem,
)
from .ws_broadcast import WsBroadcastCache, WsBroadcastService

LOGGER = logging.getLogger(__name__)


def resolve_accel_scale_g_per_lsb(config: AppConfig) -> float:
    return cast(
        float,
        (
            config.processing.accel_scale_g_per_lsb
            if config.processing.accel_scale_g_per_lsb is not None
            else get_accel_scale_g_per_lsb(config.logging.sensor_model)
        ),
    )


def build_persistence_subsystem(*, config: AppConfig) -> RuntimePersistenceSubsystem:
    history_db = HistoryDB(config.logging.history_db_path)
    try:
        recovered_runs = history_db.recover_stale_recording_runs()
    except Exception:
        LOGGER.error("Failed during early startup DB operations; closing DB.", exc_info=True)
        history_db.close()
        raise
    if recovered_runs:
        LOGGER.warning("Recovered %d stale recording run(s) on startup", recovered_runs)
    return RuntimePersistenceSubsystem(history_db=history_db)


def build_ingress_subsystem(
    *,
    config: AppConfig,
    persistence: RuntimePersistenceSubsystem,
    accel_scale_g_per_lsb: float,
) -> RuntimeIngressSubsystem:
    registry = ClientRegistry(
        db=persistence.history_db,
        stale_ttl_seconds=config.processing.client_ttl_seconds,
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
    control_plane = UDPControlPlane(
        registry=registry,
        bind_host=config.udp.control_host,
        bind_port=config.udp.control_port,
    )
    return RuntimeIngressSubsystem(
        registry=registry,
        processor=processor,
        control_plane=control_plane,
        worker_pool=worker_pool,
    )


def build_settings_subsystem(
    *,
    persistence: RuntimePersistenceSubsystem,
    gps_enabled: bool,
) -> RuntimeSettingsSubsystem:
    return RuntimeSettingsSubsystem(
        settings_store=SettingsStore(db=persistence.history_db),
        analysis_settings=AnalysisSettingsStore(),
        gps_monitor=GPSSpeedMonitor(gps_enabled=gps_enabled),
    )


def build_diagnostics_subsystem(
    *,
    config: AppConfig,
    ingress: RuntimeIngressSubsystem,
    settings: RuntimeSettingsSubsystem,
    persistence: RuntimePersistenceSubsystem,
    accel_scale_g_per_lsb: float,
) -> RuntimeDiagnosticsSubsystem:
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
        registry=ingress.registry,
        gps_monitor=settings.gps_monitor,
        processor=ingress.processor,
        analysis_settings=settings.analysis_settings,
        history_db=persistence.history_db,
        language_provider=lambda: settings.settings_store.language,
    )
    diagnostics = RuntimeDiagnosticsSubsystem(
        metrics_logger=metrics_logger,
        live_diagnostics=LiveDiagnosticsEngine(),
    )
    requeue_stale_analysis_runs(
        persistence=persistence,
        diagnostics=diagnostics,
    )
    return diagnostics


def build_update_subsystem(*, config: AppConfig) -> RuntimeUpdateSubsystem:
    return RuntimeUpdateSubsystem(
        update_manager=UpdateManager(
            ap_con_name=config.ap.con_name,
            wifi_ifname=config.ap.ifname,
            rollback_dir=str(config.update.rollback_dir),
            server_repo=config.update.server_repo,
        ),
        esp_flash_manager=EspFlashManager(),
    )


def build_processing_subsystem(
    *,
    config: AppConfig,
    ingress: RuntimeIngressSubsystem,
) -> RuntimeProcessingSubsystem:
    state = ProcessingLoopState()
    loop = ProcessingLoop(
        state=state,
        fft_update_hz=config.processing.fft_update_hz,
        sample_rate_hz=config.processing.sample_rate_hz,
        fft_n=config.processing.fft_n,
        ingress=ingress,
    )
    return RuntimeProcessingSubsystem(state=state, loop=loop)


def build_websocket_subsystem(
    *,
    config: AppConfig,
    ingress: RuntimeIngressSubsystem,
    settings: RuntimeSettingsSubsystem,
    diagnostics: RuntimeDiagnosticsSubsystem,
) -> RuntimeWebsocketSubsystem:
    cache = WsBroadcastCache()
    hub = WebSocketHub()
    broadcast = WsBroadcastService(
        cache=cache,
        ui_push_hz=config.processing.ui_push_hz,
        ui_heavy_push_hz=config.processing.ui_heavy_push_hz,
        ingress=ingress,
        settings=settings,
        diagnostics=diagnostics,
    )
    return RuntimeWebsocketSubsystem(hub=hub, cache=cache, broadcast=broadcast)


def build_route_services(
    *,
    ingress: RuntimeIngressSubsystem,
    settings: RuntimeSettingsSubsystem,
    diagnostics: RuntimeDiagnosticsSubsystem,
    persistence: RuntimePersistenceSubsystem,
    updates: RuntimeUpdateSubsystem,
    processing: RuntimeProcessingSubsystem,
    websocket: RuntimeWebsocketSubsystem,
) -> RuntimeRouteServices:
    return RuntimeRouteServices(
        ingress=ingress,
        settings=settings,
        diagnostics=diagnostics,
        persistence=persistence,
        updates=updates,
        processing=processing,
        websocket=websocket,
    )


def build_lifecycle_manager(
    *,
    config: AppConfig,
    ingress: RuntimeIngressSubsystem,
    settings: RuntimeSettingsSubsystem,
    diagnostics: RuntimeDiagnosticsSubsystem,
    persistence: RuntimePersistenceSubsystem,
    updates: RuntimeUpdateSubsystem,
    processing: RuntimeProcessingSubsystem,
    websocket: RuntimeWebsocketSubsystem,
) -> LifecycleManager:
    return LifecycleManager(
        config=config,
        ingress=ingress,
        settings=settings,
        diagnostics=diagnostics,
        persistence=persistence,
        updates=updates,
        processing=processing,
        websocket=websocket,
    )


def requeue_stale_analysis_runs(
    *,
    persistence: RuntimePersistenceSubsystem,
    diagnostics: RuntimeDiagnosticsSubsystem,
) -> None:
    stale_analyzing = persistence.history_db.stale_analyzing_run_ids()
    for stale_run_id in stale_analyzing:
        LOGGER.info("Re-queuing stuck analyzing run %s for re-analysis", stale_run_id)
        diagnostics.metrics_logger.schedule_post_analysis(stale_run_id)
    if stale_analyzing:
        LOGGER.info("Re-queued %d stuck analyzing run(s)", len(stale_analyzing))