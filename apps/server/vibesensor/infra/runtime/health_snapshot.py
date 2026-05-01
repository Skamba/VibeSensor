"""Runtime health snapshot assembly for the HTTP health endpoint."""

from __future__ import annotations

from typing import Literal, Protocol

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_state import ProcessingHealth, ProcessingLoopState
from vibesensor.shared.ingest_diagnostics import (
    IngestDiagnosticsCollector,
    RawCaptureRuntimeSnapshot,
)
from vibesensor.shared.types.health_snapshot import (
    HealthSnapshotData,
    IngestClientHealthSnapshot,
    RunRecorderHealthSnapshot,
    SubsystemHealthSnapshot,
)
from vibesensor.shared.types.payload_types import IntakeStatsPayload

__all__ = ["build_system_health_snapshot"]


class IntakeStatsProvider(Protocol):
    """Collaborator that exposes runtime intake statistics."""

    def intake_stats(self) -> IntakeStatsPayload: ...

    def buffer_overflow_drops(self) -> int: ...


class DataLossSnapshotProvider(Protocol):
    """Collaborator that exposes data-loss counters."""

    def data_loss_snapshot(self) -> dict[str, int]: ...

    def active_client_ids(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> list[str]: ...

    def get(self, client_id: str) -> object | None: ...


class RecorderHealthProvider(Protocol):
    """Collaborator that exposes recorder health data and timing stats."""

    @property
    def last_write_duration_s(self) -> float | None: ...

    @property
    def max_write_duration_s(self) -> float | None: ...

    def health_snapshot(self) -> RunRecorderHealthSnapshot: ...


def build_system_health_snapshot(
    loop_state: ProcessingLoopState,
    health_state: RuntimeHealthState,
    processor: IntakeStatsProvider,
    registry: DataLossSnapshotProvider,
    run_recorder: RecorderHealthProvider,
    ingest_diagnostics: IngestDiagnosticsCollector,
) -> HealthSnapshotData:
    """Build the app-level health snapshot from runtime collaborators."""

    def _coerce_duration(value: float | None) -> float:
        return value if value is not None else 0.0

    failures = loop_state.processing_failure_count
    data_loss = dict(registry.data_loss_snapshot())
    data_loss["buffer_overflow_drops"] = int(processor.buffer_overflow_drops())
    persistence = run_recorder.health_snapshot()
    failure_categories = dict(loop_state.processing_failure_categories)
    sample_rate_mismatch_count = len(loop_state.sample_rate_mismatch_logged)
    frame_size_mismatch_count = len(loop_state.frame_size_mismatch_logged)
    degradation_reasons: list[str] = []
    has_error = False
    if health_state.startup_state != "ready":
        degradation_reasons.append(f"startup_state:{health_state.startup_state}")
        has_error = True
    if health_state.startup_error:
        degradation_reasons.append("startup_error")
        has_error = True
    if health_state.background_task_failures:
        degradation_reasons.append("background_task_failures")
        has_error = True
    if health_state.startup_warnings:
        degradation_reasons.append("startup_warnings")
    if health_state.db_corruption_detected:
        degradation_reasons.append("db_corruption_detected")
        has_error = True
    if health_state.db_engine_unhealthy:
        degradation_reasons.append("db_engine_unhealthy")
        has_error = True
    if loop_state.processing_state != ProcessingHealth.OK:
        degradation_reasons.append(f"processing_state:{loop_state.processing_state}")
        has_error = True
    if failures > 0:
        degradation_reasons.append("processing_failures")
    if loop_state.last_failure_category:
        degradation_reasons.append(f"processing_failure:{loop_state.last_failure_category}")
    if sample_rate_mismatch_count > 0:
        degradation_reasons.append("sample_rate_mismatch")
    if frame_size_mismatch_count > 0:
        degradation_reasons.append("frame_size_mismatch")
    for key in (
        "frames_dropped",
        "buffer_overflow_drops",
        "queue_overflow_drops",
        "server_queue_drops",
        "parse_errors",
    ):
        if data_loss[key] > 0:
            degradation_reasons.append(key)
    if persistence["write_error"]:
        degradation_reasons.append("persistence_write_error")
        has_error = True
    if persistence["samples_dropped"] > 0:
        degradation_reasons.append("persistence_samples_dropped")
    if persistence["analyzing_run_count"] > 0:
        degradation_reasons.append("analyzing_runs_present")
    if persistence["last_completed_run_error"]:
        degradation_reasons.append("last_analysis_failed")
    runtime_clients = ingest_diagnostics.client_snapshots()
    udp_snapshot = ingest_diagnostics.udp_snapshot()
    raw_capture_snapshot = ingest_diagnostics.raw_capture_snapshot()
    if raw_capture_snapshot.dropped_chunks > 0:
        degradation_reasons.append("raw_capture_dropped_chunks")
    if raw_capture_snapshot.write_error_chunks > 0:
        degradation_reasons.append("raw_capture_write_errors")
        has_error = True
    if raw_capture_snapshot.pressure_state != "ok":
        degradation_reasons.append(f"raw_capture_pressure:{raw_capture_snapshot.pressure_state}")
    ws_publish_snapshot = ingest_diagnostics.ws_publish_snapshot()
    subsystems = _build_subsystem_health(
        health_state=health_state,
        loop_state=loop_state,
        data_loss=data_loss,
        persistence=persistence,
        raw_capture_snapshot=raw_capture_snapshot,
    )
    status: Literal["ok", "warn", "degraded"] = "ok"
    if degradation_reasons:
        status = "degraded" if has_error else "warn"
    ingest_clients: list[IngestClientHealthSnapshot] = []
    seen_client_ids: set[str] = set()
    for client_id in registry.active_client_ids():
        record = registry.get(client_id)
        if record is None:
            continue
        runtime_client = runtime_clients.get(client_id)
        ingest_clients.append(
            {
                "client_id": client_id,
                "advertised_sample_rate_hz": int(getattr(record, "sample_rate_hz", 0)),
                "estimated_ingest_hz": (
                    runtime_client.estimated_ingest_hz if runtime_client is not None else 0.0
                ),
                "processed_packets": (
                    runtime_client.processed_packets if runtime_client is not None else 0
                ),
                "processed_samples": (
                    runtime_client.processed_samples if runtime_client is not None else 0
                ),
                "late_packets": runtime_client.late_packets if runtime_client is not None else 0,
                "last_packet_queue_age_ms": (
                    runtime_client.last_packet_queue_age_ms if runtime_client is not None else 0.0
                ),
                "last_ack_latency_ms": (
                    runtime_client.last_ack_latency_ms if runtime_client is not None else 0.0
                ),
                "frames_dropped": int(getattr(record, "frames_dropped", 0)),
                "queue_overflow_drops": int(getattr(record, "queue_overflow_drops", 0)),
                "server_queue_drops": int(getattr(record, "server_queue_drops", 0)),
                "parse_errors": int(getattr(record, "parse_errors", 0)),
                "duplicates_received": int(getattr(record, "duplicates_received", 0)),
            }
        )
        seen_client_ids.add(client_id)
    for client_id, runtime_client in runtime_clients.items():
        if client_id in seen_client_ids:
            continue
        ingest_clients.append(
            {
                "client_id": client_id,
                "advertised_sample_rate_hz": 0,
                "estimated_ingest_hz": runtime_client.estimated_ingest_hz,
                "processed_packets": runtime_client.processed_packets,
                "processed_samples": runtime_client.processed_samples,
                "late_packets": runtime_client.late_packets,
                "last_packet_queue_age_ms": runtime_client.last_packet_queue_age_ms,
                "last_ack_latency_ms": runtime_client.last_ack_latency_ms,
                "frames_dropped": 0,
                "queue_overflow_drops": 0,
                "server_queue_drops": 0,
                "parse_errors": 0,
                "duplicates_received": 0,
            }
        )
    ingest_clients.sort(key=lambda row: str(row["client_id"]))
    return {
        "status": status,
        "startup_state": health_state.startup_state,
        "startup_phase": health_state.startup_phase,
        "startup_error": health_state.startup_error,
        "startup_warnings": list(health_state.startup_warnings),
        "background_task_failures": dict(health_state.background_task_failures),
        "db_corruption_detected": health_state.db_corruption_detected,
        "db_engine_unhealthy": health_state.db_engine_unhealthy,
        "db_engine_unhealthy_reason": health_state.db_engine_unhealthy_reason,
        "db_engine_unhealthy_details": health_state.db_engine_unhealthy_details,
        "processing_state": loop_state.processing_state,
        "processing_failures": failures,
        "processing_failure_categories": failure_categories,
        "processing_last_failure": loop_state.last_failure_message,
        "sample_rate_mismatch_count": sample_rate_mismatch_count,
        "frame_size_mismatch_count": frame_size_mismatch_count,
        "degradation_reasons": degradation_reasons,
        "subsystems": subsystems,
        "data_loss": data_loss,
        "persistence": persistence,
        "intake_stats": processor.intake_stats(),
        "ingest": {
            "udp": {
                "queue_depth": udp_snapshot.queue_depth,
                "queue_max_depth": udp_snapshot.queue_max_depth,
                "enqueued_datagrams": udp_snapshot.enqueued_datagrams,
                "dropped_datagrams": udp_snapshot.dropped_datagrams,
                "processed_datagrams": udp_snapshot.processed_datagrams,
                "last_packet_queue_age_ms": udp_snapshot.last_packet_queue_age_ms,
                "max_packet_queue_age_ms": udp_snapshot.max_packet_queue_age_ms,
                "last_ack_latency_ms": udp_snapshot.last_ack_latency_ms,
                "max_ack_latency_ms": udp_snapshot.max_ack_latency_ms,
            },
            "raw_capture": {
                "queue_depth": raw_capture_snapshot.queue_depth,
                "queue_max_depth": raw_capture_snapshot.queue_max_depth,
                "dropped_chunks": raw_capture_snapshot.dropped_chunks,
                "write_error_chunks": raw_capture_snapshot.write_error_chunks,
                "pressure_state": raw_capture_snapshot.pressure_state,
            },
            "ws_publish": {
                "active_connections": ws_publish_snapshot.active_connections,
                "total_publish_ticks": ws_publish_snapshot.total_publish_ticks,
                "last_publish_duration_ms": ws_publish_snapshot.last_publish_duration_ms,
                "max_publish_duration_ms": ws_publish_snapshot.max_publish_duration_ms,
            },
            "clients": ingest_clients,
        },
        "tick_duration_s": _coerce_duration(loop_state.last_tick_duration_s),
        "max_tick_duration_s": _coerce_duration(loop_state.max_tick_duration_s),
        "tick_count": loop_state.tick_count,
        "db_last_write_duration_s": _coerce_duration(run_recorder.last_write_duration_s),
        "db_max_write_duration_s": _coerce_duration(run_recorder.max_write_duration_s),
    }


def _subsystem(
    *,
    unhealthy: list[str] | None = None,
    degraded: list[str] | None = None,
) -> SubsystemHealthSnapshot:
    unhealthy_reasons = unhealthy or []
    degraded_reasons = degraded or []
    if unhealthy_reasons:
        return {
            "status": "unhealthy",
            "reason_codes": [*unhealthy_reasons, *degraded_reasons],
        }
    if degraded_reasons:
        return {"status": "degraded", "reason_codes": degraded_reasons}
    return {"status": "ready", "reason_codes": []}


def _build_subsystem_health(
    *,
    health_state: RuntimeHealthState,
    loop_state: ProcessingLoopState,
    data_loss: dict[str, int],
    persistence: RunRecorderHealthSnapshot,
    raw_capture_snapshot: RawCaptureRuntimeSnapshot,
) -> dict[str, SubsystemHealthSnapshot]:
    data_loss_reasons = [
        key
        for key in (
            "frames_dropped",
            "buffer_overflow_drops",
            "queue_overflow_drops",
            "server_queue_drops",
            "parse_errors",
        )
        if data_loss[key] > 0
    ]
    raw_capture_degraded: list[str] = []
    if raw_capture_snapshot.dropped_chunks > 0:
        raw_capture_degraded.append("raw_capture_dropped_chunks")
    if raw_capture_snapshot.pressure_state != "ok":
        raw_capture_degraded.append("raw_capture_pressure")
    return {
        "runtime": _subsystem(
            unhealthy=[
                reason
                for reason, active in (
                    ("startup_not_ready", health_state.startup_state != "ready"),
                    ("startup_error", bool(health_state.startup_error)),
                    ("background_task_failures", bool(health_state.background_task_failures)),
                )
                if active
            ],
            degraded=["startup_warnings"] if health_state.startup_warnings else [],
        ),
        "database": _subsystem(
            unhealthy=[
                reason
                for reason, active in (
                    ("db_corruption_detected", health_state.db_corruption_detected),
                    ("db_engine_unhealthy", health_state.db_engine_unhealthy),
                )
                if active
            ],
        ),
        "processing": _subsystem(
            unhealthy=(
                ["processing_state_not_ok"]
                if loop_state.processing_state != ProcessingHealth.OK
                else []
            ),
            degraded=[
                reason
                for reason, active in (
                    ("processing_failures", loop_state.processing_failure_count > 0),
                    ("processing_failure_category", bool(loop_state.last_failure_category)),
                    ("sample_rate_mismatch", bool(loop_state.sample_rate_mismatch_logged)),
                    ("frame_size_mismatch", bool(loop_state.frame_size_mismatch_logged)),
                )
                if active
            ],
        ),
        "ingest": _subsystem(degraded=data_loss_reasons),
        "raw_capture": _subsystem(
            unhealthy=(
                ["raw_capture_write_errors"] if raw_capture_snapshot.write_error_chunks > 0 else []
            ),
            degraded=raw_capture_degraded,
        ),
        "recorder": _subsystem(
            unhealthy=["persistence_write_error"] if persistence["write_error"] else [],
            degraded=(
                ["persistence_samples_dropped"] if persistence["samples_dropped"] > 0 else []
            ),
        ),
        "post_analysis": _subsystem(
            unhealthy=["last_analysis_failed"] if persistence["last_completed_run_error"] else [],
            degraded=(["analyzing_runs_present"] if persistence["analyzing_run_count"] > 0 else []),
        ),
        "websocket": _subsystem(),
        "updates": _subsystem(),
        "firmware": _subsystem(),
        "hotspot_network": _subsystem(),
    }
