"""SQLite-backed settings-snapshot repository built on the shared history engine."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import aiosqlite

from vibesensor.shared.async_bridge import run_coro_blocking
from vibesensor.shared.boundaries.settings.snapshot import (
    settings_snapshot_from_json,
    settings_snapshot_to_json,
)
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.settings_snapshot import SettingsSnapshotPayload

__all__ = ["SettingsSnapshotRepository"]


class SettingsSnapshotRepository:
    """Own only the `settings_snapshot` table operations."""

    __slots__ = ("_cursor_provider",)

    def __init__(
        self,
        *,
        cursor_provider: Callable[..., AbstractAsyncContextManager[aiosqlite.Cursor]],
    ) -> None:
        self._cursor_provider = cursor_provider

    def _cursor(self, *, commit: bool = True) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        return self._cursor_provider(commit=commit)

    def get_settings_snapshot(self) -> SettingsSnapshotPayload | None:
        return run_coro_blocking(self.aget_settings_snapshot())

    async def aget_settings_snapshot(self) -> SettingsSnapshotPayload | None:
        async with self._cursor(commit=False) as cur:
            await cur.execute("SELECT value_json FROM settings_snapshot WHERE id = 1")
            row = await cur.fetchone()
        if row is None:
            return None
        return settings_snapshot_from_json(row[0])

    def set_settings_snapshot(self, snapshot: SettingsSnapshotPayload) -> None:
        run_coro_blocking(self.aset_settings_snapshot(snapshot))

    async def aset_settings_snapshot(self, snapshot: SettingsSnapshotPayload) -> None:
        now = utc_now_iso()
        async with self._cursor() as cur:
            await cur.execute(
                "INSERT INTO settings_snapshot (id, value_json, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (settings_snapshot_to_json(snapshot), now),
            )
