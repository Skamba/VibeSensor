from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

from vibesensor.history_db import HistoryDB


def test_append_samples_in_chunks(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-1", "2026-01-01T00:00:00Z", {"source": "test"})
    calls: list[int] = []
    original_cursor = db._cursor

    @contextmanager
    def _wrapped_cursor():
        with original_cursor() as cur:

            class _CursorProxy:
                def __init__(self, base_cursor):
                    self._base_cursor = base_cursor

                def __getattr__(self, name: str):
                    return getattr(self._base_cursor, name)

                def executemany(self, sql: str, seq_of_parameters):
                    rows = list(seq_of_parameters)
                    calls.append(len(rows))
                    return self._base_cursor.executemany(sql, rows)

            yield _CursorProxy(cur)

    db._cursor = _wrapped_cursor  # type: ignore[method-assign]
    samples = [{"i": i, "x": 0.1} for i in range(700)]
    db.append_samples("run-1", samples)
    assert sum(calls) == 700
    assert max(calls) <= 256
    assert len(calls) >= 3


def test_history_db_thread_safe_appends(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-2", "2026-01-01T00:00:00Z", {"source": "test"})

    def _append(start: int) -> None:
        batch = [{"i": start + i} for i in range(50)]
        db.append_samples("run-2", batch)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for offset in range(0, 400, 50):
            pool.submit(_append, offset)

    assert len(db.get_run_samples("run-2")) == 400


def test_schema_version_mismatch_fails_fast(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta (key, value) VALUES ('version', '0')")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="Unsupported history DB schema version"):
        HistoryDB(db_path)


def test_iter_run_samples_batches(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-3", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-3", [{"i": i} for i in range(11)])
    batches = list(db.iter_run_samples("run-3", batch_size=4))
    assert [len(batch) for batch in batches] == [4, 4, 3]
