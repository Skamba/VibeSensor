"""Sample-building and flush coordination extracted from ``RunRecorder``."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.ports import ClientTracker, SensorMetadataReader, SignalSource, SpeedProvider
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.use_cases.run.lifecycle_state import ActiveRunSnapshot, RunLifecycleState
from vibesensor.use_cases.run.persistence_writer import RunPersistenceWriter
from vibesensor.use_cases.run.sample_builder import _LIVE_SAMPLE_WINDOW_S, build_sample_records
from vibesensor.use_cases.run.sample_speed_context import resolve_speed_context

AnalysisSettingsProvider = Callable[[], AnalysisSettingsSnapshot]
CurrentTotalProvider = Callable[[], int]
RunIdProvider = Callable[[], str | None]
MonotonicFn = Callable[[], float]
TimestampFn = Callable[[], str]

__all__ = ["SampleFlushOrchestrator"]


class SampleFlushOrchestrator:
    """Own sample building, flush decisions, and auto-stop timing checks."""

    def __init__(
        self,
        *,
        registry: ClientTracker,
        gps_monitor: SpeedProvider,
        processor: SignalSource,
        analysis_settings_snapshot: AnalysisSettingsProvider,
        default_sample_rate_hz: int,
        sensor_metadata_reader: SensorMetadataReader | None = None,
        lifecycle: RunLifecycleState,
        persistence: RunPersistenceWriter,
        active_frames_total: CurrentTotalProvider,
        current_run_id: RunIdProvider,
        monotonic: MonotonicFn = time.monotonic,
        timestamp_utc: TimestampFn = utc_now_iso,
    ) -> None:
        self._registry = registry
        self._gps_monitor = gps_monitor
        self._processor = processor
        self._analysis_settings_snapshot = analysis_settings_snapshot
        self._default_sample_rate_hz = default_sample_rate_hz
        self._sensor_metadata_reader = sensor_metadata_reader
        self._lifecycle = lifecycle
        self._persistence = persistence
        self._active_frames_total = active_frames_total
        self._current_run_id = current_run_id
        self._monotonic = monotonic
        self._timestamp_utc = timestamp_utc

    def _refresh_recent_client_metrics(
        self,
        *,
        max_age_s: float | None = _LIVE_SAMPLE_WINDOW_S,
    ) -> None:
        """Refresh metrics only for clients that still have recent live samples."""
        active_client_ids = self._registry.active_client_ids()
        if max_age_s is None:
            recent_client_ids = sorted(set(active_client_ids))
        else:
            recent_client_ids = sorted(
                set(
                    self._processor.clients_with_recent_data(
                        active_client_ids,
                        max_age_s=max_age_s,
                    ),
                ),
            )
        for client_id in recent_client_ids:
            record = self._registry.get(client_id)
            record_rate_hz = int(record.sample_rate_hz or 0) if record is not None else 0
            sample_rate_hz = (
                self._processor.latest_sample_rate_hz(client_id)
                or record_rate_hz
                or self._default_sample_rate_hz
                or None
            )
            self._processor.compute_metrics(
                client_id,
                sample_rate_hz=int(sample_rate_hz) if sample_rate_hz else None,
            )

    def build_sample_records(
        self,
        *,
        run_id: str,
        t_s: float,
        timestamp_utc: str,
        live_sample_window_s: float | None = _LIVE_SAMPLE_WINDOW_S,
        run_start_mono_s: float | None = None,
    ) -> list[SensorFrame]:
        analysis_settings_snapshot = self._analysis_settings_snapshot()
        speed_resolution = self._gps_monitor.resolve_speed()
        return build_sample_records(
            run_id=run_id,
            t_s=t_s,
            timestamp_utc=timestamp_utc,
            registry=self._registry,
            processor=self._processor,
            speed_context=resolve_speed_context(
                gps_speed_mps=self._gps_monitor.gps_speed_mps,
                resolved_speed_mps=speed_resolution.speed_mps,
                resolved_speed_source=speed_resolution.source,
                analysis_settings_snapshot=analysis_settings_snapshot,
                measured_engine_rpm=self._gps_monitor.engine_rpm,
                measured_engine_rpm_source=self._gps_monitor.engine_rpm_source,
            ),
            analysis_settings_snapshot=analysis_settings_snapshot,
            default_sample_rate_hz=self._default_sample_rate_hz,
            sensor_metadata_reader=self._sensor_metadata_reader,
            live_sample_window_s=live_sample_window_s,
            run_start_mono_s=run_start_mono_s,
        )

    def build_live_sample_records(
        self,
        *,
        run_id: str,
        live_start_mono_s: float,
        timestamp_utc: str,
    ) -> list[SensorFrame]:
        live_t_s = max(0.0, self._monotonic() - live_start_mono_s)
        return self.build_sample_records(
            run_id=run_id,
            t_s=live_t_s,
            timestamp_utc=timestamp_utc,
            run_start_mono_s=live_start_mono_s,
        )

    def pending_flush_snapshot(self) -> ActiveRunSnapshot | None:
        return self._lifecycle.pending_flush_snapshot(
            current_total=self._active_frames_total(),
            history_run_created=self._persistence.history_run_created,
        )

    def append_records(
        self,
        run_id: str,
        start_time_utc: str,
        run_start_mono_s: float,
        *,
        prebuilt_rows: list[SensorFrame] | None = None,
        refresh_metrics: bool = False,
    ) -> bool:
        now_mono_s = self._monotonic()
        if self._current_run_id() != run_id:
            return False

        if prebuilt_rows is None and refresh_metrics:
            # Capture one final up-to-date metrics snapshot before stop/rollover
            # finalizes the run; short runs can otherwise miss their first
            # FFT-complete batch depending on processing-loop timing.
            self._refresh_recent_client_metrics()

        current_total = self._active_frames_total()
        self._lifecycle.refresh_data_progress(
            now_mono_s=now_mono_s,
            current_total=current_total,
        )
        history_created = self._persistence.history_run_created
        t_s = max(0.0, now_mono_s - run_start_mono_s)
        current_timestamp = self._timestamp_utc()

        if prebuilt_rows is not None:
            rows = [replace(row, t_s=t_s, timestamp_utc=current_timestamp) for row in prebuilt_rows]
        else:
            rows = self.build_sample_records(
                run_id=run_id,
                t_s=t_s,
                timestamp_utc=current_timestamp,
                run_start_mono_s=run_start_mono_s,
            )
            if refresh_metrics and (
                not rows or not any(row.vibration_strength_db is not None for row in rows)
            ):
                # CI-short runs can land just beyond the normal recent-data window
                # after the simulator stops; salvage one final FFT-complete batch.
                self._refresh_recent_client_metrics(max_age_s=None)
                rows = self.build_sample_records(
                    run_id=run_id,
                    t_s=t_s,
                    timestamp_utc=current_timestamp,
                    live_sample_window_s=None,
                    run_start_mono_s=run_start_mono_s,
                )

        if (
            prebuilt_rows is not None
            and rows
            and self._lifecycle.should_drop_prebuilt_rows(
                current_total=current_total,
                history_run_created=history_created,
            )
        ):
            rows = []

        if rows:
            if self._current_run_id() != run_id:
                return False
            self._lifecycle.mark_rows_written(now_mono_s=now_mono_s)
            self._persistence.append_rows(
                run_id=run_id,
                start_time_utc=start_time_utc,
                rows=rows,
            )

        return (self._current_run_id() == run_id) and self._lifecycle.should_auto_stop(
            now_mono_s=now_mono_s,
        )
