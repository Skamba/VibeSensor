from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import aiosqlite

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
from vibesensor.adapters.history import (
    ProjectedHistoryExportService,
    ProjectedHistoryRunService,
)
from vibesensor.adapters.http.dependencies import (
    HealthDeps,
    HistoryDeps,
    HistoryExportServiceProtocol,
    HistoryReportServiceProtocol,
    HistoryRunServiceProtocol,
    LiveDeps,
    ObdAdminServiceProtocol,
    RouterDeps,
    SettingsDeps,
    SettingsSpeedServiceProtocol,
    UpdateDeps,
)
from vibesensor.adapters.obd import ObdAdminClient, ObdRuntime, build_obd_runtime
from vibesensor.adapters.persistence.history_db import (
    HistoryPersistenceAdapters,
    create_history_persistence_adapters,
)
from vibesensor.adapters.speed import SpeedSourceServices, build_speed_source_services
from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane
from vibesensor.adapters.websocket.hub import WebSocketHub
from vibesensor.app.config_schema import AppConfig
from vibesensor.app.runtime_state import AppRuntime, RuntimeState
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
from vibesensor.infra.runtime.ws_payload_projection import LiveWsPayloadProjector
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
    LanguageReader,
    SensorMetadataReader,
    SensorMetadataStore,
    SettingsReader,
    SettingsSnapshotPersistence,
    SpeedSourceSettingsReader,
    SpeedSourceSync,
)
from vibesensor.shared.sensor_units import ADXL345_SCALE_G_PER_LSB, SENSOR_MODEL
from vibesensor.use_cases.history.exports import HistoryExportService
from vibesensor.use_cases.history.reports import HistoryReportService
from vibesensor.use_cases.history.runs import HistoryRunService
from vibesensor.use_cases.run import RunRecorder, RunRecorderConfig
from vibesensor.use_cases.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.use_cases.updates.runtime import build_update_manager

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeSettingsDeps:
    """Focused settings readers needed by long-lived runtime collaborators."""

    settings_reader: SettingsReader
    speed_source_reader: SpeedSourceSettingsReader
    sensor_metadata_reader: SensorMetadataReader
    language_reader: LanguageReader


@dataclass(slots=True)
class SettingsServiceBundle:
    """Explicit settings wiring bundle for runtime and HTTP assembly."""

    coordinator: SettingsPersistenceCoordinator
    car_settings: CarSettingsService
    analysis_settings: ActiveCarAnalysisSettingsService
    sensor_metadata_store: SensorSettingsService
    speed_source_settings: PersistedSpeedSourceSettingsService
    ui_preferences: UiPreferencesService
    settings_reader: SettingsDerivationService
    speed_source_service: SpeedSourceSettingsService

    def runtime_deps(self) -> RuntimeSettingsDeps:
        """Return the focused runtime readers derived from this bundle."""

        return RuntimeSettingsDeps(
            settings_reader=self.settings_reader,
            speed_source_reader=self.speed_source_settings,
            sensor_metadata_reader=self.sensor_metadata_store,
            language_reader=self.ui_preferences,
        )

    def http_settings_deps(
        self,
        *,
        speed_status_service: SettingsSpeedServiceProtocol,
        obd_admin_service: ObdAdminServiceProtocol,
    ) -> SettingsDeps:
        """Return the focused HTTP settings dependency group."""

        return SettingsDeps(
            car_settings=self.car_settings,
            analysis_settings=self.analysis_settings,
            ui_preferences=self.ui_preferences,
            speed_source_service=self.speed_source_service,
            speed_status_service=speed_status_service,
            obd_admin_service=obd_admin_service,
        )


@dataclass(frozen=True, slots=True)
class SpeedRuntimeBundle:
    """GPS, OBD, and selected-speed-source runtime services."""

    gps_monitor: GPSSpeedMonitor
    obd_runtime: ObdRuntime
    speed_services: SpeedSourceServices


