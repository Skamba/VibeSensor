"""Health snapshot builder — pure business logic, no HTTP concerns."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vibesensor.infra.runtime.processing_loop import ProcessingHealth

if TYPE_CHECKING:
    from vibesensor.use_cases.run import RunRecorder
    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.infra.runtime.registry import ClientRegistry
    from vibesensor.infra.runtime.health_state import RuntimeHealthState
    from vibesensor.infra.runtime.processing_loop import ProcessingLoopState


def build_health_snapshot(
    loop_state: ProcessingLoopState,
    health_state: RuntimeHealthState,
    processor: SignalProcessor,
    registry: ClientRegistry,
    run_recorder: RunRecorder,
) -> dict[str, Any]:
    """Build the health snapshot dict."""
    failures = loop_state.processing_failure_count
    data_loss = registry.data_loss_snapshot()
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
    if degradation_reasons:
        status = "degraded" if has_error else "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "startup_state": health_state.startup_state,
        "startup_phase": health_state.startup_phase,
        "startup_error": health_state.startup_error,
        "startup_warnings": list(health_state.startup_warnings),
        "background_task_failures": dict(health_state.background_task_failures),
        "processing_state": loop_state.processing_state,
        "processing_failures": failures,
        "processing_failure_categories": failure_categories,
        "processing_last_failure": loop_state.last_failure_message,
        "sample_rate_mismatch_count": sample_rate_mismatch_count,
        "frame_size_mismatch_count": frame_size_mismatch_count,
        "degradation_reasons": degradation_reasons,
        "data_loss": data_loss,
        "persistence": persistence,
        "intake_stats": processor.intake_stats(),
        "tick_duration_s": loop_state.last_tick_duration_s,
        "max_tick_duration_s": loop_state.max_tick_duration_s,
        "tick_count": loop_state.tick_count,
        "db_last_write_duration_s": run_recorder.last_write_duration_s,
        "db_max_write_duration_s": run_recorder.max_write_duration_s,
    }
