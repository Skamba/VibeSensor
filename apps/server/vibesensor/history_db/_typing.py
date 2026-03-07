"""Typing helpers shared across HistoryDB mixins."""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from typing import Any, Protocol


class HistoryCursorProvider(Protocol):
    """Protocol for HistoryDB mixins that require SQLite cursor access."""

    def _cursor(self, *, commit: bool = True) -> AbstractContextManager[sqlite3.Cursor]: ...

    def get_setting(self, key: str) -> Any | None: ...

    def set_setting(self, key: str, value: Any) -> None: ...

    def iter_run_samples(self, run_id: str, batch_size: int = 1000, offset: int = 0) -> Any: ...

    def _iter_v2_samples(self, run_id: str, batch_size: int = 1000, offset: int = 0) -> Any: ...

    def _resolve_keyset_offset(self, table: str, run_id: str, offset: int) -> int | None: ...