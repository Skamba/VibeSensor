"""Direct SQL helpers for history-DB tests that inspect or corrupt tables."""

from __future__ import annotations

from vibesensor.history.history_db import HistoryDB


def execute_statements(
    db: HistoryDB,
    *statements: tuple[str, tuple[object, ...]],
) -> None:
    with db._write() as cur:
        for sql, params in statements:
            cur.execute(sql, params)


def fetch_one(
    db: HistoryDB,
    sql: str,
    params: tuple[object, ...] = (),
) -> tuple[object, ...] | None:
    with db._read() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return tuple(row) if row is not None else None


def fetch_all(
    db: HistoryDB,
    sql: str,
    params: tuple[object, ...] = (),
) -> list[tuple[object, ...]]:
    with db._read() as cur:
        cur.execute(sql, params)
        return [tuple(row) for row in cur.fetchall()]
