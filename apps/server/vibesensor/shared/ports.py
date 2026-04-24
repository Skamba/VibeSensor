"""Cross-layer ports shared across recording, history, runtime, and config code."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Protocol

from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot, SpeedSourceKind
from vibesensor.shared.types.aligned_speed_context import AlignedSpeedContextSnapshot
from vibesensor.shared.types.analysis_time_range import AnalysisTimeRange
from vibesensor.shared.types.car_config import CarConfigUpdatePayload, CarsSnapshot
from vibesensor.shared.types.history_records import (
    AnalyzingRunHealth,
    HistoryRunListEntry,
    StoredHistoryRun,
)
from vibesensor.shared.types.payload_types import ClientMetrics
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunk,
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorRange,
    RawRunCapture,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_config import SensorsByMacPayload
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.shared.types.settings_snapshot import SettingsSnapshotPayload
from vibesensor.shared.types.settings_types import (
    AnalysisSettingsPayload,
    LanguageCode,
    SpeedUnitCode,
)
from vibesensor.shared.types.speed_source_config import (
    ResolvedSpeedSource,
    SpeedSourceConfig,
    SpeedSourcePayload,
    SpeedSourceUpdatePayload,
)
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest

__all__ = [
    "ActiveCarReader",
    "AnalysisSettingsStore",
    "CarSettingsStore",
    "ClockSyncBroadcaster",
    "ClientTracker",
    "ClientNamePersistence",
    "LanguageReader",
    "RegistryAckMessage",
    "RegistryDataMessage",
    "RegistryHelloMessage",
    "ResolvedSpeedSnapshot",
    "RunPersistence",
    "SensorMetadataReader",
    "SensorMetadataStore",
    "SettingsReader",
    "SettingsSnapshotPersistence",
    "SignalSource",
    "SpeedProvider",
    "SpeedSourceSettingsStore",
    "SpeedSourceSettingsReader",
    "SpeedSourceSync",
    "TrackedClient",
    "UiPreferencesStore",
]


class ClockSyncBroadcaster(Protocol):
    """Minimal control-plane surface needed to broadcast sync-clock messages."""

    def broadcast_sync_clock(self) -> int: ...


class RunPersistence(Protocol):
    """Async persistence operations needed by history queries and recording flows."""

    async def alist_runs(self, limit: int = 500) -> list[HistoryRunListEntry]: ...

    async def aget_run(self, run_id: str) -> StoredHistoryRun | None: ...

    async def aget_run_metadata(self, run_id: str) -> RunMetadata | None: ...

    async def aget_active_run_id(self) -> str | None: ...

    async def astale_analyzing_run_ids(self) -> list[str]: ...

    async def aanalyzing_run_health(self) -> AnalyzingRunHealth: ...

    async def averify_run_integrity(self, run_id: str) -> list[str]: ...

    async def acreate_run(
        self,
        run_id: str,
        start_time_utc: str,
        metadata: RunMetadata,
        case_id: str | None = None,
    ) -> None: ...

    async def aappend_samples(self, run_id: str, samples: list[SensorFrame]) -> int: ...

    async def aappend_raw_capture_chunk(self, run_id: str, chunk: RawCaptureChunk) -> None: ...

    async def afinalize_run(
        self,
        run_id: str,
        end_time_utc: str,
        metadata: RunMetadata | None = None,
        case_id: str | None = None,
    ) -> bool: ...

    async def aupdate_run_metadata(self, run_id: str, metadata: RunMetadata) -> bool: ...

    async def astore_analysis(self, run_id: str, analysis: PersistedAnalysis) -> bool: ...

    async def astore_analysis_error(self, run_id: str, error: str) -> bool: ...

    async def afinalize_raw_capture(
        self,
        run_id: str,
        *,
        run_start_monotonic_us: int | None = None,
        sensor_clock_sync: Mapping[str, RawCaptureSensorClockSync] | None = None,
        sensor_losses: Mapping[str, RawCaptureLossStats] | None = None,
    ) -> RawCaptureManifest | None: ...

    async def aget_raw_capture_manifest(self, run_id: str) -> RawCaptureManifest | None: ...

    async def aload_raw_capture(self, run_id: str) -> RawRunCapture | None: ...

    async def aload_raw_capture_sensor_range(
        self,
        run_id: str,
        client_id: str,
        *,
        sample_start: int,
        sample_count: int,
    ) -> RawCaptureSensorRange | None: ...

    async def astore_whole_run_artifacts(
        self,
        run_id: str,
        manifest: WholeRunArtifactManifest,
        *,
        artifact_contents: dict[str, bytes],
    ) -> WholeRunArtifactManifest | None: ...

    async def aget_whole_run_artifact_manifest(
        self,
        run_id: str,
    ) -> WholeRunArtifactManifest | None: ...

    async def aload_whole_run_artifact(
        self,
        run_id: str,
        artifact_key: str,
    ) -> bytes | None: ...

    async def adelete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]: ...

    async def adelete_run(self, run_id: str) -> bool: ...

    async def arecover_stale_recording_runs(self) -> int: ...

    async def aprune_terminal_runs_older_than_days(self, retention_days: int) -> int: ...

    async def aget_run_samples(self, run_id: str) -> list[SensorFrame]: ...

    def aiter_run_samples(
        self,
        run_id: str,
        batch_size: int = 1000,
        *,
        stride: int = 1,
    ) -> AsyncIterator[list[SensorFrame]]: ...


class ActiveCarReader(Protocol):
    """Minimal current-car access needed by explicit history overlay composition."""

    def active_car_snapshot(self) -> CarSnapshot | None: ...


class SettingsReader(Protocol):
    """Read-only settings access needed by recording and history flows."""

    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot: ...

    def active_car_snapshot(self) -> CarSnapshot | None: ...


class LanguageReader(Protocol):
    """Read-only language access needed by long-lived runtime collaborators."""

    @property
    def language(self) -> LanguageCode: ...


class CarSettingsStore(Protocol):
    """Car-profile CRUD surface needed by HTTP settings routes."""

    def get_cars(self) -> CarsSnapshot: ...

    def set_active_car(self, car_id: str) -> CarsSnapshot: ...

    def add_car(self, car_data: CarConfigUpdatePayload) -> CarsSnapshot: ...

    def update_car(self, car_id: str, car_data: CarConfigUpdatePayload) -> CarsSnapshot: ...

    def delete_car(self, car_id: str) -> CarsSnapshot: ...


class AnalysisSettingsStore(Protocol):
    """Derived-analysis settings surface needed by HTTP settings routes."""

    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot: ...

    def update_active_car_aspects(
        self,
        aspects: AnalysisSettingsPayload,
    ) -> AnalysisSettingsPayload: ...


class UiPreferencesStore(Protocol):
    """Language and speed-unit preference surface needed by HTTP settings routes."""

    @property
    def language(self) -> LanguageCode: ...

    def set_language(self, value: str) -> LanguageCode: ...

    @property
    def speed_unit(self) -> SpeedUnitCode: ...

    def set_speed_unit(self, value: str) -> SpeedUnitCode: ...


class SpeedSourceSettingsReader(Protocol):
    """Read-only speed-source access needed by runtime/broadcast settings consumers."""

    def speed_source_config(self) -> SpeedSourceConfig: ...


class SpeedSourceSettingsStore(Protocol):
    """Persisted speed-source surface needed by runtime settings services."""

    def get_speed_source(self) -> SpeedSourcePayload: ...

    def preview_speed_source_update(self, data: SpeedSourceUpdatePayload) -> SpeedSourceConfig: ...

    def persist_speed_source(self, config: SpeedSourceConfig) -> SpeedSourceConfig: ...

    def speed_source_config(self) -> SpeedSourceConfig: ...


class SensorMetadataReader(Protocol):
    """Read-only access to canonical persisted sensor display metadata."""

    def get_sensors(self) -> SensorsByMacPayload: ...


class SensorMetadataStore(SensorMetadataReader, Protocol):
    """Canonical sensor-metadata surface shared by settings and client routes."""

    def assign_sensor_location(self, sensor_id: str, location_code: str) -> SensorsByMacPayload: ...


class SettingsSnapshotPersistence(Protocol):
    """Async settings snapshot persistence surface needed by focused settings services."""

    async def aget_settings_snapshot(self) -> SettingsSnapshotPayload | None: ...

    async def aset_settings_snapshot(self, snapshot: SettingsSnapshotPayload) -> None: ...


class SignalSource(Protocol):
    """Latest-sample and metrics access needed by recording flows."""

    def flush_client_buffer(self, client_id: str, *, reason: str = "sensor reset") -> None: ...

    def compute_metrics(
        self,
        client_id: str,
        sample_rate_hz: int | None = None,
    ) -> ClientMetrics: ...

    def clients_with_recent_data(
        self,
        client_ids: list[str],
        max_age_s: float = 3.0,
    ) -> list[str]: ...

    def latest_metrics(self, client_id: str) -> ClientMetrics: ...

    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float] | None: ...

    def latest_sample_rate_hz(self, client_id: str) -> int | None: ...

    def latest_analysis_time_range(self, client_id: str) -> AnalysisTimeRange | None: ...


class TrackedClient(Protocol):
    """Minimal active-client view consumed by recording helpers."""

    @property
    def client_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def firmware_version(self) -> str: ...

    @property
    def sample_rate_hz(self) -> int: ...

    @property
    def location_code(self) -> str: ...

    @property
    def frames_total(self) -> int: ...

    @property
    def frames_dropped(self) -> int: ...

    @property
    def queue_overflow_drops(self) -> int: ...


class ClientTracker(Protocol):
    """Client lookup operations needed by recording flows."""

    def get(self, client_id: str) -> TrackedClient | None: ...

    def active_client_ids(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> list[str]: ...


class ClientNamePersistence(Protocol):
    """Async persisted client-name operations needed by ClientRegistry."""

    async def alist_client_names(self) -> dict[str, str]: ...

    async def aupsert_client_name(self, client_id: str, name: str) -> None: ...

    async def adelete_client_name(self, client_id: str) -> bool | None: ...


class RegistryHelloMessage(Protocol):
    """Decoded HELLO message surface that ClientRegistry consumes."""

    client_id: bytes
    control_port: int
    sample_rate_hz: int
    name: str
    firmware_version: str
    frame_samples: int
    queue_overflow_drops: int


class RegistryDataMessage(Protocol):
    """Decoded DATA message surface that ClientRegistry consumes."""

    client_id: bytes
    seq: int
    t0_us: int
    sample_count: int


class RegistryAckMessage(Protocol):
    """Decoded ACK message surface that ClientRegistry consumes."""

    client_id: bytes
    cmd_seq: int
    status: int
    device_receive_us: int | None
    device_send_us: int | None


class ResolvedSpeedSnapshot(Protocol):
    """Minimal resolved-speed view consumed by the recording path."""

    @property
    def speed_mps(self) -> float | None: ...

    @property
    def source(self) -> ResolvedSpeedSource: ...


class SpeedProvider(Protocol):
    """Speed access needed by recording flows."""

    @property
    def speed_mps(self) -> float | None: ...

    @property
    def gps_speed_mps(self) -> float | None: ...

    @property
    def engine_rpm(self) -> float | None: ...

    @property
    def engine_rpm_source(self) -> str | None: ...

    def resolve_speed(self) -> ResolvedSpeedSnapshot: ...

    def resolve_speed_context_at(
        self,
        target_mono_s: float | None,
        *,
        tolerance_s: float | None = None,
    ) -> AlignedSpeedContextSnapshot: ...


class SpeedSourceSync(Protocol):
    """Minimal speed-source sync surface needed by runtime settings services."""

    def apply_speed_source_settings(
        self,
        *,
        effective_speed_kmh: float | None,
        manual_source_selected: bool,
        stale_timeout_s: float | None = None,
        selected_source: SpeedSourceKind | str | None = None,
        obd_device_mac: str | None = None,
        obd_device_name: str | None = None,
    ) -> float | None: ...

    def set_manual_source_selected(self, selected: bool) -> None: ...

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None: ...

    def set_fallback_settings(
        self,
        stale_timeout_s: float | None = None,
        **kwargs: object,
    ) -> None: ...
