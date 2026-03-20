"""Metrics recording orchestrator.

``RunRecorder`` coordinates the recording loop, lifecycle delegation, and
history-DB persistence. Focused helpers live in:

- :mod:`vibesensor.use_cases.run.persistence_writer` — history-write
  coordination, retry/backoff handling, and persistence health state.
- :mod:`vibesensor.use_cases.run.sample_flush` — sample building, flush
  decisions, and auto-stop timing checks.
- :mod:`vibesensor.use_cases.run.lifecycle_state` — in-memory recording
  session lifecycle state.
- :mod:`vibesensor.use_cases.run.sample_builder` — pure sample record
  construction.
- :mod:`vibesensor.use_cases.run.post_analysis` — background analysis
  thread/queue plus the injected post-stop analysis boundary.
- :mod:`vibesensor.use_cases.run.status_reporting` — status and health
  payload assembly above persistence/post-analysis collaborators.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4

from vibesensor.domain.snapshots import AnalysisSettingsSnapshot
from vibesensor.shared.constants import NUMERIC_TYPES
from vibesensor.shared.ports import (
    ClientTracker,
    RunPersistence,
    SettingsReader,
    SignalSource,
    SpeedProvider,
)
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.health_snapshot import RunRecorderHealthSnapshot
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.run.lifecycle_state import ActiveRunSnapshot, RunLifecycleState
from vibesensor.use_cases.run.persistence_writer import (
    _APPEND_RETRY_DELAYS_S,
    _MAX_APPEND_RETRIES,
    _MAX_HISTORY_CREATE_RETRIES,
    _RETRY_COOLDOWN_BASE_S,
    RunPersistenceWriter,
)
from vibesensor.use_cases.run.post_analysis import PostAnalysisWorker, build_post_analysis_summary
from vibesensor.use_cases.run.sample_builder import build_run_metadata, firmware_version_for_run
from vibesensor.use_cases.run.sample_flush import SampleFlushOrchestrator
from vibesensor.use_cases.run.status_reporting import (
    build_run_recorder_health_snapshot,
    build_run_recorder_status,
)

LOGGER = logging.getLogger(__name__)

__all__ = [
    "RecorderShutdownReport",
    "RunRecorder",
    "RunRecorderConfig",
    "_APPEND_RETRY_DELAYS_S",
    "_MAX_APPEND_RETRIES",
    "_MAX_HISTORY_CREATE_RETRIES",
    "_RETRY_COOLDOWN_BASE_S",
]

_DB_THREAD_TIMEOUT_S: float = 10.0
"""Timeout for DB-bound asyncio.to_thread() calls; prevents a stalled DB from
blocking the metrics-logger event loop indefinitely."""


# ---------------------------------------------------------------------------
# Configuration and shutdown report
# ---------------------------------------------------------------------------


@dataclass
class RunRecorderConfig:
    """Static configuration bundle for :class:`RunRecorder`."""

    metrics_log_hz: int
    sensor_model: str
    default_sample_rate_hz: int
    fft_window_size_samples: int
    accel_scale_g_per_lsb: float | None = None
    persist_history_db: bool = True
    no_data_timeout_s: float = 15.0


@dataclass(frozen=True, slots=True)
class RecorderShutdownReport:
    completed: bool
    active_run_id_before_stop: str | None
    analysis_queue_depth: int
    analysis_active_run_id: str | None
    analysis_queue_oldest_age_s: float | None
    analysis_in_progress: bool
    write_error: str | None
    final_status: dict[str, object]


def _build_run_metadata_record(
    recorder: RunRecorder,
    run_id: str,
    start_time_utc: str,
) -> JsonObject:
    return build_run_metadata(
        run_id=run_id,
        start_time_utc=start_time_utc,
        analysis_settings_snapshot=recorder._analysis_settings_snapshot(),
        sensor_model=recorder.sensor_model,
        firmware_version=firmware_version_for_run(recorder.registry),
        default_sample_rate_hz=recorder.default_sample_rate_hz,
        metrics_log_hz=recorder.metrics_log_hz,
        fft_window_size_samples=recorder.fft_window_size_samples,
        accel_scale_g_per_lsb=recorder.accel_scale_g_per_lsb,
        active_car_snapshot=(
            recorder._settings_store.active_car_snapshot()
            if recorder._settings_store is not None
            else None
        ),
        language_provider=recorder._language_provider,
    )


def _shutdown_report(recorder: RunRecorder, timeout_s: float) -> RecorderShutdownReport:
    with recorder._lock:
        active_run_id_before_stop = recorder._run_id
    recorder._lifecycle.shutdown_requested = True
    try:
        final_status = recorder.stop_recording()
        analysis_completed = recorder.wait_for_post_analysis(timeout_s)
        health = recorder.health_snapshot()
        return RecorderShutdownReport(
            completed=analysis_completed,
            active_run_id_before_stop=active_run_id_before_stop,
            analysis_queue_depth=health["analysis_queue_depth"],
            analysis_active_run_id=health["analysis_active_run_id"],
            analysis_queue_oldest_age_s=health["analysis_queue_oldest_age_s"],
            analysis_in_progress=health["analysis_in_progress"],
            write_error=health["write_error"],
            final_status=final_status,
        )
    finally:
        recorder._lifecycle.shutdown_requested = False


async def _run_loop(recorder: RunRecorder) -> None:
    interval = 1.0 / recorder.metrics_log_hz
    while True:
        try:
            timestamp_utc = utc_now_iso()
            with recorder._lock:
                live_start = recorder._live_start_mono_s
                run_id_for_live = recorder._run_id or "live"
            live_t_s = max(0.0, time.monotonic() - live_start)
            live_rows = await asyncio.wait_for(
                asyncio.to_thread(
                    recorder._sample_flush.build_sample_records,
                    run_id=run_id_for_live,
                    t_s=live_t_s,
                    timestamp_utc=timestamp_utc,
                ),
                timeout=_DB_THREAD_TIMEOUT_S,
            )
            if not isinstance(live_rows, list):
                LOGGER.warning(
                    "Metrics logger sample builder returned %s instead of list; dropping tick.",
                    type(live_rows).__name__,
                )
                live_rows = []
            snapshot = recorder._session_snapshot()
            if snapshot is not None:
                no_data_timeout = await asyncio.wait_for(
                    asyncio.to_thread(
                        recorder._sample_flush.append_records,
                        snapshot.run_id,
                        snapshot.start_time_utc,
                        snapshot.start_mono_s,
                        prebuilt_rows=live_rows,
                    ),
                    timeout=_DB_THREAD_TIMEOUT_S,
                )
                if no_data_timeout:
                    LOGGER.info(
                        "Auto-stopping run %s after %.1fs without new data",
                        snapshot.run_id,
                        recorder._lifecycle.no_data_timeout_s,
                    )
                    recorder.stop_recording(_only_if_run_id=snapshot.run_id)
        except TimeoutError:
            recorder._persistence.set_last_write_error("metrics logger DB call timed out")
            LOGGER.warning(
                "Metrics logger DB call exceeded %.1fs timeout; skipping tick.",
                _DB_THREAD_TIMEOUT_S,
            )
        except Exception as exc:
            recorder._persistence.set_last_write_error(f"metrics logger tick failed: {exc}")
            LOGGER.warning(
                "Metrics logger tick failed; will retry next interval.",
                exc_info=True,
            )
        await asyncio.sleep(interval)


class RunRecorder:
    """Manages recording of runs, post-analysis, and history persistence."""

    def __init__(
        self,
        config: RunRecorderConfig,
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
        self.accel_scale_g_per_lsb = (
            float(config.accel_scale_g_per_lsb)
            if isinstance(config.accel_scale_g_per_lsb, NUMERIC_TYPES)
            and config.accel_scale_g_per_lsb > 0
            else None
        )
        self._lock = RLock()
        self._history_db = history_db
        self._language_provider = language_provider
        self._live_start_mono_s = time.monotonic()

        # --- Session lifecycle ---
        self._lifecycle = RunLifecycleState(
            no_data_timeout_s=max(1.0, float(config.no_data_timeout_s)),
        )

        # --- Persistence coordination ---
        self._persistence = RunPersistenceWriter(
            lock=self._lock,
            history_db=history_db,
            persist_history_db_enabled=config.persist_history_db,
            run_id_matches=self._run_id_matches,
            metadata_builder=lambda run_id, start_time_utc: _build_run_metadata_record(
                self,
                run_id,
                start_time_utc,
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
            analysis_settings_snapshot=self._analysis_settings_snapshot,
            default_sample_rate_hz=self.default_sample_rate_hz,
            lifecycle=self._lifecycle,
            persistence=self._persistence,
            active_frames_total=self._active_frames_total,
            current_run_id=lambda: self._run_id,
            monotonic=lambda: time.monotonic(),
        )

        with self._lock:
            snapshot = self._lifecycle.start_new_run(
                run_id=uuid4().hex,
                analysis_settings_snapshot=self._analysis_settings_snapshot(),
                start_time_utc=utc_now_iso(),
                start_mono_s=time.monotonic(),
                current_total=self._active_frames_total(),
            )
            self._persistence.reset()
            self._live_start_mono_s = snapshot.start_mono_s

    # -----------------------------------------------------------------------
    # Properties
    # -----------------------------------------------------------------------

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
        if self._settings_store is not None:
            return self._settings_store.analysis_settings_snapshot()
        return AnalysisSettingsSnapshot.from_dict(AnalysisSettingsSnapshot.DEFAULTS)

    def _active_frames_total(self) -> int:
        _get = self.registry.get
        return sum(
            int(rec.frames_total)
            for cid in self.registry.active_client_ids()
            if (rec := _get(cid)) is not None
        )

    def _session_snapshot(self) -> ActiveRunSnapshot | None:
        return self._lifecycle.snapshot()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def status(self) -> dict[str, object]:
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

    def start_recording(self) -> dict[str, object]:
        completed_run_id: str | None = None
        flush_snapshot: ActiveRunSnapshot | None = None
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
            )
        with self._lock:
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
            snapshot = self._lifecycle.start_new_run(
                run_id=uuid4().hex,
                analysis_settings_snapshot=self._analysis_settings_snapshot(),
                start_time_utc=utc_now_iso(),
                start_mono_s=time.monotonic(),
                current_total=self._active_frames_total(),
            )
            self._persistence.reset()
            self._live_start_mono_s = snapshot.start_mono_s
            result = self.status()
        if completed_run_id and self._history_db is not None:
            self.schedule_post_analysis(completed_run_id)
        return result

    def stop_recording(
        self,
        *,
        _only_if_run_id: str | None = None,
    ) -> dict[str, object]:
        flush_snapshot: ActiveRunSnapshot | None = None
        with self._lock:
            if _only_if_run_id is not None and self._run_id != _only_if_run_id:
                return self.status()
            flush_snapshot = self._sample_flush.pending_flush_snapshot()
        if flush_snapshot is not None:
            self._sample_flush.append_records(
                flush_snapshot.run_id,
                flush_snapshot.start_time_utc,
                flush_snapshot.start_mono_s,
            )
        with self._lock:
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
            self._persistence.reset()
            result = self.status()
        if run_id_to_analyze and self._history_db is not None:
            self.schedule_post_analysis(run_id_to_analyze)
        return result

    def schedule_post_analysis(self, run_id: str) -> None:
        self._post_analysis.schedule(run_id)

    def wait_for_post_analysis(self, timeout_s: float = 30.0) -> bool:
        return self._post_analysis.wait(timeout_s)

    def shutdown_report(self, timeout_s: float = 30.0) -> RecorderShutdownReport:
        return _shutdown_report(self, timeout_s)

    def shutdown(self, timeout_s: float = 30.0) -> bool:
        return self.shutdown_report(timeout_s).completed

    async def run(self) -> None:
        await _run_loop(self)
