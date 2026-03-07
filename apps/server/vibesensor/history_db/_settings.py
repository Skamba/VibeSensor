"""Settings KV persistence helpers for HistoryDB."""

from __future__ import annotations

from typing import Any

from ..json_utils import safe_json_dumps, safe_json_loads
from ..runlog import utc_now_iso
from ._typing import HistoryCursorProvider


class HistorySettingsStoreMixin:
    """Mixin providing settings_kv persistence methods."""

    __slots__ = ()

    def get_setting(self: HistoryCursorProvider, key: str) -> Any | None:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT value_json FROM settings_kv WHERE key = ?", (key,))
            row = cur.fetchone()
        if row is None:
            return None
        return safe_json_loads(row[0], context=f"setting {key}")

    def set_setting(self: HistoryCursorProvider, key: str, value: Any) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO settings_kv (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (key, safe_json_dumps(value), now),
            )

    def get_settings_snapshot(self: HistoryCursorProvider) -> dict[str, Any] | None:
        snapshot = self.get_setting("settings_snapshot")
        return snapshot if isinstance(snapshot, dict) else None

    def set_settings_snapshot(self: HistoryCursorProvider, snapshot: dict[str, Any]) -> None:
        self.set_setting("settings_snapshot", snapshot)
