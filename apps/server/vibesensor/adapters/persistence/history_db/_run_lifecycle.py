"""Run lifecycle and analysis-write helpers for ``HistoryDB``."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from vibesensor.adapters.persistence.history_db._samples import V2_INSERT_SQL, sample_to_v2_row
from vibesensor.domain.run_status import RunStatus, is_run_deletable, transition_run
from vibesensor.shared.boundaries.persisted_analysis_codec import (
    persisted_analysis_to_summary,
)
from vibesensor.shared.json_utils import safe_json_dumps
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame

LOGGER = logging.getLogger(__name__)

_RECOMMENDED_METADATA_KEYS: frozenset[str] = frozenset({"sensor_model", "sample_rate_hz"})
_EXPECTED_ANALYSIS_KEYS: frozenset[str] = frozenset({"findings", "top_causes", "warnings"})


class _HistoryDBRunLifecycleMixin:
    def _cursor(self, *, commit: bool = True) -> AbstractContextManager[sqlite3.Cursor]:
        raise NotImplementedError

    def write_transaction_cursor(self) -> AbstractContextManager[sqlite3.Cursor]:
        raise NotImplementedError

    @staticmethod
    def _run_status(cur: sqlite3.Cursor, run_id: str) -> str | None:
        cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return str(row[0])

    def create_run(
        self,
        run_id: str,
        start_time_utc: str,
        metadata: RunMetadata,
        case_id: str | None = None,
    ) -> None:
        metadata_payload = metadata.to_dict()
        missing = _RECOMMENDED_METADATA_KEYS - metadata_payload.keys()
        if missing:
            LOGGER.warning(
                "create_run %s: metadata missing recommended keys: %s",
                run_id,
                ", ".join(sorted(missing)),
            )
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO runs (run_id, case_id, status, start_time_utc, metadata_json, "
                "created_at) VALUES (?, ?, 'recording', ?, ?, ?)",
                (run_id, case_id, start_time_utc, safe_json_dumps(metadata_payload), now),
            )

    def append_samples(
        self,
        run_id: str,
        samples: list[SensorFrame],
    ) -> int:
        if not samples:
            return 0
        if not run_id or not run_id.strip():
            raise ValueError("append_samples: run_id must be a non-empty string")

        chunk_size = 256
        with self.write_transaction_cursor() as cur:
            current_status = self._run_status(cur, run_id)
            if current_status != RunStatus.RECORDING.value:
                LOGGER.warning(
                    "append_samples for run %s: rejected %d sample(s) because status is %s",
                    run_id,
                    len(samples),
                    current_status or "missing",
                )
                return 0
            for start in range(0, len(samples), chunk_size):
                batch = samples[start : start + chunk_size]
                cur.executemany(
                    V2_INSERT_SQL,
                    (sample_to_v2_row(run_id, sample) for sample in batch),
                )
            cur.execute(
                "UPDATE runs SET sample_count = sample_count + ? "
                "WHERE run_id = ? AND status = 'recording'",
                (len(samples), run_id),
            )
            if int(cur.rowcount) <= 0:
                raise sqlite3.IntegrityError(
                    f"append_samples: run {run_id} left recording during append",
                )
            return len(samples)

    def finalize_run(
        self,
        run_id: str,
        end_time_utc: str,
        metadata: RunMetadata | None = None,
        case_id: str | None = None,
    ) -> bool:
        now = utc_now_iso()
        with self._cursor() as cur:
            current_status = self._run_status(cur, run_id)
            try:
                transition_run(current_status, RunStatus.ANALYZING)
            except ValueError:
                LOGGER.warning(
                    "finalize_run for run %s: invalid transition %s → analyzing",
                    run_id,
                    current_status,
                )
                return False
            assignments = ["status = 'analyzing'", "end_time_utc = ?", "analysis_started_at = ?"]
            params: list[object] = [end_time_utc, now]
            if metadata is not None:
                assignments.insert(0, "metadata_json = ?")
                params.insert(0, safe_json_dumps(metadata.to_dict()))
            if case_id is not None:
                assignments.insert(0, "case_id = ?")
                params.insert(0, case_id)
            params.append(run_id)
            cur.execute(
                f"UPDATE runs SET {', '.join(assignments)} WHERE run_id = ?",
                params,
            )
            return int(cur.rowcount) > 0

    def update_run_metadata(
        self,
        run_id: str,
        metadata: RunMetadata,
    ) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET metadata_json = ? WHERE run_id = ?",
                (safe_json_dumps(metadata.to_dict()), run_id),
            )
            return bool(int(cur.rowcount) > 0)

    def delete_run_if_safe(
        self,
        run_id: str,
    ) -> tuple[bool, str | None]:
        with self._cursor() as cur:
            cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
            if row is None:
                return False, "not_found"
            status = RunStatus(row[0])
            if not is_run_deletable(status):
                return False, "active" if status == RunStatus.RECORDING else status.value
            cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return bool(int(cur.rowcount) > 0), None

    def store_analysis(
        self,
        run_id: str,
        analysis: PersistedAnalysis,
    ) -> bool:
        summary_payload = persisted_analysis_to_summary(analysis)
        missing = _EXPECTED_ANALYSIS_KEYS - summary_payload.keys()
        if missing:
            LOGGER.warning(
                "store_analysis %s: summary missing expected keys: %s",
                run_id,
                ", ".join(sorted(missing)),
            )
        now = utc_now_iso()
        with self._cursor() as cur:
            current_status = self._run_status(cur, run_id)
            if current_status == RunStatus.COMPLETE:
                LOGGER.warning(
                    "store_analysis for run %s: skipped — already complete",
                    run_id,
                )
                return False
            try:
                transition_run(current_status, RunStatus.COMPLETE)
            except ValueError:
                LOGGER.warning(
                    "store_analysis for run %s: invalid transition %s → complete",
                    run_id,
                    current_status,
                )
                return False
            cur.execute(
                "UPDATE runs SET status = 'complete', analysis_json = ?, "
                "analysis_completed_at = ?, end_time_utc = COALESCE(end_time_utc, ?) "
                "WHERE run_id = ?",
                (
                    safe_json_dumps(analysis.to_storage_json_object()),
                    now,
                    now,
                    run_id,
                ),
            )
            return int(cur.rowcount) > 0

    def store_analysis_error(self, run_id: str, error: str) -> bool:
        now = utc_now_iso()
        with self._cursor() as cur:
            current_status = self._run_status(cur, run_id)
            if current_status == RunStatus.COMPLETE:
                LOGGER.warning(
                    "store_analysis_error for run %s: skipped — already complete",
                    run_id,
                )
                return False
            try:
                transition_run(current_status, RunStatus.ERROR)
            except ValueError:
                LOGGER.warning(
                    "store_analysis_error for run %s: invalid transition %s → error",
                    run_id,
                    current_status,
                )
                return False
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ?, "
                "analysis_completed_at = ?, end_time_utc = COALESCE(end_time_utc, ?) "
                "WHERE run_id = ?",
                (error, now, now, run_id),
            )
            return int(cur.rowcount) > 0

    def delete_run(self, run_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return bool(int(cur.rowcount) > 0)

    def recover_stale_recording_runs(self) -> int:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE status = 'recording'",
                (f"Recovered stale recording during startup at {now}",),
            )
            return int(cur.rowcount)

    def prune_terminal_runs_older_than_days(self, retention_days: int) -> int:
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        cutoff_utc = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        with self._cursor() as cur:
            cur.execute(
                """
                DELETE FROM runs
                WHERE status IN ('complete', 'error')
                  AND COALESCE(analysis_completed_at, end_time_utc, created_at) < ?
                """,
                (cutoff_utc,),
            )
            return int(cur.rowcount)
