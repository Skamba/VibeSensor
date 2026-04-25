"""Recorder configuration and lifecycle helper types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.shared.time_utils import current_utc_offset_seconds
from vibesensor.shared.types.run_schema import RunMetadata

from .run_metadata_builder import build_run_metadata, firmware_version_for_run
from .status_reporting import RunRecorderStatusSnapshot

if TYPE_CHECKING:
    from vibesensor.use_cases.run.logger import RunRecorder

__all__ = [
    "RecorderShutdownReport",
    "RunRecorderConfig",
    "_build_run_metadata_record",
    "_shutdown_report",
]


@dataclass
class RunRecorderConfig:
    """Static configuration bundle for :class:`RunRecorder`."""

    metrics_log_hz: int
    sensor_model: str
    default_sample_rate_hz: int
    fft_window_size_samples: int
    accel_scale_g_per_lsb: float | None = None
    persist_history_db: bool = True
    no_data_timeout_s: float = 15.0


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
    run_context = recorder._run_context_snapshot(run_id)
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
        raw_capture_manifest=recorder._raw_capture_manifest_for_run(run_id),
        raw_capture_finalize=recorder._raw_capture_finalize_for_run(run_id),
        language_reader=recorder._language_reader,
        recorded_utc_offset_seconds=current_utc_offset_seconds(),
        sensor_snapshots=recorder._run_sensor_snapshots_for_run(run_id),
    )


def _shutdown_report(recorder: RunRecorder, timeout_s: float) -> RecorderShutdownReport:
    with recorder._lock:
        active_run_id_before_stop = recorder._run_id
    recorder._lifecycle.shutdown_requested = True
    try:
        final_status = recorder.stop_recording(reason="shutdown")
        analysis_completed = recorder.wait_for_post_analysis(timeout_s)
        health = recorder.health_snapshot()
        if not analysis_completed:
            recorder.shutdown_post_analysis(timeout_s=1.0)
        recorder.shutdown_raw_capture(timeout_s=1.0)
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
