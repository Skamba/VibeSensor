"""Projection of registry state into transport-facing ClientSnapshot DTOs.

Pure function that takes registry state and returns ``ClientSnapshot``
rows for connected, retained, and disconnected (named-only) clients.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vibesensor.infra.runtime.client_metadata import ClientMetadataManager
from vibesensor.infra.runtime.client_snapshot import ClientSnapshot
from vibesensor.shared.types.payload_types import ClientMetrics

if TYPE_CHECKING:
    from vibesensor.infra.runtime.registry import ClientRecord

__all__ = ["project_client_snapshots"]


def project_client_snapshots(
    clients: dict[str, ClientRecord],
    metadata: ClientMetadataManager,
    *,
    now_wall: float,
    now_mono: float,
    live_ttl_seconds: float,
    metrics_by_client: dict[str, ClientMetrics] | None = None,
) -> list[ClientSnapshot]:
    """Build transport-facing ``ClientSnapshot`` rows from registry state."""
    snapshots: list[ClientSnapshot] = []
    for client_id in metadata.known_client_ids(clients):
        record = clients.get(client_id)
        if record is None:
            snapshots.append(
                ClientSnapshot(
                    client_id=client_id,
                    name=metadata.default_name_for(client_id),
                    connected=False,
                ),
            )
            continue
        age_ms = int(max(0.0, now_wall - record.last_seen) * 1000) if record.last_seen else None
        connected = bool(
            record.last_seen_mono and (now_mono - record.last_seen_mono) <= live_ttl_seconds,
        )
        snapshots.append(
            ClientSnapshot(
                client_id=record.client_id,
                name=record.name,
                connected=connected,
                location_code=record.location_code,
                firmware_version=record.firmware_version,
                sample_rate_hz=record.sample_rate_hz,
                frame_samples=record.frame_samples,
                last_seen_age_ms=age_ms,
                frames_total=record.frames_total,
                dropped_frames=record.frames_dropped,
                latest_metrics=(
                    metrics_by_client.get(record.client_id)
                    if metrics_by_client is not None
                    else None
                ),
                reset_count=record.reset_count,
                last_reset_time=record.last_reset_time,
            ),
        )
    return snapshots
