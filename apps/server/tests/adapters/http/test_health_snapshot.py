"""Behavioral tests for build_health_snapshot() branch coverage."""

from __future__ import annotations

from unittest.mock import MagicMock

from vibesensor.adapters.http.health_snapshot import build_health_snapshot
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_loop import ProcessingHealth, ProcessingLoopState


def _clean_data_loss() -> dict:
    return {
        "frames_dropped": 0,
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


def _make_deps(
    *,
    data_loss: dict | None = None,
    persistence: dict | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Return (registry, run_recorder) mocks with configurable snapshots."""
    registry = MagicMock()
    registry.data_loss_snapshot.return_value = data_loss or _clean_data_loss()
    run_recorder = MagicMock()
    run_recorder.health_snapshot.return_value = persistence or _clean_persistence()
    run_recorder.last_write_duration_s = 0.0
    run_recorder.max_write_duration_s = 0.0
    return registry, run_recorder


def _make_processor() -> MagicMock:
    proc = MagicMock()
    proc.intake_stats.return_value = {}
    return proc


class TestBuildHealthSnapshotOk:
    def test_all_healthy_returns_ok_status(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "ok"
        assert result["degradation_reasons"] == []

    def test_ok_snapshot_includes_expected_keys(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        for key in (
            "status",
            "startup_state",
            "startup_warnings",
            "degradation_reasons",
            "data_loss",
            "persistence",
            "processing_failures",
            "tick_count",
        ):
            assert key in result


class TestBuildHealthSnapshotDegraded:
    def test_startup_not_ready_is_degraded(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        # startup_state defaults to "starting" (not "ready")
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "degraded"
        assert any("startup_state" in r for r in result["degradation_reasons"])

    def test_startup_error_is_degraded(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        health_state.mark_failed("init", "something blew up")
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "degraded"
        assert "startup_error" in result["degradation_reasons"]

    def test_background_task_failure_is_degraded(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        health_state.record_task_failure("pump_task", "connection reset")
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "degraded"
        assert "background_task_failures" in result["degradation_reasons"]

    def test_processing_state_not_ok_is_degraded(self) -> None:
        loop_state = ProcessingLoopState(processing_state=ProcessingHealth.FATAL)
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "degraded"
        assert any("processing_state" in r for r in result["degradation_reasons"])

    def test_persistence_write_error_is_degraded(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        registry, run_recorder = _make_deps(
            persistence={**_clean_persistence(), "write_error": True}
        )

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "degraded"
        assert "persistence_write_error" in result["degradation_reasons"]


class TestBuildHealthSnapshotWarn:
    def test_startup_warnings_only_is_warn(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        health_state.startup_warnings = ["low disk space"]
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "warn"
        assert "startup_warnings" in result["degradation_reasons"]

    def test_processing_failures_gt_zero_adds_reason(self) -> None:
        loop_state = ProcessingLoopState(processing_failure_count=3)
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "warn"
        assert "processing_failures" in result["degradation_reasons"]

    def test_last_failure_category_adds_reason(self) -> None:
        loop_state = ProcessingLoopState(last_failure_category="io_error")
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "warn"
        assert "processing_failure:io_error" in result["degradation_reasons"]

    def test_frames_dropped_adds_reason(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        registry, run_recorder = _make_deps(data_loss={**_clean_data_loss(), "frames_dropped": 5})

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "warn"
        assert "frames_dropped" in result["degradation_reasons"]

    def test_sample_rate_mismatch_adds_reason(self) -> None:
        loop_state = ProcessingLoopState(sample_rate_mismatch_logged={"client_a"})
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "warn"
        assert "sample_rate_mismatch" in result["degradation_reasons"]

    def test_frame_size_mismatch_adds_reason(self) -> None:
        loop_state = ProcessingLoopState(frame_size_mismatch_logged={"client_b"})
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "warn"
        assert "frame_size_mismatch" in result["degradation_reasons"]

    def test_persistence_samples_dropped_adds_reason(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        registry, run_recorder = _make_deps(
            persistence={**_clean_persistence(), "samples_dropped": 10}
        )

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "warn"
        assert "persistence_samples_dropped" in result["degradation_reasons"]

    def test_analyzing_run_count_adds_reason(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        registry, run_recorder = _make_deps(
            persistence={**_clean_persistence(), "analyzing_run_count": 2}
        )

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "warn"
        assert "analyzing_runs_present" in result["degradation_reasons"]

    def test_last_completed_run_error_adds_reason(self) -> None:
        loop_state = ProcessingLoopState()
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        registry, run_recorder = _make_deps(
            persistence={**_clean_persistence(), "last_completed_run_error": True}
        )

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "warn"
        assert "last_analysis_failed" in result["degradation_reasons"]


class TestBuildHealthSnapshotMultipleReasons:
    def test_two_error_conditions_both_in_reasons(self) -> None:
        loop_state = ProcessingLoopState(processing_state=ProcessingHealth.FATAL)
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        health_state.record_task_failure("pump_task", "err")
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "degraded"
        assert any("processing_state" in r for r in result["degradation_reasons"])
        assert "background_task_failures" in result["degradation_reasons"]

    def test_warn_plus_error_escalates_to_degraded(self) -> None:
        loop_state = ProcessingLoopState(processing_failure_count=1)
        health_state = RuntimeHealthState()
        health_state.mark_ready()
        health_state.startup_warnings = ["disk low"]
        # Add a true error condition too
        health_state.record_task_failure("a_task", "crash")
        registry, run_recorder = _make_deps()

        result = build_health_snapshot(
            loop_state, health_state, _make_processor(), registry, run_recorder
        )

        assert result["status"] == "degraded"
        assert "startup_warnings" in result["degradation_reasons"]
        assert "processing_failures" in result["degradation_reasons"]
        assert "background_task_failures" in result["degradation_reasons"]
