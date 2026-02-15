from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any

from .protocol import (
    AckMessage,
    DataMessage,
    HelloMessage,
    client_id_hex,
    client_id_mac,
    parse_client_id,
)


def _sanitize_name(name: str) -> str:
    clean = name.strip()
    if not clean:
        return ""
    return clean.encode("utf-8", errors="ignore")[:32].decode("utf-8", errors="ignore")


def _normalize_client_id(client_id: str) -> str:
    return parse_client_id(client_id).hex()


@dataclass(slots=True)
class ClientRecord:
    client_id: str
    name: str
    firmware_version: str = ""
    sample_rate_hz: int = 0
    last_seen: float = 0.0
    data_addr: tuple[str, int] | None = None
    control_addr: tuple[str, int] | None = None
    frames_total: int = 0
    frames_dropped: int = 0
    queue_overflow_drops: int = 0
    parse_errors: int = 0
    last_seq: int | None = None
    last_ack_cmd_seq: int | None = None
    last_ack_status: int | None = None
    latest_metrics: dict[str, Any] = field(default_factory=dict)


class ClientRegistry:
    def __init__(self, persist_path: Path, stale_ttl_seconds: float = 120.0):
        self._lock = RLock()
        self._persist_path = persist_path
        self._stale_ttl_seconds = max(1.0, stale_ttl_seconds)
        self._persist_min_interval_seconds = 60.0
        self._last_persist_ts = 0.0
        self._last_persist_payload = ""
        self._pending_persist = False
        self._clients: dict[str, ClientRecord] = {}
        self._user_names: dict[str, str] = {}
        self._load_persisted_names()

    def _load_persisted_names(self) -> None:
        with self._lock:
            if not self._persist_path.exists():
                return
            try:
                raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return
            for entry in raw.get("clients", []):
                raw_client_id = str(entry.get("id", ""))
                try:
                    client_id = _normalize_client_id(raw_client_id)
                except ValueError:
                    continue
                name = _sanitize_name(str(entry.get("name", "")))
                if name:
                    self._user_names[client_id] = name

    def _build_names_payload(self) -> dict[str, Any]:
        names_by_id: dict[str, str] = dict(self._user_names)
        for record in self._clients.values():
            if record.name:
                names_by_id[record.client_id] = record.name
        return {
            "clients": [
                {"id": client_id, "name": name}
                for client_id, name in sorted(names_by_id.items(), key=lambda item: item[0])
            ]
        }

    def _persist_names(self, *, now_ts: float | None = None, force: bool = False) -> None:
        payload = self._build_names_payload()
        payload_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if payload_text == self._last_persist_payload and self._persist_path.exists():
            self._pending_persist = False
            return

        now_val = time.time() if now_ts is None else now_ts
        if (
            not force
            and self._last_persist_ts > 0.0
            and (now_val - self._last_persist_ts) < self._persist_min_interval_seconds
        ):
            self._pending_persist = True
            return

        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._persist_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(self._persist_path)
        self._last_persist_payload = payload_text
        self._last_persist_ts = now_val
        self._pending_persist = False

    def _flush_pending_persist(self, now_ts: float) -> None:
        if not self._pending_persist:
            return
        if (now_ts - self._last_persist_ts) < self._persist_min_interval_seconds:
            return
        self._persist_names(now_ts=now_ts, force=True)

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
    ) -> None:
        with self._lock:
            now_ts = time.time() if now is None else now
            client_id = client_id_hex(hello.client_id)
            record = self._get_or_create(client_id)
            record.last_seen = now_ts
            hello_port = int(hello.control_port)
            record.control_addr = (addr[0], hello_port if hello_port > 0 else addr[1])
            record.sample_rate_hz = hello.sample_rate_hz
            record.firmware_version = hello.firmware_version
            record.queue_overflow_drops = hello.queue_overflow_drops
            if client_id not in self._user_names:
                advertised = _sanitize_name(hello.name)
                if advertised:
                    record.name = advertised

    def update_from_data(
        self,
        data_msg: DataMessage,
        addr: tuple[str, int],
        now: float | None = None,
    ) -> None:
        with self._lock:
            now_ts = time.time() if now is None else now
            client_id = client_id_hex(data_msg.client_id)
            record = self._get_or_create(client_id)
            record.last_seen = now_ts
            record.data_addr = (addr[0], addr[1])
            record.frames_total += 1
            if record.last_seq is not None:
                expected = (record.last_seq + 1) & 0xFFFFFFFF
                if data_msg.seq != expected:
                    gap = (data_msg.seq - expected) & 0xFFFFFFFF
                    if gap < 0x80000000:
                        record.frames_dropped += gap
            record.last_seq = data_msg.seq

    def update_from_ack(self, ack: AckMessage, now: float | None = None) -> None:
        with self._lock:
            now_ts = time.time() if now is None else now
            client_id = client_id_hex(ack.client_id)
            record = self._get_or_create(client_id)
            record.last_seen = now_ts
            record.last_ack_cmd_seq = ack.cmd_seq
            record.last_ack_status = ack.status

    def note_parse_error(self, client_id: str | None) -> None:
        if not client_id:
            return
        try:
            normalized = _normalize_client_id(client_id)
        except ValueError:
            return
        with self._lock:
            record = self._get_or_create(normalized)
            record.parse_errors += 1

    def set_name(self, client_id: str, name: str) -> ClientRecord:
        clean = _sanitize_name(name)
        if not clean:
            raise ValueError("Name must be non-empty and <=32 UTF-8 bytes")
        with self._lock:
            record = self._get_or_create(client_id)
            record.name = clean
            self._user_names[record.client_id] = clean
            self._persist_names(force=True)
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
                self._persist_names(force=True)
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

    def client_ids(self) -> list[str]:
        with self._lock:
            return list(self._clients.keys())

    def active_client_ids(self, now: float | None = None) -> list[str]:
        with self._lock:
            now_ts = time.time() if now is None else now
            return [
                record.client_id
                for record in self._clients.values()
                if record.last_seen and (now_ts - record.last_seen) <= self._stale_ttl_seconds
            ]

    def evict_stale(self, now: float | None = None) -> list[str]:
        with self._lock:
            now_ts = time.time() if now is None else now
            stale_ids = [
                client_id
                for client_id, record in self._clients.items()
                if record.last_seen and (now_ts - record.last_seen) > self._stale_ttl_seconds
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
            now_ts = time.time() if now is None else now
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
                            "firmware_version": "",
                            "sample_rate_hz": 0,
                            "last_seen_age_ms": None,
                            "data_addr": None,
                            "control_addr": None,
                            "frames_total": 0,
                            "dropped_frames": 0,
                            "queue_overflow_drops": 0,
                            "parse_errors": 0,
                            "latest_metrics": {},
                            "last_ack_cmd_seq": None,
                            "last_ack_status": None,
                        }
                    )
                    continue
                age_ms = (
                    int(max(0.0, now_ts - record.last_seen) * 1000)
                    if record.last_seen
                    else None
                )
                connected = bool(
                    record.last_seen and (now_ts - record.last_seen) <= self._stale_ttl_seconds
                )
                rows.append(
                    {
                        "id": record.client_id,
                        "mac_address": client_id_mac(record.client_id),
                        "name": record.name,
                        "connected": connected,
                        "firmware_version": record.firmware_version,
                        "sample_rate_hz": record.sample_rate_hz,
                        "last_seen_age_ms": age_ms,
                        "data_addr": record.data_addr,
                        "control_addr": record.control_addr,
                        "frames_total": record.frames_total,
                        "dropped_frames": record.frames_dropped,
                        "queue_overflow_drops": record.queue_overflow_drops,
                        "parse_errors": record.parse_errors,
                        "latest_metrics": record.latest_metrics,
                        "last_ack_cmd_seq": record.last_ack_cmd_seq,
                        "last_ack_status": record.last_ack_status,
                    }
                )
            return rows

    def iter_records(self) -> list[ClientRecord]:
        with self._lock:
            return list(self._clients.values())
