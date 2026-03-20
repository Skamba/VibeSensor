"""Status and health payload helpers extracted from ``RunRecorder``."""

from __future__ import annotations

import logging
import sqlite3
import time

from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.health_snapshot import RunRecorderHealthSnapshot
from vibesensor.use_cases.run.persistence_writer import RunPersistenceWriter
from vibesensor.use_cases.run.post_analysis import PostAnalysisWorker

__all__ = [
    "build_run_recorder_health_snapshot",
    "build_run_recorder_status",
]


def build_run_recorder_status(
    *,
    enabled: bool,
    run_id: str | None,
    persistence: RunPersistenceWriter,
    post_analysis: PostAnalysisWorker,
) -> dict[str, object]:
    post_snapshot = post_analysis.snapshot()
    persist = persistence.status_snapshot()
    return {
        "enabled": enabled,
        "current_file": None,
        "run_id": run_id,
        "write_error": persist.write_error,
        "analysis_in_progress": post_analysis.is_active,
        "samples_written": persist.written_sample_count,
        "samples_dropped": persist.dropped_sample_count,
        "last_completed_run_id": post_snapshot.last_completed_run_id,
        "last_completed_run_error": post_snapshot.last_completed_error,
    }


def build_run_recorder_health_snapshot(
    *,
    history_db: RunPersistence | None,
    persistence: RunPersistenceWriter,
    post_analysis: PostAnalysisWorker,
    logger: logging.Logger,
) -> RunRecorderHealthSnapshot:
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
            raw_count = analyzing_health.get("analyzing_run_count")
            analyzing_run_count = int(raw_count) if isinstance(raw_count, int | float) else 0
            raw_oldest_age = analyzing_health.get("analyzing_oldest_age_s")
            if isinstance(raw_oldest_age, (int, float)):
                analyzing_oldest_age_s = max(0.0, float(raw_oldest_age))
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
