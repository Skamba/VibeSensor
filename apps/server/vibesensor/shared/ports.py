"""Cross-layer ports shared across recording, history, runtime, and config code."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Protocol

from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot
from vibesensor.shared.types.backend_types import ResolvedSpeedSource
from vibesensor.shared.types.json_types import JsonObject

__all__ = [
    "ClientTracker",
    "ResolvedSpeedSnapshot",
    "RunPersistence",
    "SettingsReader",
    "SettingsSnapshotPersistence",
    "SignalSource",
    "SpeedProvider",
    "SpeedSourceSync",
    "TrackedClient",
]


class RunPersistence(Protocol):
    """Persistence operations needed by history queries and recording flows."""

    def list_runs(self, limit: int = 500) -> list[JsonObject]: ...

    def get_run(self, run_id: str) -> JsonObject | None: ...

    def get_run_metadata(self, run_id: str) -> JsonObject | None: ...

    def iter_run_samples(
        self,
        run_id: str,
        batch_size: int = 1000,
    ) -> Iterator[list[JsonObject]]: ...

    def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]: ...

    def create_run(
        self,
        run_id: str,
        start_time_utc: str,
        metadata: JsonObject,
    ) -> None: ...

    def append_samples(self, run_id: str, samples: list[JsonObject]) -> None: ...

    def finalize_run(
        self,
        run_id: str,
        end_time_utc: str,
        metadata: JsonObject | None = None,
    ) -> bool: ...

    def store_analysis(self, run_id: str, analysis: JsonObject) -> bool: ...

    def store_analysis_error(self, run_id: str, error: str) -> bool: ...

    def analyzing_run_health(self) -> JsonObject: ...


class SettingsReader(Protocol):
    """Read-only settings access needed by recording and history flows."""

    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot: ...

    def active_car_snapshot(self) -> CarSnapshot | None: ...


class SettingsSnapshotPersistence(Protocol):
    """Minimal settings snapshot persistence surface needed by SettingsStore."""

    def get_settings_snapshot(self) -> JsonObject | None: ...

    def set_settings_snapshot(self, snapshot: JsonObject) -> None: ...


class SignalSource(Protocol):
    """Latest-sample and metrics access needed by recording flows."""

    def clients_with_recent_data(
        self,
        client_ids: list[str],
        max_age_s: float = 3.0,
    ) -> list[str]: ...

    def latest_metrics(self, client_id: str) -> Mapping[str, object]: ...

    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float] | None: ...

    def latest_sample_rate_hz(self, client_id: str) -> int | None: ...


class TrackedClient(Protocol):
    """Minimal active-client view consumed by recording helpers."""

    client_id: str
    name: str
    firmware_version: str
    sample_rate_hz: int
    location_code: str
    frames_total: int
    frames_dropped: int
    queue_overflow_drops: int


class ClientTracker(Protocol):
    """Client lookup operations needed by recording flows."""

    def get(self, client_id: str) -> TrackedClient | None: ...

    def active_client_ids(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> list[str]: ...


class ResolvedSpeedSnapshot(Protocol):
    """Minimal resolved-speed view consumed by the recording path."""

    @property
    def speed_mps(self) -> float | None: ...

    @property
    def source(self) -> ResolvedSpeedSource: ...


class SpeedProvider(Protocol):
    """Speed access needed by recording flows."""

    speed_mps: float | None

    def resolve_speed(self) -> ResolvedSpeedSnapshot: ...


class SpeedSourceSync(Protocol):
    """Minimal speed-source sync surface needed by SettingsStore."""

    def set_manual_source_selected(self, selected: bool) -> None: ...

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None: ...

    def set_fallback_settings(
        self,
        stale_timeout_s: float | None = None,
        **kwargs: object,
    ) -> None: ...