@dataclass(frozen=True, slots=True)
class HistoryServiceBundle:
    """History and reporting services derived from shared persistence adapters."""

    run_service: HistoryRunServiceProtocol
    report_service: HistoryReportServiceProtocol
    export_service: HistoryExportServiceProtocol

    def http_deps(self) -> HistoryDeps:
        """Return the focused HTTP history dependency group."""

        return HistoryDeps(
            run_service=self.run_service,
            report_service=self.report_service,
            export_service=self.export_service,
        )


@dataclass(frozen=True, slots=True)
class LiveRuntimeBundle:
    """Live signal-processing and operator-facing runtime services."""

    registry: ClientRegistry
    worker_pool: WorkerPool
    processor: SignalProcessor
    control_plane: UDPControlPlane
    processing_loop_state: ProcessingLoopState
    processing_loop: ProcessingLoop
    ws_hub: WebSocketHub
    ws_broadcast: WsBroadcastService
    run_recorder: RunRecorder

    def http_health_deps(self, *, health_state: RuntimeHealthState) -> HealthDeps:
        """Return the focused HTTP health dependency group."""

        return HealthDeps(
            processing_loop_state=self.processing_loop_state,
            health_state=health_state,
            processor=self.processor,
            registry=self.registry,
            run_recorder=self.run_recorder,
        )

    def http_live_deps(self, *, sensor_metadata_store: SensorMetadataStore) -> LiveDeps:
        """Return the focused HTTP live-runtime dependency group."""

        return LiveDeps(
            registry=self.registry,
            control_plane=self.control_plane,
            sensor_metadata_store=sensor_metadata_store,
            processor=self.processor,
            run_recorder=self.run_recorder,
            ws_hub=self.ws_hub,
        )


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
    except (aiosqlite.Error, OSError):
        LOGGER.error("Failed during early startup DB operations; closing DB.", exc_info=True)
        history.lifecycle.close()
        raise
    if recovered_runs:
        LOGGER.warning("Recovered %d stale recording run(s) on startup", recovered_runs)
    try:
        pruned_runs = history.run_repository.prune_terminal_runs_older_than_days(
            config.logging.run_retention_days,
        )
    except (aiosqlite.Error, OSError):
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


def build_settings_service_bundle(
    *,
    snapshot_repository: SettingsSnapshotPersistence | None,
    speed_control: SpeedSourceSync | None,
) -> SettingsServiceBundle:
    """Build the explicit settings bundle used by runtime and HTTP assembly."""

    coordinator = SettingsPersistenceCoordinator(db=snapshot_repository)
    car_settings = CarSettingsService(
        lock=coordinator.lock,
        state=coordinator.car_state,
        update_with_rollback=coordinator.update_with_rollback,
    )
    analysis_settings = ActiveCarAnalysisSettingsService(
        active_car_aspects=car_settings.active_car_aspects,
        update_active_car_aspects=car_settings.update_active_car_aspects,
    )
    sensor_metadata_store = SensorSettingsService(
        lock=coordinator.lock,
        state=coordinator.sensor_state,
        update_with_rollback=coordinator.update_with_rollback,
    )
    speed_source_settings = PersistedSpeedSourceSettingsService(
        lock=coordinator.lock,
        state=coordinator.speed_source_state,
        update_with_rollback=coordinator.update_with_rollback,
    )
    ui_preferences = UiPreferencesService(
        lock=coordinator.lock,
        state=coordinator.ui_preferences_state,
        update_with_rollback=coordinator.update_with_rollback,
    )
    settings_reader = SettingsDerivationService(
        active_car_aspects=car_settings.active_car_aspects,
        active_car_snapshot=car_settings.active_car_snapshot,
    )

    return SettingsServiceBundle(
        coordinator=coordinator,
        car_settings=car_settings,
        analysis_settings=analysis_settings,
        sensor_metadata_store=sensor_metadata_store,
        speed_source_settings=speed_source_settings,
        ui_preferences=ui_preferences,
        settings_reader=settings_reader,
        speed_source_service=SpeedSourceSettingsService(
            settings_store=speed_source_settings,
            runtime_applier=SpeedSourceRuntimeApplier(
                speed_control=speed_control,
            ),
        ),
    )


