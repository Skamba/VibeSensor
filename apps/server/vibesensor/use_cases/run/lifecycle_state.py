"""In-memory recording session lifecycle state for ``RunRecorder``.

This helper owns the active run's identity, timing, frame-progress tracking,
and shutdown gating. ``RunRecorder`` remains the higher-level coordinator for
persistence, post-analysis scheduling, and the recording tick loop.
"""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain import Run
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot

__all__ = ["ActiveRunSnapshot", "RunLifecycleState"]


@dataclass(frozen=True, slots=True)
class ActiveRunSnapshot:
    run_id: str
    start_time_utc: str
    start_mono_s: float


@dataclass(slots=True)
class RunLifecycleState:
    """Own the in-memory lifecycle for the active recording run."""

    no_data_timeout_s: float
    current_run: Run | None = None
    start_time_utc: str | None = None
    start_mono_s: float | None = None
    last_data_progress_mono_s: float | None = None
    start_frames_total: int = 0
    last_active_frames_total: int = 0
    shutdown_requested: bool = False

    @property
    def enabled(self) -> bool:
        run = self.current_run
        return run is not None and run.is_recording

    @property
    def run_id(self) -> str | None:
        run = self.current_run
        return run.run_id if run is not None else None

    def start_new_run(
        self,
        *,
        run_id: str,
        analysis_settings_snapshot: AnalysisSettingsSnapshot,
        start_time_utc: str,
        start_mono_s: float,
        current_total: int,
    ) -> ActiveRunSnapshot:
        session = Run(
            run_id=run_id,
            analysis_settings=analysis_settings_snapshot,
        )
        session.start()
        self.current_run = session
        self.start_time_utc = start_time_utc
        self.start_mono_s = start_mono_s
        self.last_data_progress_mono_s = start_mono_s
        self.start_frames_total = current_total
        self.last_active_frames_total = current_total
        return ActiveRunSnapshot(
            run_id=run_id,
            start_time_utc=start_time_utc,
            start_mono_s=start_mono_s,
        )

    def stop(self) -> None:
        run = self.current_run
        if run is not None and run.is_recording:
            run.stop()
        self.current_run = None
        self.start_time_utc = None
        self.start_mono_s = None
        self.last_data_progress_mono_s = None
        self.start_frames_total = 0
        self.last_active_frames_total = 0

    def snapshot(self) -> ActiveRunSnapshot | None:
        run_id = self.run_id
        if not self.enabled or not run_id or not self.start_time_utc or self.start_mono_s is None:
            return None
        return ActiveRunSnapshot(
            run_id=run_id,
            start_time_utc=self.start_time_utc,
            start_mono_s=self.start_mono_s,
        )

    def pending_flush_snapshot(
        self,
        *,
        current_total: int,
        history_run_created: bool,
    ) -> ActiveRunSnapshot | None:
        run_id = self.run_id
        if not self.enabled or not run_id or not self.start_time_utc or self.start_mono_s is None:
            return None
        if history_run_created:
            if current_total <= self.last_active_frames_total:
                return None
        elif current_total <= self.start_frames_total:
            return None
        return self.snapshot()

    def should_drop_prebuilt_rows(
        self,
        *,
        current_total: int,
        history_run_created: bool,
    ) -> bool:
        return (not history_run_created) and current_total <= self.start_frames_total

    def refresh_data_progress(self, *, now_mono_s: float, current_total: int) -> None:
        if current_total != self.last_active_frames_total:
            self.last_active_frames_total = current_total
            self.last_data_progress_mono_s = now_mono_s

    def mark_rows_written(self, *, now_mono_s: float) -> None:
        self.last_data_progress_mono_s = now_mono_s

    def should_auto_stop(self, *, now_mono_s: float) -> bool:
        if self.last_data_progress_mono_s is None:
            return False
        elapsed = now_mono_s - self.last_data_progress_mono_s
        return elapsed >= self.no_data_timeout_s
