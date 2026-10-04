"""Health-related HTTP API request/response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from vibesensor.ingest.registry import ExpectedFrameLoss


class HealthDataLossResponse(BaseModel):
    """Response body for aggregated client data-loss counters."""

    tracked_clients: int
    affected_clients: int
    frames_dropped: int
    buffer_overflow_drops: int
    queue_overflow_drops: int
    server_queue_drops: int
    parse_errors: int


class HealthRecentDataLossResponse(BaseModel):
    """Data loss in the last ``window_s`` seconds; health warnings use only these."""

    window_s: int
    frame_loss_clients: int
    """Clients that lost at least 1 % of their frames in the window."""
    frames_dropped: int
    expected_frames_dropped: int
    """Frames lost to an expected interruption (a sensor's first seconds after a
    server restart, a Bluetooth OBD scan or pairing); not in ``frames_dropped``
    and never a warning."""
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
    pressure_state: Literal["ok", "warn", "degraded"] = "ok"


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
    expected_frames_dropped: int
    """The part of ``frames_dropped`` lost to an expected interruption."""
    last_expected_loss_reason: ExpectedFrameLoss | None
    queue_overflow_drops: int
    server_queue_drops: int
    parse_errors: int
    duplicates_received: int
    timing_state: Literal["unknown", "ok", "timestamp_lag", "rate_mismatch"]
    timing_min_lag_ms: float | None
    effective_sample_rate_hz: float | None


class HealthIngestResponse(BaseModel):
    udp: HealthUdpIngestResponse
    raw_capture: HealthRawCaptureResponse
    ws_publish: HealthWsPublishResponse
    clients: list[HealthIngestClientResponse] = []


class HealthSubsystemResponse(BaseModel):
    status: Literal["ready", "degraded", "unhealthy"]
    reason_codes: list[str] = []


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
    subsystems: dict[str, HealthSubsystemResponse] = {}
    data_loss: HealthDataLossResponse
    recent_data_loss: HealthRecentDataLossResponse
    persistence: HealthPersistenceResponse
    intake_stats: HealthIntakeStatsResponse
    ingest: HealthIngestResponse

    tick_duration_s: float = 0.0
    max_tick_duration_s: float = 0.0
    tick_count: int = 0
    db_last_write_duration_s: float = 0.0
    db_max_write_duration_s: float = 0.0
