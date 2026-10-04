"""A sensor rename still applies in memory when the database cannot store it."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from vibesensor.history.history_db import HistoryDB
from vibesensor.ingest.registry import ClientRegistry


def test_rename_survives_a_locked_database(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "test.db")
    client_id = "aabbccddeeff"

    with patch.object(
        HistoryDB, "upsert_client_name", side_effect=sqlite3.OperationalError("locked")
    ):
        registry = ClientRegistry(db=db)
        registry.set_name(client_id, "My Sensor")

    record = registry.get(client_id)
    assert record is not None and record.name == "My Sensor"
    assert db.list_client_names() == {}
    assert ClientRegistry(db=db).get(client_id) is None
