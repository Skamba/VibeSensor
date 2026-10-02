from __future__ import annotations

import logging
from dataclasses import dataclass

from vibesensor.app.composition.settings import RuntimeSettingsDeps
from vibesensor.app.composition.speed import SpeedRuntimeBundle
from vibesensor.app.config_schema import AppConfig
from vibesensor.dsp.constants import (
    FFT_N,
    FFT_UPDATE_HZ,
    SAMPLE_RATE_HZ,
    SPECTRUM_MAX_HZ,
    SPECTRUM_MIN_HZ,
    WAVEFORM_BUFFER_SECONDS,
    WAVEFORM_DISPLAY_HZ,
)
from vibesensor.history.history_db import HistoryDB
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
from vibesensor.shared.ports import SensorMetadataStore
from vibesensor.web.dependencies import HealthDeps, LiveDeps
from vibesensor.web.health_state import RuntimeHealthState

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LiveRuntimeBundle:
    """Live signal-processing and operator-facing runtime services."""

    registry: ClientRegistry
    processor: SignalProcessor
    control_plane: UDPControlPlane
    processing_loop_state: ProcessingLoopState
    ingest_diagnostics: IngestDiagnosticsCollector
    processing_loop: ProcessingLoop
    ws_broadcaster: LiveBroadcaster
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
            ws_broadcaster=self.ws_broadcaster,
        )


def build_live_runtime(
    *,
    config: AppConfig,
    history: HistoryDB,
    speed_runtime: SpeedRuntimeBundle,
    runtime_settings: RuntimeSettingsDeps,
) -> LiveRuntimeBundle:
    """Build the grouped live processing, broadcast, and recording services."""

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
    ws_payload_projector = LiveWsPayloadProjector(
        registry=registry,
        processor=processor,
        gps_monitor=speed_runtime.speed_services.observation,
        gps_enabled=config.gps.gps_enabled,
        settings_reader=runtime_settings.settings_reader,
        speed_source_reader=runtime_settings.speed_source_reader,
        sensor_metadata_reader=runtime_settings.sensor_metadata_reader,
    )
    ws_broadcaster = LiveBroadcaster(
        payload_source=ws_payload_projector,
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
        gps_monitor=speed_runtime.speed_services.observation,
        processor=processor,
        history_db=history,
        settings_reader=runtime_settings.settings_reader,
        sensor_metadata_reader=runtime_settings.sensor_metadata_reader,
        language_reader=runtime_settings.language_reader,
        ingest_diagnostics=ingest_diagnostics,
    )

    stale_analyzing = history.stale_analyzing_run_ids()
    for stale_run_id in stale_analyzing:
        LOGGER.info("Re-queuing stuck analyzing run %s for re-analysis", stale_run_id)
        run_recorder.post_analysis.schedule(stale_run_id)
    if stale_analyzing:
        LOGGER.info("Re-queued %d stuck analyzing run(s)", len(stale_analyzing))

    return LiveRuntimeBundle(
        registry=registry,
        processor=processor,
        control_plane=control_plane,
        processing_loop_state=processing_loop_state,
        ingest_diagnostics=ingest_diagnostics,
        processing_loop=processing_loop,
        ws_broadcaster=ws_broadcaster,
        run_recorder=run_recorder,
    )
