"""Client registry — tracks active ESP32 sensor clients.

Maintains per-client state (sequence numbers, dedup windows, last-seen
timestamps) and exposes raw client snapshots for transport presenters.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import RLock
from typing import TYPE_CHECKING

from vibesensor.adapters.udp.protocol import (
    AckMessage,
    DataMessage,
    HelloMessage,
    client_id_hex,
)
from vibesensor.domain import normalize_sensor_id as _normalize_client_id
from vibesensor.infra.runtime.client_metadata import ClientMetadataManager
from vibesensor.infra.runtime.client_snapshot import ClientSnapshot
from vibesensor.infra.runtime.registry_updates import (
    DataUpdateResult,
    apply_data_message_update,
)
from vibesensor.shared.types.payload_types import ClientMetrics

if TYPE_CHECKING:
    from vibesensor.adapters.persistence.history_db import HistoryDB

LOGGER = logging.getLogger(__name__)

__all__ = ["ClientRecord", "ClientRegistry", "ClientSnapshot", "DataUpdateResult"]


def _resolve_now_wall(now: float | None) -> float:
    """Return wall-clock ``now`` if provided, else ``time.time()``."""

    return time.time() if now is None else now


def _resolve_now_mono(now_mono: float | None) -> float:
    """Return monotonic ``now_mono`` if provided, else ``time.monotonic()``."""

    return time.monotonic() if now_mono is None else now_mono


@dataclass(slots=True)
class ClientRecord:
    """Per-client state: last-seen timestamps, dedup window, hello/firmware metadata."""

    client_id: str
    name: str
    firmware_version: str = ""
    sample_rate_hz: int = 0
    frame_samples: int = 0
    last_seen: float = 0.0
    last_seen_mono: float = 0.0
    location_code: str = ""
    data_addr: tuple[str, int] | None = None
    control_addr: tuple[str, int] | None = None
    frames_total: int = 0
    frames_dropped: int = 0
    queue_overflow_drops: int = 0
    server_queue_drops: int = 0
    parse_errors: int = 0
    last_seq: int | None = None
    last_ack_cmd_seq: int | None = None
    last_ack_status: int | None = None
    reset_count: int = 0
    last_reset_time: float | None = None
    last_t0_us: int | None = None
    timing_jitter_us_ema: float = 0.0
    timing_drift_us_total: float = 0.0
    duplicates_received: int = 0
    _seen_seqs: set[int] = field(default_factory=set)
    _seen_seqs_max: int = -1

    # -- deduplication window helpers -----------------------------------------

    def clear_dedup(self) -> None:
        """Reset the per-client dedup window (e.g. on restart or hard reset)."""
        self._seen_seqs.clear()
        self._seen_seqs_max = -1

    def has_seq(self, seq: int) -> bool:
        """Return True if *seq* is already in the dedup window."""
        return seq in self._seen_seqs

    def record_seq(self, seq: int) -> None:
        """Add *seq* to the dedup window and update the running max."""
        self._seen_seqs.add(seq)
        self._seen_seqs_max = max(self._seen_seqs_max, seq)

    def prune_seqs(self, window_size: int) -> None:
        """Discard old entries so the window stays bounded to *window_size*."""
        if len(self._seen_seqs) > window_size:
            cutoff = self._seen_seqs_max - window_size + 1
            self._seen_seqs = {s for s in self._seen_seqs if s >= cutoff}


class ClientRegistry:
    """Thread-safe registry of connected ESP32 clients with raw snapshot helpers."""

    def __init__(
        self,
        db: HistoryDB | None = None,
        stale_ttl_seconds: float = 120.0,
    ):
        self._lock = RLock()
        self._stale_ttl_seconds = max(1.0, stale_ttl_seconds)
        self._clients: dict[str, ClientRecord] = {}
        self._metadata = ClientMetadataManager(
            lock=self._lock,
            get_or_create=self._get_or_create,
            list_client_names=(lambda: db.list_client_names()) if db is not None else None,
            persist_client_name=(lambda client_id, name: db.upsert_client_name(client_id, name))
            if db is not None
            else None,
            delete_client_name=(lambda client_id: db.delete_client_name(client_id))
            if db is not None
            else None,
        )

    def _get_or_create(self, client_id: str) -> ClientRecord:
        normalized = _normalize_client_id(client_id)
        record = self._clients.get(normalized)
        if record is None:
            default_name = self._metadata.default_name_for(normalized)
            record = ClientRecord(client_id=normalized, name=default_name)
            self._clients[normalized] = record
        return record

    def update_from_hello(
        self,
        hello: HelloMessage,
        addr: tuple[str, int],
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> None:
        with self._lock:
            now_ts = _resolve_now_wall(now)
            mono = _resolve_now_mono(now_mono)
            client_id = client_id_hex(hello.client_id)
            record = self._get_or_create(client_id)
            record.last_seen = now_ts
            record.last_seen_mono = mono
            hello_port = int(hello.control_port)
            record.control_addr = (addr[0], hello_port if hello_port > 0 else addr[1])
            record.sample_rate_hz = hello.sample_rate_hz
            record.frame_samples = hello.frame_samples
            if record.firmware_version and hello.firmware_version != record.firmware_version:
                record.reset_count += 1
                record.last_reset_time = now_ts
                record.clear_dedup()
            record.firmware_version = hello.firmware_version
            record.queue_overflow_drops = hello.queue_overflow_drops
            self._metadata.apply_advertised_name(record, hello.name)

    def update_from_data(
        self,
        data_msg: DataMessage,
        addr: tuple[str, int],
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> DataUpdateResult:
        """Update bookkeeping from a DATA message.

        Returns a :class:`DataUpdateResult` indicating whether a sensor reset
        was detected and whether this message is a duplicate retransmit.
        Duplicates are tracked but do not inflate counters or timing metrics.
        """
        with self._lock:
            now_ts = _resolve_now_wall(now)
            mono = _resolve_now_mono(now_mono)
            client_id = client_id_hex(data_msg.client_id)
            record = self._get_or_create(client_id)
            return apply_data_message_update(
                record,
                seq=data_msg.seq,
                sample_count=data_msg.sample_count,
                t0_us=data_msg.t0_us,
                addr=addr,
                now_ts=now_ts,
                mono=mono,
            )

    def update_from_ack(
        self,
        ack: AckMessage,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> None:
        with self._lock:
            now_ts = _resolve_now_wall(now)
            mono = _resolve_now_mono(now_mono)
            client_id = client_id_hex(ack.client_id)
            record = self._get_or_create(client_id)
            record.last_seen = now_ts
            record.last_seen_mono = mono
            record.last_ack_cmd_seq = ack.cmd_seq
            record.last_ack_status = ack.status

    def _note_client_counter(self, client_id: str | None, attr: str) -> None:
        """Increment a counter attribute on a client record, creating it if needed."""
        if not client_id:
            return
        try:
            normalized = _normalize_client_id(client_id)
        except ValueError:
            return
        with self._lock:
            record = self._get_or_create(normalized)
            setattr(record, attr, getattr(record, attr) + 1)

    def note_parse_error(self, client_id: str | None) -> None:
        self._note_client_counter(client_id, "parse_errors")

    def note_server_queue_drop(self, client_id: str | None) -> None:
        self._note_client_counter(client_id, "server_queue_drops")

    def set_name(self, client_id: str, name: str) -> ClientRecord:
        return self._metadata.set_name(client_id, name)

    def clear_name(self, client_id: str) -> ClientRecord:
        """Remove the user-assigned name and revert to the default."""
        return self._metadata.clear_name(client_id)

    def set_location(self, client_id: str, location: str) -> ClientRecord:
        """Assign a location code (e.g. ``"front-left"``) to a sensor.

        The value is stripped of leading/trailing whitespace and capped at
        64 UTF-8 bytes to bound stored string size (consistent with the
        32-byte cap applied to client names).

        Raises
        ------
        ValueError
            If the location is already assigned to a different client.
        """
        clean = location.strip()
        # Cap at 64 UTF-8 bytes without splitting multi-byte characters.
        encoded = clean.encode("utf-8", errors="ignore")
        if len(encoded) > 64:
            clean = encoded[:64].decode("utf-8", errors="ignore")
        with self._lock:
            if clean:
                conflict = next(
                    (
                        cid
                        for cid, rec in self._clients.items()
                        if cid != _normalize_client_id(client_id) and rec.location_code == clean
                    ),
                    None,
                )
                if conflict is not None:
                    conflict_name = self._clients[conflict].name or conflict
                    raise ValueError(f"Location '{clean}' already assigned to {conflict_name}")
            record = self._get_or_create(client_id)
            record.location_code = clean
            return record

    def remove_client(self, client_id: str) -> bool:
        try:
            normalized = _normalize_client_id(client_id)
        except ValueError:
            return False
        with self._lock:
            had_client = normalized in self._clients
            self._clients.pop(normalized, None)
        had_name = self._metadata.discard_name(normalized)
        return had_client or had_name

    def get(self, client_id: str) -> ClientRecord | None:
        try:
            normalized = _normalize_client_id(client_id)
        except ValueError:
            return None
        with self._lock:
            return self._clients.get(normalized)

    def active_client_ids(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> list[str]:
        with self._lock:
            mono_now = _resolve_now_mono(now_mono)
            return [
                record.client_id
                for record in self._clients.values()
                if record.last_seen_mono
                and (mono_now - record.last_seen_mono) <= self._stale_ttl_seconds
            ]

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

    def evict_stale(self, now: float | None = None, *, now_mono: float | None = None) -> list[str]:
        with self._lock:
            mono_now = _resolve_now_mono(now_mono)
            stale_ids = [
                client_id
                for client_id, record in self._clients.items()
                if record.last_seen_mono
                and (mono_now - record.last_seen_mono) > self._stale_ttl_seconds
            ]
            for client_id in stale_ids:
                self._clients.pop(client_id, None)
            return stale_ids

    def mark_cmd_sent(self, client_id: str, cmd_seq: int) -> None:
        with self._lock:
            record = self._get_or_create(client_id)
            record.last_ack_cmd_seq = cmd_seq
            record.last_ack_status = None

    def client_snapshots(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
        metrics_by_client: dict[str, ClientMetrics] | None = None,
    ) -> list[ClientSnapshot]:
        """Return raw per-client snapshots for transport presenters."""
        with self._lock:
            now_ts = _resolve_now_wall(now)
            mono_now = _resolve_now_mono(now_mono)
            snapshots: list[ClientSnapshot] = []
            all_client_ids = self._metadata.known_client_ids(self._clients)
            for client_id in all_client_ids:
                record = self._clients.get(client_id)
                if record is None:
                    snapshots.append(
                        ClientSnapshot(
                            client_id=client_id,
                            name=self._metadata.default_name_for(client_id),
                            connected=False,
                        ),
                    )
                    continue
                age_ms = (
                    int(max(0.0, now_ts - record.last_seen) * 1000) if record.last_seen else None
                )
                connected = bool(
                    record.last_seen_mono
                    and (mono_now - record.last_seen_mono) <= self._stale_ttl_seconds,
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
