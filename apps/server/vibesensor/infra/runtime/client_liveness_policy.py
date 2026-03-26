"""Client liveness and stale-retention policy for runtime registry state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ClientRecord

__all__ = ["ClientLivenessPolicy"]


@dataclass(frozen=True, slots=True)
class ClientLivenessPolicy:
    """Own the live/retained/stale time windows for tracked clients."""

    live_ttl_seconds: float = 10.0
    retention_ttl_seconds: float = 120.0

    def __post_init__(self) -> None:
        live_ttl_seconds = max(1.0, float(self.live_ttl_seconds))
        retention_ttl_seconds = max(live_ttl_seconds, float(self.retention_ttl_seconds))
        object.__setattr__(self, "live_ttl_seconds", live_ttl_seconds)
        object.__setattr__(self, "retention_ttl_seconds", retention_ttl_seconds)

    def is_live(self, record: ClientRecord, mono_now: float) -> bool:
        return bool(
            record.last_seen_mono and (mono_now - record.last_seen_mono) <= self.live_ttl_seconds,
        )

    def is_retained(self, record: ClientRecord, mono_now: float) -> bool:
        return bool(
            record.last_seen_mono
            and (mono_now - record.last_seen_mono) <= self.retention_ttl_seconds,
        )

    def active_client_ids(
        self,
        clients: Mapping[str, ClientRecord],
        mono_now: float,
    ) -> list[str]:
        return [record.client_id for record in clients.values() if self.is_live(record, mono_now)]

    def stale_client_ids(
        self,
        clients: Mapping[str, ClientRecord],
        mono_now: float,
    ) -> list[str]:
        return [
            client_id
            for client_id, record in clients.items()
            if record.last_seen_mono and not self.is_retained(record, mono_now)
        ]
