"""Recorder configuration and lifecycle helper types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.recording.lifecycle_state import MAX_RECORDING_DURATION_S
from vibesensor.recording.run_metadata_builder import (
    build_run_metadata,
    firmware_version_for_run,
)
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.status_reporting import RunRecorderStatusSnapshot

if TYPE_CHECKING:
    from vibesensor.recording.recorder import RunRecorder

__all__ = [
    "RecorderShutdownReport",
    "RunRecorderConfig",
    "_build_run_metadata_record",
    "_shutdown_report",
]


@dataclass(kw_only=True)
class RunRecorderConfig:
    """Static configuration bundle for :class:`RunRecorder`."""

    sensor_model: str
    default_sample_rate_hz: int
    fft_window_size_samples: int
    metrics_log_hz: int = 4
    accel_scale_g_per_lsb: float | None = None
    persist_history_db: bool = True
    no_data_timeout_s: float = 60.0
    """Sensor silence that stops a run. A sensor's Wi-Fi reconnect (15 s connect
    timeout, then retries at most 10 s apart) can take 25 s or more, and the raw
    capture records the gap, so a run waits a minute before giving up."""
    max_recording_duration_s: float = MAX_RECORDING_DURATION_S


@dataclass(frozen=True, slots=True)
class RecorderShutdownReport:
    completed: bool
    active_run_id_before_stop: str | None
    analysis_queue_depth: int
    analysis_active_run_id: str | None
    analysis_queue_oldest_age_s: float | None
    analysis_in_progress: bool
    write_error: str | None
    final_status: RunRecorderStatusSnapshot


def _build_run_metadata_record(
    recorder: RunRecorder,
    run_id: str,
    start_time_utc: str,
) -> RunMetadata:
    session = recorder._recording_session
    finalize_registry = recorder._raw_capture_finalize_registry
    run_context = session.run_context_snapshot(run_id)
    return build_run_metadata(
        run_id=run_id,
        start_time_utc=start_time_utc,
        analysis_settings_snapshot=run_context.analysis_settings,
        sensor_model=recorder.sensor_model,
        firmware_version=firmware_version_for_run(recorder.registry),
        default_sample_rate_hz=recorder.default_sample_rate_hz,
        metrics_log_hz=recorder.metrics_log_hz,
        fft_window_size_samples=recorder.fft_window_size_samples,
        accel_scale_g_per_lsb=recorder.accel_scale_g_per_lsb,
        active_car_snapshot=run_context.car,
        raw_capture_manifest=finalize_registry.manifest_for_run(run_id),
        raw_capture_finalize=finalize_registry.finalize_for_run(run_id),
        ui_preferences=recorder._ui_preferences,
        sensor_snapshots=session.run_sensor_snapshots_for_run(run_id),
        guided_phases=session.guided_phases_for_run(run_id),
        start_time_unverified=session.start_time_unverified(run_id),
        start_clock=session.unverified_start_clock(run_id),
        power_issues=session.power_issues(run_id),
    )


def _shutdown_report(recorder: RunRecorder, timeout_s: float) -> RecorderShutdownReport:
    with recorder._lock:
        active_run_id_before_stop = recorder._run_id
    recorder._lifecycle.shutdown_requested = True
    try:
        final_status = recorder.stop_recording(reason="shutdown")
        analysis_completed = recorder.post_analysis.wait(timeout_s)
        health = recorder.health_snapshot()
        if not analysis_completed:
            recorder.post_analysis.shutdown(timeout_s=1.0)
        recorder.raw_capture.shutdown(timeout_s=1.0)
        return RecorderShutdownReport(
            completed=analysis_completed,
            active_run_id_before_stop=active_run_id_before_stop,
            analysis_queue_depth=health["analysis_queue_depth"],
            analysis_active_run_id=health["analysis_active_run_id"],
            analysis_queue_oldest_age_s=health["analysis_queue_oldest_age_s"],
            analysis_in_progress=health["analysis_in_progress"],
            write_error=health["write_error"],
            final_status=final_status,
        )
    finally:
        recorder._lifecycle.shutdown_requested = False
