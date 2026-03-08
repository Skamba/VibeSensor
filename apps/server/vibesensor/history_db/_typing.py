"""Typing helpers shared across HistoryDB mixins."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Protocol

from ..json_types import JsonObject, JsonValue


class HistoryCursorProvider(Protocol):
    """Protocol for HistoryDB mixins that require SQLite cursor access."""

    def _cursor(self, *, commit: bool = True) -> AbstractContextManager[sqlite3.Cursor]: ...

    def get_setting(self, key: str) -> JsonValue | None: ...

    def set_setting(self, key: str, value: JsonValue) -> None: ...

    def iter_run_samples(
        self,
        run_id: str,
        batch_size: int = 1000,
        offset: int = 0,
    ) -> Iterator[list[JsonObject]]: ...

    def _iter_v2_samples(
        self,
        run_id: str,
        batch_size: int = 1000,
        offset: int = 0,
    ) -> Iterator[list[JsonObject]]: ...

    def _resolve_keyset_offset(self, table: str, run_id: str, offset: int) -> int | None: ...
