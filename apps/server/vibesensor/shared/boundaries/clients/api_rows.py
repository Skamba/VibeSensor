"""Client API/WS payload projection helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

from vibesensor.domain import normalize_sensor_id
from vibesensor.shared.ports import SensorMetadataReader
from vibesensor.shared.sensor_metadata import resolve_sensor_presentation
from vibesensor.shared.types.payload_types import ClientApiRow, ClientMetrics

__all__ = [
    "ClientSnapshotLike",
    "ClientSnapshotSource",
    "build_client_api_row",
    "build_client_api_rows",
    "snapshot_for_api",
]


class ClientSnapshotLike(Protocol):
    """Protocol describing the client snapshot fields needed for payload projection."""

    client_id: str
    name: str
    connected: bool
    location_code: str
    firmware_version: str
    sample_rate_hz: int
    frame_samples: int
    last_seen_age_ms: int | None
    frames_total: int
    dropped_frames: int
    latest_metrics: ClientMetrics | None
    reset_count: int
    last_reset_time: float | None


class ClientSnapshotSource(Protocol):
    """Collaborator that can project runtime state into client snapshots."""

    def client_snapshots(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
        metrics_by_client: dict[str, ClientMetrics] | None = None,
    ) -> Sequence[ClientSnapshotLike]: ...


def build_client_api_row(
    snapshot: ClientSnapshotLike,
    *,
    include_metrics: bool = True,
    sensor_metadata_reader: SensorMetadataReader | None = None,
) -> ClientApiRow:
    """Build a single client row for HTTP and WebSocket payloads."""

    normalized_client_id = normalize_sensor_id(snapshot.client_id)
    name = snapshot.name
    location_code = snapshot.location_code
    if sensor_metadata_reader is not None:
        name, location_code = resolve_sensor_presentation(
            sensor_id=snapshot.client_id,
            sensors_by_mac=sensor_metadata_reader.get_sensors(),
            fallback_name=snapshot.name,
            fallback_location_code=snapshot.location_code,
        )
    row: ClientApiRow = {
        "id": normalized_client_id,
        "mac_address": ":".join(
            normalized_client_id[idx : idx + 2] for idx in range(0, len(normalized_client_id), 2)
        ),
        "name": name,
        "connected": snapshot.connected,
        "location_code": location_code,
        "firmware_version": snapshot.firmware_version,
        "sample_rate_hz": snapshot.sample_rate_hz,
        "last_seen_age_ms": snapshot.last_seen_age_ms,
        "frames_total": snapshot.frames_total,
        "dropped_frames": snapshot.dropped_frames,
        "frame_samples": snapshot.frame_samples,
    }
    if include_metrics:
        row["latest_metrics"] = (
            snapshot.latest_metrics if snapshot.latest_metrics is not None else ClientMetrics()
        )
        row["reset_count"] = snapshot.reset_count
        row["last_reset_time"] = snapshot.last_reset_time
    return row


def build_client_api_rows(
    snapshots: Iterable[ClientSnapshotLike],
    *,
    include_metrics: bool = True,
    sensor_metadata_reader: SensorMetadataReader | None = None,
) -> list[ClientApiRow]:
    """Project runtime snapshots into the existing API/WS payload rows."""

    return [
        build_client_api_row(
            snapshot,
            include_metrics=include_metrics,
            sensor_metadata_reader=sensor_metadata_reader,
        )
        for snapshot in snapshots
    ]


def snapshot_for_api(
    registry: ClientSnapshotSource,
    now: float | None = None,
    *,
    now_mono: float | None = None,
    metrics_by_client: dict[str, ClientMetrics] | None = None,
    include_metrics: bool = True,
    sensor_metadata_reader: SensorMetadataReader | None = None,
) -> list[ClientApiRow]:
    """Convenience presenter from client snapshots to API rows."""

    return build_client_api_rows(
        registry.client_snapshots(
            now=now,
            now_mono=now_mono,
            metrics_by_client=metrics_by_client,
        ),
        include_metrics=include_metrics,
        sensor_metadata_reader=sensor_metadata_reader,
    )
