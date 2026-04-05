from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
from vibesensor.adapters.history import (
    ProjectedHistoryExportService,
    ProjectedHistoryRunService,
)
from vibesensor.adapters.http.dependencies import (
    HistoryDeps,
    RouterDeps,
    SettingsDeps,
    TelemetryDeps,
    UpdateDeps,
)
from vibesensor.adapters.obd import ObdAdminClient, build_obd_runtime
from vibesensor.adapters.persistence.history_db import (
    HistoryPersistenceAdapters,
    create_history_persistence_adapters,
)
from vibesensor.adapters.speed import build_speed_source_services
from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane
from vibesensor.adapters.websocket.hub import WebSocketHub
from vibesensor.app.runtime_state import AppRuntime, RuntimeState
from vibesensor.app.settings import AppConfig
from vibesensor.infra.config.analysis_settings import ActiveCarAnalysisSettingsService
from vibesensor.infra.config.car_settings import CarSettingsService
from vibesensor.infra.config.sensor_settings import SensorSettingsService
from vibesensor.infra.config.settings_derivation import SettingsDerivationService
from vibesensor.infra.config.settings_persistence import SettingsPersistenceCoordinator
from vibesensor.infra.config.speed_source_runtime import (
    SpeedSourceRuntimeApplier,
    SpeedSourceSettingsService,
)
from vibesensor.infra.config.speed_source_settings import PersistedSpeedSourceSettingsService
from vibesensor.infra.config.ui_preferences import UiPreferencesService
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_loop import ProcessingLoop
from vibesensor.infra.runtime.processing_state import ProcessingLoopState
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.infra.runtime.ws_broadcast import WsBroadcastService
from vibesensor.infra.workers.worker_pool import WorkerPool
from vibesensor.shared.boundaries.reporting import PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import ReportDocument
from vibesensor.shared.constants.dsp import (
    FFT_N,
    FFT_UPDATE_HZ,
    SPECTRUM_MAX_HZ,
    SPECTRUM_MIN_HZ,
    WAVEFORM_DISPLAY_HZ,
)
from vibesensor.shared.constants.ui import UI_HEAVY_PUSH_HZ, UI_PUSH_HZ
from vibesensor.shared.ports import (
    AnalysisSettingsStore,
    CarSettingsStore,
    SensorMetadataReader,
    SensorMetadataStore,
    SpeedSourceSettingsReader,
    SpeedSourceSettingsStore,
    UiPreferencesStore,
)
from vibesensor.shared.sensor_units import ADXL345_SCALE_G_PER_LSB, SENSOR_MODEL
from vibesensor.use_cases.history.exports import HistoryExportService
from vibesensor.use_cases.history.reports import HistoryReportService
from vibesensor.use_cases.history.runs import HistoryRunService
from vibesensor.use_cases.run import RunRecorder, RunRecorderConfig
from vibesensor.use_cases.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.use_cases.updates.runtime import build_update_manager

LOGGER = logging.getLogger(__name__)


def _build_pdf_bytes(document: ReportDocument) -> bytes:
    """Render a prepared report document through the PDF adapter boundary."""
    from vibesensor.adapters.pdf.pdf_engine import build_report_pdf

    return build_report_pdf(document)


def _build_prepared_pdf_bytes(prepared: PreparedReportInput) -> bytes:
    """Render a prepared report input through the PDF adapter boundary."""
    from vibesensor.adapters.pdf.pdf_engine import build_prepared_report_pdf

    return build_prepared_report_pdf(prepared)


def resolve_accel_scale_g_per_lsb(config: AppConfig) -> float:
    return config.processing.accel_scale_g_per_lsb or ADXL345_SCALE_G_PER_LSB