def build_speed_runtime(config: AppConfig) -> SpeedRuntimeBundle:
    """Build the grouped GPS/OBD speed-source runtime services."""

    gps_monitor = GPSSpeedMonitor(gps_enabled=config.gps.gps_enabled)
    obd_admin_client = ObdAdminClient()
    obd_runtime = build_obd_runtime(admin_client=obd_admin_client)
    return SpeedRuntimeBundle(
        gps_monitor=gps_monitor,
        obd_runtime=obd_runtime,
        speed_services=build_speed_source_services(
            gps_monitor=gps_monitor,
            obd_facts=obd_runtime.observation.facts,
            obd_projection=obd_runtime.observation.projection,
            obd_device_admin=obd_admin_client,
            obd_status_refresher=obd_runtime.control.admin,
            obd_control=obd_runtime.control.settings,
        ),
    )


def build_history_service_bundle(
    *,
    history: HistoryPersistenceAdapters,
    current_car_reader: SettingsReader,
) -> HistoryServiceBundle:
    """Build the focused history/reporting services over shared persistence."""

    history_run_service = HistoryRunService(history.run_repository)
    history_export_service = HistoryExportService(history.run_repository)
    return HistoryServiceBundle(
        run_service=ProjectedHistoryRunService(
            history_run_service,
            current_car_reader=current_car_reader,
        ),
        report_service=HistoryReportService(
            history.run_repository,
            pdf_renderer=_build_prepared_pdf_bytes,
        ),
        export_service=ProjectedHistoryExportService(history_export_service),
    )


def build_live_runtime(
    *,
    config: AppConfig,
    accel_scale_g_per_lsb: float,
    history: HistoryPersistenceAdapters,
    speed_runtime: SpeedRuntimeBundle,
    runtime_settings: RuntimeSettingsDeps,
) -> LiveRuntimeBundle:
    """Build the grouped live processing, broadcast, and recording services."""

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
    ws_hub = WebSocketHub()
    ws_payload_projector = LiveWsPayloadProjector(
        registry=registry,
        processor=processor,
        gps_monitor=speed_runtime.speed_services.observation,
        gps_enabled=config.gps.gps_enabled,
        settings_reader=runtime_settings.settings_reader,
        speed_source_reader=runtime_settings.speed_source_reader,
        sensor_metadata_reader=runtime_settings.sensor_metadata_reader,
    )
    ws_broadcast = WsBroadcastService(
        ui_push_hz=UI_PUSH_HZ,
        ui_heavy_push_hz=UI_HEAVY_PUSH_HZ,
        payload_source=ws_payload_projector,
    )
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
        gps_monitor=speed_runtime.speed_services.observation,
        processor=processor,
        history_db=history.run_repository,
        settings_reader=runtime_settings.settings_reader,
        sensor_metadata_reader=runtime_settings.sensor_metadata_reader,
        language_reader=runtime_settings.language_reader,
    )

    stale_analyzing = history.run_repository.stale_analyzing_run_ids()
    for stale_run_id in stale_analyzing:
        LOGGER.info("Re-queuing stuck analyzing run %s for re-analysis", stale_run_id)
        run_recorder.schedule_post_analysis(stale_run_id)
    if stale_analyzing:
        LOGGER.info("Re-queued %d stuck analyzing run(s)", len(stale_analyzing))

    return LiveRuntimeBundle(
        registry=registry,
        worker_pool=worker_pool,
        processor=processor,
        control_plane=control_plane,
        processing_loop_state=processing_loop_state,
        processing_loop=processing_loop,
        ws_hub=ws_hub,
        ws_broadcast=ws_broadcast,
        run_recorder=run_recorder,
    )


