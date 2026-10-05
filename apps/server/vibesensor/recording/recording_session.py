"""Active recording session state and startup coordination."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from threading import RLock
from typing import TYPE_CHECKING
from uuid import uuid4

from vibesensor.common.time_utils import utc_now_iso
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.run_context import RunContextSnapshot
from vibesensor.recording.lifecycle_state import ActiveRunSnapshot, RunLifecycleState
from vibesensor.recording.persistence_writer import RunPersistenceWriter
from vibesensor.recording.raw_capture import RawCaptureLossStats
from vibesensor.recording.raw_capture_writer import RunRawCaptureWriter
from vibesensor.recording.run_context import build_run_context_snapshot
from vibesensor.recording.run_schema import GuidedPhaseName, RunGuidedPhase, RunSensorMetadata
from vibesensor.recording.run_sensor_snapshot import (
    build_run_sensor_snapshot,
    capture_run_sensor_snapshots,
)
from vibesensor.settings.sensor_config import SensorConfigPayload

if TYPE_CHECKING:
    from vibesensor.ingest.registry import ClientRegistry
    from vibesensor.live.processor import SignalProcessor
    from vibesensor.settings.sensor_settings import SensorSettingsService
    from vibesensor.settings.settings_derivation import SettingsDerivationService

__all__ = ["RunRecordingSessionService", "snapshot_server_queue_drops"]


class RunRecordingSessionService:
    """Own active-run context, sensor snapshots, and run-start side effects."""

    def __init__(
        self,
        *,
        lock: RLock,
        registry: ClientRegistry,
        processor: SignalProcessor,
        settings_reader: SettingsDerivationService | None,
        sensor_metadata_reader: SensorSettingsService | None,
        lifecycle: RunLifecycleState,
        persistence: RunPersistenceWriter,
        raw_capture: RunRawCaptureWriter,
        analysis_settings_snapshot: Callable[[], AnalysisSettingsSnapshot],
        active_frames_total: Callable[[], int],
        monotonic: Callable[[], float],
        uuid_factory: Callable[[], str] | None = None,
        clock_trusted: Callable[[], bool] | None = None,
    ) -> None:
        self._lock = lock
        self._registry = registry
        self._processor = processor
        self._settings_reader = settings_reader
        self._sensor_metadata_reader = sensor_metadata_reader
        self._lifecycle = lifecycle
        self._persistence = persistence
        self._raw_capture = raw_capture
        self._analysis_settings_snapshot = analysis_settings_snapshot
        self._active_frames_total = active_frames_total
        self._monotonic = monotonic
        self._uuid_factory = uuid_factory or (lambda: uuid4().hex)
        self._clock_trusted = clock_trusted or (lambda: True)
        self._start_time_trusted = True
        self._live_start_mono_s = monotonic()
        self._active_run_context: RunContextSnapshot | None = None
        self._run_sensor_snapshots: dict[str, RunSensorMetadata] = {}
        self._run_ingest_drop_baseline: dict[str, int] | None = None
        self._guided_phases: list[RunGuidedPhase] = []

    @property
    def live_start_mono_s(self) -> float:
        return self._live_start_mono_s

    def live_run_context_snapshot(self) -> RunContextSnapshot:
        active_car_snapshot = (
            self._settings_reader.active_car_snapshot()
            if self._settings_reader is not None
            else None
        )
        return build_run_context_snapshot(
            analysis_settings_snapshot=self._analysis_settings_snapshot(),
            active_car_snapshot=active_car_snapshot,
        )

    def run_context_snapshot(self, run_id: str | None = None) -> RunContextSnapshot:
        with self._lock:
            current_run = self._lifecycle.current_run
            active_run_context = self._active_run_context
            if (
                active_run_context is not None
                and current_run is not None
                and current_run.is_recording
                and (run_id is None or current_run.run_id == run_id)
            ):
                return active_run_context
        return self.live_run_context_snapshot()

    def recording_analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot:
        return self.run_context_snapshot().analysis_settings

    def run_sensor_snapshots_for_run(self, run_id: str) -> tuple[RunSensorMetadata, ...]:
        with self._lock:
            current_run = self._lifecycle.current_run
            if current_run is None or current_run.run_id != run_id:
                return tuple()
            return tuple(
                self._run_sensor_snapshots[client_id]
                for client_id in sorted(self._run_sensor_snapshots)
            )

    def mark_guided_phase(self, phase: GuidedPhaseName | None) -> None:
        """Close the open guided test-drive step and start *phase* (``None`` ends the test)."""
        with self._lock:
            current_run = self._lifecycle.current_run
            if current_run is None or not current_run.is_recording:
                return
            t_s = max(0.0, self._monotonic() - self._live_start_mono_s)
            if self._guided_phases and self._guided_phases[-1].end_t_s is None:
                self._guided_phases[-1] = replace(self._guided_phases[-1], end_t_s=t_s)
            if phase is not None:
                self._guided_phases.append(RunGuidedPhase(phase=phase, start_t_s=t_s))

    def current_guided_phase(self) -> GuidedPhaseName | None:
        with self._lock:
            if self._guided_phases and self._guided_phases[-1].end_t_s is None:
                return self._guided_phases[-1].phase
            return None

    def completed_guided_phases(self) -> tuple[GuidedPhaseName, ...]:
        """Distinct guided steps the driver finished in this run, in the order first finished."""
        with self._lock:
            done = (step.phase for step in self._guided_phases if step.end_t_s is not None)
            return tuple(dict.fromkeys(done))

    def start_time_unverified(self, run_id: str) -> bool:
        """Whether *run_id* started before the Pi clock was set (by NTP or a browser)."""
        with self._lock:
            current_run = self._lifecycle.current_run
            if current_run is None or current_run.run_id != run_id:
                return False
            return not self._start_time_trusted

    def guided_phases_for_run(self, run_id: str) -> tuple[RunGuidedPhase, ...]:
        with self._lock:
            current_run = self._lifecycle.current_run
            if current_run is None or current_run.run_id != run_id:
                return ()
            return tuple(self._guided_phases)

    def resolve_run_sensor_presentation(
        self,
        *,
        client_id: str,
        fallback_name: str,
        fallback_location_code: str,
        sample_rate_hz: int | None,
        firmware_version: str | None,
        sensors_by_mac: Mapping[str, SensorConfigPayload],
    ) -> tuple[str, str]:
        with self._lock:
            snapshot = self._run_sensor_snapshots.get(client_id)
            if snapshot is None:
                snapshot = build_run_sensor_snapshot(
                    sensor_id=client_id,
                    fallback_name=fallback_name,
                    fallback_location_code=fallback_location_code,
                    sample_rate_hz=sample_rate_hz,
                    firmware_version=firmware_version,
                    sensors_by_mac=sensors_by_mac,
                )
                self._run_sensor_snapshots[client_id] = snapshot
            return snapshot.display_name, snapshot.location_code

    def start_new_run(self) -> ActiveRunSnapshot:
        for client_id in self._registry.active_client_ids():
            self._processor.flush_client_buffer(
                client_id,
                reason="recording run start",
            )
        run_context = self.live_run_context_snapshot()
        self._start_time_trusted = self._clock_trusted()
        start_mono_s = self._monotonic()
        snapshot = self._lifecycle.start_new_run(
            run_id=self._uuid_factory(),
            analysis_settings_snapshot=run_context.analysis_settings,
            start_time_utc=utc_now_iso(),
            start_mono_s=start_mono_s,
            current_total=self._active_frames_total(),
        )
        self._active_run_context = run_context
        self._run_sensor_snapshots = capture_run_sensor_snapshots(
            client_ids=self._registry.active_client_ids(),
            registry=self._registry,
            sensor_metadata_reader=self._sensor_metadata_reader,
        )
        self._persistence.reset()
        self._guided_phases = []
        self._live_start_mono_s = snapshot.start_mono_s
        self._raw_capture.start_run(
            snapshot.run_id,
            run_start_monotonic_us=int(round(snapshot.start_mono_s * 1_000_000.0)),
        )
        self._run_ingest_drop_baseline = snapshot_server_queue_drops(self._registry)
        return snapshot

    def ingest_drop_losses(self) -> dict[str, RawCaptureLossStats] | None:
        return udp_ingest_drop_sensor_losses(
            self._registry,
            baseline=self._run_ingest_drop_baseline,
        )

    def clear_stopped_run(self) -> None:
        self._guided_phases = []
        self._active_run_context = None
        self._run_sensor_snapshots = {}
        self._run_ingest_drop_baseline = None


def snapshot_server_queue_drops(registry: ClientRegistry) -> dict[str, int]:
    client_ids: set[str] = set()
    client_snapshots = getattr(registry, "client_snapshots", None)
    if callable(client_snapshots):
        for client_snapshot in client_snapshots():
            client_id = str(getattr(client_snapshot, "client_id", "") or "").strip()
            if client_id:
                client_ids.add(client_id)
    else:
        client_ids.update(str(client_id) for client_id in registry.active_client_ids())
    queue_drop_snapshot: dict[str, int] = {}
    for client_id in sorted(client_ids):
        record = registry.get(client_id)
        if record is None:
            continue
        queue_drop_snapshot[client_id] = _int_attr(record, "server_queue_drops") or 0
    return queue_drop_snapshot


def udp_ingest_drop_sensor_losses(
    registry: ClientRegistry,
    *,
    baseline: dict[str, int] | None,
) -> dict[str, RawCaptureLossStats] | None:
    current = snapshot_server_queue_drops(registry)
    client_ids = set(current) | set(baseline or {})
    if not client_ids:
        return None
    losses: dict[str, RawCaptureLossStats] = {}
    for client_id in sorted(client_ids):
        delta = max(0, current.get(client_id, 0) - (baseline or {}).get(client_id, 0))
        if delta <= 0:
            continue
        losses[client_id] = RawCaptureLossStats(udp_ingest_queue_drop_count=delta)
    return losses or None


def _int_attr(value: object, name: str) -> int | None:
    raw_value = getattr(value, name, None)
    return int(raw_value) if isinstance(raw_value, int) else None
