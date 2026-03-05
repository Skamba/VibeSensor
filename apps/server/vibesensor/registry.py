from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import RLock
from typing import TYPE_CHECKING, Any

from .protocol import (
    AckMessage,
    DataMessage,
    HelloMessage,
    client_id_hex,
    client_id_mac,
    parse_client_id,
)

if TYPE_CHECKING:
    from .history_db import HistoryDB

LOGGER = logging.getLogger(__name__)

__all__ = ["ClientRecord", "ClientRegistry", "ClientSnapshot", "DataUpdateResult"]

# Maximum number of recent sequence numbers tracked per client for
# deduplication.  Bounds memory while covering the largest realistic
# retransmit / out-of-order window on a local Wi-Fi link.
_DEDUP_WINDOW = 128
# Maximum backward distance (last_seq − incoming seq) that still looks
# like a genuine retransmit / UDP duplicate.  Anything beyond this is
# treated as a client restart so that the dedup window is cleared.
_DEDUP_RESTART_GAP = 4

# Magic-number extraction: sequence gap that indicates a client restarted
# its firmware (as opposed to a minor out-of-order retransmit).
_RESTART_SEQ_GAP = 1000
"""If a DATA message's seq is more than this many steps behind last_seq,
the client is assumed to have rebooted and counters are reset."""

# EMA smoothing factor for timing jitter tracking.
_JITTER_EMA_ALPHA = 0.2
"""Exponential moving-average smoothing factor (0–1) for per-client
timing jitter estimates.  Smaller values smooth more; 0.2 gives ~5-sample
effective window."""

# 32-bit sequence-number arithmetic masks (used in update_from_data).
_SEQ_MASK = 0xFFFFFFFF
_SEQ_HALF = 0x80000000


def _sanitize_name(name: str) -> str:
    """Sanitize a client name: strip control chars, enforce 32 UTF-8 byte limit."""
    # Strip control characters (U+0000–U+001F, U+007F) except common whitespace
    clean = "".join(c for c in name if (o := ord(c)) >= 0x20 and o != 0x7F)
    clean = clean.strip()
    if not clean:
        return ""
    # Truncate to at most 32 UTF-8 bytes without splitting multi-byte characters.
    # We slice at 32 bytes and decode with errors="ignore" which drops any
    # incomplete trailing byte sequence — this is safe because the source is
    # valid UTF-8 from ``str.encode()``.
    encoded = clean.encode("utf-8", errors="ignore")
    if len(encoded) <= 32:
        return clean
    return encoded[:32].decode("utf-8", errors="ignore")


def _normalize_client_id(client_id: str) -> str:
    return parse_client_id(client_id).hex()


@dataclass(slots=True)
class DataUpdateResult:
    """Return value of :meth:`ClientRegistry.update_from_data`."""

    reset_detected: bool = False
    is_duplicate: bool = False


