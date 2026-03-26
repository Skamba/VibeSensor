"""Transport diagnostics and data-loss aggregation for ``ClientRegistry``."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import TYPE_CHECKING, Literal

from vibesensor.domain import normalize_sensor_id

if TYPE_CHECKING:
    from .registry import ClientRecord

GetOrCreateRecord = Callable[[str], "ClientRecord"]
CounterAttribute = Literal["parse_errors", "server_queue_drops"]

__all__ = ["RegistryDiagnostics"]


class RegistryDiagnostics:
    """Own transport-error counter mutation and fleet-level data-loss snapshots."""

    def __init__(
        self,
        *,
        lock: RLock,
        clients: dict[str, ClientRecord],
        get_or_create: GetOrCreateRecord,
    ) -> None:
        self._lock = lock
        self._clients = clients
        self._get_or_create = get_or_create

    def _note_client_counter(self, client_id: str | None, attr: CounterAttribute) -> None:
        if not client_id:
            return
        try:
            normalized = normalize_sensor_id(client_id)
        except ValueError:
            return
        with self._lock:
            record = self._get_or_create(normalized)
            setattr(record, attr, getattr(record, attr) + 1)

    def note_parse_error(self, client_id: str | None) -> None:
        self._note_client_counter(client_id, "parse_errors")

    def note_server_queue_drop(self, client_id: str | None) -> None:
        self._note_client_counter(client_id, "server_queue_drops")

    def data_loss_snapshot(self) -> dict[str, int]:
        with self._lock:
            snapshot: dict[str, int] = {
                "tracked_clients": len(self._clients),
                "affected_clients": 0,
                "frames_dropped": 0,
                "queue_overflow_drops": 0,
                "server_queue_drops": 0,
                "parse_errors": 0,
            }
            for record in self._clients.values():
                snapshot["frames_dropped"] += int(record.frames_dropped)
                snapshot["queue_overflow_drops"] += int(record.queue_overflow_drops)
                snapshot["server_queue_drops"] += int(record.server_queue_drops)
                snapshot["parse_errors"] += int(record.parse_errors)
                if (
                    record.frames_dropped > 0
                    or record.queue_overflow_drops > 0
                    or record.server_queue_drops > 0
                    or record.parse_errors > 0
                ):
                    snapshot["affected_clients"] += 1
            return snapshot
