"""Exception discipline: narrowed catches let code bugs propagate.

After Chunk 3 exception narrowing, catches that previously used bare
``except Exception`` now specify exact types (sqlite3.Error, OSError, etc.).
These tests verify that programming bugs (TypeError, AttributeError,
KeyError in unexpected code paths) are **not** silently swallowed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.infra.config.settings_store import PersistenceError, SettingsStore
from vibesensor.infra.runtime.registry import ClientRegistry

# ── HistoryDB — sqlite3.Error caught, bugs propagate ─────────────────────


class TestHistoryDBExceptionDiscipline:
    """HistoryDB catches sqlite3.Error but lets coding bugs propagate."""

    def test_sqlite_error_in_cursor_is_caught_and_rolled_back(self, tmp_path: Path) -> None:
        """sqlite3.IntegrityError (a sqlite3.Error subclass) is caught by _cursor."""
        db = HistoryDB(tmp_path / "test.db")
        run_id = "run-exc-test"
        db.create_run(run_id, "2026-01-01T00:00:00Z", {"src": "t"})

        # Duplicate insert → IntegrityError, which is sqlite3.Error
        with pytest.raises(sqlite3.IntegrityError):
            db.create_run(run_id, "2026-01-01T00:00:00Z", {"src": "t"})

        # DB is still usable after IntegrityError (was rolled back)
        runs = db.list_runs()
        assert any(r["run_id"] == run_id for r in runs)
        db.close()

    def test_type_error_in_write_tx_propagates(self, tmp_path: Path) -> None:
        """TypeError inside a write transaction must not be silently caught."""
        db = HistoryDB(tmp_path / "test.db")
        with pytest.raises(TypeError), db.write_transaction_cursor() as cur:
            cur.execute("SELECT 1")
            raise TypeError("simulated code bug")
        db.close()

    def test_attribute_error_in_cursor_propagates(self, tmp_path: Path) -> None:
        """AttributeError must not be silently caught."""
        db = HistoryDB(tmp_path / "test.db")
        with pytest.raises(AttributeError), db._cursor() as cur:
            cur.execute("SELECT 1")
            raise AttributeError("simulated code bug")
        db.close()


# ── SettingsStore — (sqlite3.Error, OSError) caught, bugs propagate ──────


class TestSettingsStoreExceptionDiscipline:
    """SettingsStore._persist catches (sqlite3.Error, OSError), wraps as PersistenceError."""

    def test_sqlite_error_wrapped_as_persistence_error(self, tmp_path: Path) -> None:
        """An sqlite3.OperationalError from the DB is wrapped as PersistenceError."""
        db = HistoryDB(tmp_path / "test.db")
        store = SettingsStore(db=db)
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = sqlite3.OperationalError("disk I/O error")

        with pytest.raises(PersistenceError, match="Failed to persist"):
            store.add_car({"name": "Test"})

    def test_os_error_wrapped_as_persistence_error(self, tmp_path: Path) -> None:
        """An OSError from the DB is wrapped as PersistenceError."""
        db = HistoryDB(tmp_path / "test.db")
        store = SettingsStore(db=db)
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = OSError("disk full")

        with pytest.raises(PersistenceError, match="Failed to persist"):
            store.add_car({"name": "Test"})

    def test_type_error_propagates_through_persist(self, tmp_path: Path) -> None:
        """TypeError from the DB is NOT wrapped — it propagates as a code bug."""
        db = HistoryDB(tmp_path / "test.db")
        store = SettingsStore(db=db)
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = TypeError("bad argument type")

        with pytest.raises(TypeError, match="bad argument type"):
            store.add_car({"name": "Test"})

    def test_attribute_error_propagates_through_persist(self, tmp_path: Path) -> None:
        """AttributeError from the DB is NOT wrapped — it's a code bug."""
        db = HistoryDB(tmp_path / "test.db")
        store = SettingsStore(db=db)
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = AttributeError("no such method")

        with pytest.raises(AttributeError, match="no such method"):
            store.add_car({"name": "Test"})


# ── ClientRegistry — sqlite3.Error caught, bugs propagate ────────────────


class TestRegistryExceptionDiscipline:
    """ClientRegistry catches sqlite3.Error for name persistence, lets bugs through."""

    def test_sqlite_error_on_persist_name_is_swallowed(self, tmp_path: Path) -> None:
        """DB errors during name persistence are logged, not propagated."""
        db = HistoryDB(tmp_path / "test.db")
        registry = ClientRegistry(db=db)
        client_id = "aabbccddeeff"

        # Sabotage the DB
        with patch.object(db, "upsert_client_name", side_effect=sqlite3.OperationalError("locked")):
            # Should not raise — operational errors are tolerated for name persistence
            registry.set_name(client_id, "My Sensor")

        # Name is set in-memory even though DB persist failed
        rec = registry.get(client_id)
        assert rec is not None
        assert rec.name == "My Sensor"

    def test_type_error_on_persist_name_propagates(self, tmp_path: Path) -> None:
        """TypeError during name persistence indicates a code bug and must propagate."""
        db = HistoryDB(tmp_path / "test.db")
        registry = ClientRegistry(db=db)
        client_id = "aabbccddeeff"

        with patch.object(db, "upsert_client_name", side_effect=TypeError("wrong type")):
            with pytest.raises(TypeError, match="wrong type"):
                registry.set_name(client_id, "My Sensor")
