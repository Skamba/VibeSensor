"""Metrics recording orchestrator.

``MetricsLogger`` coordinates session lifecycle, data persistence, and the
live-sample buffer.  Heavy-lifting is delegated to:

- :mod:`~vibesensor.metrics_log.sample_builder` — pure sample record
  construction.
- :mod:`~vibesensor.metrics_log.post_analysis` — background analysis
  thread/queue.
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
from .post_analysis import PostAnalysisWorker
from .sample_builder import (
    _LIVE_SAMPLE_WINDOW_S,
    build_run_metadata,
    build_sample_records,
    firmware_version_for_run,
)

if TYPE_CHECKING:
    from ..analysis_settings import AnalysisSettingsStore
    from ..gps_speed import GPSSpeedMonitor
    from ..history_db import HistoryDB
    from ..payload_types import HealthPersistencePayload
    from ..processing import SignalProcessor
    from ..registry import ClientRegistry

LOGGER = logging.getLogger(__name__)

_MAX_HISTORY_CREATE_RETRIES = 5
_DB_THREAD_TIMEOUT_S: float = 10.0
"""Timeout for DB-bound asyncio.to_thread() calls; prevents a stalled DB from
blocking the metrics-logger event loop indefinitely."""


@dataclass
class MetricsLoggerConfig:
    """Static configuration bundle for :class:`MetricsLogger`.

    Separates the immutable configuration knobs from the runtime collaborators
    so that :meth:`MetricsLogger.__init__` has a manageable signature.
    """

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
        language_provider: Callable[[], str] | None = None,
    ):
        self.enabled = bool(config.enabled)
        self.log_path = config.log_path
        self.metrics_log_hz = max(1, config.metrics_log_hz)
        self.registry = registry
        self.gps_monitor = gps_monitor
        self.processor = processor
        self.analysis_settings = analysis_settings
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
        self._run_id: str | None = None
        self._run_start_utc: str | None = None
        self._run_start_mono_s: float | None = None
        self._last_write_error: str | None = None
        self._history_db = history_db
        self._persist_history_db = bool(config.persist_history_db)
        self._language_provider = language_provider
        self._history_run_created = False
        self._history_create_fail_count = 0
        self._written_sample_count = 0
        self._no_data_timeout_s = max(1.0, float(config.no_data_timeout_s))
        self._last_data_progress_mono_s: float | None = None
        self._session_generation: int = 0
        self._session_start_frames_total = 0
        self._last_active_frames_total = 0
        self._live_start_mono_s = time.monotonic()
        self.live_analysis = LiveAnalysisWindow(
            metadata_builder=self._run_metadata_record,
            live_sample_window_s=_LIVE_SAMPLE_WINDOW_S,
        )

        # Delegate analysis to PostAnalysisWorker
        self._post_analysis = PostAnalysisWorker(
            history_db=history_db,
            error_callback=self._set_last_write_error,
            clear_error_callback=self._clear_last_write_error,
        )

        if self.enabled:
            self._start_new_session_locked()

    # -- session lifecycle ----------------------------------------------------

    def _start_new_session_locked(self) -> None:
        self._session_generation += 1
        self._run_id = uuid4().hex
        self._run_start_utc = utc_now_iso()
        self._run_start_mono_s = time.monotonic()
        self._last_write_error = None
        self._history_run_created = False
        self._history_create_fail_count = 0
        self._written_sample_count = 0
        self._last_data_progress_mono_s = self._run_start_mono_s
        self._session_start_frames_total = self._active_frames_total()
        self._last_active_frames_total = self._session_start_frames_total
        assert self._run_id is not None
        assert self._run_start_utc is not None
        self.live_analysis.start_session(
            run_id=self._run_id,
            start_time_utc=self._run_start_utc,
        )

    def _set_last_write_error(self, message: str) -> None:
        with self._lock:
            self._last_write_error = message

    def _clear_last_write_error(self) -> None:
        with self._lock:
            self._last_write_error = None

    def _active_frames_total(self) -> int:
        _get = self.registry.get
        return sum(
            int(rec.frames_total)
            for cid in self.registry.active_client_ids()
            if (rec := _get(cid)) is not None
        )

    def _refresh_data_progress_marker(self, now_mono_s: float) -> None:
        """Update data-progress tracking.

        Must be called while holding ``self._lock``.
        """
        current_total = self._active_frames_total()
        if current_total != self._last_active_frames_total:
            self._last_active_frames_total = current_total
            self._last_data_progress_mono_s = now_mono_s

    def _session_snapshot(self) -> tuple[str, str, float, int] | None:
        with self._lock:
            if (
                not self.enabled
                or not self._run_id
                or not self._run_start_utc
                or self._run_start_mono_s is None
            ):
                return None
            return (
                self._run_id,
                self._run_start_utc,
                self._run_start_mono_s,
                self._session_generation,
            )

    # -- public API -----------------------------------------------------------

    def status(self) -> dict[str, str | bool | None]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "current_file": None,
                "run_id": self._run_id,
                "write_error": self._last_write_error,
                "analysis_in_progress": self._post_analysis.is_active,
            }

    def health_snapshot(self) -> HealthPersistencePayload:
        with self._lock:
            return {
                "write_error": self._last_write_error,
                "analysis_in_progress": self._post_analysis.is_active,
            }

    def start_logging(self) -> dict[str, str | bool | None]:
        completed_run_id: str | None = None
        flush_snapshot: tuple[str, str, float, int] | None = None
        with self._lock:
            if self.enabled and self._run_id:
                flush_snapshot = self._pending_flush_snapshot_locked()
        if flush_snapshot is not None:
            run_id, start_time_utc, start_mono_s, generation = flush_snapshot
            self._append_records(
                run_id,
                start_time_utc,
                start_mono_s,
                session_generation=generation,
            )
        with self._lock:
            if self.enabled and self._run_id:
                if self._history_run_created and self._written_sample_count > 0:
                    completed_run_id = self._run_id
                if not self._finalize_run_locked():
                    completed_run_id = None
            self.enabled = True
            self._start_new_session_locked()
            self._live_start_mono_s = self._run_start_mono_s or time.monotonic()
            result = self.status()
        if completed_run_id and self._history_db is not None:
            self.schedule_post_analysis(completed_run_id)
        return result

    def stop_logging(
        self, *, _only_if_generation: int | None = None
    ) -> dict[str, str | bool | None]:
        flush_snapshot: tuple[str, str, float, int] | None = None
        with self._lock:
            if _only_if_generation is not None and self._session_generation != _only_if_generation:
                return self.status()
            flush_snapshot = self._pending_flush_snapshot_locked()
        if flush_snapshot is not None:
            run_id, start_time_utc, start_mono_s, generation = flush_snapshot
            self._append_records(
                run_id,
                start_time_utc,
                start_mono_s,
                session_generation=generation,
            )
        with self._lock:
            if _only_if_generation is not None and self._session_generation != _only_if_generation:
                return self.status()
            run_id_to_analyze: str | None = None
            if self.enabled and self._run_id:
                if self._history_run_created and self._written_sample_count > 0:
                    run_id_to_analyze = self._run_id
                finalized_ok = self._finalize_run_locked()
                if not finalized_ok:
                    run_id_to_analyze = None
            self._session_generation += 1
            self.enabled = False
            self._run_id = None
            self._run_start_utc = None
            self._run_start_mono_s = None
            self._last_write_error = None
            self._history_run_created = False
            self._history_create_fail_count = 0
            self._written_sample_count = 0
            self._last_data_progress_mono_s = None
            self._session_start_frames_total = 0
            self._last_active_frames_total = 0
            self.live_analysis.stop_session()
            result = self.status()
        if run_id_to_analyze and self._history_db is not None:
            self.schedule_post_analysis(run_id_to_analyze)
        return result

    def analysis_snapshot(
        self,
        max_rows: int = 4000,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        return self.live_analysis.snapshot(max_rows=max_rows)

    # -- metadata & sample building -------------------------------------------

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

    def _pending_flush_snapshot_locked(self) -> tuple[str, str, float, int] | None:
        if (
            not self.enabled
            or not self._run_id
            or not self._run_start_utc
            or self._run_start_mono_s is None
        ):
            return None
        current_total = self._active_frames_total()
        if self._history_run_created:
            if current_total <= self._last_active_frames_total:
                return None
        elif current_total <= self._session_start_frames_total:
            return None
        return (
            self._run_id,
            self._run_start_utc,
            self._run_start_mono_s,
            self._session_generation,
        )

    # -- persistence ----------------------------------------------------------

    def _ensure_history_run_created(
        self, run_id: str, start_time_utc: str, *, session_generation: int
    ) -> None:
        with self._lock:
            if self._session_generation != session_generation:
                return
            if self._history_db is None or self._history_run_created:
                return
            if self._history_create_fail_count >= _MAX_HISTORY_CREATE_RETRIES:
                return
        metadata = self._run_metadata_record(run_id, start_time_utc)
        try:
            self._history_db.create_run(run_id, start_time_utc, metadata)
            with self._lock:
                if self._session_generation != session_generation:
                    return
                self._history_run_created = True
                self._history_create_fail_count = 0
            self._clear_last_write_error()
        except Exception as exc:
            with self._lock:
                if self._session_generation != session_generation:
                    return
                self._history_create_fail_count += 1
                fail_count = self._history_create_fail_count
            msg = (
                f"history create_run failed"
                f" (attempt {fail_count}"
                f"/{_MAX_HISTORY_CREATE_RETRIES}): {exc}"
            )
            self._set_last_write_error(msg)
            if fail_count >= _MAX_HISTORY_CREATE_RETRIES:
                LOGGER.error(
                    "Persistent DB failure: giving up after %d attempts for run %s — "
                    "all subsequent samples will be dropped. Error: %s",
                    fail_count,
                    run_id,
                    exc,
                    exc_info=True,
                )
            else:
                LOGGER.warning(
                    "Failed to create history run in DB (attempt %d)",
                    fail_count,
                    exc_info=True,
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
        with self._lock:
            if self._session_generation != session_generation:
                return False
            previous_total = self._last_active_frames_total
            current_total = self._active_frames_total()
            if current_total != previous_total:
                self._last_active_frames_total = current_total
                self._last_data_progress_mono_s = now_mono_s
            history_created = self._history_run_created
            session_start_total = self._session_start_frames_total
        t_s = max(0.0, now_mono_s - run_start_mono_s)
        timestamp_utc = utc_now_iso()
        if prebuilt_rows is not None:
            rows = [{**row, "t_s": t_s, "timestamp_utc": timestamp_utc} for row in prebuilt_rows]
        else:
            rows = self._build_sample_records(run_id=run_id, t_s=t_s, timestamp_utc=timestamp_utc)
        if (
            prebuilt_rows is not None
            and rows
            and not history_created
            and current_total <= session_start_total
        ):
            rows = []
        if rows:
            with self._lock:
                if self._session_generation != session_generation:
                    return False
                self._last_data_progress_mono_s = now_mono_s
            if self._history_db is not None and self._persist_history_db:
                self._ensure_history_run_created(
                    run_id, start_time_utc, session_generation=session_generation
                )
                with self._lock:
                    if self._session_generation != session_generation:
                        return False
                    history_created = self._history_run_created
                if history_created:
                    try:
                        self._history_db.append_samples(run_id, rows)
                        with self._lock:
                            if self._session_generation != session_generation:
                                return False
                            self._written_sample_count += len(rows)
                        self._clear_last_write_error()
                    except Exception as exc:
                        self._set_last_write_error(f"history append_samples failed: {exc}")
                        LOGGER.warning("Failed to append samples to history DB", exc_info=True)
                else:
                    with self._lock:
                        fail_count = self._history_create_fail_count
                    LOGGER.warning(
                        "Dropping %d sample(s) for run %s: "
                        "history run not created (fail count %d/%d)",
                        len(rows),
                        run_id,
                        fail_count,
                        _MAX_HISTORY_CREATE_RETRIES,
                    )
            else:
                with self._lock:
                    if self._session_generation != session_generation:
                        return False
                    self._written_sample_count += len(rows)

        with self._lock:
            if self._session_generation != session_generation:
                return False
            if self._last_data_progress_mono_s is None:
                return False
            return (now_mono_s - self._last_data_progress_mono_s) >= self._no_data_timeout_s

    def _prune_live_samples_locked(self, live_t_s: float) -> None:
        """Keep only the rolling live window used by the dashboard."""
        cutoff = float(live_t_s) - max(0.0, self._live_sample_window_s)
        _samples = self._live_samples
        _popleft = _samples.popleft
        _isinstance = isinstance
        _NUMERIC = NUMERIC_TYPES
        while _samples:
            ts = _samples[0].get("t_s")
            if not _isinstance(ts, _NUMERIC):
                _popleft()
                continue
            if float(ts) >= cutoff:
                break
            _popleft()

    def _finalize_run_locked(self) -> bool:
        """Finalize the current run in the history DB.

        Returns ``True`` when finalization succeeded (or was skipped because
        there is nothing to finalize), ``False`` on DB failure so that callers
        can avoid scheduling analysis for an un-finalized run.
        """
        if not self._run_id:
            return True
        if not self._history_run_created:
            return True
        end_utc = utc_now_iso()
        if self._history_db is not None:
            try:
                start_time_utc = self._run_start_utc or end_utc
                latest_metadata = self._run_metadata_record(self._run_id, start_time_utc)
                latest_metadata["end_time_utc"] = end_utc
                self._history_db.finalize_run_with_metadata(self._run_id, end_utc, latest_metadata)
                self._clear_last_write_error()
            except Exception as exc:
                self._set_last_write_error(f"history finalize_run failed: {exc}")
                LOGGER.warning("Failed to finalize run in history DB", exc_info=True)
                return False
        return True

    # -- post-analysis delegates ----------------------------------------------

    def schedule_post_analysis(self, run_id: str) -> None:
        """Queue *run_id* for background post-run analysis."""
        self._post_analysis.schedule(run_id)

    def wait_for_post_analysis(self, timeout_s: float = 30.0) -> bool:
        return self._post_analysis.wait(timeout_s)

    def shutdown(self, timeout_s: float = 30.0) -> bool:
        """Stop recording and wait for any queued post-analysis to complete."""
        self.stop_logging()
        return self.wait_for_post_analysis(timeout_s)

    # -- main async loop ------------------------------------------------------

    async def run(self) -> None:
        interval = 1.0 / self.metrics_log_hz
        while True:
            try:
                timestamp_utc = utc_now_iso()
                with self._lock:
                    _live_start = self._live_start_mono_s
                    run_id_for_live = self._run_id or "live"
                live_t_s = max(0.0, time.monotonic() - _live_start)
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
                    run_id, start_time_utc, start_mono_s, generation = snapshot
                    no_data_timeout = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._append_records,
                            run_id,
                            start_time_utc,
                            start_mono_s,
                            session_generation=generation,
                            prebuilt_rows=live_rows,
                        ),
                        timeout=_DB_THREAD_TIMEOUT_S,
                    )
                    if no_data_timeout:
                        LOGGER.info(
                            "Auto-stopping run %s after %.1fs without new data",
                            run_id,
                            self._no_data_timeout_s,
                        )
                        self.stop_logging(_only_if_generation=generation)
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
