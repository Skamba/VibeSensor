from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import RLock
from typing import TYPE_CHECKING, Any

from .domain_models import normalize_sensor_id
from .protocol import (
    AckMessage,
    DataMessage,
    HelloMessage,
    client_id_hex,
    client_id_mac,
)

if TYPE_CHECKING:
    from .history_db import HistoryDB

LOGGER = logging.getLogger(__name__)

# Maximum number of recent sequence numbers tracked per client for
# deduplication.  Bounds memory while covering the largest realistic
# retransmit / out-of-order window on a local Wi-Fi link.
_DEDUP_WINDOW = 128
# Maximum backward distance (last_seq − incoming seq) that still looks
# like a genuine retransmit / UDP duplicate.  Anything beyond this is
# treated as a client restart so that the dedup window is cleared.
_DEDUP_RESTART_GAP = 4


def _sanitize_name(name: str) -> str:
    # Strip control characters (U+0000–U+001F, U+007F) except common whitespace
    clean = "".join(c for c in name if ord(c) >= 0x20 and ord(c) != 0x7F)
    clean = clean.strip()
    if not clean:
        return ""
    return clean.encode("utf-8", errors="ignore")[:32].decode("utf-8", errors="ignore")


@dataclass(slots=True)
class DataUpdateResult:
    """Return value of :meth:`ClientRegistry.update_from_data`."""

    reset_detected: bool = False
    is_duplicate: bool = False


@dataclass(slots=True)
class ClientRecord:
    client_id: str
    name: str
    firmware_version: str = ""
    sample_rate_hz: int = 0
    frame_samples: int = 0
    last_seen: float = 0.0
    last_seen_mono: float = 0.0
    location: str = ""
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
    latest_metrics: dict[str, Any] = field(default_factory=dict)
    duplicates_received: int = 0
    _seen_seqs: set[int] = field(default_factory=set)
    _seen_seqs_max: int = -1


