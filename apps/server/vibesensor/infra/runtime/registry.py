"""Client registry — tracks active ESP32 sensor clients.

Maintains per-client state (sequence numbers, dedup windows, last-seen
timestamps, transport-error counters), applies HELLO/DATA/ACK bookkeeping,
owns the live/retained/stale liveness policy, and projects raw client
snapshots for transport presenters. User-assigned client names live in
``client_metadata``.
"""

from __future__ import annotations

import copy
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import RLock
from typing import Literal

from vibesensor.domain.sensor import normalize_sensor_id
from vibesensor.infra.location_assignment_validator import (
    AssignedLocation,
    LocationAssignmentValidator,
)
from vibesensor.infra.runtime.client_metadata import ClientMetadataManager
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
    "ClientLivenessPolicy",
    "ClientRecord",
    "ClientRegistry",
    "ClientSnapshot",
    "DataUpdateResult",
    "DedupWindow",
    "apply_data_message_update",
    "project_client_snapshots",
]

_DEFAULT_DEDUP_WINDOW_SIZE = 128
_RESTART_SEQ_GAP = 1000
# A sensor that reboots restarts its sequence counter and its device clock; until
# the server's clock offset is re-applied (second sync, ~10 s after boot) its
# t0_us is far behind the previous session. Genuine late/reordered UDP frames are
# only milliseconds behind, so a rewind this large means a new session.
_RESTART_T0_REWIND_US = 2_000_000
_JITTER_EMA_ALPHA = 0.2
_SEQ_MASK = 0xFFFFFFFF
_SEQ_HALF = 0x80000000


def _resolve_now_wall(now: float | None) -> float:
    """Return wall-clock ``now`` if provided, else ``time.time()``."""

    return time.time() if now is None else now


def _resolve_now_mono(now_mono: float | None) -> float:
    """Return monotonic ``now_mono`` if provided, else ``time.monotonic()``."""

    return time.monotonic() if now_mono is None else now_mono


@dataclass(slots=True)
class DedupWindow:
    """Track a bounded window of recently seen sequence numbers."""

    _seen_seqs: set[int] = field(default_factory=set)
    _seen_seqs_max: int = -1

    def clear(self) -> None:
        """Reset the dedup window to its initial empty state."""

        self._seen_seqs.clear()
        self._seen_seqs_max = -1

    def contains(self, seq: int) -> bool:
        """Return ``True`` when *seq* is still within the dedup window."""

        return seq in self._seen_seqs

    def record(self, seq: int) -> None:
        """Record *seq* and advance the tracked maximum sequence value."""

        self._seen_seqs.add(seq)
        self._seen_seqs_max = max(self._seen_seqs_max, seq)

    def prune(self, window_size: int) -> None:
        """Discard old entries so the dedup window stays bounded."""

        if len(self._seen_seqs) > window_size:
            cutoff = self._seen_seqs_max - window_size + 1
            self._seen_seqs = {seen for seen in self._seen_seqs if seen >= cutoff}

    def track(self, seq: int, *, window_size: int = _DEFAULT_DEDUP_WINDOW_SIZE) -> bool:
        """Return ``True`` for duplicates; otherwise record *seq* and prune."""

        if self.contains(seq):
            return True
        self.record(seq)
        self.prune(window_size)
        return False


@dataclass(slots=True)
class DataUpdateResult:
    """Return value of :func:`apply_data_message_update`."""

    reset_detected: bool = False
    is_duplicate: bool = False
    is_late: bool = False


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
    last_sync_monotonic_us: int | None = None
    reset_count: int = 0
    last_reset_time: float | None = None
    last_t0_us: int | None = None
    timing_jitter_us_ema: float = 0.0
    timing_drift_us_total: float = 0.0
    duplicates_received: int = 0
    dedup_window: DedupWindow = field(default_factory=DedupWindow)


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


def _is_short_session_restart(
    record: ClientRecord,
    *,
    seq: int,
    t0_us: int,
) -> bool:
    last_seq = record.last_seq
    last_t0_us = record.last_t0_us
    return (
        last_seq is not None
        and last_t0_us is not None
        and seq <= last_seq
        and t0_us > last_t0_us
        and (last_seq - seq) < _RESTART_SEQ_GAP
    )


def _is_rebooted_session(
    record: ClientRecord,
    *,
    seq: int,
    t0_us: int,
) -> bool:
    last_seq = record.last_seq
    last_t0_us = record.last_t0_us
    return (
        last_seq is not None
        and last_t0_us is not None
        and _is_seq_behind(seq=seq, last_seq=last_seq)
        and t0_us < last_t0_us - _RESTART_T0_REWIND_US
    )


def _is_seq_behind(*, seq: int, last_seq: int) -> bool:
    return seq != last_seq and ((last_seq - seq) & _SEQ_MASK) < _SEQ_HALF


