"""Persisted client metadata and user-name coordination for ``ClientRegistry``."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from threading import RLock
from typing import TYPE_CHECKING

import aiosqlite

from vibesensor.domain import normalize_sensor_id

if TYPE_CHECKING:
    from .registry import ClientRecord

LOGGER = logging.getLogger(__name__)

GetOrCreateRecord = Callable[[str], "ClientRecord"]
ListClientNames = Callable[[], dict[str, str]]
PersistClientName = Callable[[str, str], None]
DeleteClientName = Callable[[str], bool | None]

__all__ = ["ClientMetadataManager", "sanitize_client_name"]


def sanitize_client_name(name: str) -> str:
    """Strip control chars and enforce the 32-byte persisted/display name cap."""

    clean = "".join(c for c in name if (o := ord(c)) >= 0x20 and o != 0x7F)
    clean = clean.strip()
    if not clean:
        return ""

    encoded = clean.encode("utf-8", errors="ignore")
    if len(encoded) <= 32:
        return clean
    return encoded[:32].decode("utf-8", errors="ignore")


class ClientMetadataManager:
    """Own persisted client names and related metadata mutations."""

    def __init__(
        self,
        *,
        lock: RLock,
        get_or_create: GetOrCreateRecord,
        list_client_names: ListClientNames | None = None,
        persist_client_name: PersistClientName | None = None,
        delete_client_name: DeleteClientName | None = None,
    ) -> None:
        self._lock = lock
        self._get_or_create = get_or_create
        self._list_client_names = list_client_names
        self._persist_client_name = persist_client_name
        self._delete_client_name = delete_client_name
        self._user_names: dict[str, str] = {}
        self._load_persisted_names()

    def _load_persisted_names(self) -> None:
        if self._list_client_names is None:
            return
        try:
            rows = self._list_client_names()
        except (aiosqlite.Error, OSError) as exc:
            LOGGER.warning("Could not load persisted client names from DB: %s", exc)
            return

        with self._lock:
            for client_id, name in rows.items():
                clean = sanitize_client_name(name)
                if clean:
                    self._user_names[client_id] = clean

    def _persist_name(self, client_id: str, name: str) -> None:
        if self._persist_client_name is None:
            return
        try:
            self._persist_client_name(client_id, name)
        except (aiosqlite.Error, OSError):
            LOGGER.warning("Failed to persist client name to DB", exc_info=True)

    def _delete_persisted_name(self, client_id: str) -> None:
        if self._delete_client_name is None:
            return
        try:
            self._delete_client_name(client_id)
        except (aiosqlite.Error, OSError):
            LOGGER.warning("Failed to delete client name from DB", exc_info=True)

    @staticmethod
    def _default_name(client_id: str) -> str:
        return f"client-{client_id[-4:]}"

    def default_name_for(self, client_id: str) -> str:
        normalized = normalize_sensor_id(client_id)
        with self._lock:
            return self._user_names.get(normalized, self._default_name(normalized))

    def has_user_name(self, client_id: str) -> bool:
        normalized = normalize_sensor_id(client_id)
        with self._lock:
            return normalized in self._user_names

    def apply_advertised_name(self, record: ClientRecord, advertised_name: str) -> None:
        with self._lock:
            if record.client_id in self._user_names:
                return
            clean = sanitize_client_name(advertised_name)
            if clean:
                record.name = clean

    def set_name(self, client_id: str, name: str) -> ClientRecord:
        clean = sanitize_client_name(name)
        if not clean:
            raise ValueError("Name must be non-empty and <=32 UTF-8 bytes")

        with self._lock:
            record = self._get_or_create(client_id)
            record.name = clean
            self._user_names[record.client_id] = clean
            normalized = record.client_id

        self._persist_name(normalized, clean)
        return record

    def clear_name(self, client_id: str) -> ClientRecord:
        with self._lock:
            record = self._get_or_create(client_id)
            record.name = self._default_name(record.client_id)
            self._user_names.pop(record.client_id, None)
            normalized = record.client_id

        self._delete_persisted_name(normalized)
        return record

    def discard_name(self, client_id: str) -> bool:
        normalized = normalize_sensor_id(client_id)
        with self._lock:
            existed = normalized in self._user_names
            self._user_names.pop(normalized, None)

        if existed:
            self._delete_persisted_name(normalized)
        return existed

    def known_client_ids(self, active_client_ids: Iterable[str]) -> list[str]:
        with self._lock:
            return sorted(set(active_client_ids) | set(self._user_names))
