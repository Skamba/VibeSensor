"""Thin recording orchestrator around the focused run helpers."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from threading import RLock
from typing import TYPE_CHECKING
from uuid import uuid4

from vibesensor.shared.ports import (
    ClientTracker,
    RunPersistence,
    SettingsReader,
    SignalSource,
    SpeedProvider,
)
from vibesensor.shared.time_utils import utc_now_iso
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
from vibesensor.use_cases.run.run_context import build_run_context_snapshot
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
        settings_store: SettingsReader | None = None,
        language_provider: Callable[[], str] | None = None,
    ):
        self.metrics_log_hz = max(1, config.metrics_log_hz)
        self.registry = registry
        self.gps_monitor = gps_monitor
        self.processor = processor
        self._settings_store = settings_store
        self.sensor_model = config.sensor_model.strip() or "unknown"
        self.default_sample_rate_hz = int(config.default_sample_rate_hz)
        self.fft_window_size_samples = int(config.fft_window_size_samples)
        self.accel_scale_g_per_lsb = _recorder_runtime.normalize_accel_scale_g_per_lsb(
            config.accel_scale_g_per_lsb,
        )
        self._lock = RLock()
        self._history_db = history_db
        self._language_provider = language_provider
        self._live_start_mono_s = time.monotonic()
        self._active_run_context: RunContextSnapshot | None = None

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

        self._sample_flush = SampleFlushOrchestrator(
            registry=self.registry,
            gps_monitor=self.gps_monitor,
            processor=self.processor,
            analysis_settings_snapshot=self._recording_analysis_settings_snapshot,
            default_sample_rate_hz=self.default_sample_rate_hz,
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
        return _recorder_runtime.analysis_settings_snapshot(self._settings_store)

    def _live_run_context_snapshot(self) -> RunContextSnapshot:
        active_car_snapshot = (
            self._settings_store.active_car_snapshot() if self._settings_store is not None else None
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
        self._persistence.reset()
        self._live_start_mono_s = snapshot.start_mono_s
        return snapshot

    def status(self) -> RunRecorderStatusSnapshot:
        return build_run_recorder_status(
            enabled=self.enabled,
            run_id=self._run_id,
            persistence=self._persistence,
            post_analysis=self._post_analysis,
        )

    def health_snapshot(self) -> RunRecorderHealthSnapshot:
        return build_run_recorder_health_snapshot(
            history_db=self._history_db,
            persistence=self._persistence,
            post_analysis=self._post_analysis,
            logger=LOGGER,
        )

    def start_recording(self) -> RunRecorderStatusSnapshot:
        completed_run_id: str | None = None
        with self._lock:
            if self._lifecycle.shutdown_requested:
                LOGGER.info(
                    "Ignoring start_recording() while metrics logger shutdown is in progress.",
                )
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
                if run_id and not self._persistence.finalize_run(
                    run_id,
                    start_time_utc,
                    utc_now_iso(),
                ):
                    # finalize_run may fail (e.g. DB unavailable), but
                    # store_analysis handles the RECORDING→COMPLETE bypass
                    # path, so schedule analysis anyway.
                    LOGGER.warning(
                        "finalize_run failed for %s; scheduling analysis anyway",
                        run_id,
                    )
            self._start_new_run_locked()
            result = self.status()
        if completed_run_id and self._history_db is not None:
            self.schedule_post_analysis(completed_run_id)
        return result

    def stop_recording(
        self,
        *,
        _only_if_run_id: str | None = None,
    ) -> RunRecorderStatusSnapshot:
        with self._lock:
            if _only_if_run_id is not None and self._run_id != _only_if_run_id:
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
                return self.status()
            run_id = self._run_id
            run_id_to_analyze = self._persistence.ready_for_analysis(run_id)
            start_time_utc = self._lifecycle.start_time_utc or utc_now_iso()
            if run_id and not self._persistence.finalize_run(
                run_id,
                start_time_utc,
                utc_now_iso(),
            ):
                # finalize_run may fail (e.g. DB unavailable), but
                # store_analysis handles the RECORDING→COMPLETE bypass
                # path, so schedule analysis anyway.
                LOGGER.warning(
                    "finalize_run failed for %s; scheduling analysis anyway",
                    run_id,
                )
            self._lifecycle.stop()
            self._active_run_context = None
            self._persistence.reset()
            result = self.status()
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

    async def run(self) -> None:
        await _recorder_runtime.run_loop(self, logger=LOGGER)