def _is_late_packet(
    record: ClientRecord,
    *,
    seq: int,
    t0_us: int,
) -> bool:
    last_seq = record.last_seq
    last_t0_us = record.last_t0_us
    return (
        last_seq is not None
        and last_t0_us is not None
        and _is_seq_behind(seq=seq, last_seq=last_seq)
        and t0_us <= last_t0_us
    )


def apply_data_message_update(
    record: ClientRecord,
    *,
    seq: int,
    sample_count: int,
    t0_us: int,
    addr: tuple[str, int],
    now_ts: float,
    mono: float,
) -> DataUpdateResult:
    """Apply one DATA message to an existing client record."""

    record.last_seen = now_ts
    record.last_seen_mono = mono
    record.data_addr = (addr[0], addr[1])

    if _is_short_session_restart(record, seq=seq, t0_us=t0_us):
        # A restarted short-lived sender can reuse low sequence numbers with a
        # strictly newer t0_us before the large-gap reset heuristic fires.
        record.dedup_window.clear()
        record.last_seq = None
        record.last_t0_us = None
        record.timing_jitter_us_ema = 0.0
        record.timing_drift_us_total = 0.0

    rebooted = _is_rebooted_session(record, seq=seq, t0_us=t0_us)
    if rebooted:
        # Treat the rewound frame as the first frame of a new session instead of
        # discarding every frame as "late" until the sensor's clock catches up.
        record.reset_count += 1
        record.last_reset_time = now_ts
        record.last_seq = None
        record.last_t0_us = None
        record.timing_jitter_us_ema = 0.0
        record.timing_drift_us_total = 0.0
        record.dedup_window.clear()

    if record.dedup_window.track(seq):
        record.duplicates_received += 1
        return DataUpdateResult(is_duplicate=True)
    if _is_late_packet(record, seq=seq, t0_us=t0_us):
        return DataUpdateResult(is_late=True)

    record.frames_total += 1
    reset_detected = rebooted
    if (
        record.sample_rate_hz > 0
        and sample_count > 0
        and record.last_t0_us is not None
        and t0_us >= record.last_t0_us
    ):
        expected_delta_us = (float(sample_count) / float(record.sample_rate_hz)) * 1_000_000.0
        actual_delta_us = float(t0_us - record.last_t0_us)
        jitter_us = actual_delta_us - expected_delta_us
        record.timing_jitter_us_ema = (
            1.0 - _JITTER_EMA_ALPHA
        ) * record.timing_jitter_us_ema + _JITTER_EMA_ALPHA * jitter_us
        record.timing_drift_us_total += jitter_us

    if record.last_seq is not None:
        if seq < record.last_seq and (record.last_seq - seq) > _RESTART_SEQ_GAP:
            record.reset_count += 1
            record.last_reset_time = now_ts
            record.last_t0_us = None
            record.timing_jitter_us_ema = 0.0
            record.timing_drift_us_total = 0.0
            record.dedup_window.clear()
            record.dedup_window.track(seq)
            reset_detected = True
        else:
            expected = (record.last_seq + 1) & _SEQ_MASK
            if seq != expected:
                gap = (seq - expected) & _SEQ_MASK
                if gap < _SEQ_HALF:
                    record.frames_dropped += gap

    if record.last_seq is None or ((seq - record.last_seq) & _SEQ_MASK) < _SEQ_HALF:
        record.last_seq = seq
    record.last_t0_us = t0_us
    return DataUpdateResult(reset_detected=reset_detected)


def project_client_snapshots(
    clients: dict[str, ClientRecord],
    metadata: ClientMetadataManager,
    *,
    now_wall: float,
    now_mono: float,
    policy: ClientLivenessPolicy,
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
        connected = policy.is_live(record, now_mono)
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
        self._metadata = ClientMetadataManager(
            lock=self._lock,
            get_or_create=self._get_or_create,
            list_client_names=db.list_client_names if db is not None else None,
            persist_client_name=db.upsert_client_name if db is not None else None,
            delete_client_name=db.delete_client_name if db is not None else None,
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
                    record.last_sync_monotonic_us = server_receive_us
                record.pending_sync_cmd_seq = None
                record.pending_sync_send_us = None

    def _note_client_counter(
        self,
        client_id: str | None,
        attr: Literal["parse_errors", "server_queue_drops"],
    ) -> None:
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

    def get(self, client_id: str) -> ClientRecord | None:
        """Return a point-in-time copy of *client_id*'s record."""
        try:
            normalized = normalize_sensor_id(client_id)
        except ValueError:
            return None
        with self._lock:
            record = self._clients.get(normalized)
            if record is None:
                return None
            return copy.copy(record)

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
        with self._lock:
            return project_client_snapshots(
                self._clients,
                self._metadata,
                now_wall=_resolve_now_wall(now),
                now_mono=_resolve_now_mono(now_mono),
                policy=self._liveness_policy,
                metrics_by_client=metrics_by_client,
            )