def build_update_deps(config: AppConfig) -> UpdateDeps:
    """Build the grouped updater and firmware-flash dependencies."""

    return UpdateDeps(
        update_manager=build_update_manager(
            ap_con_name=config.ap.con_name,
            wifi_ifname=config.ap.ifname,
            rollback_dir=str(config.update.rollback_dir),
        ),
        esp_flash_manager=EspFlashManager(),
    )


def build_lifecycle_state(
    *,
    config: AppConfig,
    health_state: RuntimeHealthState,
    history: HistoryPersistenceAdapters,
    speed_runtime: SpeedRuntimeBundle,
    runtime_settings: RuntimeSettingsDeps,
    live_runtime: LiveRuntimeBundle,
    updates: UpdateDeps,
) -> RuntimeState:
    """Build the lifecycle-focused runtime dependency bundle."""

    return RuntimeState(
        config=config,
        registry=live_runtime.registry,
        processor=live_runtime.processor,
        control_plane=live_runtime.control_plane,
        worker_pool=live_runtime.worker_pool,
        settings_reader=runtime_settings.settings_reader,
        gps_monitor=speed_runtime.gps_monitor,
        obd_runner=speed_runtime.obd_runtime.connection.runner,
        history_db=history.lifecycle,
        processing_loop_state=live_runtime.processing_loop_state,
        health_state=health_state,
        processing_loop=live_runtime.processing_loop,
        ws_hub=live_runtime.ws_hub,
        ws_broadcast=live_runtime.ws_broadcast,
        run_recorder=live_runtime.run_recorder,
        update_manager=updates.update_manager,
        esp_flash_manager=updates.esp_flash_manager,
    )


def build_router_deps(
    *,
    health_state: RuntimeHealthState,
    speed_runtime: SpeedRuntimeBundle,
    settings_services: SettingsServiceBundle,
    history_services: HistoryServiceBundle,
    live_runtime: LiveRuntimeBundle,
    updates: UpdateDeps,
) -> RouterDeps:
    """Build the grouped HTTP route dependency bundle."""

    settings = settings_services.http_settings_deps(
        speed_status_service=speed_runtime.speed_services.observation,
        obd_admin_service=speed_runtime.speed_services.admin,
    )
    return RouterDeps(
        health=live_runtime.http_health_deps(health_state=health_state),
        settings=settings,
        live=live_runtime.http_live_deps(
            sensor_metadata_store=settings_services.sensor_metadata_store,
        ),
        history=history_services.http_deps(),
        updates=updates,
    )


def build_runtime(config: AppConfig) -> AppRuntime:
    """Construct all services and return the app runtime bundle."""
    accel_scale_g_per_lsb = resolve_accel_scale_g_per_lsb(config)
    health_state = RuntimeHealthState()

    history = create_history_db(
        config,
        corruption_reporter=health_state.mark_db_corrupted,
    )
    speed_runtime = build_speed_runtime(config)
    settings_services = build_settings_service_bundle(
        snapshot_repository=history.settings_snapshot_repository,
        speed_control=speed_runtime.speed_services.control,
    )
    runtime_settings = settings_services.runtime_deps()
    history_services = build_history_service_bundle(
        history=history,
        current_car_reader=settings_services.settings_reader,
    )
    live_runtime = build_live_runtime(
        config=config,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        history=history,
        speed_runtime=speed_runtime,
        runtime_settings=runtime_settings,
    )
    updates = build_update_deps(config)
    lifecycle = build_lifecycle_state(
        config=config,
        health_state=health_state,
        history=history,
        speed_runtime=speed_runtime,
        runtime_settings=runtime_settings,
        live_runtime=live_runtime,
        updates=updates,
    )
    router = build_router_deps(
        health_state=health_state,
        speed_runtime=speed_runtime,
        settings_services=settings_services,
        history_services=history_services,
        live_runtime=live_runtime,
        updates=updates,
    )
    settings_services.speed_source_service.sync_all()
    return AppRuntime(lifecycle=lifecycle, router=router)