def create_history_db(
    config: AppConfig,
    *,
    corruption_reporter: Callable[[str], None] | None = None,
) -> HistoryPersistenceAdapters:
    """Create and initialise the shared history persistence collaborators."""
    history = create_history_persistence_adapters(
        config.logging.history_db_path,
        corruption_reporter=corruption_reporter,
    )
    if history.lifecycle.corruption_detected:
        LOGGER.error(
            "History DB corruption detected at startup; skipping stale-run recovery, "
            "retention pruning, and "
            "continuing with writes disabled until the DB is repaired.",
        )
        return history
    try:
        recovered_runs = history.run_repository.recover_stale_recording_runs()
    except (sqlite3.Error, OSError):
        LOGGER.error("Failed during early startup DB operations; closing DB.", exc_info=True)
        history.lifecycle.close()
        raise
    if recovered_runs:
        LOGGER.warning("Recovered %d stale recording run(s) on startup", recovered_runs)
    try:
        pruned_runs = history.run_repository.prune_terminal_runs_older_than_days(
            config.logging.run_retention_days,
        )
    except (sqlite3.Error, OSError):
        LOGGER.warning(
            "Failed to prune terminal runs older than %d day(s) during startup maintenance",
            config.logging.run_retention_days,
            exc_info=True,
        )
    else:
        if pruned_runs:
            LOGGER.info(
                "Pruned %d terminal run(s) older than %d day(s) during startup maintenance",
                pruned_runs,
                config.logging.run_retention_days,
            )
    return history


