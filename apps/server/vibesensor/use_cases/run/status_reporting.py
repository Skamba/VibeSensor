"""Status and health snapshot helpers extracted from ``RunRecorder``."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import aiosqlite

from vibesensor.domain import CaptureReadiness
from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.health_snapshot import RunRecorderHealthSnapshot
from vibesensor.use_cases.run.persistence_writer import RunPersistenceWriter
from vibesensor.use_cases.run.post_analysis import PostAnalysisWorker

__all__ = [
    "RunRecorderStatusSnapshot",
    "build_run_recorder_health_snapshot",
    "build_run_recorder_status",
]


@dataclass(frozen=True, slots=True)
class RunRecorderStatusSnapshot:
    enabled: bool
    run_id: str | None
    write_error: str | None
    analysis_in_progress: bool
    start_time_utc: str | None = None
    samples_written: int = 0
    samples_dropped: int = 0
    last_completed_run_id: str | None = None
    last_completed_run_error: str | None = None
    capture_readiness: CaptureReadiness | None = None


def build_run_recorder_status(
    *,
    enabled: bool,
    run_id: str | None,
    start_time_utc: str | None,
    persistence: RunPersistenceWriter,
    post_analysis: PostAnalysisWorker,
    capture_readiness: CaptureReadiness | None = None,
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
        samples_written=persist.written_sample_count,
        samples_dropped=persist.dropped_sample_count,
        last_completed_run_id=post_snapshot.last_completed_run_id,
        last_completed_run_error=post_snapshot.last_completed_error,
        capture_readiness=capture_readiness,
    )


def build_run_recorder_health_snapshot(
    *,
    history_db: RunPersistence | None,
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
        aanalyzing = getattr(history_db, "aanalyzing_run_health", None)
        if callable(aanalyzing):
            try:
                run_on_loop = getattr(history_db, "_run_on_engine_loop", None)
                if callable(run_on_loop):
                    analyzing_health = run_on_loop(aanalyzing())
                else:
                    import asyncio as _asyncio

                    analyzing_health = _asyncio.run(aanalyzing())
                analyzing_run_count = analyzing_health.analyzing_run_count
                if analyzing_health.analyzing_oldest_age_s is not None:
                    analyzing_oldest_age_s = max(0.0, analyzing_health.analyzing_oldest_age_s)
            except aiosqlite.Error:
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
