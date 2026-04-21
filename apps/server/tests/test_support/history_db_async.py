"""Sync history-db test helpers for direct table inspection and mutation.

Uses the engine's persistent loop so aiosqlite's worker thread stays bound to
the same loop that opened the connection.
"""

from __future__ import annotations

from typing import Any


def _engine(db: Any) -> Any:
    if hasattr(db, "_run_on_engine_loop"):
        return db
    for attr in ("lifecycle", "_engine"):
        inner = getattr(db, attr, None)
        if inner is not None and hasattr(inner, "_run_on_engine_loop"):
            return inner
    raise AttributeError("cannot locate engine loop runner on db object")


def execute_statements(
    db: Any,
    *statements: tuple[str, tuple[object, ...]],
) -> None:
    async def _run() -> None:
        async with db._cursor() as cur:
            for sql, params in statements:
                await cur.execute(sql, params)

    _engine(db)._run_on_engine_loop(_run())


def fetch_one(
    db: Any,
    sql: str,
    params: tuple[object, ...] = (),
) -> tuple[object, ...] | None:
    async def _run() -> tuple[object, ...] | None:
        async with db._cursor(commit=False) as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
        return tuple(row) if row is not None else None

    return _engine(db)._run_on_engine_loop(_run())


def fetch_all(
    db: Any,
    sql: str,
    params: tuple[object, ...] = (),
) -> list[tuple[object, ...]]:
    async def _run() -> list[tuple[object, ...]]:
        async with db._cursor(commit=False) as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()
        return [tuple(row) for row in rows]

    return _engine(db)._run_on_engine_loop(_run())
