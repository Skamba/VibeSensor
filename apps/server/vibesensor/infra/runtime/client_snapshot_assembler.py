"""ClientSnapshot assembly extracted from ``ClientRegistry``."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import TYPE_CHECKING

from vibesensor.infra.runtime.client_liveness_policy import ClientLivenessPolicy
from vibesensor.infra.runtime.client_metadata import ClientMetadataManager
from vibesensor.infra.runtime.client_snapshot import ClientSnapshot
from vibesensor.infra.runtime.client_snapshot_projection import project_client_snapshots
from vibesensor.shared.types.payload_types import ClientMetrics

if TYPE_CHECKING:
    from .registry import ClientRecord

ResolveNow = Callable[[float | None], float]

__all__ = ["ClientSnapshotAssembler"]


class ClientSnapshotAssembler:
    """Own the read-side assembly of transport-facing client snapshots."""

    def __init__(
        self,
        *,
        lock: RLock,
        clients: dict[str, ClientRecord],
        metadata: ClientMetadataManager,
        policy: ClientLivenessPolicy,
        resolve_now_wall: ResolveNow,
        resolve_now_mono: ResolveNow,
    ) -> None:
        self._lock = lock
        self._clients = clients
        self._metadata = metadata
        self._policy = policy
        self._resolve_now_wall = resolve_now_wall
        self._resolve_now_mono = resolve_now_mono

    def client_snapshots(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
        metrics_by_client: dict[str, ClientMetrics] | None = None,
    ) -> list[ClientSnapshot]:
        with self._lock:
            return project_client_snapshots(
                self._clients,
                self._metadata,
                now_wall=self._resolve_now_wall(now),
                now_mono=self._resolve_now_mono(now_mono),
                policy=self._policy,
                metrics_by_client=metrics_by_client,
            )
