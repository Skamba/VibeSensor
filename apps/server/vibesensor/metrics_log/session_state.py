"""Explicit recording-session state for :mod:`vibesensor.metrics_log.logger`.

The logger used to manage a dozen independent session fields directly.  This
module groups that mutable lifecycle state behind a narrow API so the logger
can focus on orchestration instead of primitive-field bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True, slots=True)
class MetricsSessionSnapshot:
    run_id: str
    start_time_utc: str
    start_mono_s: float
    generation: int


class MetricsSessionState:
    """Owns the active recording session lifecycle and progress markers."""

    def __init__(self, *, enabled: bool, no_data_timeout_s: float) -> None:
        self._lock = RLock()
        self._enabled = bool(enabled)
        self._no_data_timeout_s = max(1.0, float(no_data_timeout_s))
        self._run_id: str | None = None
        self._run_start_utc: str | None = None
        self._run_start_mono_s: float | None = None
        self._last_data_progress_mono_s: float | None = None
        self._session_generation = 0
        self._session_start_frames_total = 0
        self._last_active_frames_total = 0
        self._shutdown_requested = False

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = bool(value)

    @property
    def run_id(self) -> str | None:
        with self._lock:
            return self._run_id

    @property
    def run_start_utc(self) -> str | None:
        with self._lock:
            return self._run_start_utc

    @property
    def run_start_mono_s(self) -> float | None:
        with self._lock:
            return self._run_start_mono_s

    @property
    def last_data_progress_mono_s(self) -> float | None:
        with self._lock:
            return self._last_data_progress_mono_s

    @last_data_progress_mono_s.setter
    def last_data_progress_mono_s(self, value: float | None) -> None:
        with self._lock:
            self._last_data_progress_mono_s = float(value) if value is not None else None

    @property
    def session_generation(self) -> int:
        with self._lock:
            return self._session_generation

    @property
    def shutdown_requested(self) -> bool:
        with self._lock:
            return self._shutdown_requested

    @property
    def no_data_timeout_s(self) -> float:
        with self._lock:
            return self._no_data_timeout_s

    def set_shutdown_requested(self, requested: bool) -> None:
        with self._lock:
            self._shutdown_requested = bool(requested)

    def start_new_session(
        self,
        *,
        run_id: str,
        start_time_utc: str,
        start_mono_s: float,
        current_total: int,
    ) -> MetricsSessionSnapshot:
        with self._lock:
            self._session_generation += 1
            self._enabled = True
            self._run_id = run_id
            self._run_start_utc = start_time_utc
            self._run_start_mono_s = start_mono_s
            self._last_data_progress_mono_s = start_mono_s
            self._session_start_frames_total = current_total
            self._last_active_frames_total = current_total
            return MetricsSessionSnapshot(
                run_id=run_id,
                start_time_utc=start_time_utc,
                start_mono_s=start_mono_s,
                generation=self._session_generation,
            )

    def stop_session(self) -> None:
        with self._lock:
            self._session_generation += 1
            self._enabled = False
            self._run_id = None
            self._run_start_utc = None
            self._run_start_mono_s = None
            self._last_data_progress_mono_s = None
            self._session_start_frames_total = 0
            self._last_active_frames_total = 0

    def matches_generation(self, generation: int) -> bool:
        with self._lock:
            return self._session_generation == generation

    def snapshot(self) -> MetricsSessionSnapshot | None:
        with self._lock:
            if (
                not self._enabled
                or not self._run_id
                or not self._run_start_utc
                or self._run_start_mono_s is None
            ):
                return None
            return MetricsSessionSnapshot(
                run_id=self._run_id,
                start_time_utc=self._run_start_utc,
                start_mono_s=self._run_start_mono_s,
                generation=self._session_generation,
            )

    def pending_flush_snapshot(
        self, *, current_total: int, history_run_created: bool
    ) -> MetricsSessionSnapshot | None:
        with self._lock:
            if (
                not self._enabled
                or not self._run_id
                or not self._run_start_utc
                or self._run_start_mono_s is None
            ):
                return None
            if history_run_created:
                if current_total <= self._last_active_frames_total:
                    return None
            elif current_total <= self._session_start_frames_total:
                return None
            return MetricsSessionSnapshot(
                run_id=self._run_id,
                start_time_utc=self._run_start_utc,
                start_mono_s=self._run_start_mono_s,
                generation=self._session_generation,
            )

    def should_drop_prebuilt_rows(self, *, current_total: int, history_run_created: bool) -> bool:
        with self._lock:
            return (not history_run_created) and current_total <= self._session_start_frames_total

    def refresh_data_progress(self, *, now_mono_s: float, current_total: int) -> None:
        with self._lock:
            if current_total != self._last_active_frames_total:
                self._last_active_frames_total = current_total
                self._last_data_progress_mono_s = now_mono_s

    def mark_rows_written(self, *, now_mono_s: float) -> None:
        with self._lock:
            self._last_data_progress_mono_s = now_mono_s

    def should_auto_stop(self, *, now_mono_s: float) -> bool:
        with self._lock:
            if self._last_data_progress_mono_s is None:
                return False
            return (now_mono_s - self._last_data_progress_mono_s) >= self._no_data_timeout_s

    def status_payload(
        self, *, write_error: str | None, analysis_in_progress: bool
    ) -> dict[str, str | bool | None]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "current_file": None,
                "run_id": self._run_id,
                "write_error": write_error,
                "analysis_in_progress": analysis_in_progress,
            }
