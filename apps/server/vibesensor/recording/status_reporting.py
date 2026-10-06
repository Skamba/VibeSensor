"""Status and health snapshot helpers extracted from ``RunRecorder``."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from vibesensor.analysis.post_analysis import PostAnalysisWorker
from vibesensor.domain.capture_readiness import CaptureReadiness
from vibesensor.recording.lifecycle_state import RecordingStopReason
from vibesensor.recording.persistence_writer import RunPersistenceWriter
from vibesensor.recording.run_schema import GuidedPhaseName

if TYPE_CHECKING:
    from vibesensor.history.history_db import HistoryDB

__all__ = [
    "RunRecorderHealthSnapshot",
    "RunRecorderStatusSnapshot",
    "build_run_recorder_health_snapshot",
    "build_run_recorder_status",
]


class RunRecorderHealthSnapshot(TypedDict):
    """Health snapshot dict returned by ``RunRecorder.health_snapshot()``."""

    write_error: str | None
    analysis_in_progress: bool
    analysis_queue_depth: int
    analysis_queue_max_depth: int
    analysis_active_run_id: str | None
    analysis_started_at: float | None
    analysis_elapsed_s: float | None
    analysis_queue_oldest_age_s: float | None
    analyzing_run_count: int
    analyzing_oldest_age_s: float | None
    samples_written: int
    samples_dropped: int
    last_completed_run_id: str | None
    last_completed_run_error: str | None


@dataclass(frozen=True, slots=True)
class RunRecorderStatusSnapshot:
    enabled: bool
    run_id: str | None
    write_error: str | None
    analysis_in_progress: bool
    start_time_utc: str | None = None
    elapsed_s: float | None = None
    samples_written: int = 0
    samples_dropped: int = 0
    last_completed_run_id: str | None = None
    last_completed_run_error: str | None = None
    capture_readiness: CaptureReadiness | None = None
    last_stop_reason: RecordingStopReason | None = None
    last_run_id: str | None = None
    guided_phase: GuidedPhaseName | None = None
    guided_phases_completed: tuple[GuidedPhaseName, ...] = ()
    guided_brake_stops: int = 0


def build_run_recorder_status(
    *,
    enabled: bool,
    run_id: str | None,
    start_time_utc: str | None,
    elapsed_s: float | None,
    persistence: RunPersistenceWriter,
    post_analysis: PostAnalysisWorker,
    capture_readiness: CaptureReadiness | None = None,
    last_stop_reason: RecordingStopReason | None = None,
    last_run_id: str | None = None,
    guided_phase: GuidedPhaseName | None = None,
    guided_phases_completed: tuple[GuidedPhaseName, ...] = (),
    guided_brake_stops: int = 0,
) -> RunRecorderStatusSnapshot:
    """Build the compact status snapshot exposed by recorder-facing APIs."""
    post_snapshot = post_analysis.snapshot()
    persist = persistence.status_snapshot()
    return RunRecorderStatusSnapshot(
        enabled=enabled,
        run_id=run_id,
        write_error=persist.write_error,
        analysis_in_progress=post_analysis.is_active,
        start_time_utc=start_time_utc,
        elapsed_s=elapsed_s,
        samples_written=persist.written_sample_count,
        samples_dropped=persist.dropped_sample_count,
        last_completed_run_id=post_snapshot.last_completed_run_id,
        last_completed_run_error=post_snapshot.last_completed_error,
        capture_readiness=capture_readiness,
        last_stop_reason=last_stop_reason,
        last_run_id=last_run_id,
        guided_phase=guided_phase,
        guided_phases_completed=guided_phases_completed,
        guided_brake_stops=guided_brake_stops,
    )


def build_run_recorder_health_snapshot(
    *,
    history_db: HistoryDB | None,
    persistence: RunPersistenceWriter,
    post_analysis: PostAnalysisWorker,
    logger: logging.Logger,
) -> RunRecorderHealthSnapshot:
    """Build the richer health snapshot used by diagnostics and monitoring surfaces."""
    snapshot = post_analysis.snapshot()
    analysis_elapsed_s = None
    if snapshot.active_started_at is not None:
        analysis_elapsed_s = max(0.0, time.time() - snapshot.active_started_at)

    queue_oldest_age_s = None
    if snapshot.oldest_queued_at is not None:
        queue_oldest_age_s = max(0.0, time.time() - snapshot.oldest_queued_at)

    analyzing_run_count = 0
    analyzing_oldest_age_s = None
    if history_db is not None:
        try:
            analyzing_health = history_db.analyzing_run_health()
            analyzing_run_count = analyzing_health.analyzing_run_count
            if analyzing_health.analyzing_oldest_age_s is not None:
                analyzing_oldest_age_s = max(0.0, analyzing_health.analyzing_oldest_age_s)
        except sqlite3.Error:
            logger.warning("Failed to read analyzing-run health snapshot", exc_info=True)

    persist = persistence.status_snapshot()
    return {
        "write_error": persist.write_error,
        "analysis_in_progress": post_analysis.is_active,
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
