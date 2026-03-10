"""Run-history write/mutation helpers for HistoryDB."""

from __future__ import annotations

import logging
import sqlite3

from ..analysis_persistence import wrap_analysis_for_storage
from ..domain_models import SensorFrame
from ..json_types import JsonObject
from ..json_utils import safe_json_dumps
from ..runlog import utc_now_iso
from ._samples import V2_INSERT_SQL, sample_to_v2_row
from ._schema import (
    ANALYSIS_SCHEMA_VERSION,
    HistoryCursorProvider,
    RunStatus,
    can_transition_run,
)

LOGGER = logging.getLogger(__name__)

_RECOMMENDED_METADATA_KEYS: frozenset[str] = frozenset({"sensor_model", "sample_rate_hz"})


_EXPECTED_ANALYSIS_KEYS: frozenset[str] = frozenset({"findings", "top_causes", "warnings"})


class HistoryRunWriteMixin:
    """Mixin providing run mutation and persistence methods."""

    __slots__ = ()

    @staticmethod
    def _run_status(cur: sqlite3.Cursor, run_id: str) -> str | None:
        cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return str(row[0])

    @staticmethod
    def _log_transition_skip(run_id: str, current_status: str | None, target_status: str) -> None:
        if current_status is None:
            LOGGER.warning(
                "Skipping run transition to %s for %s: run not found",
                target_status,
                run_id,
            )
            return
        LOGGER.warning(
            "Skipping run transition for %s: %s -> %s is not allowed",
            run_id,
            current_status,
            target_status,
        )

    def create_run(
        self: HistoryCursorProvider,
        run_id: str,
        start_time_utc: str,
        metadata: JsonObject,
    ) -> None:
        missing = _RECOMMENDED_METADATA_KEYS - metadata.keys()
        if missing:
            LOGGER.warning(
                "create_run %s: metadata missing recommended keys: %s",
                run_id,
                ", ".join(sorted(missing)),
            )
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE status = 'recording'",
                (f"Recovered stale recording when starting run {run_id} at {now}",),
            )
            if cur.rowcount > 0:
                LOGGER.warning(
                    "Recovered %d stale recording run(s) while starting run %s",
                    cur.rowcount,
                    run_id,
                )
            cur.execute(
                "INSERT INTO runs (run_id, status, start_time_utc, metadata_json, created_at) "
                "VALUES (?, 'recording', ?, ?, ?)",
                (run_id, start_time_utc, safe_json_dumps(metadata), now),
            )

    def append_samples(
        self: HistoryCursorProvider,
        run_id: str,
        samples: list[JsonObject] | list[SensorFrame],
    ) -> None:
        if not samples:
            return
        if not run_id or not run_id.strip():
            raise ValueError("append_samples: run_id must be a non-empty string")

        chunk_size = 256
        with self.write_transaction_cursor() as cur:
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

    def finalize_run(self: HistoryCursorProvider, run_id: str, end_time_utc: str) -> bool:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'analyzing', end_time_utc = ?, "
                "analysis_started_at = ? WHERE run_id = ? AND status = 'recording'",
                (end_time_utc, now, run_id),
            )
            if int(cur.rowcount) > 0:
                return True
            current_status = self._run_status(cur, run_id)
            if not can_transition_run(current_status, RunStatus.ANALYZING):
                self._log_transition_skip(run_id, current_status, RunStatus.ANALYZING)
            return False

    def update_run_metadata(
        self: HistoryCursorProvider,
        run_id: str,
        metadata: JsonObject,
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
        metadata: JsonObject,
    ) -> bool:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET metadata_json = ?, status = 'analyzing', "
                "end_time_utc = ?, analysis_started_at = ? "
                "WHERE run_id = ? AND status = 'recording'",
                (safe_json_dumps(metadata), end_time_utc, now, run_id),
            )
            if int(cur.rowcount) > 0:
                return True
            current_status = self._run_status(cur, run_id)
            if not can_transition_run(current_status, RunStatus.ANALYZING):
                self._log_transition_skip(run_id, current_status, RunStatus.ANALYZING)
            return False

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
        analysis: JsonObject,
    ) -> bool:
        missing = _EXPECTED_ANALYSIS_KEYS - analysis.keys()
        if missing:
            LOGGER.warning(
                "store_analysis %s: summary missing expected keys: %s",
                run_id,
                ", ".join(sorted(missing)),
            )
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'complete', analysis_json = ?, "
                "analysis_version = ?, analysis_completed_at = ? "
                "WHERE run_id = ? AND status IN ('recording', 'analyzing')",
                (
                    safe_json_dumps(wrap_analysis_for_storage(analysis)),
                    ANALYSIS_SCHEMA_VERSION,
                    now,
                    run_id,
                ),
            )
            if int(cur.rowcount) > 0:
                return True
            current_status = self._run_status(cur, run_id)
            if current_status == RunStatus.COMPLETE:
                LOGGER.warning(
                    "store_analysis for run %s: skipped — already complete",
                    run_id,
                )
            elif not can_transition_run(current_status, RunStatus.COMPLETE):
                self._log_transition_skip(run_id, current_status, RunStatus.COMPLETE)
            return False

    def store_analysis_error(self: HistoryCursorProvider, run_id: str, error: str) -> bool:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ?, "
                "analysis_completed_at = ? "
                "WHERE run_id = ? AND status IN ('recording', 'analyzing')",
                (error, now, run_id),
            )
            if int(cur.rowcount) > 0:
                return True
            current_status = self._run_status(cur, run_id)
            if current_status == RunStatus.COMPLETE:
                LOGGER.warning(
                    "store_analysis_error for run %s: skipped — already complete",
                    run_id,
                )
            elif not can_transition_run(current_status, RunStatus.ERROR):
                self._log_transition_skip(run_id, current_status, RunStatus.ERROR)
            return False

    def delete_run(self: HistoryCursorProvider, run_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return bool(int(cur.rowcount) > 0)

    def recover_stale_recording_runs(self: HistoryCursorProvider) -> int:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE status = 'recording'",
                (f"Recovered stale recording during startup at {now}",),
            )
            return int(cur.rowcount)
