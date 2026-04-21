"""SQLite-backed settings-snapshot repository built on the shared history engine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, TypeVar

import aiosqlite

from vibesensor.shared.boundaries.settings.snapshot import (
    settings_snapshot_from_json,
    settings_snapshot_to_json,
)
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.settings_snapshot import SettingsSnapshotPayload

if TYPE_CHECKING:
    from vibesensor.adapters.persistence.history_db._engine import SQLiteHistoryEngine

__all__ = ["SettingsSnapshotRepository"]

_T = TypeVar("_T")


class SettingsSnapshotRepository:
    """Own only the `settings_snapshot` table operations."""

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

    def get_settings_snapshot(self) -> SettingsSnapshotPayload | None:
        return self._run_sync(self.aget_settings_snapshot())

    async def aget_settings_snapshot(self) -> SettingsSnapshotPayload | None:
        async with self._cursor(commit=False) as cur:
            await cur.execute("SELECT value_json FROM settings_snapshot WHERE id = 1")
            row = await cur.fetchone()
        if row is None:
            return None
        return settings_snapshot_from_json(row[0])

    def set_settings_snapshot(self, snapshot: SettingsSnapshotPayload) -> None:
        self._run_sync(self.aset_settings_snapshot(snapshot))

    async def aset_settings_snapshot(self, snapshot: SettingsSnapshotPayload) -> None:
        now = utc_now_iso()
        async with self._cursor() as cur:
            await cur.execute(
                "INSERT INTO settings_snapshot (id, value_json, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (settings_snapshot_to_json(snapshot), now),
            )
