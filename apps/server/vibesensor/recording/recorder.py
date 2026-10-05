"""Thin recording orchestrator around the focused run helpers."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from threading import RLock
from typing import TYPE_CHECKING

from vibesensor.analysis.post_analysis import PostAnalysisWorker
from vibesensor.analysis.post_analysis_summary import build_post_analysis_summary
from vibesensor.common.structured_logging import log_extra
from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.recording import _recorder_runtime, _recorder_types
from vibesensor.recording.capture_readiness import CaptureReadinessTracker
from vibesensor.recording.capture_readiness_observation import observe_capture_readiness
from vibesensor.recording.finalize_stages import (
    ActiveRunFinalizeResult,
    finalize_active_run,
)
from vibesensor.recording.lifecycle_state import (
    AutoStopReason,
    RecordingStopReason,
    RunLifecycleState,
)
from vibesensor.recording.persistence_writer import (
    _APPEND_RETRY_DELAYS_S,
    _MAX_APPEND_RETRIES,
    _MAX_HISTORY_CREATE_RETRIES,
    _RETRY_COOLDOWN_BASE_S,
    RunPersistenceWriter,
)
from vibesensor.recording.raw_capture import (
    RawCaptureClockProofState,
    RawCaptureSensorClockSync,
)
from vibesensor.recording.raw_capture_finalize_registry import RawCaptureFinalizeRegistry
from vibesensor.recording.raw_capture_writer import (
    RawCaptureFinalizeResult,
    RunRawCaptureWriter,
)
from vibesensor.recording.recording_session import RunRecordingSessionService
from vibesensor.recording.run_schema import GuidedPhaseName
from vibesensor.recording.sample_flush import SampleFlushOrchestrator
from vibesensor.recording.status_reporting import (
    RunRecorderStatusSnapshot,
    build_run_recorder_health_snapshot,
    build_run_recorder_status,
)

if TYPE_CHECKING:
    from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
    from vibesensor.history.history_db import HistoryDB
    from vibesensor.ingest.registry import ClientRegistry
    from vibesensor.live.processor import SignalProcessor
    from vibesensor.recording.status_reporting import RunRecorderHealthSnapshot
    from vibesensor.settings.sensor_settings import SensorSettingsService
    from vibesensor.settings.settings_derivation import SettingsDerivationService
    from vibesensor.settings.ui_preferences import UiPreferencesService
    from vibesensor.speed.source_coordinator import SpeedSourceObservationService

LOGGER = logging.getLogger(__name__)
_RAW_CAPTURE_MAX_SYNC_AGE_US = 15_000_000
_RAW_CAPTURE_MAX_SYNC_RTT_US = 50_000

__all__ = [
    "RunRecorder",
    "_APPEND_RETRY_DELAYS_S",
    "_MAX_APPEND_RETRIES",
    "_MAX_HISTORY_CREATE_RETRIES",
    "_RETRY_COOLDOWN_BASE_S",
]


class RunRecorder:
    """Manages recording of runs, post-analysis, and history persistence."""

    def __init__(
        self,
        config: _recorder_types.RunRecorderConfig,
        registry: ClientRegistry,
        gps_monitor: SpeedSourceObservationService,
        processor: SignalProcessor,
        history_db: HistoryDB | None = None,
        settings_reader: SettingsDerivationService | None = None,
        sensor_metadata_reader: SensorSettingsService | None = None,
        ui_preferences: UiPreferencesService | None = None,
        ingest_diagnostics: IngestDiagnosticsCollector | None = None,
        clock_trusted: Callable[[], bool] | None = None,
    ):
        self.metrics_log_hz = max(1, config.metrics_log_hz)
        self.registry = registry
        self.gps_monitor = gps_monitor
        self.processor = processor
        self._settings_reader = settings_reader
        self._sensor_metadata_reader = sensor_metadata_reader
        self.sensor_model = config.sensor_model.strip() or "unknown"
        self.default_sample_rate_hz = int(config.default_sample_rate_hz)
        self.fft_window_size_samples = int(config.fft_window_size_samples)
        self.accel_scale_g_per_lsb = _recorder_runtime.normalize_accel_scale_g_per_lsb(
            config.accel_scale_g_per_lsb,
        )
        self._lock = RLock()
        self._history_db = history_db
        self._ui_preferences = ui_preferences
        self._capture_readiness = CaptureReadinessTracker()

        self._lifecycle = RunLifecycleState(
            no_data_timeout_s=max(1.0, float(config.no_data_timeout_s)),
            max_duration_s=max(1.0, float(config.max_recording_duration_s)),
        )

        self._persistence = RunPersistenceWriter(
            lock=self._lock,
            history_db=history_db,
            persist_history_db_enabled=config.persist_history_db,
            run_id_matches=self._run_id_matches,
            metadata_builder=lambda run_id, start_time_utc: (
                _recorder_types._build_run_metadata_record(
                    self,
                    run_id,
                    start_time_utc,
                )
            ),
            monotonic=lambda: time.monotonic(),
            sleep=lambda seconds: time.sleep(seconds),
            logger_provider=lambda: LOGGER,
        )

        self.post_analysis = PostAnalysisWorker(
            history_db=history_db,
            error_callback=self._persistence.set_last_write_error,
            clear_error_callback=self._persistence.clear_last_write_error,
            analysis_runner=build_post_analysis_summary,
        )
        self.raw_capture = RunRawCaptureWriter(
            history_db=history_db if config.persist_history_db else None,
            logger=LOGGER,
            ingest_diagnostics=ingest_diagnostics,
            sensor_sync_snapshotter=lambda client_ids: _snapshot_raw_capture_sensor_sync(
                self.registry,
                client_ids,
            ),
            late_finalize_callback=self._handle_late_raw_capture_finalize_result,
        )
        self._raw_capture_finalize_registry = RawCaptureFinalizeRegistry(logger=LOGGER)
        self._recording_session = RunRecordingSessionService(
            lock=self._lock,
            registry=self.registry,
            processor=self.processor,
            settings_reader=settings_reader,
            sensor_metadata_reader=sensor_metadata_reader,
            lifecycle=self._lifecycle,
            persistence=self._persistence,
            raw_capture=self.raw_capture,
            analysis_settings_snapshot=self._analysis_settings_snapshot,
            active_frames_total=lambda: _recorder_runtime.active_frames_total(self.registry),
            monotonic=lambda: time.monotonic(),
            clock_trusted=clock_trusted,
        )

        self._sample_flush = SampleFlushOrchestrator(
            registry=self.registry,
            gps_monitor=self.gps_monitor,
            processor=self.processor,
            analysis_settings_snapshot=self._recording_session.recording_analysis_settings_snapshot,
            default_sample_rate_hz=self.default_sample_rate_hz,
            sensor_metadata_reader=sensor_metadata_reader,
            run_sensor_presentation_resolver=(
                self._recording_session.resolve_run_sensor_presentation
            ),
            lifecycle=self._lifecycle,
            persistence=self._persistence,
            active_frames_total=lambda: _recorder_runtime.active_frames_total(self.registry),
            current_run_id=lambda: self._run_id,
            monotonic=lambda: time.monotonic(),
        )

        with self._lock:
            self._persistence.reset()

    @property
    def enabled(self) -> bool:
        return self._lifecycle.enabled

    @property
    def last_write_duration_s(self) -> float:
        return self._persistence.last_write_duration_s

    @property
    def max_write_duration_s(self) -> float:
        return self._persistence.max_write_duration_s

    @property
    def _run_id(self) -> str | None:
        return self._lifecycle.run_id

    def _run_id_matches(self, run_id: str) -> bool:
        current = self._lifecycle.current_run
        return current is not None and current.run_id == run_id

    def _analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot:
        return _recorder_runtime.analysis_settings_snapshot(self._settings_reader)

    def status(self) -> RunRecorderStatusSnapshot:
        with self._lock:
            enabled = self._lifecycle.enabled
            run_id = self._lifecycle.run_id
            start_time_utc = self._lifecycle.start_time_utc
            last_stop_reason = self._lifecycle.last_stop_reason
            last_run_id = self._lifecycle.last_run_id
            capture_readiness = None
            if not enabled or run_id is None:
                capture_readiness = self._capture_readiness.evaluate(
                    observe_capture_readiness(
                        registry=self.registry,
                        run_context=self._recording_session.live_run_context_snapshot(),
                        speed_provider=self.gps_monitor,
                        sensor_metadata_reader=self._sensor_metadata_reader,
                        now_mono=time.monotonic(),
                    )
                )
        return build_run_recorder_status(
            enabled=enabled,
            run_id=run_id,
            start_time_utc=start_time_utc,
            persistence=self._persistence,
            post_analysis=self.post_analysis,
            capture_readiness=capture_readiness,
            last_stop_reason=last_stop_reason,
            last_run_id=last_run_id,
            guided_phase=self._recording_session.current_guided_phase(),
            guided_phases_completed=self._recording_session.completed_guided_phases(),
        )

    def mark_guided_phase(self, phase: GuidedPhaseName | None) -> RunRecorderStatusSnapshot:
        """Mark the guided test-drive step the driver starts now (``None`` ends the test)."""
        self._recording_session.mark_guided_phase(phase)
        return self.status()

    def health_snapshot(self) -> RunRecorderHealthSnapshot:
        return build_run_recorder_health_snapshot(
            history_db=self._history_db,
            persistence=self._persistence,
            post_analysis=self.post_analysis,
            logger=LOGGER,
        )

    def _log_run_lifecycle_event(
        self,
        *,
        action: str,
        run_id: str,
        start_time_utc: str,
        end_time_utc: str | None = None,
        stop_reason: str | None = None,
        samples_written: int | None = None,
        samples_dropped: int | None = None,
    ) -> None:
        extra: dict[str, object] = {
            "event": "run_lifecycle",
            "run_action": action,
            "run_id": run_id,
            "start_time_utc": start_time_utc,
        }
        if end_time_utc is not None:
            extra["end_time_utc"] = end_time_utc
        if stop_reason is not None:
            extra["stop_reason"] = stop_reason
        if samples_written is not None:
            extra["samples_written"] = samples_written
        if samples_dropped is not None:
            extra["samples_dropped"] = samples_dropped
        LOGGER.info("run_lifecycle", extra=log_extra(**extra))

    def _finalize_active_run_locked(self, *, reason: str) -> ActiveRunFinalizeResult:
        return finalize_active_run(
            run_id=self._run_id,
            start_time_utc=self._lifecycle.start_time_utc,
            stop_reason=reason,
            ingest_drop_losses=self._recording_session.ingest_drop_losses(),
            sample_flush=self._sample_flush,
            persistence=self._persistence,
            raw_capture=self.raw_capture,
            record_raw_capture_finalize_result=self._raw_capture_finalize_registry.record_result,
            record_finalization_stage_results=self._persistence.update_finalization_stage_results,
            logger=LOGGER,
        )

    def start_recording(self) -> RunRecorderStatusSnapshot:
        completed_run_id: str | None = None
        lifecycle_events: list[
            tuple[str, str, str, str | None, str | None, int | None, int | None]
        ] = []
        with self._lock:
            if self._lifecycle.shutdown_requested:
                LOGGER.info(
                    "Ignoring start_recording() while metrics logger shutdown is in progress.",
                )
                return self.status()
            if self.enabled and self._run_id:
                finalize_result = self._finalize_active_run_locked(reason="restart")
                completed_run_id = finalize_result.run_id_to_analyze
                if (
                    finalize_result.run_id is not None
                    and finalize_result.persistence_snapshot is not None
                ):
                    lifecycle_events.append(
                        (
                            "stopped",
                            finalize_result.run_id,
                            finalize_result.start_time_utc,
                            finalize_result.end_time_utc,
                            "restart",
                            finalize_result.persistence_snapshot.written_sample_count,
                            finalize_result.persistence_snapshot.dropped_sample_count,
                        )
                    )
            started_run = self._recording_session.start_new_run()
            lifecycle_events.append(
                (
                    "started",
                    started_run.run_id,
                    started_run.start_time_utc,
                    None,
                    None,
                    None,
                    None,
                )
            )
            result = self.status()
        for (
            event_action,
            event_run_id,
            event_start_time_utc,
            event_end_time_utc,
            event_stop_reason,
            event_samples_written,
            event_samples_dropped,
        ) in lifecycle_events:
            self._log_run_lifecycle_event(
                action=event_action,
                run_id=event_run_id,
                start_time_utc=event_start_time_utc,
                end_time_utc=event_end_time_utc,
                stop_reason=event_stop_reason,
                samples_written=event_samples_written,
                samples_dropped=event_samples_dropped,
            )
        if completed_run_id and self._history_db is not None:
            self.post_analysis.schedule(completed_run_id)
        return result

    def stop_recording(
        self,
        *,
        _only_if_run_id: str | None = None,
        reason: RecordingStopReason = "manual",
    ) -> RunRecorderStatusSnapshot:
        lifecycle_event: (
            tuple[str, str, str, str | None, str | None, int | None, int | None] | None
        ) = None
        with self._lock:
            if _only_if_run_id is not None and self._run_id != _only_if_run_id:
                return self.status()
            finalize_result = self._finalize_active_run_locked(reason=reason)
            run_id_to_analyze = finalize_result.run_id_to_analyze
            if (
                finalize_result.run_id is not None
                and finalize_result.persistence_snapshot is not None
            ):
                lifecycle_event = (
                    "stopped",
                    finalize_result.run_id,
                    finalize_result.start_time_utc,
                    finalize_result.end_time_utc,
                    reason,
                    finalize_result.persistence_snapshot.written_sample_count,
                    finalize_result.persistence_snapshot.dropped_sample_count,
                )
            self._lifecycle.stop(reason=reason)
            self._persistence.end_run()
            self._recording_session.clear_stopped_run()
        if lifecycle_event is not None:
            (
                event_action,
                event_run_id,
                event_start_time_utc,
                event_end_time_utc,
                event_stop_reason,
                event_samples_written,
                event_samples_dropped,
            ) = lifecycle_event
            self._log_run_lifecycle_event(
                action=event_action,
                run_id=event_run_id,
                start_time_utc=event_start_time_utc,
                end_time_utc=event_end_time_utc,
                stop_reason=event_stop_reason,
                samples_written=event_samples_written,
                samples_dropped=event_samples_dropped,
            )
        if run_id_to_analyze and self._history_db is not None:
            self.post_analysis.schedule(run_id_to_analyze)
        # After scheduling, so the stopped run's analysis is visible: with no earlier
        # completed run the response would otherwise read as idle.
        return self.status()

    def shutdown_report(self, timeout_s: float = 30.0) -> _recorder_types.RecorderShutdownReport:
        return _recorder_types._shutdown_report(self, timeout_s)

    def _handle_late_raw_capture_finalize_result(
        self,
        run_id: str,
        result: RawCaptureFinalizeResult,
    ) -> None:
        with self._lock:
            finalized = self._raw_capture_finalize_registry.record_late_result(run_id, result)
            if finalized is None:
                return
        if not self._persistence.update_raw_capture_finalize(run_id, finalized):
            LOGGER.warning(
                "late_raw_capture_finalize_metadata_update_failed",
                extra=log_extra(
                    event="late_raw_capture_finalize_metadata_update_failed",
                    run_id=run_id,
                    raw_capture_finalize_status=result.status,
                    raw_capture_error=result.error,
                ),
            )
            return
        if self._history_db is not None:
            LOGGER.info(
                "late_raw_capture_finalize_scheduling_post_analysis",
                extra=log_extra(
                    event="late_raw_capture_finalize_scheduling_post_analysis",
                    run_id=run_id,
                    raw_capture_finalize_status=result.status,
                ),
            )
            self.post_analysis.schedule(run_id)

    def flush_tick(self) -> tuple[str | None, AutoStopReason | None]:
        """Append one tick of live samples to the active run.

        Returns the active run id (``None`` when idle) and why the run should
        auto-stop now, if it should; ``run()`` calls this at ``metrics_log_hz``.
        """
        return _recorder_runtime.flush_active_run_tick(self, logger=LOGGER)

    async def run(self) -> None:
        await _recorder_runtime.run_loop(self, logger=LOGGER)


def _snapshot_raw_capture_sensor_sync(
    registry: ClientRegistry,
    client_ids: tuple[str, ...],
) -> dict[str, RawCaptureSensorClockSync]:
    observed_monotonic_us = int(round(time.monotonic() * 1_000_000.0))
    snapshot: dict[str, RawCaptureSensorClockSync] = {}
    for client_id in client_ids:
        record = registry.get(client_id)
        if record is None:
            snapshot[client_id] = RawCaptureSensorClockSync(
                clock_domain="unverified",
                proof_state="missing_registry_record",
                observed_monotonic_us=observed_monotonic_us,
                max_sync_age_us=_RAW_CAPTURE_MAX_SYNC_AGE_US,
                max_sync_rtt_us=_RAW_CAPTURE_MAX_SYNC_RTT_US,
            )
            continue
        sync_offset_us = _int_attr(record, "sync_offset_us")
        sync_rtt_us = _int_attr(record, "sync_rtt_us")
        last_sync_monotonic_us = _int_attr(record, "last_sync_monotonic_us")
        proof_state = _raw_capture_clock_proof_state(
            observed_monotonic_us=observed_monotonic_us,
            last_sync_monotonic_us=last_sync_monotonic_us,
            sync_offset_us=sync_offset_us,
            sync_rtt_us=sync_rtt_us,
            timing_degraded=record.timing_guard.degraded,
        )
        snapshot[client_id] = RawCaptureSensorClockSync(
            clock_domain="server_monotonic" if proof_state == "verified" else "unverified",
            proof_state=proof_state,
            observed_monotonic_us=observed_monotonic_us,
            last_sync_monotonic_us=last_sync_monotonic_us,
            sync_offset_us=sync_offset_us,
            sync_rtt_us=sync_rtt_us,
            max_sync_age_us=_RAW_CAPTURE_MAX_SYNC_AGE_US,
            max_sync_rtt_us=_RAW_CAPTURE_MAX_SYNC_RTT_US,
        )
    return snapshot


def _raw_capture_clock_proof_state(
    *,
    observed_monotonic_us: int,
    last_sync_monotonic_us: int | None,
    sync_offset_us: int | None,
    sync_rtt_us: int | None,
    timing_degraded: bool,
) -> RawCaptureClockProofState:
    if sync_offset_us is None or sync_rtt_us is None or last_sync_monotonic_us is None:
        return "missing_sync"
    if observed_monotonic_us < last_sync_monotonic_us:
        return "stale_sync"
    if (observed_monotonic_us - last_sync_monotonic_us) > _RAW_CAPTURE_MAX_SYNC_AGE_US:
        return "stale_sync"
    if sync_rtt_us > _RAW_CAPTURE_MAX_SYNC_RTT_US:
        return "high_rtt"
    if timing_degraded:
        # Synced, but its stamps fall behind real time or its rate is off
        # (``SensorTimingGuard``): the offset does not make them trustworthy.
        return "timing_unreliable"
    return "verified"


def _int_attr(value: object, name: str) -> int | None:
    raw_value = getattr(value, name, None)
    return int(raw_value) if isinstance(raw_value, int) else None
