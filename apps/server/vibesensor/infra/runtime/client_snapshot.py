"""Client snapshot model and API/WS presenter helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.domain import normalize_sensor_id
from vibesensor.shared.types.payload_types import ClientApiRow, ClientMetrics

if TYPE_CHECKING:
    from vibesensor.infra.runtime.registry import ClientRegistry


@dataclass(slots=True)
class ClientSnapshot:
    """Raw client snapshot assembled from registry runtime state."""

    client_id: str
    name: str
    connected: bool
    location_code: str = ""
    firmware_version: str = ""
    sample_rate_hz: int = 0
    frame_samples: int = 0
    last_seen_age_ms: int | None = None
    frames_total: int = 0
    dropped_frames: int = 0
    latest_metrics: ClientMetrics | None = None
    reset_count: int = 0
    last_reset_time: float | None = None


def build_client_api_row(
    snapshot: ClientSnapshot,
    *,
    include_metrics: bool = True,
) -> ClientApiRow:
    """Build a single client row for HTTP and WebSocket payloads."""
    normalized_client_id = normalize_sensor_id(snapshot.client_id)
    row: ClientApiRow = {
        "id": normalized_client_id,
        "mac_address": ":".join(
            normalized_client_id[idx : idx + 2] for idx in range(0, len(normalized_client_id), 2)
        ),
        "name": snapshot.name,
        "connected": snapshot.connected,
        "location_code": snapshot.location_code,
        "firmware_version": snapshot.firmware_version,
        "sample_rate_hz": snapshot.sample_rate_hz,
        "last_seen_age_ms": snapshot.last_seen_age_ms,
        "frames_total": snapshot.frames_total,
        "dropped_frames": snapshot.dropped_frames,
    }
    if include_metrics:
        row["frame_samples"] = snapshot.frame_samples
        row["latest_metrics"] = (
            snapshot.latest_metrics if snapshot.latest_metrics is not None else ClientMetrics()
        )
        row["reset_count"] = snapshot.reset_count
        row["last_reset_time"] = snapshot.last_reset_time
    return row


def build_client_api_rows(
    snapshots: list[ClientSnapshot],
    *,
    include_metrics: bool = True,
) -> list[ClientApiRow]:
    """Project registry snapshots into the existing API/WS payload rows."""
    return [
        build_client_api_row(snapshot, include_metrics=include_metrics) for snapshot in snapshots
    ]


def snapshot_for_api(
    registry: ClientRegistry,
    now: float | None = None,
    *,
    now_mono: float | None = None,
    metrics_by_client: dict[str, ClientMetrics] | None = None,
    include_metrics: bool = True,
) -> list[ClientApiRow]:
    """Convenience presenter from registry snapshots to API rows."""
    return build_client_api_rows(
        registry.client_snapshots(
            now=now,
            now_mono=now_mono,
            metrics_by_client=metrics_by_client,
        ),
        include_metrics=include_metrics,
    )
