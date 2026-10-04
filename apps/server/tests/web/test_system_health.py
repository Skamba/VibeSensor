"""Behavioral tests for build_system_health_snapshot() branch coverage."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import MagicMock, create_autospec

import pytest

from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.ingest.registry import ClientRegistry
from vibesensor.ingest.sensor_timing import SensorTimingGuard
from vibesensor.live.payload_types import IntakeStatsPayload
from vibesensor.live.processing_loop import ProcessingHealth, ProcessingLoopState
from vibesensor.live.processor import SignalProcessor
from vibesensor.recording.recorder import RunRecorder
from vibesensor.web.health_snapshot import build_system_health_snapshot
from vibesensor.web.health_state import RuntimeHealthState


def _clean_data_loss() -> dict:
    return {
        "frames_dropped": 0,
        "buffer_overflow_drops": 0,
        "queue_overflow_drops": 0,
        "server_queue_drops": 0,
        "parse_errors": 0,
    }


def _clean_recent_data_loss() -> dict:
    return {
        "window_s": 60,
        "frame_loss_clients": 0,
        "frames_dropped": 0,
        "expected_frames_dropped": 0,
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


def _make_deps(
    *,
    data_loss: dict | None = None,
    recent_data_loss: dict | None = None,
    persistence: dict | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Return (registry, run_recorder) mocks with configurable snapshots."""
    registry = create_autospec(ClientRegistry, instance=True)
    registry.data_loss_snapshot.return_value = data_loss or _clean_data_loss()
    registry.recent_data_loss_snapshot.return_value = recent_data_loss or _clean_recent_data_loss()
    registry.active_client_ids.return_value = []
    registry.get.return_value = None
    run_recorder = create_autospec(RunRecorder, instance=True)
    run_recorder.health_snapshot.return_value = persistence or _clean_persistence()
    run_recorder.last_write_duration_s = 0.0
    run_recorder.max_write_duration_s = 0.0
    return registry, run_recorder


def _make_processor(*, intake_stats: IntakeStatsPayload | None = None) -> MagicMock:
    proc = create_autospec(SignalProcessor, instance=True)
    proc.intake_stats.return_value = intake_stats or _clean_intake_stats()
    proc.buffer_overflow_drops.return_value = 0
    proc.recent_buffer_overflow_drops.return_value = 0
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
    bundled_firmware_version: str = "",
) -> dict:
    return build_system_health_snapshot(
        loop_state,
        health_state,
        _make_processor() if processor is None else processor,
        registry,
        run_recorder,
        IngestDiagnosticsCollector() if ingest_diagnostics is None else ingest_diagnostics,
        bundled_firmware_version,
    )