class ClientRegistry:
    def __init__(
        self,
        db: HistoryDB | None = None,
        stale_ttl_seconds: float = 120.0,
    ):
        self._lock = RLock()
        self._db = db
        self._stale_ttl_seconds = max(1.0, stale_ttl_seconds)
        self._clients: dict[str, ClientRecord] = {}
        self._user_names: dict[str, str] = {}
        self._load_persisted_names()

    def _load_persisted_names(self) -> None:
        if self._db is None:
            return
        with self._lock:
            try:
                rows = self._db.list_client_names()
                for client_id, name in rows.items():
                    clean = _sanitize_name(name)
                    if clean:
                        self._user_names[client_id] = clean
            except Exception as exc:
                LOGGER.warning("Could not load persisted client names from DB: %s", exc)

    def _persist_name(self, client_id: str, name: str) -> None:
        if self._db is None:
            return
        try:
            self._db.upsert_client_name(client_id, name)
        except Exception:
            LOGGER.warning("Failed to persist client name to DB", exc_info=True)

    def _delete_persisted_name(self, client_id: str) -> None:
        if self._db is None:
            return
        try:
            self._db.delete_client_name(client_id)
        except Exception:
            LOGGER.warning("Failed to delete client name from DB", exc_info=True)

    @staticmethod
    def _resolve_now_wall(now: float | None) -> float:
        """Return wall-clock ``now`` if provided, else ``time.time()``."""
        return time.time() if now is None else now

    @staticmethod
    def _resolve_now_mono(now: float | None) -> float:
        """Return monotonic ``now`` if wall time is not injected."""
        return time.monotonic() if now is None else now

    def _get_or_create(self, client_id: str) -> ClientRecord:
        normalized = normalize_sensor_id(client_id)
        record = self._clients.get(normalized)
        if record is None:
            default_name = self._user_names.get(normalized, f"client-{normalized[-4:]}")
            record = ClientRecord(client_id=normalized, name=default_name)
            self._clients[normalized] = record
        return record

    def update_from_hello(
        self,
        hello: HelloMessage,
        addr: tuple[str, int],
        now: float | None = None,
    ) -> None:
        with self._lock:
            now_ts = self._resolve_now_wall(now)
            now_mono = self._resolve_now_mono(now)
            client_id = client_id_hex(hello.client_id)
            record = self._get_or_create(client_id)
            record.last_seen = now_ts
            record.last_seen_mono = now_mono
            hello_port = int(hello.control_port)
            record.control_addr = (addr[0], hello_port if hello_port > 0 else addr[1])
            record.sample_rate_hz = hello.sample_rate_hz
            record.frame_samples = hello.frame_samples
            if record.firmware_version and hello.firmware_version != record.firmware_version:
                record.reset_count += 1
                record.last_reset_time = now_ts
            record.firmware_version = hello.firmware_version
            record.queue_overflow_drops = hello.queue_overflow_drops
            if client_id not in self._user_names:
                advertised = _sanitize_name(hello.name)
                if advertised:
                    record.name = advertised

    @staticmethod
    def _clear_dedup(record: ClientRecord) -> None:
        """Reset the per-client dedup window (e.g. on restart or hard reset)."""
        record._seen_seqs.clear()
        record._seen_seqs_max = -1

    def update_from_data(
        self,
        data_msg: DataMessage,
        addr: tuple[str, int],
        now: float | None = None,
    ) -> DataUpdateResult:
        """Update bookkeeping from a DATA message.

        Returns a :class:`DataUpdateResult` indicating whether a sensor reset
        was detected and whether this message is a duplicate retransmit.
        Duplicates are tracked but do not inflate counters or timing metrics.
        """
        with self._lock:
            now_ts = self._resolve_now_wall(now)
            now_mono = self._resolve_now_mono(now)
            client_id = client_id_hex(data_msg.client_id)
            record = self._get_or_create(client_id)
            record.last_seen = now_ts
            record.last_seen_mono = now_mono
            record.data_addr = (addr[0], addr[1])

            # --- Deduplication check ---
            if data_msg.seq in record._seen_seqs:
                # Distinguish genuine retransmit from client restart.
                # A retransmit has seq close to last_seq (backward ≤ gap).
                # A restart reuses low seq numbers while last_seq is higher.
                # Note: backward=0 covers same-seq retransmit (last_seq ==
                # data_msg.seq) and forward duplicates — both are genuine dups.
                # Wraparound is not handled; 32-bit seq wraps after ~4 billion
                # frames which far exceeds any realistic session.
                backward = (
                    (record.last_seq - data_msg.seq)
                    if record.last_seq is not None and record.last_seq > data_msg.seq
                    else 0
                )
                if backward <= _DEDUP_RESTART_GAP:
                    record.duplicates_received += 1
                    return DataUpdateResult(is_duplicate=True)
                # Likely client restart — clear dedup window and accept.
                self._clear_dedup(record)

            record._seen_seqs.add(data_msg.seq)
            if data_msg.seq > record._seen_seqs_max:
                record._seen_seqs_max = data_msg.seq
            # Prune old entries to keep the window bounded.
            if len(record._seen_seqs) > _DEDUP_WINDOW:
                cutoff = record._seen_seqs_max - _DEDUP_WINDOW + 1
                record._seen_seqs = {s for s in record._seen_seqs if s >= cutoff}

            # --- Normal (non-duplicate) processing ---
            record.frames_total += 1
            reset_detected = False
            if (
                record.sample_rate_hz > 0
                and data_msg.sample_count > 0
                and record.last_t0_us is not None
                and data_msg.t0_us >= record.last_t0_us
            ):
                expected_delta_us = (
                    float(data_msg.sample_count) / float(record.sample_rate_hz)
                ) * 1_000_000.0
                actual_delta_us = float(data_msg.t0_us - record.last_t0_us)
                jitter_us = actual_delta_us - expected_delta_us
                alpha = 0.2
                record.timing_jitter_us_ema = (1.0 - alpha) * record.timing_jitter_us_ema + (
                    alpha * jitter_us
                )
                record.timing_drift_us_total += jitter_us
            if record.last_seq is not None:
                if data_msg.seq < record.last_seq and (record.last_seq - data_msg.seq) > 1000:
                    record.reset_count += 1
                    record.last_reset_time = now_ts
                    record.last_t0_us = None
                    record.timing_jitter_us_ema = 0.0
                    record.timing_drift_us_total = 0.0
                    record._seen_seqs.clear()
                    record._seen_seqs.add(data_msg.seq)
                    record._seen_seqs_max = data_msg.seq
                    reset_detected = True
                else:
                    expected = (record.last_seq + 1) & 0xFFFFFFFF
                    if data_msg.seq != expected:
                        gap = (data_msg.seq - expected) & 0xFFFFFFFF
                        if gap < 0x80000000:
                            record.frames_dropped += gap
            record.last_seq = data_msg.seq
            record.last_t0_us = data_msg.t0_us
            return DataUpdateResult(reset_detected=reset_detected)

    def update_from_ack(self, ack: AckMessage, now: float | None = None) -> None:
        with self._lock:
            now_ts = self._resolve_now_wall(now)
            now_mono = self._resolve_now_mono(now)
            client_id = client_id_hex(ack.client_id)
            record = self._get_or_create(client_id)
            record.last_seen = now_ts
            record.last_seen_mono = now_mono
            record.last_ack_cmd_seq = ack.cmd_seq
            record.last_ack_status = ack.status

    def note_parse_error(self, client_id: str | None) -> None:
        if not client_id:
            return
        try:
            normalized = normalize_sensor_id(client_id)
        except ValueError:
            return
        with self._lock:
            record = self._get_or_create(normalized)
            record.parse_errors += 1

    def note_server_queue_drop(self, client_id: str | None) -> None:
        if not client_id:
            return
        try:
            normalized = normalize_sensor_id(client_id)
        except ValueError:
            return
        with self._lock:
            record = self._get_or_create(normalized)
            record.server_queue_drops += 1

    def set_name(self, client_id: str, name: str) -> ClientRecord:
        clean = _sanitize_name(name)
        if not clean:
            raise ValueError("Name must be non-empty and <=32 UTF-8 bytes")
        with self._lock:
            record = self._get_or_create(client_id)
            record.name = clean
            self._user_names[record.client_id] = clean
            self._persist_name(record.client_id, clean)
            return record

    def clear_name(self, client_id: str) -> ClientRecord:
        """Remove the user-assigned name and revert to the default."""
        with self._lock:
            record = self._get_or_create(client_id)
            default = f"client-{record.client_id[-4:]}"
            record.name = default
            self._user_names.pop(record.client_id, None)
            self._delete_persisted_name(record.client_id)
            return record

    def set_location(self, client_id: str, location: str) -> ClientRecord:
        """Assign a location code (e.g. ``"front-left"``) to a sensor."""
        clean = location.strip()
        with self._lock:
            record = self._get_or_create(client_id)
            record.location = clean
            return record

    def remove_client(self, client_id: str) -> bool:
        try:
            normalized = normalize_sensor_id(client_id)
        except ValueError:
            return False
        with self._lock:
            existed = normalized in self._clients or normalized in self._user_names
            self._clients.pop(normalized, None)
            self._user_names.pop(normalized, None)
            if existed:
                self._delete_persisted_name(normalized)
            return existed

    def set_latest_metrics(self, client_id: str, metrics: dict[str, Any]) -> None:
        with self._lock:
            record = self._get_or_create(client_id)
            record.latest_metrics = metrics

    def get(self, client_id: str) -> ClientRecord | None:
        try:
            normalized = normalize_sensor_id(client_id)
        except ValueError:
            return None
        with self._lock:
            return self._clients.get(normalized)

    def active_client_ids(self, now: float | None = None) -> list[str]:
        with self._lock:
            now_mono = self._resolve_now_mono(now)
            return [
                record.client_id
                for record in self._clients.values()
                if record.last_seen_mono
                and (now_mono - record.last_seen_mono) <= self._stale_ttl_seconds
            ]

    def evict_stale(self, now: float | None = None) -> list[str]:
        with self._lock:
            now_mono = self._resolve_now_mono(now)
            stale_ids = [
                client_id
                for client_id, record in self._clients.items()
                if record.last_seen_mono
                and (now_mono - record.last_seen_mono) > self._stale_ttl_seconds
            ]
            for client_id in stale_ids:
                self._clients.pop(client_id, None)
            return stale_ids

    def mark_cmd_sent(self, client_id: str, cmd_seq: int) -> None:
        with self._lock:
            record = self._get_or_create(client_id)
            record.last_ack_cmd_seq = cmd_seq
            record.last_ack_status = None

    def snapshot_for_api(self, now: float | None = None) -> list[dict[str, Any]]:
        with self._lock:
            now_ts = self._resolve_now_wall(now)
            now_mono = self._resolve_now_mono(now)
            rows: list[dict[str, Any]] = []
            all_client_ids = sorted(set(self._clients.keys()) | set(self._user_names.keys()))
            for client_id in all_client_ids:
                record = self._clients.get(client_id)
                if record is None:
                    rows.append(
                        {
                            "id": client_id,
                            "mac_address": client_id_mac(client_id),
                            "name": self._user_names.get(client_id, f"client-{client_id[-4:]}"),
                            "connected": False,
                            "location": "",
                            "firmware_version": "",
                            "sample_rate_hz": 0,
                            "frame_samples": 0,
                            "last_seen_age_ms": None,
                            "data_addr": None,
                            "control_addr": None,
                            "frames_total": 0,
                            "dropped_frames": 0,
                            "duplicates_received": 0,
                            "queue_overflow_drops": 0,
                            "parse_errors": 0,
                            "server_queue_drops": 0,
                            "latest_metrics": {},
                            "last_ack_cmd_seq": None,
                            "last_ack_status": None,
                            "reset_count": 0,
                            "last_reset_time": None,
                            "timing_health": {},
                        }
                    )
                    continue
                age_ms = (
                    int(max(0.0, now_ts - record.last_seen) * 1000) if record.last_seen else None
                )
                connected = bool(
                    record.last_seen_mono
                    and (now_mono - record.last_seen_mono) <= self._stale_ttl_seconds
                )
                rows.append(
                    {
                        "id": record.client_id,
                        "mac_address": client_id_mac(record.client_id),
                        "name": record.name,
                        "connected": connected,
                        "location": record.location,
                        "firmware_version": record.firmware_version,
                        "sample_rate_hz": record.sample_rate_hz,
                        "frame_samples": record.frame_samples,
                        "last_seen_age_ms": age_ms,
                        "data_addr": record.data_addr,
                        "control_addr": record.control_addr,
                        "frames_total": record.frames_total,
                        "dropped_frames": record.frames_dropped,
                        "duplicates_received": record.duplicates_received,
                        "queue_overflow_drops": record.queue_overflow_drops,
                        "parse_errors": record.parse_errors,
                        "server_queue_drops": record.server_queue_drops,
                        "latest_metrics": record.latest_metrics,
                        "last_ack_cmd_seq": record.last_ack_cmd_seq,
                        "last_ack_status": record.last_ack_status,
                        "reset_count": record.reset_count,
                        "last_reset_time": record.last_reset_time,
                        "timing_health": {
                            "jitter_us_ema": record.timing_jitter_us_ema,
                            "drift_us_total": record.timing_drift_us_total,
                            "last_t0_us": record.last_t0_us,
                        },
                    }
                )
            return rows
