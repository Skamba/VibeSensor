"""Client API/WS payload projection helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from vibesensor.domain.sensor import normalize_sensor_id
from vibesensor.domain.sensor_firmware import firmware_status
from vibesensor.live.payload_types import ClientApiRow
from vibesensor.settings.sensor_metadata import resolve_sensor_presentation

if TYPE_CHECKING:
    from vibesensor.ingest.registry import ClientRegistry, ClientSnapshot
    from vibesensor.settings.sensor_settings import SensorSettingsService

__all__ = [
    "build_client_api_row",
    "build_client_api_rows",
    "snapshot_for_api",
]


def build_client_api_row(
    snapshot: ClientSnapshot,
    *,
    bundled_firmware_version: str = "",
    sensor_metadata_reader: SensorSettingsService | None = None,
) -> ClientApiRow:
    """Build a single client row for HTTP and WebSocket payloads.

    ``bundled_firmware_version`` is the firmware the Pi would flash ("" when unknown).
    """

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
        "firmware_status": firmware_status(snapshot.firmware_version, bundled_firmware_version),
        "sample_rate_hz": snapshot.sample_rate_hz,
        "last_seen_age_ms": snapshot.last_seen_age_ms,
        "frames_total": snapshot.frames_total,
        "dropped_frames": snapshot.dropped_frames,
        "frame_loss_recent": snapshot.frame_loss_recent,
        "frame_samples": snapshot.frame_samples,
    }
    return row


def build_client_api_rows(
    snapshots: Iterable[ClientSnapshot],
    *,
    bundled_firmware_version: str = "",
    sensor_metadata_reader: SensorSettingsService | None = None,
) -> list[ClientApiRow]:
    """Project runtime snapshots into the existing API/WS payload rows."""

    return [
        build_client_api_row(
            snapshot,
            bundled_firmware_version=bundled_firmware_version,
            sensor_metadata_reader=sensor_metadata_reader,
        )
        for snapshot in snapshots
    ]


def snapshot_for_api(
    registry: ClientRegistry,
    now: float | None = None,
    *,
    bundled_firmware_version: str = "",
    now_mono: float | None = None,
    sensor_metadata_reader: SensorSettingsService | None = None,
) -> list[ClientApiRow]:
    """Convenience presenter from client snapshots to API rows."""

    return build_client_api_rows(
        registry.client_snapshots(
            now=now,
            now_mono=now_mono,
        ),
        bundled_firmware_version=bundled_firmware_version,
        sensor_metadata_reader=sensor_metadata_reader,
    )
