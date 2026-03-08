"""Metrics recording orchestrator.

``MetricsLogger`` coordinates recording lifecycle and delegates focused work to:

- :mod:`vibesensor.metrics_log.sample_builder` — pure sample record
  construction.
- :mod:`vibesensor.metrics_log.live_analysis` — rolling live snapshot storage.
- :mod:`vibesensor.metrics_log.persistence` — history DB create/append/finalize
  coordination.
- :mod:`vibesensor.metrics_log.post_analysis` — background analysis
  thread/queue.
- :mod:`vibesensor.metrics_log.session_state` — explicit recording-session
  state.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING
from uuid import uuid4

from ..constants import NUMERIC_TYPES
from ..runlog import utc_now_iso
from .live_analysis import LiveAnalysisWindow
from .persistence import MetricsPersistenceCoordinator
from .post_analysis import PostAnalysisWorker
from .sample_builder import (
    _LIVE_SAMPLE_WINDOW_S,
    build_run_metadata,
    build_sample_records,
    firmware_version_for_run,
)
from .session_state import MetricsSessionSnapshot, MetricsSessionState

if TYPE_CHECKING:
    from ..analysis_settings import AnalysisSettingsStore
    from ..gps_speed import GPSSpeedMonitor
    from ..history_db import HistoryDB
    from ..payload_types import HealthPersistencePayload
    from ..processing import SignalProcessor
    from ..registry import ClientRegistry
    from ..settings_store import SettingsStore

LOGGER = logging.getLogger(__name__)

_MAX_HISTORY_CREATE_RETRIES = 5
_DB_THREAD_TIMEOUT_S: float = 10.0
"""Timeout for DB-bound asyncio.to_thread() calls; prevents a stalled DB from
blocking the metrics-logger event loop indefinitely."""


@dataclass
class MetricsLoggerConfig:
    """Static configuration bundle for :class:`MetricsLogger`."""

    enabled: bool
    log_path: Path
    metrics_log_hz: int
    sensor_model: str
    default_sample_rate_hz: int
    fft_window_size_samples: int
    fft_window_type: str = "hann"
    peak_picker_method: str = "max_peak_amp_across_axes"
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
    final_status: dict[str, str | bool | None]


class MetricsLogger:
    """Manages recording of runs, post-analysis, and history persistence."""

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
        self.log_path = config.log_path
        self.metrics_log_hz = max(1, config.metrics_log_hz)
        self.registry = registry
        self.gps_monitor = gps_monitor
        self.processor = processor
        self.analysis_settings = analysis_settings
        self._settings_store = settings_store
        self.sensor_model = config.sensor_model.strip() or "unknown"
        self.default_sample_rate_hz = int(config.default_sample_rate_hz)
        self.fft_window_size_samples = int(config.fft_window_size_samples)
        self.fft_window_type = config.fft_window_type
        self.peak_picker_method = config.peak_picker_method
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
        self._session = MetricsSessionState(
            enabled=False,
            no_data_timeout_s=config.no_data_timeout_s,
        )
        self._persistence = MetricsPersistenceCoordinator(
            history_db=history_db,
            persist_history_db=config.persist_history_db,
            metadata_builder=self._run_metadata_record,
            generation_matches=self._session.matches_generation,
        )
        self.live_analysis = LiveAnalysisWindow(
            metadata_builder=self._run_metadata_record,
            live_sample_window_s=_LIVE_SAMPLE_WINDOW_S,
        )
        self._post_analysis = PostAnalysisWorker(
            history_db=history_db,
            error_callback=self._set_last_write_error,
            clear_error_callback=self._clear_last_write_error,
        )

        if config.enabled:
            with self._lock:
                snapshot = self._start_new_session_locked()
                self._live_start_mono_s = snapshot.start_mono_s

    @property
    def enabled(self) -> bool:
        return self._session.enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._session.enabled = value

    @property
    def _run_id(self) -> str | None:
        return self._session.run_id

    @property
    def _session_generation(self) -> int:
        return self._session.session_generation

    @property
    def _run_start_utc(self) -> str | None:
        return self._session.run_start_utc

    @property
    def _run_start_mono_s(self) -> float | None:
        return self._session.run_start_mono_s

    @property
    def _history_run_created(self) -> bool:
        return self._persistence.history_run_created

    @_history_run_created.setter
    def _history_run_created(self, value: bool) -> None:
        self._persistence.history_run_created = value

    @property
    def _history_create_fail_count(self) -> int:
        return self._persistence.history_create_fail_count

    @property
    def _last_data_progress_mono_s(self) -> float | None:
        return self._session.last_data_progress_mono_s

    @_last_data_progress_mono_s.setter
    def _last_data_progress_mono_s(self, value: float | None) -> None:
        self._session.last_data_progress_mono_s = value

    @property
    def _written_sample_count(self) -> int:
        return self._persistence.written_sample_count

    @_written_sample_count.setter
    def _written_sample_count(self, value: int) -> None:
        self._persistence.written_sample_count = value

    def _start_new_session_locked(self) -> MetricsSessionSnapshot:
        snapshot = self._session.start_new_session(
            run_id=uuid4().hex,
            start_time_utc=utc_now_iso(),
            start_mono_s=time.monotonic(),
            current_total=self._active_frames_total(),
        )
        self._persistence.reset_for_new_session()
        self.live_analysis.start_session(
            run_id=snapshot.run_id,
            start_time_utc=snapshot.start_time_utc,
        )
        return snapshot

    def _stop_session_locked(self) -> None:
        self._session.stop_session()
        self._persistence.reset_for_new_session()
        self.live_analysis.stop_session()

    def _set_last_write_error(self, message: str) -> None:
        self._persistence.set_last_write_error(message)

    def _clear_last_write_error(self) -> None:
        self._persistence.clear_last_write_error()

    def _active_frames_total(self) -> int:
        _get = self.registry.get
        return sum(
            int(rec.frames_total)
            for cid in self.registry.active_client_ids()
            if (rec := _get(cid)) is not None
        )

    def _session_snapshot(self) -> MetricsSessionSnapshot | None:
        return self._session.snapshot()

    def status(self) -> dict[str, str | bool | None]:
        return self._session.status_payload(
            write_error=self._persistence.write_error,
            analysis_in_progress=self._post_analysis.is_active,
        )

    def health_snapshot(self) -> HealthPersistencePayload:
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
            except Exception:
                LOGGER.warning("Failed to read analyzing-run health snapshot", exc_info=True)
        return {
            "write_error": self._persistence.write_error,
            "analysis_in_progress": self._post_analysis.is_active,
            "analysis_queue_depth": snapshot.queue_depth,
            "analysis_queue_max_depth": snapshot.max_queue_depth,
            "analysis_active_run_id": snapshot.active_run_id,
            "analysis_started_at": snapshot.active_started_at,
            "analysis_elapsed_s": analysis_elapsed_s,
            "analysis_queue_oldest_age_s": queue_oldest_age_s,
            "analyzing_run_count": analyzing_run_count,
            "analyzing_oldest_age_s": analyzing_oldest_age_s,
        }

    def start_logging(self) -> dict[str, str | bool | None]:
        completed_run_id: str | None = None
        flush_snapshot: MetricsSessionSnapshot | None = None
        with self._lock:
            if self._session.shutdown_requested:
                LOGGER.info(
                    "Ignoring start_logging() while metrics logger shutdown is in progress."
                )
                return self.status()
            if self.enabled and self._run_id:
                flush_snapshot = self._pending_flush_snapshot_locked()
        if flush_snapshot is not None:
            self._append_records(
                flush_snapshot.run_id,
                flush_snapshot.start_time_utc,
                flush_snapshot.start_mono_s,
                session_generation=flush_snapshot.generation,
            )
        with self._lock:
            if self.enabled and self._run_id:
                completed_run_id = self._persistence.ready_for_analysis(self._run_id)
                if not self._finalize_run_locked():
                    completed_run_id = None
            snapshot = self._start_new_session_locked()
            self._live_start_mono_s = snapshot.start_mono_s
            result = self.status()
        if completed_run_id and self._history_db is not None:
            self.schedule_post_analysis(completed_run_id)
        return result

    def stop_logging(
        self, *, _only_if_generation: int | None = None
    ) -> dict[str, str | bool | None]:
        flush_snapshot: MetricsSessionSnapshot | None = None
        with self._lock:
            if _only_if_generation is not None and not self._session.matches_generation(
                _only_if_generation
            ):
                return self.status()
            flush_snapshot = self._pending_flush_snapshot_locked()
        if flush_snapshot is not None:
            self._append_records(
                flush_snapshot.run_id,
                flush_snapshot.start_time_utc,
                flush_snapshot.start_mono_s,
                session_generation=flush_snapshot.generation,
            )
        with self._lock:
            if _only_if_generation is not None and not self._session.matches_generation(
                _only_if_generation
            ):
                return self.status()
            run_id_to_analyze = self._persistence.ready_for_analysis(self._run_id)
            if self._run_id and not self._finalize_run_locked():
                run_id_to_analyze = None
            self._stop_session_locked()
            result = self.status()
        if run_id_to_analyze and self._history_db is not None:
            self.schedule_post_analysis(run_id_to_analyze)
        return result

    def analysis_snapshot(
        self,
        max_rows: int = 4000,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        return self.live_analysis.snapshot(max_rows=max_rows)

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
            fft_window_type=self.fft_window_type,
            peak_picker_method=self.peak_picker_method,
            accel_scale_g_per_lsb=self.accel_scale_g_per_lsb,
            active_car_snapshot=(
                self._settings_store.active_car_snapshot()
                if self._settings_store is not None
                else None
            ),
            language_provider=self._language_provider,
        )

    def _build_sample_records(
        self, *, run_id: str, t_s: float, timestamp_utc: str
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
        return self._session.pending_flush_snapshot(
            current_total=self._active_frames_total(),
            history_run_created=self._persistence.history_run_created,
        )

    def _ensure_history_run_created(
        self, run_id: str, start_time_utc: str, *, session_generation: int
    ) -> None:
        self._persistence.ensure_history_run_created(
            run_id,
            start_time_utc,
            session_generation=session_generation,
        )

    def _append_records(
        self,
        run_id: str,
        start_time_utc: str,
        run_start_mono_s: float,
        *,
        session_generation: int,
        prebuilt_rows: list[dict[str, object]] | None = None,
    ) -> bool:
        now_mono_s = time.monotonic()
        if not self._session.matches_generation(session_generation):
            return False
        current_total = self._active_frames_total()
        self._session.refresh_data_progress(now_mono_s=now_mono_s, current_total=current_total)
        history_created = self._persistence.history_run_created
        t_s = max(0.0, now_mono_s - run_start_mono_s)
        timestamp_utc = utc_now_iso()
        if prebuilt_rows is not None:
            rows = [{**row, "t_s": t_s, "timestamp_utc": timestamp_utc} for row in prebuilt_rows]
        else:
            rows = self._build_sample_records(run_id=run_id, t_s=t_s, timestamp_utc=timestamp_utc)
        if (
            prebuilt_rows is not None
            and rows
            and self._session.should_drop_prebuilt_rows(
                current_total=current_total,
                history_run_created=history_created,
            )
        ):
            rows = []
        if rows:
            if not self._session.matches_generation(session_generation):
                return False
            self._session.mark_rows_written(now_mono_s=now_mono_s)
            self._persistence.append_rows(
                run_id=run_id,
                start_time_utc=start_time_utc,
                rows=rows,
                session_generation=session_generation,
            )
        return self._session.matches_generation(
            session_generation
        ) and self._session.should_auto_stop(now_mono_s=now_mono_s)

    def _finalize_run_locked(self) -> bool:
        run_id = self._run_id
        if not run_id:
            return True
        start_time_utc = self._session.run_start_utc or utc_now_iso()
        end_utc = utc_now_iso()
        return self._persistence.finalize_run(run_id, start_time_utc, end_utc)

    def schedule_post_analysis(self, run_id: str) -> None:
        self._post_analysis.schedule(run_id)

    def wait_for_post_analysis(self, timeout_s: float = 30.0) -> bool:
        return self._post_analysis.wait(timeout_s)

    def shutdown_report(self, timeout_s: float = 30.0) -> MetricsShutdownReport:
        active_run_id_before_stop = self._run_id
        self._session.set_shutdown_requested(True)
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
            self._session.set_shutdown_requested(False)

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
                self.live_analysis.extend_rows(live_rows, live_t_s=live_t_s)
                snapshot = self._session_snapshot()
                if snapshot is not None:
                    no_data_timeout = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._append_records,
                            snapshot.run_id,
                            snapshot.start_time_utc,
                            snapshot.start_mono_s,
                            session_generation=snapshot.generation,
                            prebuilt_rows=live_rows,
                        ),
                        timeout=_DB_THREAD_TIMEOUT_S,
                    )
                    if no_data_timeout:
                        LOGGER.info(
                            "Auto-stopping run %s after %.1fs without new data",
                            snapshot.run_id,
                            self._session.no_data_timeout_s,
                        )
                        self.stop_logging(_only_if_generation=snapshot.generation)
            except TimeoutError:
                self._set_last_write_error("metrics logger DB call timed out")
                LOGGER.warning(
                    "Metrics logger DB call exceeded %.1fs timeout; skipping tick.",
                    _DB_THREAD_TIMEOUT_S,
                )
            except Exception as exc:
                self._set_last_write_error(f"metrics logger tick failed: {exc}")
                LOGGER.warning(
                    "Metrics logger tick failed; will retry next interval.",
                    exc_info=True,
                )
            await asyncio.sleep(interval)
