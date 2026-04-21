"""SQLite-backed client-name repository built on the shared history engine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, TypeVar

import aiosqlite

from vibesensor.shared.time_utils import utc_now_iso

if TYPE_CHECKING:
    from vibesensor.adapters.persistence.history_db._engine import SQLiteHistoryEngine

__all__ = ["ClientNameRepository"]

_T = TypeVar("_T")


class ClientNameRepository:
    """Own only the `client_names` table operations."""

    __slots__ = ("_cursor_provider", "_engine")

    def __init__(
        self,
        *,
        engine: SQLiteHistoryEngine,
        cursor_provider: Callable[..., AbstractAsyncContextManager[aiosqlite.Cursor]],
    ) -> None:
        self._engine = engine
        self._cursor_provider = cursor_provider

    def _cursor(self, *, commit: bool = True) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        return self._cursor_provider(commit=commit)

    def _run_sync(self, coro: Awaitable[_T]) -> _T:
        return self._engine._run_on_engine_loop(coro)

    def list_client_names(self) -> dict[str, str]:
        return self._run_sync(self.alist_client_names())

    async def alist_client_names(self) -> dict[str, str]:
        async with self._cursor(commit=False) as cur:
            await cur.execute("SELECT client_id, name FROM client_names")
            rows = await cur.fetchall()
        return {row[0]: row[1] for row in rows}

    def upsert_client_name(self, client_id: str, name: str) -> None:
        self._run_sync(self.aupsert_client_name(client_id, name))

    async def aupsert_client_name(self, client_id: str, name: str) -> None:
        now = utc_now_iso()
        async with self._cursor() as cur:
            await cur.execute(
                "INSERT INTO client_names (client_id, name, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(client_id) DO UPDATE SET name = excluded.name, "
                "updated_at = excluded.updated_at",
                (client_id, name, now),
            )

    def delete_client_name(self, client_id: str) -> bool:
        return self._run_sync(self.adelete_client_name(client_id))

    async def adelete_client_name(self, client_id: str) -> bool:
        async with self._cursor() as cur:
            await cur.execute("DELETE FROM client_names WHERE client_id = ?", (client_id,))
            return bool(int(cur.rowcount) > 0)
