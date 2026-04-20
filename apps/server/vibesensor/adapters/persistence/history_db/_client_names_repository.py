"""SQLite-backed client-name repository built on the shared history engine."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import aiosqlite

from vibesensor.shared.async_bridge import run_coro_blocking
from vibesensor.shared.time_utils import utc_now_iso

__all__ = ["ClientNameRepository"]


class ClientNameRepository:
    """Own only the `client_names` table operations."""

    __slots__ = ("_cursor_provider",)

    def __init__(
        self,
        *,
        cursor_provider: Callable[..., AbstractAsyncContextManager[aiosqlite.Cursor]],
    ) -> None:
        self._cursor_provider = cursor_provider

    def _cursor(self, *, commit: bool = True) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        return self._cursor_provider(commit=commit)

    def list_client_names(self) -> dict[str, str]:
        return run_coro_blocking(self.alist_client_names())

    async def alist_client_names(self) -> dict[str, str]:
        async with self._cursor(commit=False) as cur:
            await cur.execute("SELECT client_id, name FROM client_names")
            rows = await cur.fetchall()
        return {row[0]: row[1] for row in rows}

    def upsert_client_name(self, client_id: str, name: str) -> None:
        run_coro_blocking(self.aupsert_client_name(client_id, name))

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
        return run_coro_blocking(self.adelete_client_name(client_id))

    async def adelete_client_name(self, client_id: str) -> bool:
        async with self._cursor() as cur:
            await cur.execute("DELETE FROM client_names WHERE client_id = ?", (client_id,))
            return bool(int(cur.rowcount) > 0)
