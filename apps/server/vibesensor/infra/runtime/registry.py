"""Client registry — tracks active ESP32 sensor clients.

Maintains per-client state (sequence numbers, dedup windows, last-seen
timestamps) and exposes raw client snapshots for transport presenters.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import RLock

from vibesensor.domain import normalize_sensor_id
from vibesensor.infra.location_assignment_validator import (
    AssignedLocation,
    LocationAssignmentValidator,
)
from vibesensor.infra.runtime.client_liveness_policy import ClientLivenessPolicy
from vibesensor.infra.runtime.client_metadata import ClientMetadataManager
from vibesensor.infra.runtime.client_snapshot import ClientSnapshot
from vibesensor.infra.runtime.client_snapshot_assembler import ClientSnapshotAssembler
from vibesensor.infra.runtime.dedup_window import DedupWindow
from vibesensor.infra.runtime.registry_diagnostics import RegistryDiagnostics
from vibesensor.infra.runtime.registry_updates import (
    DataUpdateResult,
    apply_data_message_update,
)
from vibesensor.shared.ports import (
    ClientNamePersistence,
    RegistryAckMessage,
    RegistryDataMessage,
    RegistryHelloMessage,
)
from vibesensor.shared.types.payload_types import ClientMetrics

LOGGER = logging.getLogger(__name__)
_LOCATION_VALIDATOR = LocationAssignmentValidator()

__all__ = [
    "ClientRecord",
    "ClientRecordSnapshot",
    "ClientRegistry",
    "ClientSnapshot",
    "DataUpdateResult",
]


def _resolve_now_wall(now: float | None) -> float:
    """Return wall-clock ``now`` if provided, else ``time.time()``."""

    return time.time() if now is None else now


def _resolve_now_mono(now_mono: float | None) -> float:
    """Return monotonic ``now_mono`` if provided, else ``time.monotonic()``."""

    return time.monotonic() if now_mono is None else now_mono


@dataclass(slots=True)
class ClientRecord:
    """Per-client state: last-seen timestamps, dedup helper, hello/firmware metadata."""

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
    pending_sync_cmd_seq: int | None = None
    pending_sync_send_us: int | None = None
    sync_offset_us: int | None = None
    sync_rtt_us: int | None = None
    reset_count: int = 0
    last_reset_time: float | None = None
    last_t0_us: int | None = None
    timing_jitter_us_ema: float = 0.0
    timing_drift_us_total: float = 0.0
    duplicates_received: int = 0
    dedup_window: DedupWindow = field(default_factory=DedupWindow)


@dataclass(frozen=True, slots=True)
class ClientRecordSnapshot:
    """Immutable point-in-time view returned by :meth:`ClientRegistry.get`."""

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
    sync_offset_us: int | None = None
    sync_rtt_us: int | None = None
    reset_count: int = 0
    last_reset_time: float | None = None
    last_t0_us: int | None = None
    timing_jitter_us_ema: float = 0.0
    timing_drift_us_total: float = 0.0
    duplicates_received: int = 0


def _snapshot_record(record: ClientRecord) -> ClientRecordSnapshot:
    return ClientRecordSnapshot(
        client_id=record.client_id,
        name=record.name,
        firmware_version=record.firmware_version,
        sample_rate_hz=record.sample_rate_hz,
        frame_samples=record.frame_samples,
        last_seen=record.last_seen,
        last_seen_mono=record.last_seen_mono,
        location_code=record.location_code,
        data_addr=record.data_addr,
        control_addr=record.control_addr,
        frames_total=record.frames_total,
        frames_dropped=record.frames_dropped,
        queue_overflow_drops=record.queue_overflow_drops,
        server_queue_drops=record.server_queue_drops,
        parse_errors=record.parse_errors,
        last_seq=record.last_seq,
        last_ack_cmd_seq=record.last_ack_cmd_seq,
        last_ack_status=record.last_ack_status,
        sync_offset_us=record.sync_offset_us,
        sync_rtt_us=record.sync_rtt_us,
        reset_count=record.reset_count,
        last_reset_time=record.last_reset_time,
        last_t0_us=record.last_t0_us,
        timing_jitter_us_ema=record.timing_jitter_us_ema,
        timing_drift_us_total=record.timing_drift_us_total,
        duplicates_received=record.duplicates_received,
    )


class ClientRegistry:
    """Thread-safe registry of live and recently-retained ESP32 clients."""

    def __init__(
        self,
        db: ClientNamePersistence | None = None,
        live_ttl_seconds: float = 10.0,
        retention_ttl_seconds: float = 120.0,
    ):
        self._lock = RLock()
        self._liveness_policy = ClientLivenessPolicy(
            live_ttl_seconds=live_ttl_seconds,
            retention_ttl_seconds=retention_ttl_seconds,
        )
        self._clients: dict[str, ClientRecord] = {}
        self._diagnostics = RegistryDiagnostics(
            lock=self._lock,
            clients=self._clients,
            get_or_create=self._get_or_create,
        )
        self._metadata = ClientMetadataManager(
            lock=self._lock,
            get_or_create=self._get_or_create,
            list_client_names=(
                (lambda: db.list_client_names()) if db is not None else None  # type: ignore[attr-defined]
            ),
            persist_client_name=(
                (lambda client_id, name: db.upsert_client_name(client_id, name))  # type: ignore[attr-defined]
                if db is not None
                else None
            ),
            delete_client_name=(
                (lambda client_id: db.delete_client_name(client_id))  # type: ignore[attr-defined]
                if db is not None
                else None
            ),
        )
        self._snapshot_assembler = ClientSnapshotAssembler(
            lock=self._lock,
            clients=self._clients,
            metadata=self._metadata,
            policy=self._liveness_policy,
            resolve_now_wall=_resolve_now_wall,
            resolve_now_mono=_resolve_now_mono,
        )

    @staticmethod
    def _normalize_wire_client_id(client_id: bytes) -> str:
        return normalize_sensor_id(client_id.hex())

    def _get_or_create(self, client_id: str) -> ClientRecord:
        normalized = normalize_sensor_id(client_id)
        record = self._clients.get(normalized)
        if record is None:
            default_name = self._metadata.default_name_for(normalized)
            record = ClientRecord(client_id=normalized, name=default_name)
            self._clients[normalized] = record
        return record

    def update_from_hello(
        self,
        hello: RegistryHelloMessage,
        addr: tuple[str, int],
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> None:
        with self._lock:
            now_ts = _resolve_now_wall(now)
            mono = _resolve_now_mono(now_mono)
            client_id = self._normalize_wire_client_id(hello.client_id)
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
                record.dedup_window.clear()
            record.firmware_version = hello.firmware_version
            record.queue_overflow_drops = hello.queue_overflow_drops
            self._metadata.apply_advertised_name(record, hello.name)

    def update_from_data(
        self,
        data_msg: RegistryDataMessage,
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
            client_id = self._normalize_wire_client_id(data_msg.client_id)
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
        ack: RegistryAckMessage,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> None:
        with self._lock:
            now_ts = _resolve_now_wall(now)
            mono = _resolve_now_mono(now_mono)
            client_id = self._normalize_wire_client_id(ack.client_id)
            record = self._get_or_create(client_id)
            record.last_seen = now_ts
            record.last_seen_mono = mono
            record.last_ack_cmd_seq = ack.cmd_seq
            record.last_ack_status = ack.status
            if record.pending_sync_cmd_seq == ack.cmd_seq:
                if (
                    ack.device_receive_us is not None
                    and ack.device_send_us is not None
                    and record.pending_sync_send_us is not None
                ):
                    server_receive_us = int(mono * 1_000_000)
                    processing_us = max(0, ack.device_send_us - ack.device_receive_us)
                    round_trip_us = max(
                        0,
                        server_receive_us - record.pending_sync_send_us - processing_us,
                    )
                    record.sync_offset_us = (
                        (record.pending_sync_send_us - ack.device_receive_us)
                        + (server_receive_us - ack.device_send_us)
                    ) // 2
                    record.sync_rtt_us = round_trip_us
                record.pending_sync_cmd_seq = None
                record.pending_sync_send_us = None

    def note_parse_error(self, client_id: str | None) -> None:
        self._diagnostics.note_parse_error(client_id)

    def note_server_queue_drop(self, client_id: str | None) -> None:
        self._diagnostics.note_server_queue_drop(client_id)

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
        normalized_client_id = normalize_sensor_id(client_id)
        clean = _LOCATION_VALIDATOR.normalize(location)
        with self._lock:
            _LOCATION_VALIDATOR.validate_assignment(
                owner_id=normalized_client_id,
                location_code=clean,
                assigned_locations=(
                    AssignedLocation(
                        owner_id=cid,
                        owner_name=rec.name or cid,
                        location_code=rec.location_code,
                    )
                    for cid, rec in self._clients.items()
                ),
            )
            record = self._get_or_create(normalized_client_id)
            record.location_code = clean
            return record

    def remove_client(self, client_id: str) -> bool:
        try:
            normalized = normalize_sensor_id(client_id)
        except ValueError:
            return False
        with self._lock:
            had_client = normalized in self._clients
            self._clients.pop(normalized, None)
        had_name = self._metadata.discard_name(normalized)
        return had_client or had_name

    def get(self, client_id: str) -> ClientRecordSnapshot | None:
        """Return an immutable point-in-time snapshot for *client_id*."""
        try:
            normalized = normalize_sensor_id(client_id)
        except ValueError:
            return None
        with self._lock:
            record = self._clients.get(normalized)
            if record is None:
                return None
            return _snapshot_record(record)

    def active_client_ids(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> list[str]:
        with self._lock:
            mono_now = _resolve_now_mono(now_mono)
            return self._liveness_policy.active_client_ids(self._clients, mono_now)

    def data_loss_snapshot(self) -> dict[str, int]:
        return self._diagnostics.data_loss_snapshot()

    def evict_stale(self, now: float | None = None, *, now_mono: float | None = None) -> list[str]:
        with self._lock:
            mono_now = _resolve_now_mono(now_mono)
            stale_ids = self._liveness_policy.stale_client_ids(self._clients, mono_now)
            for client_id in stale_ids:
                self._clients.pop(client_id, None)
            return stale_ids

    def mark_cmd_sent(
        self,
        client_id: str,
        cmd_seq: int,
        *,
        sync_send_us: int | None = None,
    ) -> None:
        with self._lock:
            record = self._get_or_create(client_id)
            record.last_ack_cmd_seq = cmd_seq
            record.last_ack_status = None
            if sync_send_us is not None:
                record.pending_sync_cmd_seq = cmd_seq
                record.pending_sync_send_us = sync_send_us

    def client_snapshots(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
        metrics_by_client: dict[str, ClientMetrics] | None = None,
    ) -> list[ClientSnapshot]:
        """Return raw per-client snapshots for transport presenters."""
        return self._snapshot_assembler.client_snapshots(
            now=now,
            now_mono=now_mono,
            metrics_by_client=metrics_by_client,
        )
