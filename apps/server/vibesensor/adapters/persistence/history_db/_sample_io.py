"""Sample streaming helpers for ``HistoryDB``."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import AbstractContextManager

from vibesensor.adapters.persistence.history_db._samples import (
    ALLOWED_SAMPLE_TABLES,
    V2_SELECT_SQL_COLS,
    v2_row_to_sensor_frame,
)
from vibesensor.shared.boundaries.sensor_frame_codec import SensorFrameDecodeError
from vibesensor.shared.types.sensor_frame import SensorFrame

LOGGER = logging.getLogger(__name__)


class _HistoryDBSampleIOMixin:
    def _cursor(self, *, commit: bool = True) -> AbstractContextManager[sqlite3.Cursor]:
        raise NotImplementedError

    def get_run_samples(self, run_id: str) -> list[SensorFrame]:
        rows: list[SensorFrame] = []
        for batch in self.iter_run_samples(run_id):
            rows.extend(batch)
        return rows

    def iter_run_samples(
        self,
        run_id: str,
        batch_size: int = 1000,
        offset: int = 0,
        *,
        stride: int = 1,
    ) -> Iterator[list[SensorFrame]]:
        if offset < 0:
            raise ValueError(f"iter_run_samples: offset must be >= 0, got {offset}")
        if stride < 1:
            raise ValueError(f"iter_run_samples: stride must be >= 1, got {stride}")
        yield from self._iter_v2_samples(run_id, batch_size, offset, stride)

    def _resolve_keyset_offset(
        self,
        table: str,
        run_id: str,
        offset: int,
    ) -> int | None:
        if table not in ALLOWED_SAMPLE_TABLES:
            raise ValueError(
                f"_resolve_keyset_offset: invalid table name {table!r}; "
                f"must be one of {sorted(ALLOWED_SAMPLE_TABLES)}",
            )
        with self._cursor(commit=False) as cur:
            cur.execute(
                f"SELECT id FROM {table} WHERE run_id = ? ORDER BY id LIMIT 1 OFFSET ?",
                (run_id, offset - 1),
            )
            row = cur.fetchone()
        return int(row[0]) if row else None

    def _iter_v2_samples(
        self,
        run_id: str,
        batch_size: int = 1000,
        offset: int = 0,
        stride: int = 1,
    ) -> Iterator[list[SensorFrame]]:
        size = max(1, batch_size)
        last_id: int | None = None
        if offset > 0:
            last_id = self._resolve_keyset_offset("samples_v2", run_id, offset)
            if last_id is None:
                return
        total_skipped = 0
        sample_index = offset
        while True:
            with self._cursor(commit=False) as cur:
                if last_id is None:
                    cur.execute(
                        f"SELECT {V2_SELECT_SQL_COLS} FROM samples_v2"
                        " WHERE run_id = ? ORDER BY id LIMIT ?",
                        (run_id, size),
                    )
                else:
                    cur.execute(
                        f"SELECT {V2_SELECT_SQL_COLS} FROM samples_v2"
                        " WHERE run_id = ? AND id > ? ORDER BY id LIMIT ?",
                        (run_id, last_id, size),
                    )
                batch_rows = cur.fetchall()
            if not batch_rows:
                if total_skipped:
                    LOGGER.warning(
                        "run_id=%s: skipped %d corrupt v2 sample row(s) in total",
                        run_id,
                        total_skipped,
                    )
                return
            last_id = batch_rows[-1][0]
            parsed_batch: list[SensorFrame] = []
            for row in batch_rows:
                include_row = (sample_index % stride) == 0
                sample_index += 1
                if not include_row:
                    continue
                try:
                    parsed_batch.append(v2_row_to_sensor_frame(row))
                except SensorFrameDecodeError as exc:
                    total_skipped += 1
                    LOGGER.warning("Skipping corrupt v2 sample row id=%s: %s", row[0], exc)
            if parsed_batch:
                yield parsed_batch
