"""Metrics recording orchestrator.

``MetricsLogger`` coordinates recording lifecycle, session state, and
history-DB persistence in a single class.  Focused helpers live in:

- :mod:`vibesensor.metrics_log.sample_builder` — pure sample record
  construction.
- :mod:`vibesensor.metrics_log.post_analysis` — background analysis
  thread/queue.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..constants import NUMERIC_TYPES
from ..domain import Run, SessionStatus
from ..runlog import utc_now_iso
from .post_analysis import PostAnalysisWorker
from .sample_builder import (
    build_run_metadata,
    build_sample_records,
    firmware_version_for_run,
)

if TYPE_CHECKING:
    from ..analysis_settings import AnalysisSettingsStore
    from ..gps_speed import GPSSpeedMonitor
    from ..history_db import HistoryDB
    from ..processing import SignalProcessor
    from ..registry import ClientRegistry
    from ..settings_store import SettingsStore

LOGGER = logging.getLogger(__name__)

_MAX_HISTORY_CREATE_RETRIES = 5
_RETRY_COOLDOWN_BASE_S = 2.0
"""Base seconds for exponential backoff between retry cycles (doubles each cycle, capped at 10s)."""
_MAX_APPEND_RETRIES = 3
_APPEND_RETRY_DELAYS_S = (0.1, 0.3)
_DB_THREAD_TIMEOUT_S: float = 10.0
"""Timeout for DB-bound asyncio.to_thread() calls; prevents a stalled DB from
blocking the metrics-logger event loop indefinitely."""


# ---------------------------------------------------------------------------
# Return-value dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MetricsSessionSnapshot:
    run_id: str
    start_time_utc: str
    start_mono_s: float


@dataclass(frozen=True, slots=True)
class PersistenceStatusSnapshot:
    """Bulk snapshot of persistence status fields (single lock acquisition)."""

    write_error: str | None
    written_sample_count: int
    dropped_sample_count: int


@dataclass(frozen=True, slots=True)
class AppendRowsResult:
    history_created: bool
    rows_written: int


# ---------------------------------------------------------------------------
# Configuration and shutdown report
# ---------------------------------------------------------------------------


@dataclass
class MetricsLoggerConfig:
    """Static configuration bundle for :class:`MetricsLogger`."""

    enabled: bool
    metrics_log_hz: int
    sensor_model: str
    default_sample_rate_hz: int
    fft_window_size_samples: int
    accel_scale_g_per_lsb: float | None = None
    persist_history_db: bool = True
    no_data_timeout_s: float = 15.0


@dataclass(frozen=True, slots=True)
class MetricsShutdownReport:
    completed: bool
    active_run_id_before_stop: str | None
    analysis_queue_depth: int
    analysis_active_run_id: str | None
    analysis_queue_oldest_age_s: float | None
    analysis_in_progress: bool
    write_error: str | None
    final_status: dict[str, object]


class MetricsLogger:
    """Manages recording of runs, post-analysis, and history persistence.

    Session lifecycle and persistence coordination are handled inline;
    focused helpers live in sibling modules (``sample_builder``,
    ``post_analysis``).
    """

    def __init__(
        self,
        config: MetricsLoggerConfig,
        registry: ClientRegistry,
        gps_monitor: GPSSpeedMonitor,
        processor: SignalProcessor,
        analysis_settings: AnalysisSettingsStore,
        history_db: HistoryDB | None = None,
        settings_store: SettingsStore | None = None,
        language_provider: Callable[[], str] | None = None,
    ):
        self.metrics_log_hz = max(1, config.metrics_log_hz)
        self.registry = registry
        self.gps_monitor = gps_monitor
        self.processor = processor
        self.analysis_settings = analysis_settings
        self._settings_store = settings_store
        self.sensor_model = config.sensor_model.strip() or "unknown"
        self.default_sample_rate_hz = int(config.default_sample_rate_hz)
        self.fft_window_size_samples = int(config.fft_window_size_samples)
        self.accel_scale_g_per_lsb = (
            float(config.accel_scale_g_per_lsb)  # type: ignore[arg-type]
            if isinstance(config.accel_scale_g_per_lsb, NUMERIC_TYPES)
            and config.accel_scale_g_per_lsb > 0  # type: ignore[operator]
            else None
        )
        self._lock = RLock()
        self._history_db = history_db
        self._language_provider = language_provider
        self._live_start_mono_s = time.monotonic()

        # --- Session state ---
        # The Run domain object owns the session identity
        # (session_id) and lifecycle status (pending → running → stopped).
        # Infrastructure-level concerns (monotonic timestamps, frame counts,
        # timeout tracking) remain as standalone fields.
        self._diagnostic_session: Run | None = None
        self._sess_no_data_timeout_s: float = max(1.0, float(config.no_data_timeout_s))
        self._sess_run_start_utc: str | None = None
        self._sess_run_start_mono_s: float | None = None
        self._sess_last_data_progress_mono_s: float | None = None
        self._sess_start_frames_total: int = 0
        self._sess_last_active_frames_total: int = 0
        self._sess_shutdown_requested: bool = False

        # --- Persistence coordination ---
        self._persist_history_db_enabled: bool = bool(config.persist_history_db)
        self._persist_current_run_id: str | None = None
        self._persist_history_run_created: bool = False
        self._persist_history_create_fail_count: int = 0
        self._persist_retry_cycle_count: int = 0
        self._persist_written_sample_count: int = 0
        self._persist_dropped_sample_count: int = 0
        self._persist_last_write_error: str | None = None
        self._persist_retry_after_mono_s: float = 0.0
        self._persist_last_write_duration_s: float = 0.0
        self._persist_max_write_duration_s: float = 0.0

        self._post_analysis = PostAnalysisWorker(
            history_db=history_db,
            error_callback=lambda msg: setattr(self, "_persist_last_write_error", msg),
            clear_error_callback=lambda: setattr(self, "_persist_last_write_error", None),
        )

        if config.enabled:
            with self._lock:
                snapshot = self._start_new_session_locked()
                self._live_start_mono_s = snapshot.start_mono_s

    # -----------------------------------------------------------------------
    # Properties
    # -----------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        ds = self._diagnostic_session
        return ds is not None and ds.status is SessionStatus.RUNNING

    @enabled.setter
    def enabled(self, value: bool) -> None:
        # Setting ``True`` is a no-op — use ``start_logging()`` to begin a
        # new session.  Setting ``False`` gracefully stops any running session.
        if not value and self._diagnostic_session is not None:
            if self._diagnostic_session.status is SessionStatus.RUNNING:
                self._diagnostic_session.stop()
            self._diagnostic_session = None

    @property
    def last_write_duration_s(self) -> float:
        return self._persist_last_write_duration_s

    @property
    def max_write_duration_s(self) -> float:
        return self._persist_max_write_duration_s

    @property
    def _run_id(self) -> str | None:
        ds = self._diagnostic_session
        return ds.session_id if ds is not None else None

    # -----------------------------------------------------------------------
    # Session state
    # -----------------------------------------------------------------------

    def _sess_start_new(
        self,
        *,
        run_id: str,
        start_time_utc: str,
        start_mono_s: float,
        current_total: int,
    ) -> MetricsSessionSnapshot:
        with self._lock:
            session = Run(
                session_id=run_id,
                analysis_settings=dict(self.analysis_settings.snapshot()),
            )
            session.start()
            self._diagnostic_session = session
            self._sess_run_start_utc = start_time_utc
            self._sess_run_start_mono_s = start_mono_s
            self._sess_last_data_progress_mono_s = start_mono_s
            self._sess_start_frames_total = current_total
            self._sess_last_active_frames_total = current_total
            return MetricsSessionSnapshot(
                run_id=run_id,
                start_time_utc=start_time_utc,
                start_mono_s=start_mono_s,
            )

    def _sess_stop(self) -> None:
        with self._lock:
            if (
                self._diagnostic_session is not None
                and self._diagnostic_session.status is SessionStatus.RUNNING
            ):
                self._diagnostic_session.stop()
            self._diagnostic_session = None
            self._sess_run_start_utc = None
            self._sess_run_start_mono_s = None
            self._sess_last_data_progress_mono_s = None
            self._sess_start_frames_total = 0
            self._sess_last_active_frames_total = 0

    def _sess_snapshot(self) -> MetricsSessionSnapshot | None:
        with self._lock:
            if (
                not self.enabled
                or not self._run_id
                or not self._sess_run_start_utc
                or self._sess_run_start_mono_s is None
            ):
                return None
            return MetricsSessionSnapshot(
                run_id=self._run_id,
                start_time_utc=self._sess_run_start_utc,
                start_mono_s=self._sess_run_start_mono_s,
            )

    def _sess_pending_flush_snapshot(
        self,
        *,
        current_total: int,
        history_run_created: bool,
    ) -> MetricsSessionSnapshot | None:
        with self._lock:
            run_id = self._run_id
            if (
                not self.enabled
                or not run_id
                or not self._sess_run_start_utc
                or self._sess_run_start_mono_s is None
            ):
                return None
            if history_run_created:
                if current_total <= self._sess_last_active_frames_total:
                    return None
            elif current_total <= self._sess_start_frames_total:
                return None
            return MetricsSessionSnapshot(
                run_id=run_id,
                start_time_utc=self._sess_run_start_utc,
                start_mono_s=self._sess_run_start_mono_s,
            )

    def _sess_should_drop_prebuilt_rows(
        self, *, current_total: int, history_run_created: bool
    ) -> bool:
        with self._lock:
            return (not history_run_created) and current_total <= self._sess_start_frames_total

    def _sess_refresh_data_progress(self, *, now_mono_s: float, current_total: int) -> None:
        with self._lock:
            if current_total != self._sess_last_active_frames_total:
                self._sess_last_active_frames_total = current_total
                self._sess_last_data_progress_mono_s = now_mono_s

    def _sess_mark_rows_written(self, *, now_mono_s: float) -> None:
        with self._lock:
            self._sess_last_data_progress_mono_s = now_mono_s

    def _sess_should_auto_stop(self, *, now_mono_s: float) -> bool:
        with self._lock:
            if self._sess_last_data_progress_mono_s is None:
                return False
            elapsed = now_mono_s - self._sess_last_data_progress_mono_s
            return elapsed >= self._sess_no_data_timeout_s

    # -----------------------------------------------------------------------
    # Persistence coordination
    # -----------------------------------------------------------------------

    def _persist_status_snapshot(self) -> PersistenceStatusSnapshot:
        """Read all status-relevant fields under a single lock acquisition."""
        with self._lock:
            return PersistenceStatusSnapshot(
                write_error=self._persist_last_write_error,
                written_sample_count=self._persist_written_sample_count,
                dropped_sample_count=self._persist_dropped_sample_count,
            )

    def _persist_reset(self, run_id: str | None = None) -> None:
        with self._lock:
            self._persist_current_run_id = run_id
            self._persist_history_run_created = False
            self._persist_history_create_fail_count = 0
            self._persist_retry_cycle_count = 0
            self._persist_written_sample_count = 0
            self._persist_dropped_sample_count = 0
            self._persist_last_write_error = None
            self._persist_retry_after_mono_s = 0.0

    def _persist_ready_for_analysis(self, run_id: str | None) -> str | None:
        with self._lock:
            ready = (
                run_id
                and self._persist_history_run_created
                and self._persist_written_sample_count > 0
            )
            if ready:
                return run_id
            return None

    def _persist_run_id_matches(self, run_id: str) -> bool:
        return self._persist_current_run_id is not None and self._persist_current_run_id == run_id

    def _persist_ensure_history_run(
        self,
        run_id: str,
        start_time_utc: str,
    ) -> None:
        with self._lock:
            if not self._persist_run_id_matches(run_id):
                return
            if self._history_db is None or self._persist_history_run_created:
                return
            if self._persist_history_create_fail_count >= _MAX_HISTORY_CREATE_RETRIES:
                if time.monotonic() < self._persist_retry_after_mono_s:
                    return
                self._persist_retry_cycle_count += 1
                LOGGER.info(
                    "Retry cooldown expired for run %s; resetting "
                    "failure counter and retrying (cycle %d)",
                    run_id,
                    self._persist_retry_cycle_count,
                )
                self._persist_history_create_fail_count = 0
        metadata = self._run_metadata_record(run_id, start_time_utc)
        try:
            self._history_db.create_run(run_id, start_time_utc, metadata)  # type: ignore[arg-type]
            with self._lock:
                if not self._persist_run_id_matches(run_id):
                    return
                self._persist_history_run_created = True
                self._persist_history_create_fail_count = 0
                self._persist_retry_cycle_count = 0
                self._persist_retry_after_mono_s = 0.0
            self._persist_last_write_error = None
        except (sqlite3.Error, OSError) as exc:
            with self._lock:
                if not self._persist_run_id_matches(run_id):
                    return
                self._persist_history_create_fail_count += 1
                fail_count = self._persist_history_create_fail_count
                if fail_count >= _MAX_HISTORY_CREATE_RETRIES:
                    cooldown = min(
                        10.0,
                        _RETRY_COOLDOWN_BASE_S * (2**self._persist_retry_cycle_count),
                    )
                    self._persist_retry_after_mono_s = time.monotonic() + cooldown
                else:
                    cooldown = None
            msg = (
                f"history create_run failed"
                f" (attempt {fail_count}"
                f"/{_MAX_HISTORY_CREATE_RETRIES}): {exc}"
            )
            self._persist_last_write_error = msg
            if cooldown is not None:
                LOGGER.error(
                    "Persistent DB failure after %d attempts for run %s — "
                    "samples will be dropped until retry in %.1fs. Error: %s",
                    fail_count,
                    run_id,
                    cooldown,
                    exc,
                    exc_info=True,
                )
            else:
                LOGGER.warning(
                    "Failed to create history run in DB (attempt %d)",
                    fail_count,
                    exc_info=True,
                )

    def _persist_append_rows(
        self,
        *,
        run_id: str,
        start_time_utc: str,
        rows: list[dict[str, object]],
    ) -> AppendRowsResult:
        if not rows:
            return AppendRowsResult(
                history_created=self._persist_history_run_created,
                rows_written=0,
            )
        if self._history_db is not None and self._persist_history_db_enabled:
            self._persist_ensure_history_run(
                run_id,
                start_time_utc,
            )
            with self._lock:
                if not self._persist_run_id_matches(run_id):
                    return AppendRowsResult(history_created=False, rows_written=0)
                history_created = self._persist_history_run_created
            if history_created:
                last_exc: Exception | None = None
                for attempt in range(_MAX_APPEND_RETRIES):
                    try:
                        write_start = time.monotonic()
                        self._history_db.append_samples(run_id, rows)  # type: ignore[arg-type]
                        write_dur = time.monotonic() - write_start
                        with self._lock:
                            if not self._persist_run_id_matches(run_id):
                                return AppendRowsResult(history_created=True, rows_written=0)
                            self._persist_written_sample_count += len(rows)
                            self._persist_last_write_duration_s = write_dur
                            if write_dur > self._persist_max_write_duration_s:
                                self._persist_max_write_duration_s = write_dur
                        self._persist_last_write_error = None
                        return AppendRowsResult(history_created=True, rows_written=len(rows))
                    except (sqlite3.Error, OSError) as exc:
                        last_exc = exc
                        if attempt < _MAX_APPEND_RETRIES - 1:
                            time.sleep(_APPEND_RETRY_DELAYS_S[attempt])
                with self._lock:
                    self._persist_dropped_sample_count += len(rows)
                self._persist_last_write_error = f"history append_samples failed: {last_exc}"
                LOGGER.warning(
                    "Failed to append %d samples to history DB after %d attempts",
                    len(rows),
                    _MAX_APPEND_RETRIES,
                    exc_info=True,
                )
                return AppendRowsResult(history_created=True, rows_written=0)
            with self._lock:
                self._persist_dropped_sample_count += len(rows)
                fail_count = self._persist_history_create_fail_count
            LOGGER.warning(
                "Dropping %d sample(s) for run %s: history run not created (fail count %d/%d)",
                len(rows),
                run_id,
                fail_count,
                _MAX_HISTORY_CREATE_RETRIES,
            )
            return AppendRowsResult(history_created=False, rows_written=0)
        with self._lock:
            if not self._persist_run_id_matches(run_id):
                return AppendRowsResult(history_created=False, rows_written=0)
            self._persist_written_sample_count += len(rows)
        return AppendRowsResult(history_created=False, rows_written=len(rows))

    def _persist_finalize_run(self, run_id: str, start_time_utc: str, end_utc: str) -> bool:
        with self._lock:
            if not self._persist_history_run_created:
                return True
        if self._history_db is None:
            return True
        try:
            latest_metadata = self._run_metadata_record(run_id, start_time_utc)
            latest_metadata["end_time_utc"] = end_utc
            finalized = self._history_db.finalize_run(
                run_id,
                end_utc,
                metadata=latest_metadata,  # type: ignore[arg-type]
            )
            if finalized is False:
                self._persist_last_write_error = "history finalize_run skipped due to invalid state"
                LOGGER.warning(
                    "History DB finalize_run skipped for run %s",
                    run_id,
                )
                return False
            self._persist_last_write_error = None
            return True
        except (sqlite3.Error, OSError) as exc:
            self._persist_last_write_error = f"history finalize_run failed: {exc}"
            LOGGER.warning("Failed to finalize run in history DB", exc_info=True)
            return False

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _start_new_session_locked(self) -> MetricsSessionSnapshot:
        snapshot = self._sess_start_new(
            run_id=uuid4().hex,
            start_time_utc=utc_now_iso(),
            start_mono_s=time.monotonic(),
            current_total=self._active_frames_total(),
        )
        self._persist_reset(run_id=snapshot.run_id)
        return snapshot

    def _stop_session_locked(self) -> None:
        self._sess_stop()
        self._persist_reset()

    def _active_frames_total(self) -> int:
        _get = self.registry.get
        return sum(
            int(rec.frames_total)
            for cid in self.registry.active_client_ids()
            if (rec := _get(cid)) is not None
        )

    def _session_snapshot(self) -> MetricsSessionSnapshot | None:
        return self._sess_snapshot()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def status(self) -> dict[str, object]:
        post_snapshot = self._post_analysis.snapshot()
        persist = self._persist_status_snapshot()
        return {
            "enabled": self.enabled,
            "current_file": None,
            "run_id": self._run_id,
            "write_error": persist.write_error,
            "analysis_in_progress": self._post_analysis.is_active,
            "samples_written": persist.written_sample_count,
            "samples_dropped": persist.dropped_sample_count,
            "last_completed_run_id": post_snapshot.last_completed_run_id,
            "last_completed_run_error": post_snapshot.last_completed_error,
        }

    def health_snapshot(self) -> dict[str, Any]:
        snapshot = self._post_analysis.snapshot()
        analysis_elapsed_s = None
        if snapshot.active_started_at is not None:
            analysis_elapsed_s = max(0.0, time.time() - snapshot.active_started_at)
        queue_oldest_age_s = None
        if snapshot.oldest_queued_at is not None:
            queue_oldest_age_s = max(0.0, time.time() - snapshot.oldest_queued_at)
        analyzing_run_count = 0
        analyzing_oldest_age_s = None
        if self._history_db is not None:
            try:
                analyzing_health = self._history_db.analyzing_run_health()
                raw_count = analyzing_health.get("analyzing_run_count")
                analyzing_run_count = int(raw_count) if isinstance(raw_count, int | float) else 0
                raw_oldest_age = analyzing_health.get("analyzing_oldest_age_s")
                if isinstance(raw_oldest_age, (int, float)):
                    analyzing_oldest_age_s = max(0.0, float(raw_oldest_age))
            except sqlite3.Error:
                LOGGER.warning("Failed to read analyzing-run health snapshot", exc_info=True)
        persist = self._persist_status_snapshot()
        return {
            "write_error": persist.write_error,
            "analysis_in_progress": self._post_analysis.is_active,
            "analysis_queue_depth": snapshot.queue_depth,
            "analysis_queue_max_depth": snapshot.max_queue_depth,
            "analysis_active_run_id": snapshot.active_run_id,
            "analysis_started_at": snapshot.active_started_at,
            "analysis_elapsed_s": analysis_elapsed_s,
            "analysis_queue_oldest_age_s": queue_oldest_age_s,
            "analyzing_run_count": analyzing_run_count,
            "analyzing_oldest_age_s": analyzing_oldest_age_s,
            "samples_written": persist.written_sample_count,
            "samples_dropped": persist.dropped_sample_count,
            "last_completed_run_id": snapshot.last_completed_run_id,
            "last_completed_run_error": snapshot.last_completed_error,
        }

    def start_logging(self) -> dict[str, object]:
        completed_run_id: str | None = None
        flush_snapshot: MetricsSessionSnapshot | None = None
        with self._lock:
            if self._sess_shutdown_requested:
                LOGGER.info(
                    "Ignoring start_logging() while metrics logger shutdown is in progress.",
                )
                return self.status()
            if self.enabled and self._run_id:
                flush_snapshot = self._pending_flush_snapshot_locked()
        if flush_snapshot is not None:
            self._append_records(
                flush_snapshot.run_id,
                flush_snapshot.start_time_utc,
                flush_snapshot.start_mono_s,
            )
        with self._lock:
            if self.enabled and self._run_id:
                completed_run_id = self._persist_ready_for_analysis(self._run_id)
                if not self._finalize_run_locked():
                    completed_run_id = None
            snapshot = self._start_new_session_locked()
            self._live_start_mono_s = snapshot.start_mono_s
            result = self.status()
        if completed_run_id and self._history_db is not None:
            self.schedule_post_analysis(completed_run_id)
        return result

    def stop_logging(
        self,
        *,
        _only_if_run_id: str | None = None,
    ) -> dict[str, object]:
        flush_snapshot: MetricsSessionSnapshot | None = None
        with self._lock:
            if _only_if_run_id is not None and self._run_id != _only_if_run_id:
                return self.status()
            flush_snapshot = self._pending_flush_snapshot_locked()
        if flush_snapshot is not None:
            self._append_records(
                flush_snapshot.run_id,
                flush_snapshot.start_time_utc,
                flush_snapshot.start_mono_s,
            )
        with self._lock:
            if _only_if_run_id is not None and self._run_id != _only_if_run_id:
                return self.status()
            run_id_to_analyze = self._persist_ready_for_analysis(self._run_id)
            if self._run_id and not self._finalize_run_locked():
                run_id_to_analyze = None
            self._stop_session_locked()
            result = self.status()
        if run_id_to_analyze and self._history_db is not None:
            self.schedule_post_analysis(run_id_to_analyze)
        return result

    def _run_metadata_record(self, run_id: str, start_time_utc: str) -> dict[str, object]:
        return build_run_metadata(
            run_id=run_id,
            start_time_utc=start_time_utc,
            analysis_settings_snapshot=self.analysis_settings.snapshot(),
            sensor_model=self.sensor_model,
            firmware_version=firmware_version_for_run(self.registry),
            default_sample_rate_hz=self.default_sample_rate_hz,
            metrics_log_hz=self.metrics_log_hz,
            fft_window_size_samples=self.fft_window_size_samples,
            accel_scale_g_per_lsb=self.accel_scale_g_per_lsb,
            active_car_snapshot=(
                self._settings_store.active_car_snapshot()
                if self._settings_store is not None
                else None
            ),
            language_provider=self._language_provider,
        )

    def _build_sample_records(
        self,
        *,
        run_id: str,
        t_s: float,
        timestamp_utc: str,
    ) -> list[dict[str, object]]:
        return build_sample_records(
            run_id=run_id,
            t_s=t_s,
            timestamp_utc=timestamp_utc,
            registry=self.registry,
            processor=self.processor,
            gps_monitor=self.gps_monitor,
            analysis_settings_snapshot=self.analysis_settings.snapshot(),
            default_sample_rate_hz=self.default_sample_rate_hz,
        )

    def _pending_flush_snapshot_locked(self) -> MetricsSessionSnapshot | None:
        return self._sess_pending_flush_snapshot(
            current_total=self._active_frames_total(),
            history_run_created=self._persist_history_run_created,
        )

    def _append_records(
        self,
        run_id: str,
        start_time_utc: str,
        run_start_mono_s: float,
        *,
        prebuilt_rows: list[dict[str, object]] | None = None,
    ) -> bool:
        now_mono_s = time.monotonic()
        if self._run_id != run_id:
            return False
        current_total = self._active_frames_total()
        self._sess_refresh_data_progress(now_mono_s=now_mono_s, current_total=current_total)
        history_created = self._persist_history_run_created
        t_s = max(0.0, now_mono_s - run_start_mono_s)
        timestamp_utc = utc_now_iso()
        if prebuilt_rows is not None:
            rows = [{**row, "t_s": t_s, "timestamp_utc": timestamp_utc} for row in prebuilt_rows]
        else:
            rows = self._build_sample_records(run_id=run_id, t_s=t_s, timestamp_utc=timestamp_utc)
        if (
            prebuilt_rows is not None
            and rows
            and self._sess_should_drop_prebuilt_rows(
                current_total=current_total,
                history_run_created=history_created,
            )
        ):
            rows = []
        if rows:
            if self._run_id != run_id:
                return False
            self._sess_mark_rows_written(now_mono_s=now_mono_s)
            self._persist_append_rows(
                run_id=run_id,
                start_time_utc=start_time_utc,
                rows=rows,
            )
        return (self._run_id == run_id) and self._sess_should_auto_stop(now_mono_s=now_mono_s)

    def _finalize_run_locked(self) -> bool:
        run_id = self._run_id
        if not run_id:
            return True
        start_time_utc = self._sess_run_start_utc or utc_now_iso()
        end_utc = utc_now_iso()
        return self._persist_finalize_run(run_id, start_time_utc, end_utc)

    def schedule_post_analysis(self, run_id: str) -> None:
        self._post_analysis.schedule(run_id)

    def wait_for_post_analysis(self, timeout_s: float = 30.0) -> bool:
        return self._post_analysis.wait(timeout_s)

    def shutdown_report(self, timeout_s: float = 30.0) -> MetricsShutdownReport:
        with self._lock:
            active_run_id_before_stop = self._run_id
        self._sess_shutdown_requested = True
        try:
            final_status = self.stop_logging()
            analysis_completed = self.wait_for_post_analysis(timeout_s)
            health = self.health_snapshot()
            return MetricsShutdownReport(
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
            self._sess_shutdown_requested = False

    def shutdown(self, timeout_s: float = 30.0) -> bool:
        return self.shutdown_report(timeout_s).completed

    async def run(self) -> None:
        interval = 1.0 / self.metrics_log_hz
        while True:
            try:
                timestamp_utc = utc_now_iso()
                with self._lock:
                    live_start = self._live_start_mono_s
                    run_id_for_live = self._run_id or "live"
                live_t_s = max(0.0, time.monotonic() - live_start)
                live_rows = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._build_sample_records,
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
                snapshot = self._session_snapshot()
                if snapshot is not None:
                    no_data_timeout = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._append_records,
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
                            self._sess_no_data_timeout_s,
                        )
                        self.stop_logging(_only_if_run_id=snapshot.run_id)
            except TimeoutError:
                self._persist_last_write_error = "metrics logger DB call timed out"
                LOGGER.warning(
                    "Metrics logger DB call exceeded %.1fs timeout; skipping tick.",
                    _DB_THREAD_TIMEOUT_S,
                )
            except Exception as exc:
                self._persist_last_write_error = f"metrics logger tick failed: {exc}"
                LOGGER.warning(
                    "Metrics logger tick failed; will retry next interval.",
                    exc_info=True,
                )
            await asyncio.sleep(interval)
