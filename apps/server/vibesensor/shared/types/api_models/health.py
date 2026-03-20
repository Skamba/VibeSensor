"""Health-related HTTP API request/response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthDataLossResponse(BaseModel):
    """Response body for aggregated client data-loss counters."""

    tracked_clients: int
    affected_clients: int
    frames_dropped: int
    queue_overflow_drops: int
    server_queue_drops: int
    parse_errors: int


class HealthPersistenceResponse(BaseModel):
    """Response body for persistence health details."""

    write_error: str | None
    analysis_in_progress: bool
    analysis_queue_depth: int = 0
    analysis_queue_max_depth: int = 0
    analysis_active_run_id: str | None = None
    analysis_started_at: float | None = None
    analysis_elapsed_s: float | None = None
    analysis_queue_oldest_age_s: float | None = None
    analyzing_run_count: int = 0
    analyzing_oldest_age_s: float | None = None
    samples_written: int = 0
    samples_dropped: int = 0
    last_completed_run_id: str | None = None
    last_completed_run_error: str | None = None


class HealthIntakeStatsResponse(BaseModel):
    """Response body for processing intake timing and throughput counters."""

    total_ingested_samples: int
    total_compute_calls: int
    last_compute_duration_s: float
    last_compute_all_duration_s: float
    last_ingest_duration_s: float


class HealthResponse(BaseModel):
    """Response body for the server health check endpoint."""

    status: Literal["ok", "warn", "degraded"]
    startup_state: str
    startup_phase: str
    startup_error: str | None
    startup_warnings: list[str] = []
    background_task_failures: dict[str, str]
    processing_state: str
    processing_failures: int
    processing_failure_categories: dict[str, int]
    processing_last_failure: str | None
    sample_rate_mismatch_count: int
    frame_size_mismatch_count: int

    degradation_reasons: list[str]
    data_loss: HealthDataLossResponse
    persistence: HealthPersistenceResponse
    intake_stats: HealthIntakeStatsResponse

    tick_duration_s: float = 0.0
    max_tick_duration_s: float = 0.0
    tick_count: int = 0
    db_last_write_duration_s: float = 0.0
    db_max_write_duration_s: float = 0.0
