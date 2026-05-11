from __future__ import annotations

import logging
from dataclasses import dataclass

from vibesensor.adapters.http.dependencies import HealthDeps, LiveDeps
from vibesensor.adapters.persistence.history_db import HistoryPersistenceAdapters
from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane
from vibesensor.adapters.websocket.hub import WebSocketHub
from vibesensor.app.composition.settings import RuntimeSettingsDeps
from vibesensor.app.composition.speed import SpeedRuntimeBundle
from vibesensor.app.config_schema import AppConfig
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_loop import ProcessingLoop
from vibesensor.infra.runtime.processing_state import ProcessingLoopState
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.infra.runtime.ws_broadcast import WsBroadcastService
from vibesensor.infra.runtime.ws_payload_projection import LiveWsPayloadProjector
from vibesensor.infra.workers.worker_pool import WorkerPool
from vibesensor.shared.constants.dsp import (
    FFT_N,
    FFT_UPDATE_HZ,
    SPECTRUM_MAX_HZ,
    SPECTRUM_MIN_HZ,
    WAVEFORM_DISPLAY_HZ,
)
from vibesensor.shared.constants.ui import UI_HEAVY_PUSH_HZ, UI_PUSH_HZ
from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector
from vibesensor.shared.ports import SensorMetadataStore
from vibesensor.shared.sensor_units import ADXL345_SCALE_G_PER_LSB, SENSOR_MODEL
from vibesensor.use_cases.run import RunRecorder, RunRecorderConfig

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LiveRuntimeBundle:
    """Live signal-processing and operator-facing runtime services."""

    registry: ClientRegistry
    worker_pool: WorkerPool
    processor: SignalProcessor
    control_plane: UDPControlPlane
    processing_loop_state: ProcessingLoopState
    ingest_diagnostics: IngestDiagnosticsCollector
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
            ingest_diagnostics=self.ingest_diagnostics,
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


def resolve_accel_scale_g_per_lsb(config: AppConfig) -> float:
    return config.processing.accel_scale_g_per_lsb or ADXL345_SCALE_G_PER_LSB


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
    ingest_diagnostics = IngestDiagnosticsCollector()
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
        ingest_diagnostics=ingest_diagnostics,
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
        ingest_diagnostics=ingest_diagnostics,
        processing_loop=processing_loop,
        ws_hub=ws_hub,
        ws_broadcast=ws_broadcast,
        run_recorder=run_recorder,
    )
