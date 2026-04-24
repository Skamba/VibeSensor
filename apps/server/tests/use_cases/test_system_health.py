"""Behavioral tests for build_system_health_snapshot() branch coverage."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from vibesensor.infra.runtime.health_snapshot import build_system_health_snapshot
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_state import ProcessingHealth, ProcessingLoopState
from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector
from vibesensor.shared.types.payload_types import IntakeStatsPayload, WorkerPoolStats


def _clean_data_loss() -> dict:
    return {
        "frames_dropped": 0,
        "buffer_overflow_drops": 0,
        "queue_overflow_drops": 0,
        "server_queue_drops": 0,
        "parse_errors": 0,
    }


def _clean_persistence() -> dict:
    return {
        "write_error": False,
        "samples_dropped": 0,
        "analyzing_run_count": 0,
        "last_completed_run_error": False,
    }


def _clean_intake_stats() -> IntakeStatsPayload:
    return {
        "total_ingested_samples": 0,
        "total_compute_calls": 0,
        "last_compute_duration_s": 0.0,
        "last_compute_all_duration_s": 0.0,
        "last_ingest_duration_s": 0.0,
    }


def _worker_pool_stats() -> WorkerPoolStats:
    return {
        "max_workers": 2,
        "max_queue_size": 2,
        "max_pending_tasks": 4,
        "total_tasks": 7,
        "pending_tasks": 1,
        "queued_tasks": 0,
        "running_tasks": 1,
        "rejected_tasks": 0,
        "total_run_s": 1.5,
        "avg_run_s": 0.75,
        "total_submit_wait_s": 0.2,
        "avg_submit_wait_s": 0.1,
        "default_submit_timeout_s": None,
        "alive": True,
    }


def _make_deps(
    *,
    data_loss: dict | None = None,
    persistence: dict | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Return (registry, run_recorder) mocks with configurable snapshots."""
    registry = MagicMock()
    registry.data_loss_snapshot.return_value = data_loss or _clean_data_loss()
    registry.active_client_ids.return_value = []
    registry.get.return_value = None
    run_recorder = MagicMock()
    run_recorder.health_snapshot.return_value = persistence or _clean_persistence()
    run_recorder.last_write_duration_s = 0.0
    run_recorder.max_write_duration_s = 0.0
    return registry, run_recorder


def _make_processor(*, intake_stats: IntakeStatsPayload | None = None) -> MagicMock:
    proc = MagicMock()
    proc.intake_stats.return_value = intake_stats or _clean_intake_stats()
    proc.buffer_overflow_drops.return_value = 0
    return proc


def _ready_health_state() -> RuntimeHealthState:
    health_state = RuntimeHealthState()
    health_state.mark_ready()
    return health_state


def _snapshot(
    loop_state: ProcessingLoopState,
    health_state: RuntimeHealthState,
    registry: MagicMock,
    run_recorder: MagicMock,
    *,
    processor: MagicMock | None = None,
    ingest_diagnostics: IngestDiagnosticsCollector | None = None,
) -> dict:
    return build_system_health_snapshot(
        loop_state,
        health_state,
        _make_processor() if processor is None else processor,
        registry,
        run_recorder,
        IngestDiagnosticsCollector() if ingest_diagnostics is None else ingest_diagnostics,
    )


