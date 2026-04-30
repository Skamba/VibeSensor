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


class UdpIngestHealthSnapshot(TypedDict):
    queue_depth: int
    queue_max_depth: int
    enqueued_datagrams: int
    dropped_datagrams: int
    processed_datagrams: int
    last_packet_queue_age_ms: float
    max_packet_queue_age_ms: float
    last_ack_latency_ms: float
    max_ack_latency_ms: float


class RawCaptureQueueHealthSnapshot(TypedDict):
    queue_depth: int
    queue_max_depth: int
    dropped_chunks: int
    write_error_chunks: int


class WsPublishHealthSnapshot(TypedDict):
    active_connections: int
    total_publish_ticks: int
    last_publish_duration_ms: float
    max_publish_duration_ms: float


class IngestClientHealthSnapshot(TypedDict):
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


class IngestHealthSnapshot(TypedDict):
    udp: UdpIngestHealthSnapshot
    raw_capture: RawCaptureQueueHealthSnapshot
    ws_publish: WsPublishHealthSnapshot
    clients: list[IngestClientHealthSnapshot]


class HealthSnapshotData(TypedDict):
    """Typed snapshot returned by the health-snapshot builder."""

    status: Literal["ok", "warn", "degraded"]
    startup_state: str
    startup_phase: str
    startup_error: str | None
    startup_warnings: list[str]
    background_task_failures: dict[str, str]
    db_corruption_detected: bool
    db_engine_unhealthy: bool
    db_engine_unhealthy_reason: str | None
    db_engine_unhealthy_details: str | None
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
    ingest: IngestHealthSnapshot
    tick_duration_s: float | None
    max_tick_duration_s: float | None
    tick_count: int
    db_last_write_duration_s: float | None
    db_max_write_duration_s: float | None
