"""Raw settings-snapshot writer for settings load-path tests."""

from __future__ import annotations

from vibesensor.common.time_utils import utc_now_iso
from vibesensor.history.history_db import HistoryDB

__all__ = ["write_raw_settings_snapshot"]


def write_raw_settings_snapshot(db: HistoryDB, value_json: str) -> None:
    """Write raw JSON into the settings snapshot table for load-path tests."""
    with db._write() as cur:
        cur.execute(
            "INSERT INTO settings_snapshot (id, value_json, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET value_json = excluded.value_json, "
            "updated_at = excluded.updated_at",
            (value_json, utc_now_iso()),
        )
