"""SQLite-backed settings-snapshot repository built on the shared history engine."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager

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
        cursor_provider: Callable[..., AbstractContextManager[sqlite3.Cursor]],
    ) -> None:
        self._cursor_provider = cursor_provider

    def _cursor(self, *, commit: bool = True) -> AbstractContextManager[sqlite3.Cursor]:
        return self._cursor_provider(commit=commit)

    def get_settings_snapshot(self) -> SettingsSnapshotPayload | None:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT value_json FROM settings_snapshot WHERE id = 1")
            row = cur.fetchone()
        if row is None:
            return None
        return settings_snapshot_from_json(row[0])

    def set_settings_snapshot(self, snapshot: SettingsSnapshotPayload) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO settings_snapshot (id, value_json, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (settings_snapshot_to_json(snapshot), now),
            )