class TestBuildSystemHealthSnapshotOk:
    def test_all_healthy_returns_ok_status(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "ok"
        assert result["degradation_reasons"] == []
        assert result["subsystems"]["runtime"] == {"status": "ready", "reason_codes": []}
        assert result["subsystems"]["recorder"] == {"status": "ready", "reason_codes": []}

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

    def test_ingest_snapshot_merges_runtime_and_registry_client_diagnostics(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()
        registry.active_client_ids.return_value = ["sensor-a"]
        registry.get.return_value = SimpleNamespace(
            firmware_version="2026.10.5+0123456789ab",
            sample_rate_hz=800,
            frames_dropped=5,
            expected_frames_dropped=3,
            last_expected_loss_reason="bluetooth_scan",
            queue_overflow_drops=1,
            server_queue_drops=0,
            parse_errors=0,
            duplicates_received=3,
            # Stamps 14.5 s behind real time at 742 samples/s (firmware cf117a43e).
            timing_guard=SensorTimingGuard(
                state="timestamp_lag", min_lag_us=14_500_000, effective_rate_hz=742.0
            ),
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
            bundled_firmware_version="2026.10.5+0123456789ab",
        )

        assert result["ingest"]["udp"]["max_packet_queue_age_ms"] == 20.0
        assert result["ingest"]["raw_capture"]["queue_max_depth"] == 3
        assert result["ingest"]["raw_capture"]["pressure_state"] == "warn"
        assert result["ingest"]["ws_publish"]["active_connections"] == 1
        assert result["ingest"]["ws_publish"]["max_publish_duration_ms"] == 12.0
        [client] = result["ingest"]["clients"]
        assert client["client_id"] == "sensor-a"
        assert client["firmware_version"] == "2026.10.5+0123456789ab"
        assert client["firmware_status"] == "current"
        assert client["advertised_sample_rate_hz"] == 800
        assert client["estimated_ingest_hz"] == 400.0
        assert client["processed_packets"] == 2
        assert client["processed_samples"] == 800
        assert client["late_packets"] == 1
        assert client["last_packet_queue_age_ms"] == 20.0
        assert client["last_ack_latency_ms"] == 30.0
        assert client["frames_dropped"] == 5
        assert client["expected_frames_dropped"] == 3
        assert client["last_expected_loss_reason"] == "bluetooth_scan"
        assert client["queue_overflow_drops"] == 1
        assert client["duplicates_received"] == 3
        assert client["timing_state"] == "timestamp_lag"
        assert client["timing_min_lag_ms"] == 14_500.0
        assert client["effective_sample_rate_hz"] == 742.0
        assert "sensor_timestamp_lag" in result["degradation_reasons"]
        assert result["status"] == "warn"

    def test_outdated_sensor_firmware_degrades_only_the_firmware_subsystem(self) -> None:
        registry, run_recorder = _make_deps()
        registry.active_client_ids.return_value = ["sensor-a"]
        registry.get.return_value = SimpleNamespace(
            firmware_version="esp32-atom-0.1",
            sample_rate_hz=800,
            frames_dropped=0,
            expected_frames_dropped=0,
            last_expected_loss_reason=None,
            queue_overflow_drops=0,
            server_queue_drops=0,
            parse_errors=0,
            duplicates_received=0,
            timing_guard=SensorTimingGuard(),
        )

        result = _snapshot(
            ProcessingLoopState(),
            _ready_health_state(),
            registry,
            run_recorder,
            bundled_firmware_version="2026.10.5+0123456789ab",
        )

        [client] = result["ingest"]["clients"]
        assert client["firmware_status"] == "outdated"
        assert result["subsystems"]["firmware"] == {
            "status": "degraded",
            "reason_codes": ["sensor_firmware_outdated"],
        }
        # The updater's boot check reads the overall status: a sensor still to
        # be flashed must not roll back a server update.
        assert result["status"] == "ok"
        assert result["degradation_reasons"] == []


_HEALTH_MUTATIONS: dict[str, Callable[[RuntimeHealthState], None]] = {
    "startup_failed": lambda h: h.mark_failed("init", "something blew up"),
    "task_failure": lambda h: h.record_task_failure("pump_task", "connection reset"),
    "db_corrupted": lambda h: h.mark_db_corrupted("row 7 missing from index"),
    "startup_warning": lambda h: setattr(h, "startup_warnings", ["low disk space"]),
}

# Each scenario may set: loop (ProcessingLoopState kwargs), health (mutation name),
# recent_data_loss / persistence (snapshot overrides), fields (extra expected result fields).
_SINGLE_CONDITION_CASES = [
    pytest.param({"health": "startup_failed"}, "degraded", "startup_error", id="startup-error"),
    pytest.param(
        {
            "health": "task_failure",
            "fields": {"runtime": ["unhealthy", "background_task_failures"]},
        },
        "degraded",
        "background_task_failures",
        id="background-task-failure",
    ),
    pytest.param(
        {"loop": {"processing_state": ProcessingHealth.FATAL}},
        "degraded",
        f"processing_state:{ProcessingHealth.FATAL}",
        id="processing-state-not-ok",
    ),
    pytest.param(
        {
            "persistence": {"write_error": True},
            "fields": {"recorder": ["unhealthy", "persistence_write_error"]},
        },
        "degraded",
        "persistence_write_error",
        id="persistence-write-error",
    ),
    pytest.param(
        {"health": "db_corrupted", "fields": {"db_corruption_detected": True}},
        "degraded",
        "db_corruption_detected",
        id="db-corruption",
    ),
    pytest.param({"health": "startup_warning"}, "warn", "startup_warnings", id="startup-warnings"),
    pytest.param(
        {"loop": {"processing_failure_count": 3}},
        "warn",
        "processing_failures",
        id="processing-failures",
    ),
    pytest.param(
        {"loop": {"last_failure_category": "io_error"}},
        "warn",
        "processing_failure:io_error",
        id="last-failure-category",
    ),
    pytest.param(
        {
            "recent_data_loss": {"frame_loss_clients": 1, "frames_dropped": 5},
            "fields": {"ingest": ["degraded", "frames_dropped"]},
        },
        "warn",
        "frames_dropped",
        id="frames-dropped",
    ),
    pytest.param(
        {"loop": {"sample_rate_mismatch_logged": {"client_a"}}},
        "warn",
        "sample_rate_mismatch",
        id="sample-rate-mismatch",
    ),
    pytest.param(
        {"loop": {"frame_size_mismatch_logged": {"client_b"}}},
        "warn",
        "frame_size_mismatch",
        id="frame-size-mismatch",
    ),
    pytest.param(
        {"persistence": {"samples_dropped": 10}},
        "warn",
        "persistence_samples_dropped",
        id="persistence-samples-dropped",
    ),
    pytest.param(
        {"persistence": {"analyzing_run_count": 2}},
        "warn",
        "analyzing_runs_present",
        id="analyzing-runs-present",
    ),
    pytest.param(
        {"persistence": {"last_completed_run_error": True}},
        "warn",
        "last_analysis_failed",
        id="last-analysis-failed",
    ),
]


class TestBuildSystemHealthSnapshotSingleCondition:
    @pytest.mark.parametrize(
        ("scenario", "expected_status", "expected_reason"), _SINGLE_CONDITION_CASES
    )
    def test_single_condition_sets_status_and_reason(
        self,
        scenario: dict,
        expected_status: str,
        expected_reason: str,
    ) -> None:
        loop_state = ProcessingLoopState(**scenario.get("loop", {}))
        health_state = _ready_health_state()
        if "health" in scenario:
            _HEALTH_MUTATIONS[scenario["health"]](health_state)
        registry, run_recorder = _make_deps(
            recent_data_loss={
                **_clean_recent_data_loss(),
                **scenario.get("recent_data_loss", {}),
            },
            persistence={**_clean_persistence(), **scenario.get("persistence", {})},
        )

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == expected_status
        assert expected_reason in result["degradation_reasons"]
        for key, expected in scenario.get("fields", {}).items():
            if key in result["subsystems"]:
                status, reason_code = expected
                assert result["subsystems"][key] == {
                    "status": status,
                    "reason_codes": [reason_code],
                }
            else:
                assert result[key] == expected

    def test_startup_not_ready_is_degraded(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        registry, run_recorder = _make_deps()

        result = _snapshot(loop_state, health_state, registry, run_recorder)

        assert result["status"] == "degraded"
        assert any("startup_state" in reason for reason in result["degradation_reasons"])

    def test_raw_capture_queue_overflow_is_degraded(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()
        ingest_diagnostics = IngestDiagnosticsCollector()
        ingest_diagnostics.note_raw_capture_drop(depth=0)

        result = _snapshot(
            loop_state,
            health_state,
            registry,
            run_recorder,
            ingest_diagnostics=ingest_diagnostics,
        )

        assert result["status"] == "warn"
        assert result["ingest"]["raw_capture"]["pressure_state"] == "warn"
        assert result["ingest"]["raw_capture"]["dropped_chunks"] == 1
        assert "raw_capture_dropped_chunks" in result["degradation_reasons"]
        assert result["subsystems"]["raw_capture"] == {
            "status": "degraded",
            "reason_codes": ["raw_capture_dropped_chunks", "raw_capture_pressure"],
        }

    def test_buffer_overflow_drops_add_reason(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = _ready_health_state()
        registry, run_recorder = _make_deps()
        processor = _make_processor()
        processor.buffer_overflow_drops.return_value = 3
        processor.recent_buffer_overflow_drops.return_value = 3

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

    def test_old_data_loss_keeps_totals_but_not_the_warning(self) -> None:
        # The totals never reset; only loss in the recent window warns.
        totals = {
            "frames_dropped": 40,
            "buffer_overflow_drops": 0,
            "queue_overflow_drops": 2,
            "server_queue_drops": 1,
            "parse_errors": 3,
        }
        registry, run_recorder = _make_deps(data_loss=totals)
        processor = _make_processor()
        processor.buffer_overflow_drops.return_value = 7

        result = _snapshot(
            ProcessingLoopState(),
            _ready_health_state(),
            registry,
            run_recorder,
            processor=processor,
        )

        assert result["status"] == "ok"
        assert result["degradation_reasons"] == []
        assert result["subsystems"]["ingest"] == {"status": "ready", "reason_codes": []}
        assert result["data_loss"] == {**totals, "buffer_overflow_drops": 7}
        assert result["recent_data_loss"] == {
            **_clean_recent_data_loss(),
            "buffer_overflow_drops": 0,
        }

    @pytest.mark.parametrize("key", ["queue_overflow_drops", "server_queue_drops", "parse_errors"])
    def test_recent_counter_loss_warns(self, key: str) -> None:
        registry, run_recorder = _make_deps(recent_data_loss={**_clean_recent_data_loss(), key: 1})

        result = _snapshot(ProcessingLoopState(), _ready_health_state(), registry, run_recorder)

        assert result["status"] == "warn"
        assert result["degradation_reasons"] == [key]

    def test_dropped_frames_below_the_loss_ratio_do_not_warn(self) -> None:
        registry, run_recorder = _make_deps(
            recent_data_loss={**_clean_recent_data_loss(), "frames_dropped": 1}
        )

        result = _snapshot(ProcessingLoopState(), _ready_health_state(), registry, run_recorder)

        assert result["status"] == "ok"


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
