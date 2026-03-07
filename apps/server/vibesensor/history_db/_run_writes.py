"""Run-history write/mutation helpers for HistoryDB."""

from __future__ import annotations

import logging
from typing import Any

from ..domain_models import SensorFrame
from ..json_utils import safe_json_dumps
from ..runlog import utc_now_iso
from ._run_common import ANALYSIS_SCHEMA_VERSION, RunStatus
from ._samples import V2_INSERT_SQL, sample_to_v2_row
from ._typing import HistoryCursorProvider

LOGGER = logging.getLogger(__name__)


class HistoryRunWriteMixin:
    """Mixin providing run mutation and persistence methods."""

    __slots__ = ()

    def create_run(
        self: HistoryCursorProvider,
        run_id: str,
        start_time_utc: str,
        metadata: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE status = 'recording'",
                ("Recovered stale recording on new run creation",),
            )
            cur.execute(
                "INSERT INTO runs (run_id, status, start_time_utc, metadata_json, created_at) "
                "VALUES (?, 'recording', ?, ?, ?)",
                (run_id, start_time_utc, safe_json_dumps(metadata), now),
            )

    def append_samples(
        self: HistoryCursorProvider,
        run_id: str,
        samples: list[dict[str, Any]] | list[SensorFrame],
    ) -> None:
        if not samples:
            return
        if not run_id or not run_id.strip():
            raise ValueError("append_samples: run_id must be a non-empty string")

        chunk_size = 256
        with self._cursor() as cur:
            for start in range(0, len(samples), chunk_size):
                batch = samples[start : start + chunk_size]
                cur.executemany(
                    V2_INSERT_SQL,
                    (sample_to_v2_row(run_id, sample) for sample in batch),
                )
            cur.execute(
                "UPDATE runs SET sample_count = sample_count + ? WHERE run_id = ?",
                (len(samples), run_id),
            )

    def finalize_run(self: HistoryCursorProvider, run_id: str, end_time_utc: str) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'analyzing', end_time_utc = ?, "
                "analysis_started_at = ? WHERE run_id = ? AND status = 'recording'",
                (end_time_utc, now, run_id),
            )
            if cur.rowcount == 0:
                LOGGER.warning(
                    "finalize_run for run %s: no rows updated "
                    "(run missing or not in 'recording' state)",
                    run_id,
                )

    def update_run_metadata(
        self: HistoryCursorProvider,
        run_id: str,
        metadata: dict[str, Any],
    ) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET metadata_json = ? WHERE run_id = ?",
                (safe_json_dumps(metadata), run_id),
            )
            return bool(int(cur.rowcount) > 0)

    def finalize_run_with_metadata(
        self: HistoryCursorProvider,
        run_id: str,
        end_time_utc: str,
        metadata: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET metadata_json = ?, status = 'analyzing', "
                "end_time_utc = ?, analysis_started_at = ? "
                "WHERE run_id = ? AND status = 'recording'",
                (safe_json_dumps(metadata), end_time_utc, now, run_id),
            )
            if cur.rowcount == 0:
                LOGGER.warning(
                    "finalize_run_with_metadata for run %s: no rows updated "
                    "(run missing or not in 'recording' state)",
                    run_id,
                )

    def delete_run_if_safe(
        self: HistoryCursorProvider,
        run_id: str,
    ) -> tuple[bool, str | None]:
        with self._cursor() as cur:
            cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
            if row is None:
                return False, "not_found"
            status = row[0]
            if status == RunStatus.RECORDING:
                return False, "active"
            if status == RunStatus.ANALYZING:
                return False, RunStatus.ANALYZING
            cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return bool(int(cur.rowcount) > 0), None

    def store_analysis(
        self: HistoryCursorProvider,
        run_id: str,
        analysis: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'complete', analysis_json = ?, "
                "analysis_version = ?, analysis_completed_at = ? "
                "WHERE run_id = ? AND status NOT IN ('complete')",
                (
                    safe_json_dumps(analysis),
                    ANALYSIS_SCHEMA_VERSION,
                    now,
                    run_id,
                ),
            )
            if cur.rowcount == 0:
                cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
                row = cur.fetchone()
                if row is not None and row[0] == RunStatus.COMPLETE:
                    LOGGER.warning(
                        "store_analysis for run %s: skipped — already complete",
                        run_id,
                    )

    def store_analysis_error(self: HistoryCursorProvider, run_id: str, error: str) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ?, "
                "analysis_completed_at = ? "
                "WHERE run_id = ? AND status NOT IN ('complete')",
                (error, now, run_id),
            )
            if cur.rowcount == 0:
                LOGGER.warning(
                    "store_analysis_error for run %s: no rows updated "
                    "(run not found or already complete)",
                    run_id,
                )

    def delete_run(self: HistoryCursorProvider, run_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return bool(int(cur.rowcount) > 0)

    def recover_stale_recording_runs(self: HistoryCursorProvider) -> int:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE status = 'recording'",
                ("Recovered stale recording during startup",),
            )
            return int(cur.rowcount)
