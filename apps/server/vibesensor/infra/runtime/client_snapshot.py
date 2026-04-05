"""Client snapshot runtime DTO."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.shared.types.payload_types import ClientMetrics


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
