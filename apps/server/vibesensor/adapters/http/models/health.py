"""Health-related HTTP API request/response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthDataLossResponse(BaseModel):
    """Response body for aggregated client data-loss counters."""

    tracked_clients: int
    affected_clients: int
    frames_dropped: int
    buffer_overflow_drops: int
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


class HealthUdpIngestResponse(BaseModel):
    queue_depth: int
    queue_max_depth: int
    enqueued_datagrams: int
    dropped_datagrams: int
    processed_datagrams: int
    last_packet_queue_age_ms: float
    max_packet_queue_age_ms: float
    last_ack_latency_ms: float
    max_ack_latency_ms: float


class HealthRawCaptureResponse(BaseModel):
    queue_depth: int
    queue_max_depth: int
    dropped_chunks: int
    write_error_chunks: int


class HealthWsPublishResponse(BaseModel):
    active_connections: int
    total_publish_ticks: int
    last_publish_duration_ms: float
    max_publish_duration_ms: float


class HealthIngestClientResponse(BaseModel):
    client_id: str
    advertised_sample_rate_hz: int
    estimated_ingest_hz: float
    processed_packets: int
    processed_samples: int
    late_packets: int
    last_packet_queue_age_ms: float
    last_ack_latency_ms: float
    frames_dropped: int
    queue_overflow_drops: int
    server_queue_drops: int
    parse_errors: int
    duplicates_received: int


class HealthIngestResponse(BaseModel):
    udp: HealthUdpIngestResponse
    raw_capture: HealthRawCaptureResponse
    ws_publish: HealthWsPublishResponse
    clients: list[HealthIngestClientResponse] = []


class HealthResponse(BaseModel):
    """Response body for the server health check endpoint."""

    status: Literal["ok", "warn", "degraded"]
    startup_state: str
    startup_phase: str
    startup_error: str | None
    startup_warnings: list[str] = []
    background_task_failures: dict[str, str]
    db_corruption_detected: bool = False
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
    ingest: HealthIngestResponse

    tick_duration_s: float = 0.0
    max_tick_duration_s: float = 0.0
    tick_count: int = 0
    db_last_write_duration_s: float = 0.0
    db_max_write_duration_s: float = 0.0