@dataclass
class ClientSnapshot:
    """Flattened view of a single client for the API snapshot response.

    Collected by :meth:`ClientRegistry.snapshot_for_api` from a
    :class:`ClientRecord` and passed to :meth:`ClientRegistry._client_api_row`
    so that the row-builder receives a single structured argument instead of
    22 keyword parameters.
    """

    name: str
    connected: bool
    location: str = ""
    firmware_version: str = ""
    sample_rate_hz: int = 0
    frame_samples: int = 0
    last_seen_age_ms: int | None = None
    data_addr: tuple[str, int] | None = None
    control_addr: tuple[str, int] | None = None
    frames_total: int = 0
    dropped_frames: int = 0
    duplicates_received: int = 0
    queue_overflow_drops: int = 0
    parse_errors: int = 0
    server_queue_drops: int = 0
    latest_metrics: dict[str, Any] | None = None
    last_ack_cmd_seq: int | None = None
    last_ack_status: int | None = None
    reset_count: int = 0
    last_reset_time: float | None = None
    timing_health: dict[str, Any] | None = None


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
        if seq > self._seen_seqs_max:
            self._seen_seqs_max = seq

    def prune_seqs(self, window_size: int) -> None:
        """Discard old entries so the window stays bounded to *window_size*."""
        if len(self._seen_seqs) > window_size:
            cutoff = self._seen_seqs_max - window_size + 1
            self._seen_seqs = {s for s in self._seen_seqs if s >= cutoff}


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
    def _resolve_now_mono(now_mono: float | None) -> float:
        """Return monotonic ``now_mono`` if provided, else ``time.monotonic()``.

        Callers **must not** pass a wall-clock value here — the monotonic
        and wall-clock domains are intentionally separate to avoid eviction
        bugs when system time jumps.
        """
        return time.monotonic() if now_mono is None else now_mono

    def _get_or_create(self, client_id: str) -> ClientRecord:
        normalized = _normalize_client_id(client_id)
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
        *,
        now_mono: float | None = None,
    ) -> None:
        with self._lock:
            now_ts = self._resolve_now_wall(now)
            mono = self._resolve_now_mono(now_mono)
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
                self._clear_dedup(record)
            record.firmware_version = hello.firmware_version
            record.queue_overflow_drops = hello.queue_overflow_drops
            if client_id not in self._user_names:
                advertised = _sanitize_name(hello.name)
                if advertised:
                    record.name = advertised

    @staticmethod
    def _clear_dedup(record: ClientRecord) -> None:
        """Reset the per-client dedup window (e.g. on restart or hard reset)."""
        record.clear_dedup()

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
            now_ts = self._resolve_now_wall(now)
            mono = self._resolve_now_mono(now_mono)
            client_id = client_id_hex(data_msg.client_id)
            record = self._get_or_create(client_id)
            record.last_seen = now_ts
            record.last_seen_mono = mono
            record.data_addr = (addr[0], addr[1])

            # Local-bind constants used in hot-path arithmetic below.
            seq_mask = _SEQ_MASK
            seq_half = _SEQ_HALF
            dedup_window = _DEDUP_WINDOW
            restart_gap = _RESTART_SEQ_GAP
            dedup_restart_gap = _DEDUP_RESTART_GAP
            jitter_alpha = _JITTER_EMA_ALPHA

            # --- Deduplication check ---
            if record.has_seq(data_msg.seq):
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
                if backward <= dedup_restart_gap:
                    record.duplicates_received += 1
                    return DataUpdateResult(is_duplicate=True)
                # Likely client restart — clear dedup window and accept.
                self._clear_dedup(record)

            record.record_seq(data_msg.seq)
            record.prune_seqs(dedup_window)

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
                record.timing_jitter_us_ema = (
                    1.0 - jitter_alpha
                ) * record.timing_jitter_us_ema + jitter_alpha * jitter_us
                record.timing_drift_us_total += jitter_us
            if record.last_seq is not None:
                if (
                    data_msg.seq < record.last_seq
                    and (record.last_seq - data_msg.seq) > restart_gap
                ):
                    record.reset_count += 1
                    record.last_reset_time = now_ts
                    record.last_t0_us = None
                    record.timing_jitter_us_ema = 0.0
                    record.timing_drift_us_total = 0.0
                    record.clear_dedup()
                    record.record_seq(data_msg.seq)
                    reset_detected = True
                else:
                    expected = (record.last_seq + 1) & seq_mask
                    if data_msg.seq != expected:
                        gap = (data_msg.seq - expected) & seq_mask
                        if gap < seq_half:
                            record.frames_dropped += gap
            # Only advance last_seq forward to prevent out-of-order UDP
            # packets from regressing the counter and inflating frames_dropped.
            if record.last_seq is None or ((data_msg.seq - record.last_seq) & seq_mask) < seq_half:
                record.last_seq = data_msg.seq
            record.last_t0_us = data_msg.t0_us
            return DataUpdateResult(reset_detected=reset_detected)

    def update_from_ack(
        self,
        ack: AckMessage,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> None:
        with self._lock:
            now_ts = self._resolve_now_wall(now)
            mono = self._resolve_now_mono(now_mono)
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
            normalized = _normalize_client_id(client_id)
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
            normalized = _normalize_client_id(client_id)
        except ValueError:
            return None
        with self._lock:
            return self._clients.get(normalized)

    def active_client_ids(
        self, now: float | None = None, *, now_mono: float | None = None
    ) -> list[str]:
        with self._lock:
            now_mono = self._resolve_now_mono(now_mono)
            return [
                record.client_id
                for record in self._clients.values()
                if record.last_seen_mono
                and (now_mono - record.last_seen_mono) <= self._stale_ttl_seconds
            ]

    def evict_stale(self, now: float | None = None, *, now_mono: float | None = None) -> list[str]:
        with self._lock:
            now_mono = self._resolve_now_mono(now_mono)
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

    @staticmethod
    def _client_api_row(client_id: str, snapshot: ClientSnapshot) -> dict[str, Any]:
        """Build a single client row for the API snapshot.

        Centralises the dict shape so both connected and disconnected
        branches produce identical key sets.
        """
        return {
            "id": client_id,
            "mac_address": client_id_mac(client_id),
            "name": snapshot.name,
            "connected": snapshot.connected,
            "location": snapshot.location,
            "firmware_version": snapshot.firmware_version,
            "sample_rate_hz": snapshot.sample_rate_hz,
            "frame_samples": snapshot.frame_samples,
            "last_seen_age_ms": snapshot.last_seen_age_ms,
            "data_addr": snapshot.data_addr,
            "control_addr": snapshot.control_addr,
            "frames_total": snapshot.frames_total,
            "dropped_frames": snapshot.dropped_frames,
            "duplicates_received": snapshot.duplicates_received,
            "queue_overflow_drops": snapshot.queue_overflow_drops,
            "parse_errors": snapshot.parse_errors,
            "server_queue_drops": snapshot.server_queue_drops,
            "latest_metrics": snapshot.latest_metrics
            if snapshot.latest_metrics is not None
            else {},
            "last_ack_cmd_seq": snapshot.last_ack_cmd_seq,
            "last_ack_status": snapshot.last_ack_status,
            "reset_count": snapshot.reset_count,
            "last_reset_time": snapshot.last_reset_time,
            "timing_health": snapshot.timing_health if snapshot.timing_health is not None else {},
        }

    def snapshot_for_api(
        self, now: float | None = None, *, now_mono: float | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            now_ts = self._resolve_now_wall(now)
            now_mono = self._resolve_now_mono(now_mono)
            rows: list[dict[str, Any]] = []
            all_client_ids = sorted(set(self._clients) | set(self._user_names))
            for client_id in all_client_ids:
                record = self._clients.get(client_id)
                if record is None:
                    rows.append(
                        self._client_api_row(
                            client_id,
                            ClientSnapshot(
                                name=self._user_names.get(client_id, f"client-{client_id[-4:]}"),
                                connected=False,
                            ),
                        )
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
                    self._client_api_row(
                        record.client_id,
                        ClientSnapshot(
                            name=record.name,
                            connected=connected,
                            location=record.location,
                            firmware_version=record.firmware_version,
                            sample_rate_hz=record.sample_rate_hz,
                            frame_samples=record.frame_samples,
                            last_seen_age_ms=age_ms,
                            data_addr=record.data_addr,
                            control_addr=record.control_addr,
                            frames_total=record.frames_total,
                            dropped_frames=record.frames_dropped,
                            duplicates_received=record.duplicates_received,
                            queue_overflow_drops=record.queue_overflow_drops,
                            parse_errors=record.parse_errors,
                            server_queue_drops=record.server_queue_drops,
                            latest_metrics=record.latest_metrics,
                            last_ack_cmd_seq=record.last_ack_cmd_seq,
                            last_ack_status=record.last_ack_status,
                            reset_count=record.reset_count,
                            last_reset_time=record.last_reset_time,
                            timing_health={
                                "jitter_us_ema": record.timing_jitter_us_ema,
                                "drift_us_total": record.timing_drift_us_total,
                                "last_t0_us": record.last_t0_us,
                            },
                        ),
                    )
                )
            return rows
