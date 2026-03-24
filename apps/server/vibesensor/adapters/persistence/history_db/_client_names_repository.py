"""SQLite-backed client-name repository built on the shared history engine."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager

from vibesensor.shared.time_utils import utc_now_iso

__all__ = ["ClientNameRepository"]


class ClientNameRepository:
    """Own only the `client_names` table operations."""

    __slots__ = ("_cursor_provider",)

    def __init__(
        self,
        *,
        cursor_provider: Callable[..., AbstractContextManager[sqlite3.Cursor]],
    ) -> None:
        self._cursor_provider = cursor_provider

    def _cursor(self, *, commit: bool = True) -> AbstractContextManager[sqlite3.Cursor]:
        return self._cursor_provider(commit=commit)

    def list_client_names(self) -> dict[str, str]:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT client_id, name FROM client_names")
            rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}

    def upsert_client_name(self, client_id: str, name: str) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO client_names (client_id, name, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(client_id) DO UPDATE SET name = excluded.name, "
                "updated_at = excluded.updated_at",
                (client_id, name, now),
            )

    def delete_client_name(self, client_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM client_names WHERE client_id = ?", (client_id,))
            return bool(int(cur.rowcount) > 0)
