"""Async history-db test helpers for direct table inspection and mutation."""

from __future__ import annotations

from typing import Any

from vibesensor.shared.async_bridge import run_coro_blocking


def execute_statements(
    db: Any,
    *statements: tuple[str, tuple[object, ...]],
) -> None:
    async def _run() -> None:
        async with db._cursor_async() as cur:
            for sql, params in statements:
                await cur.execute(sql, params)

    run_coro_blocking(_run())


def fetch_one(
    db: Any,
    sql: str,
    params: tuple[object, ...] = (),
) -> tuple[object, ...] | None:
    async def _run() -> tuple[object, ...] | None:
        async with db._cursor_async(commit=False) as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
        return tuple(row) if row is not None else None

    return run_coro_blocking(_run())


def fetch_all(
    db: Any,
    sql: str,
    params: tuple[object, ...] = (),
) -> list[tuple[object, ...]]:
    async def _run() -> list[tuple[object, ...]]:
        async with db._cursor_async(commit=False) as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()
        return [tuple(row) for row in rows]

    return run_coro_blocking(_run())