class TestBuildSystemHealthSnapshotOk:
    def test_all_healthy_returns_ok_status(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "ok"
        assert result["degradation_reasons"] == []

    def test_ok_snapshot_includes_expected_keys(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        for key in (
            "status",
            "startup_state",
            "startup_warnings",
            "db_corruption_detected",
            "degradation_reasons",
            "data_loss",
            "persistence",
            "processing_failures",
            "tick_count",
        ):
            assert key in result

    def test_internal_snapshot_preserves_worker_pool_stats(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()
        intake_stats: IntakeStatsPayload = {
            **_clean_intake_stats(),
            "worker_pool": _worker_pool_stats(),
        }

        result = _snapshot(
            loop_state,
            health_state,
            registry,
            run_recorder,
            processor=_make_processor(intake_stats=intake_stats),
        )

        assert result["intake_stats"]["worker_pool"]["total_tasks"] == 7

    def test_ingest_snapshot_merges_runtime_and_registry_client_diagnostics(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()
        registry.active_client_ids.return_value = ["sensor-a"]
        registry.get.return_value = SimpleNamespace(
            sample_rate_hz=800,
            frames_dropped=2,
            queue_overflow_drops=1,
            server_queue_drops=0,
            parse_errors=0,
            duplicates_received=3,
        )
        ingest_diagnostics = IngestDiagnosticsCollector()
        ingest_diagnostics.note_udp_processed(
            client_id="sensor-a",
            sample_count=400,
            queue_age_s=0.015,
            ack_latency_s=0.025,
            processed_at_mono_s=10.0,
            count_for_ingest=True,
        )
        ingest_diagnostics.note_udp_processed(
            client_id="sensor-a",
            sample_count=400,
            queue_age_s=0.020,
            ack_latency_s=0.030,
            processed_at_mono_s=11.0,
            count_for_ingest=True,
        )
        ingest_diagnostics.note_late_packet(client_id="sensor-a")
        ingest_diagnostics.note_raw_capture_queue_depth(3)
        ingest_diagnostics.note_ws_publish(connection_count=1, duration_s=0.012)

        result = _snapshot(
            loop_state,
            health_state,
            registry,
            run_recorder,
            ingest_diagnostics=ingest_diagnostics,
        )

        assert result["ingest"]["udp"]["max_packet_queue_age_ms"] == 20.0
        assert result["ingest"]["raw_capture"]["queue_max_depth"] == 3
        assert result["ingest"]["ws_publish"]["active_connections"] == 1
        assert result["ingest"]["ws_publish"]["max_publish_duration_ms"] == 12.0
        assert result["ingest"]["clients"] == [
            {
                "client_id": "sensor-a",
                "advertised_sample_rate_hz": 800,
                "estimated_ingest_hz": 400.0,
                "processed_packets": 2,
                "processed_samples": 800,
                "late_packets": 1,
                "last_packet_queue_age_ms": 20.0,
                "last_ack_latency_ms": 30.0,
                "frames_dropped": 2,
                "queue_overflow_drops": 1,
                "server_queue_drops": 0,
                "parse_errors": 0,
                "duplicates_received": 3,
            }
        ]


class TestBuildSystemHealthSnapshotDegraded:
    def test_startup_not_ready_is_degraded(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        registry, run_recorder = _make_deps()

        result = build_system_health_snapshot(
            loop_state,
            health_state,
            _make_processor(),
            registry,
            run_recorder,
            IngestDiagnosticsCollector(),
        )

        assert result["status"] == "degraded"
        assert any("startup_state" in reason for reason in result["degradation_reasons"])

    def test_startup_error_is_degraded(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        health_state.mark_failed("init", "something blew up")
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "degraded"
        assert "startup_error" in result["degradation_reasons"]

    def test_background_task_failure_is_degraded(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        health_state.record_task_failure("pump_task", "connection reset")
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "degraded"
        assert "background_task_failures" in result["degradation_reasons"]

    def test_processing_state_not_ok_is_degraded(self) -> None:
        loop_state = ProcessingLoopState(processing_state=ProcessingHealth.FATAL)
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "degraded"
        assert any("processing_state" in reason for reason in result["degradation_reasons"])

    def test_persistence_write_error_is_degraded(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps(
            persistence={**_clean_persistence(), "write_error": True}
        )

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "degraded"
        assert "persistence_write_error" in result["degradation_reasons"]

    def test_db_corruption_is_degraded(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        health_state.mark_db_corrupted("row 7 missing from index")
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "degraded"
        assert result["db_corruption_detected"] is True
        assert "db_corruption_detected" in result["degradation_reasons"]


class TestBuildSystemHealthSnapshotWarn:
    def test_startup_warnings_only_is_warn(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        health_state.startup_warnings = ["low disk space"]
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "warn"
        assert "startup_warnings" in result["degradation_reasons"]

    def test_processing_failures_gt_zero_adds_reason(self) -> None:
        loop_state = ProcessingLoopState(processing_failure_count=3)
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "warn"
        assert "processing_failures" in result["degradation_reasons"]

    def test_last_failure_category_adds_reason(self) -> None:
        loop_state = ProcessingLoopState(last_failure_category="io_error")
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "warn"
        assert "processing_failure:io_error" in result["degradation_reasons"]

    def test_frames_dropped_adds_reason(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps(data_loss={**_clean_data_loss(), "frames_dropped": 5})

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "warn"
        assert "frames_dropped" in result["degradation_reasons"]

    def test_buffer_overflow_drops_add_reason(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()
        processor = _make_processor()
        processor.buffer_overflow_drops.return_value = 3

        result = _snapshot(
            loop_state,
            health_state,
            registry,
            run_recorder,
            processor=processor,
        )

        assert result["status"] == "warn"
        assert result["data_loss"]["buffer_overflow_drops"] == 3
        assert "buffer_overflow_drops" in result["degradation_reasons"]

    def test_sample_rate_mismatch_adds_reason(self) -> None:
        loop_state = ProcessingLoopState(sample_rate_mismatch_logged={"client_a"})
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "warn"
        assert "sample_rate_mismatch" in result["degradation_reasons"]

    def test_frame_size_mismatch_adds_reason(self) -> None:
        loop_state = ProcessingLoopState(frame_size_mismatch_logged={"client_b"})
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "warn"
        assert "frame_size_mismatch" in result["degradation_reasons"]

    def test_persistence_samples_dropped_adds_reason(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps(
            persistence={**_clean_persistence(), "samples_dropped": 10}
        )

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "warn"
        assert "persistence_samples_dropped" in result["degradation_reasons"]

    def test_analyzing_run_count_adds_reason(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps(
            persistence={**_clean_persistence(), "analyzing_run_count": 2}
        )

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "warn"
        assert "analyzing_runs_present" in result["degradation_reasons"]

    def test_last_completed_run_error_adds_reason(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps(
            persistence={**_clean_persistence(), "last_completed_run_error": True}
        )

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "warn"
        assert "last_analysis_failed" in result["degradation_reasons"]


class TestBuildSystemHealthSnapshotMultipleReasons:
    def test_two_error_conditions_both_in_reasons(self) -> None:
        loop_state = ProcessingLoopState(processing_state=ProcessingHealth.FATAL)
        health_state = _ready_health_state()
        health_state.record_task_failure("pump_task", "err")
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "degraded"
        assert any("processing_state" in reason for reason in result["degradation_reasons"])
        assert "background_task_failures" in result["degradation_reasons"]

    def test_warn_plus_error_escalates_to_degraded(self) -> None:
        loop_state = ProcessingLoopState(processing_failure_count=1)
        health_state = _ready_health_state()
        health_state.startup_warnings = ["disk low"]
        health_state.record_task_failure("a_task", "crash")
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "degraded"
        assert "startup_warnings" in result["degradation_reasons"]
        assert "processing_failures" in result["degradation_reasons"]
        assert "background_task_failures" in result["degradation_reasons"]
