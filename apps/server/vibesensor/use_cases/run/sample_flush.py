"""Sample-building and flush coordination extracted from ``RunRecorder``."""

from __future__ import annotations

import time
from collections.abc import Callable

from vibesensor.domain.snapshots import AnalysisSettingsSnapshot
from vibesensor.shared.ports import ClientTracker, SignalSource, SpeedProvider
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.use_cases.run.lifecycle_state import ActiveRunSnapshot, RunLifecycleState
from vibesensor.use_cases.run.persistence_writer import RunPersistenceWriter
from vibesensor.use_cases.run.sample_builder import build_sample_records, resolve_speed_context

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
        self._lifecycle = lifecycle
        self._persistence = persistence
        self._active_frames_total = active_frames_total
        self._current_run_id = current_run_id
        self._monotonic = monotonic
        self._timestamp_utc = timestamp_utc

    def build_sample_records(
        self,
        *,
        run_id: str,
        t_s: float,
        timestamp_utc: str,
    ) -> list[dict[str, object]]:
        analysis_settings_snapshot = self._analysis_settings_snapshot()
        speed_resolution = self._gps_monitor.resolve_speed()
        return build_sample_records(
            run_id=run_id,
            t_s=t_s,
            timestamp_utc=timestamp_utc,
            registry=self._registry,
            processor=self._processor,
            speed_context=resolve_speed_context(
                gps_speed_mps=self._gps_monitor.speed_mps,
                resolved_speed_mps=speed_resolution.speed_mps,
                resolved_speed_source=speed_resolution.source,
                analysis_settings_snapshot=analysis_settings_snapshot,
            ),
            analysis_settings_snapshot=analysis_settings_snapshot,
            default_sample_rate_hz=self._default_sample_rate_hz,
        )

    def build_live_sample_records(
        self,
        *,
        run_id: str,
        live_start_mono_s: float,
        timestamp_utc: str,
    ) -> list[dict[str, object]]:
        live_t_s = max(0.0, self._monotonic() - live_start_mono_s)
        return self.build_sample_records(
            run_id=run_id,
            t_s=live_t_s,
            timestamp_utc=timestamp_utc,
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
        prebuilt_rows: list[dict[str, object]] | None = None,
    ) -> bool:
        now_mono_s = self._monotonic()
        if self._current_run_id() != run_id:
            return False

        current_total = self._active_frames_total()
        self._lifecycle.refresh_data_progress(
            now_mono_s=now_mono_s,
            current_total=current_total,
        )
        history_created = self._persistence.history_run_created
        t_s = max(0.0, now_mono_s - run_start_mono_s)
        current_timestamp = self._timestamp_utc()

        if prebuilt_rows is not None:
            rows = [
                {**row, "t_s": t_s, "timestamp_utc": current_timestamp} for row in prebuilt_rows
            ]
        else:
            rows = self.build_sample_records(
                run_id=run_id,
                t_s=t_s,
                timestamp_utc=current_timestamp,
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
