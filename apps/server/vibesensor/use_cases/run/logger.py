"""Thin recording orchestrator around the focused run helpers."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from threading import RLock
from typing import TYPE_CHECKING
from uuid import uuid4

import numpy as np
from opentelemetry.trace import SpanKind

from vibesensor.shared.ports import (
    ClientTracker,
    LanguageReader,
    RunPersistence,
    SensorMetadataReader,
    SettingsReader,
    SignalSource,
    SpeedProvider,
)
from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.tracing import mark_span_error, start_span
from vibesensor.shared.types.raw_capture import (
    RawCaptureClockProofState,
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
)
from vibesensor.shared.types.run_schema import RunSensorMetadata
from vibesensor.shared.types.sensor_config import SensorConfigPayload
from vibesensor.use_cases.run.capture_readiness import CaptureReadinessTracker
from vibesensor.use_cases.run.capture_readiness_observation import observe_capture_readiness
from vibesensor.use_cases.run.lifecycle_state import RunLifecycleState
from vibesensor.use_cases.run.persistence_writer import (
    _APPEND_RETRY_DELAYS_S,
    _MAX_APPEND_RETRIES,
    _MAX_HISTORY_CREATE_RETRIES,
    _RETRY_COOLDOWN_BASE_S,
    RunPersistenceWriter,
)
from vibesensor.use_cases.run.post_analysis import PostAnalysisWorker
from vibesensor.use_cases.run.post_analysis_summary import build_post_analysis_summary
from vibesensor.use_cases.run.raw_capture_writer import RunRawCaptureWriter
from vibesensor.use_cases.run.run_context import build_run_context_snapshot
from vibesensor.use_cases.run.run_sensor_snapshot import (
    build_run_sensor_snapshot,
    capture_run_sensor_snapshots,
)
from vibesensor.use_cases.run.sample_flush import SampleFlushOrchestrator
from vibesensor.use_cases.run.status_reporting import (
    RunRecorderStatusSnapshot,
    build_run_recorder_health_snapshot,
    build_run_recorder_status,
)

from . import _recorder_runtime, _recorder_types

if TYPE_CHECKING:
    from vibesensor.domain import RunContextSnapshot
    from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
    from vibesensor.shared.types.health_snapshot import RunRecorderHealthSnapshot
    from vibesensor.use_cases.run.lifecycle_state import ActiveRunSnapshot

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
        registry: ClientTracker,
        gps_monitor: SpeedProvider,
        processor: SignalSource,
        history_db: RunPersistence | None = None,
        settings_reader: SettingsReader | None = None,
        sensor_metadata_reader: SensorMetadataReader | None = None,
        language_reader: LanguageReader | None = None,
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
        self._language_reader = language_reader
        self._live_start_mono_s = time.monotonic()
        self._active_run_context: RunContextSnapshot | None = None
        self._run_sensor_snapshots: dict[str, RunSensorMetadata] = {}
        self._capture_readiness = CaptureReadinessTracker()

        self._lifecycle = RunLifecycleState(
            no_data_timeout_s=max(1.0, float(config.no_data_timeout_s)),
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

        self._post_analysis = PostAnalysisWorker(
            history_db=history_db,
            error_callback=self._persistence.set_last_write_error,
            clear_error_callback=self._persistence.clear_last_write_error,
            analysis_runner=build_post_analysis_summary,
        )
        self._raw_capture = RunRawCaptureWriter(
            history_db=history_db if config.persist_history_db else None,
            logger=LOGGER,
            sensor_sync_snapshotter=lambda client_ids: _snapshot_raw_capture_sensor_sync(
                self.registry,
                client_ids,
            ),
        )

        self._sample_flush = SampleFlushOrchestrator(
            registry=self.registry,
            gps_monitor=self.gps_monitor,
            processor=self.processor,
            analysis_settings_snapshot=self._recording_analysis_settings_snapshot,
            default_sample_rate_hz=self.default_sample_rate_hz,
            sensor_metadata_reader=sensor_metadata_reader,
            run_sensor_presentation_resolver=self._resolve_run_sensor_presentation,
            lifecycle=self._lifecycle,
            persistence=self._persistence,
            active_frames_total=lambda: _recorder_runtime.active_frames_total(self.registry),
            current_run_id=lambda: self._run_id,
            monotonic=lambda: time.monotonic(),
        )

        with self._lock:
            self._persistence.reset()
        self._run_ingest_drop_baseline: dict[str, int] | None = None
        self._finalized_raw_capture_manifests: dict[str, RawCaptureManifest] = {}

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

    def _raw_capture_manifest_for_run(self, run_id: str) -> RawCaptureManifest | None:
        return self._finalized_raw_capture_manifests.get(run_id)

    def _live_run_context_snapshot(self) -> RunContextSnapshot:
        active_car_snapshot = (
            self._settings_reader.active_car_snapshot()
            if self._settings_reader is not None
            else None
        )
        return build_run_context_snapshot(
            analysis_settings_snapshot=self._analysis_settings_snapshot(),
            active_car_snapshot=active_car_snapshot,
        )

    def _run_context_snapshot(self, run_id: str | None = None) -> RunContextSnapshot:
        with self._lock:
            current_run = self._lifecycle.current_run
            active_run_context = self._active_run_context
            if (
                active_run_context is not None
                and current_run is not None
                and current_run.is_recording
                and (run_id is None or current_run.run_id == run_id)
            ):
                return active_run_context
        return self._live_run_context_snapshot()

    def _recording_analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot:
        return self._run_context_snapshot().analysis_settings

    def _run_sensor_snapshots_for_run(self, run_id: str) -> tuple[RunSensorMetadata, ...]:
        with self._lock:
            current_run = self._lifecycle.current_run
            if current_run is None or current_run.run_id != run_id:
                return tuple()
            return tuple(
                self._run_sensor_snapshots[client_id]
                for client_id in sorted(self._run_sensor_snapshots)
            )

    def _resolve_run_sensor_presentation(
        self,
        *,
        client_id: str,
        fallback_name: str,
        fallback_location_code: str,
        sample_rate_hz: int | None,
        firmware_version: str | None,
        sensors_by_mac: Mapping[str, SensorConfigPayload],
    ) -> tuple[str, str]:
        with self._lock:
            snapshot = self._run_sensor_snapshots.get(client_id)
            if snapshot is None:
                snapshot = build_run_sensor_snapshot(
                    sensor_id=client_id,
                    fallback_name=fallback_name,
                    fallback_location_code=fallback_location_code,
                    sample_rate_hz=sample_rate_hz,
                    firmware_version=firmware_version,
                    sensors_by_mac=sensors_by_mac,
                )
                self._run_sensor_snapshots[client_id] = snapshot
            return snapshot.display_name, snapshot.location_code

    def _session_snapshot(self) -> ActiveRunSnapshot | None:
        with self._lock:
            return self._lifecycle.snapshot()

    def _start_new_run_locked(self) -> ActiveRunSnapshot:
        for client_id in self.registry.active_client_ids():
            self.processor.flush_client_buffer(
                client_id,
                reason="recording run start",
            )
        run_context = self._live_run_context_snapshot()
        snapshot = self._lifecycle.start_new_run(
            run_id=uuid4().hex,
            analysis_settings_snapshot=run_context.analysis_settings,
            start_time_utc=utc_now_iso(),
            start_mono_s=time.monotonic(),
            current_total=_recorder_runtime.active_frames_total(self.registry),
        )
        self._active_run_context = run_context
        self._run_sensor_snapshots = capture_run_sensor_snapshots(
            client_ids=self.registry.active_client_ids(),
            registry=self.registry,
            sensor_metadata_reader=self._sensor_metadata_reader,
        )
        self._persistence.reset()
        self._live_start_mono_s = snapshot.start_mono_s
        self._raw_capture.start_run(
            snapshot.run_id,
            run_start_monotonic_us=int(round(snapshot.start_mono_s * 1_000_000.0)),
        )
        self._run_ingest_drop_baseline = _snapshot_server_queue_drops(self.registry)
        return snapshot

    def capture_raw_samples(
        self,
        *,
        client_id: str,
        sample_rate_hz: int | None,
        t0_us: int,
        samples: object,
    ) -> None:
        if not isinstance(samples, np.ndarray):
            return
        self._raw_capture.capture_raw_samples(
            client_id=client_id,
            sample_rate_hz=sample_rate_hz,
            t0_us=t0_us,
            samples=samples,
        )

    def note_late_packet_loss(self, *, client_id: str) -> None:
        self._raw_capture.note_late_packet_loss(client_id=client_id)

    def status(self) -> RunRecorderStatusSnapshot:
        with self._lock:
            enabled = self._lifecycle.enabled
            run_id = self._lifecycle.run_id
            start_time_utc = self._lifecycle.start_time_utc
            capture_readiness = None
            if not enabled or run_id is None:
                capture_readiness = self._capture_readiness.evaluate(
                    observe_capture_readiness(
                        registry=self.registry,
                        run_context=self._live_run_context_snapshot(),
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
            post_analysis=self._post_analysis,
            capture_readiness=capture_readiness,
        )

    def health_snapshot(self) -> RunRecorderHealthSnapshot:
        return build_run_recorder_health_snapshot(
            history_db=self._history_db,
            persistence=self._persistence,
            post_analysis=self._post_analysis,
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

    def start_recording(self) -> RunRecorderStatusSnapshot:
        with start_span(__name__, "run.recording.start", kind=SpanKind.INTERNAL) as span:
            completed_run_id: str | None = None
            lifecycle_events: list[
                tuple[str, str, str, str | None, str | None, int | None, int | None]
            ] = []
            try:
                with self._lock:
                    if self._lifecycle.shutdown_requested:
                        LOGGER.info(
                            "Ignoring start_recording() while metrics logger "
                            "shutdown is in progress.",
                        )
                        span.set_attribute("vibesensor.ignored_shutdown", True)
                        return self.status()
                    if self.enabled and self._run_id:
                        flush_snapshot = self._sample_flush.pending_flush_snapshot()
                        if flush_snapshot is not None:
                            self._sample_flush.append_records(
                                flush_snapshot.run_id,
                                flush_snapshot.start_time_utc,
                                flush_snapshot.start_mono_s,
                                refresh_metrics=True,
                            )
                    if self.enabled and self._run_id:
                        run_id = self._run_id
                        completed_run_id = self._persistence.ready_for_analysis(run_id)
                        start_time_utc = self._lifecycle.start_time_utc or utc_now_iso()
                        end_time_utc = utc_now_iso()
                        persistence_snapshot = self._persistence.status_snapshot()
                        ingest_drop_losses = _udp_ingest_drop_sensor_losses(
                            self.registry,
                            baseline=self._run_ingest_drop_baseline,
                        )
                        if run_id:
                            manifest = self._raw_capture.finalize_run(
                                run_id,
                                sensor_losses=ingest_drop_losses,
                            )
                            if manifest is not None:
                                self._finalized_raw_capture_manifests[run_id] = manifest
                        if run_id and not self._persistence.finalize_run(
                            run_id,
                            start_time_utc,
                            end_time_utc,
                        ):
                            LOGGER.warning(
                                "finalize_run failed for %s; scheduling analysis anyway",
                                run_id,
                            )
                        lifecycle_events.append(
                            (
                                "stopped",
                                run_id,
                                start_time_utc,
                                end_time_utc,
                                "restart",
                                persistence_snapshot.written_sample_count,
                                persistence_snapshot.dropped_sample_count,
                            )
                        )
                    started_run = self._start_new_run_locked()
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
            except Exception as exc:
                mark_span_error(span, exc)
                raise
            span.set_attribute("vibesensor.run_id", result.run_id or "")
            span.set_attribute("vibesensor.restarted_previous_run", completed_run_id is not None)
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
            self.schedule_post_analysis(completed_run_id)
        return result

    def stop_recording(
        self,
        *,
        _only_if_run_id: str | None = None,
        reason: str = "manual",
    ) -> RunRecorderStatusSnapshot:
        with start_span(
            __name__,
            "run.recording.stop",
            kind=SpanKind.INTERNAL,
            attributes={"vibesensor.stop_reason": reason},
        ) as span:
            lifecycle_event: (
                tuple[str, str, str, str | None, str | None, int | None, int | None] | None
            ) = None
            try:
                with self._lock:
                    if _only_if_run_id is not None and self._run_id != _only_if_run_id:
                        span.set_attribute("vibesensor.skipped_run_id_guard", True)
                        return self.status()
                    flush_snapshot = self._sample_flush.pending_flush_snapshot()
                    if flush_snapshot is not None:
                        self._sample_flush.append_records(
                            flush_snapshot.run_id,
                            flush_snapshot.start_time_utc,
                            flush_snapshot.start_mono_s,
                            refresh_metrics=True,
                        )
                    if _only_if_run_id is not None and self._run_id != _only_if_run_id:
                        span.set_attribute("vibesensor.skipped_run_id_guard", True)
                        return self.status()
                    run_id = self._run_id
                    run_id_to_analyze = self._persistence.ready_for_analysis(run_id)
                    start_time_utc = self._lifecycle.start_time_utc or utc_now_iso()
                    end_time_utc = utc_now_iso()
                    persistence_snapshot = self._persistence.status_snapshot()
                    ingest_drop_losses = _udp_ingest_drop_sensor_losses(
                        self.registry,
                        baseline=self._run_ingest_drop_baseline,
                    )
                    if run_id:
                        manifest = self._raw_capture.finalize_run(
                            run_id,
                            sensor_losses=ingest_drop_losses,
                        )
                        if manifest is not None:
                            self._finalized_raw_capture_manifests[run_id] = manifest
                    if run_id and not self._persistence.finalize_run(
                        run_id,
                        start_time_utc,
                        end_time_utc,
                    ):
                        LOGGER.warning(
                            "finalize_run failed for %s; scheduling analysis anyway",
                            run_id,
                        )
                    if run_id is not None:
                        lifecycle_event = (
                            "stopped",
                            run_id,
                            start_time_utc,
                            end_time_utc,
                            reason,
                            persistence_snapshot.written_sample_count,
                            persistence_snapshot.dropped_sample_count,
                        )
                    self._lifecycle.stop()
                    self._active_run_context = None
                    self._run_sensor_snapshots = {}
                    self._persistence.reset()
                    self._run_ingest_drop_baseline = None
                    result = self.status()
            except Exception as exc:
                mark_span_error(span, exc)
                raise
            span.set_attribute("vibesensor.run_id", lifecycle_event[1] if lifecycle_event else "")
            span.set_attribute("vibesensor.post_analysis_scheduled", bool(run_id_to_analyze))
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
            self.schedule_post_analysis(run_id_to_analyze)
        return result

    def schedule_post_analysis(self, run_id: str) -> None:
        self._post_analysis.schedule(run_id)

    def wait_for_post_analysis(self, timeout_s: float = 30.0) -> bool:
        return self._post_analysis.wait(timeout_s)

    def shutdown_post_analysis(self, timeout_s: float = 5.0) -> bool:
        return self._post_analysis.shutdown(timeout_s)

    def shutdown_report(self, timeout_s: float = 30.0) -> _recorder_types.RecorderShutdownReport:
        return _recorder_types._shutdown_report(self, timeout_s)

    def shutdown(self, timeout_s: float = 30.0) -> bool:
        return self.shutdown_report(timeout_s).completed

    def shutdown_raw_capture(self, timeout_s: float = 5.0) -> bool:
        return self._raw_capture.shutdown(timeout_s)

    async def run(self) -> None:
        await _recorder_runtime.run_loop(self, logger=LOGGER)


def _snapshot_raw_capture_sensor_sync(
    registry: ClientTracker,
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
) -> RawCaptureClockProofState:
    if sync_offset_us is None or sync_rtt_us is None or last_sync_monotonic_us is None:
        return "missing_sync"
    if observed_monotonic_us < last_sync_monotonic_us:
        return "stale_sync"
    if (observed_monotonic_us - last_sync_monotonic_us) > _RAW_CAPTURE_MAX_SYNC_AGE_US:
        return "stale_sync"
    if sync_rtt_us > _RAW_CAPTURE_MAX_SYNC_RTT_US:
        return "high_rtt"
    return "verified"


def _int_attr(value: object, name: str) -> int | None:
    raw_value = getattr(value, name, None)
    return int(raw_value) if isinstance(raw_value, int) else None


def _snapshot_server_queue_drops(registry: ClientTracker) -> dict[str, int]:
    client_ids: set[str] = set()
    client_snapshots = getattr(registry, "client_snapshots", None)
    if callable(client_snapshots):
        for client_snapshot in client_snapshots():
            client_id = str(getattr(client_snapshot, "client_id", "") or "").strip()
            if client_id:
                client_ids.add(client_id)
    else:
        client_ids.update(str(client_id) for client_id in registry.active_client_ids())
    queue_drop_snapshot: dict[str, int] = {}
    for client_id in sorted(client_ids):
        record = registry.get(client_id)
        if record is None:
            continue
        queue_drop_snapshot[client_id] = _int_attr(record, "server_queue_drops") or 0
    return queue_drop_snapshot


def _udp_ingest_drop_sensor_losses(
    registry: ClientTracker,
    *,
    baseline: dict[str, int] | None,
) -> dict[str, RawCaptureLossStats] | None:
    current = _snapshot_server_queue_drops(registry)
    client_ids = set(current) | set(baseline or {})
    if not client_ids:
        return None
    losses: dict[str, RawCaptureLossStats] = {}
    for client_id in sorted(client_ids):
        delta = max(0, current.get(client_id, 0) - (baseline or {}).get(client_id, 0))
        if delta <= 0:
            continue
        losses[client_id] = RawCaptureLossStats(udp_ingest_queue_drop_count=delta)
    return losses or None