def build_runtime(config: AppConfig) -> AppRuntime:
    """Construct all services and return the app runtime bundle."""
    accel_scale_g_per_lsb = resolve_accel_scale_g_per_lsb(config)
    health_state = RuntimeHealthState()

    # DB + settings
    history = create_history_db(
        config,
        corruption_reporter=health_state.mark_db_corrupted,
    )
    history_db = history.run_repository
    history_lifecycle = history.lifecycle
    gps_monitor = GPSSpeedMonitor(gps_enabled=config.gps.gps_enabled)
    obd_admin_client = ObdAdminClient()
    obd_runtime = build_obd_runtime(admin_client=obd_admin_client)
    speed_services = build_speed_source_services(
        gps_monitor=gps_monitor,
        obd_facts=obd_runtime.observation.facts,
        obd_projection=obd_runtime.observation.projection,
        obd_device_admin=obd_admin_client,
        obd_status_refresher=obd_runtime.control.admin,
        obd_control=obd_runtime.control.settings,
    )
    settings_persistence = SettingsPersistenceCoordinator(db=history.settings_snapshot_repository)
    car_settings_service = CarSettingsService(
        lock=settings_persistence.lock,
        state=settings_persistence.car_state,
        update_with_rollback=settings_persistence.update_with_rollback,
    )
    analysis_settings_service = ActiveCarAnalysisSettingsService(
        active_car_aspects=car_settings_service.active_car_aspects,
        update_active_car_aspects=car_settings_service.update_active_car_aspects,
    )
    sensor_metadata_service = SensorSettingsService(
        lock=settings_persistence.lock,
        state=settings_persistence.sensor_state,
        update_with_rollback=settings_persistence.update_with_rollback,
    )
    speed_source_settings_service = PersistedSpeedSourceSettingsService(
        lock=settings_persistence.lock,
        state=settings_persistence.speed_source_state,
        update_with_rollback=settings_persistence.update_with_rollback,
    )
    ui_preferences_service = UiPreferencesService(
        lock=settings_persistence.lock,
        state=settings_persistence.ui_preferences_state,
        update_with_rollback=settings_persistence.update_with_rollback,
    )
    car_settings: CarSettingsStore = car_settings_service
    analysis_settings: AnalysisSettingsStore = analysis_settings_service
    sensor_metadata_store: SensorMetadataStore = sensor_metadata_service
    sensor_metadata_reader: SensorMetadataReader = sensor_metadata_store
    speed_source_store: SpeedSourceSettingsStore = speed_source_settings_service
    speed_source_reader: SpeedSourceSettingsReader = speed_source_store
    ui_preferences: UiPreferencesStore = ui_preferences_service
    settings_reader = SettingsDerivationService(
        active_car_aspects=car_settings_service.active_car_aspects,
        active_car_snapshot=car_settings_service.active_car_snapshot,
    )
    speed_source_service = SpeedSourceSettingsService(
        settings_store=speed_source_store,
        runtime_applier=SpeedSourceRuntimeApplier(
            speed_control=speed_services.control,
        ),
    )

    # persistence services
    history_run_service = HistoryRunService(
        history_db,
    )
    report_service = HistoryReportService(
        history_db,
        pdf_renderer=_build_prepared_pdf_bytes,
    )
    history_export_service = HistoryExportService(
        history_db,
    )
    run_service = ProjectedHistoryRunService(
        history_run_service,
        current_car_reader=settings_reader,
    )
    export_service = ProjectedHistoryExportService(history_export_service)

    # ingress
    registry = ClientRegistry(
        db=history.client_name_repository,
        live_ttl_seconds=config.processing.client_live_ttl_seconds,
        retention_ttl_seconds=config.processing.client_ttl_seconds,
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
    ws_hub = WebSocketHub()
    ws_broadcast = WsBroadcastService(
        ui_push_hz=UI_PUSH_HZ,
        ui_heavy_push_hz=UI_HEAVY_PUSH_HZ,
        registry=registry,
        processor=processor,
        gps_monitor=speed_services.observation,
        gps_enabled=config.gps.gps_enabled,
        settings_reader=settings_reader,
        speed_source_reader=speed_source_reader,
        sensor_metadata_reader=sensor_metadata_reader,
    )

    # run recorder
    run_recorder = RunRecorder(
        RunRecorderConfig(
            metrics_log_hz=config.logging.metrics_log_hz,
            no_data_timeout_s=config.logging.no_data_timeout_s,
            sensor_model=SENSOR_MODEL,
            default_sample_rate_hz=config.processing.sample_rate_hz,
            fft_window_size_samples=FFT_N,
            accel_scale_g_per_lsb=accel_scale_g_per_lsb,
            persist_history_db=config.logging.persist_history_db,
        ),
        registry=registry,
        gps_monitor=speed_services.observation,
        processor=processor,
        history_db=history_db,
        settings_store=settings_reader,
        sensor_metadata_reader=sensor_metadata_reader,
        language_provider=lambda: ui_preferences.language,
    )

    # requeue stale analysis runs
    stale_analyzing = history_db.stale_analyzing_run_ids()
    for stale_run_id in stale_analyzing:
        LOGGER.info("Re-queuing stuck analyzing run %s for re-analysis", stale_run_id)
        run_recorder.schedule_post_analysis(stale_run_id)
    if stale_analyzing:
        LOGGER.info("Re-queued %d stuck analyzing run(s)", len(stale_analyzing))

    # update manager
    update_manager = build_update_manager(
        ap_con_name=config.ap.con_name,
        wifi_ifname=config.ap.ifname,
        rollback_dir=str(config.update.rollback_dir),
    )

    esp_flash_manager = EspFlashManager()

    lifecycle = RuntimeState(
        config=config,
        registry=registry,
        processor=processor,
        control_plane=control_plane,
        worker_pool=worker_pool,
        settings_store=settings_reader,
        gps_monitor=gps_monitor,
        obd_runner=obd_runtime.connection.runner,
        history_db=history_lifecycle,
        processing_loop_state=processing_loop_state,
        health_state=health_state,
        processing_loop=processing_loop,
        ws_hub=ws_hub,
        ws_broadcast=ws_broadcast,
        run_recorder=run_recorder,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
    )
    router = RouterDeps(
        telemetry=TelemetryDeps(
            processing_loop_state=processing_loop_state,
            health_state=health_state,
            processor=processor,
            registry=registry,
            control_plane=control_plane,
            run_recorder=run_recorder,
            ws_hub=ws_hub,
        ),
        settings=SettingsDeps(
            car_settings=car_settings,
            analysis_settings=analysis_settings,
            sensor_metadata_store=sensor_metadata_store,
            ui_preferences=ui_preferences,
            speed_source_service=speed_source_service,
            speed_status_service=speed_services.observation,
            obd_admin_service=speed_services.admin,
        ),
        history=HistoryDeps(
            run_service=run_service,
            report_service=report_service,
            export_service=export_service,
        ),
        updates=UpdateDeps(
            update_manager=update_manager,
            esp_flash_manager=esp_flash_manager,
        ),
    )
    speed_source_service.sync_all()
    return AppRuntime(lifecycle=lifecycle, router=router)
