"""Shared typed contracts for runtime and persistence health snapshots."""

from __future__ import annotations

from typing import Literal, TypedDict

from vibesensor.shared.types.payload_types import IntakeStatsPayload


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


class HealthSnapshotData(TypedDict):
    """Typed snapshot returned by the health-snapshot builder."""

    status: Literal["ok", "warn", "degraded"]
    startup_state: str
    startup_phase: str
    startup_error: str | None
    startup_warnings: list[str]
    background_task_failures: dict[str, str]
    db_corruption_detected: bool
    processing_state: str
    processing_failures: int
    processing_failure_categories: dict[str, int]
    processing_last_failure: str | None
    sample_rate_mismatch_count: int
    frame_size_mismatch_count: int
    degradation_reasons: list[str]
    data_loss: dict[str, int]
    persistence: RunRecorderHealthSnapshot
    intake_stats: IntakeStatsPayload
    tick_duration_s: float | None
    max_tick_duration_s: float | None
    tick_count: int
    db_last_write_duration_s: float | None
    db_max_write_duration_s: float | None
