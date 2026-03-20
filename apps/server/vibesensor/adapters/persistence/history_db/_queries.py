"""Read/query helpers for ``HistoryDB``."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import AbstractContextManager
from datetime import UTC, datetime

from vibesensor.domain.run_status import RunStatus
from vibesensor.shared.json_utils import safe_json_loads
from vibesensor.shared.types.json_types import JsonObject, is_json_object

LOGGER = logging.getLogger(__name__)


class _HistoryDBQueryMixin:
    def _cursor(self, *, commit: bool = True) -> AbstractContextManager[sqlite3.Cursor]:
        raise NotImplementedError

    def list_runs(self, limit: int = 500) -> list[JsonObject]:
        with self._cursor(commit=False) as cur:
            limit = max(limit, 0)
            if limit > 0:
                cur.execute(
                    "SELECT r.run_id, r.status, r.start_time_utc, r.end_time_utc, "
                    "r.created_at, r.error_message, r.sample_count "
                    "FROM runs r ORDER BY r.created_at DESC LIMIT ?",
                    (limit,),
                )
            else:
                cur.execute(
                    "SELECT r.run_id, r.status, r.start_time_utc, r.end_time_utc, "
                    "r.created_at, r.error_message, r.sample_count "
                    "FROM runs r ORDER BY r.created_at DESC",
                )
            rows = cur.fetchall()
        result: list[JsonObject] = []
        for row in rows:
            run_id, status_raw, start, end, created, error, sample_count = row
            status = RunStatus(status_raw)
            entry: JsonObject = {
                "run_id": run_id,
                "status": status,
                "start_time_utc": start,
                "end_time_utc": end,
                "created_at": created,
                "sample_count": sample_count,
            }
            if error:
                entry["error_message"] = error
            result.append(entry)
        return result

    def get_run(self, run_id: str) -> JsonObject | None:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT run_id, case_id, status, start_time_utc, end_time_utc, "
                "metadata_json, analysis_json, error_message, created_at, "
                "sample_count, analysis_started_at, analysis_completed_at "
                "FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        (
            rid,
            case_id,
            status_raw,
            start,
            end,
            meta_json,
            analysis_json,
            error,
            created,
            sample_count,
            analysis_started,
            analysis_completed,
        ) = row
        status = RunStatus(status_raw)
        entry: JsonObject = {
            "run_id": rid,
            "status": status,
            "start_time_utc": start,
            "end_time_utc": end,
            "metadata": safe_json_loads(meta_json, context=f"run {run_id} metadata") or {},
            "created_at": created,
            "sample_count": sample_count,
        }
        if case_id is not None:
            entry["case_id"] = case_id
        if analysis_json:
            parsed_analysis = safe_json_loads(analysis_json, context=f"run {run_id} analysis")
            if is_json_object(parsed_analysis):
                entry["analysis"] = parsed_analysis
            else:
                entry["analysis_corrupt"] = True
        if error:
            entry["error_message"] = error
        if analysis_started:
            entry["analysis_started_at"] = analysis_started
        if analysis_completed:
            entry["analysis_completed_at"] = analysis_completed
        return entry

    def get_run_metadata(self, run_id: str) -> JsonObject | None:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT metadata_json FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        if row is None:
            return None
        parsed = safe_json_loads(row[0], context=f"run {run_id} metadata")
        if not is_json_object(parsed):
            if parsed is not None:
                LOGGER.warning(
                    "get_run_metadata: run %s metadata_json parsed to %s, expected dict; "
                    "returning None",
                    run_id,
                    type(parsed).__name__,
                )
            return None
        return parsed

    def get_active_run_id(self) -> str | None:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT run_id FROM runs WHERE status = 'recording' "
                "ORDER BY created_at DESC LIMIT 1",
            )
            row = cur.fetchone()
        return str(row[0]) if row else None

    def stale_analyzing_run_ids(self) -> list[str]:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT run_id FROM runs WHERE status = 'analyzing' "
                "ORDER BY created_at ASC LIMIT 1000",
            )
            return [str(row[0]) for row in cur.fetchall()]

    def analyzing_run_health(self) -> JsonObject:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT COUNT(*), MIN(analysis_started_at) FROM runs WHERE status = 'analyzing'",
            )
            row = cur.fetchone()
        count = int(row[0]) if row and row[0] is not None else 0
        oldest_started_at = str(row[1]) if row and row[1] else None
        oldest_age_s: float | None = None
        if oldest_started_at:
            try:
                started = datetime.fromisoformat(oldest_started_at.replace("Z", "+00:00"))
                oldest_age_s = max(
                    0.0,
                    (datetime.now(UTC) - started).total_seconds(),
                )
            except ValueError:
                LOGGER.warning(
                    "analyzing_run_health: invalid timestamp %r; ignoring",
                    oldest_started_at,
                )
        result: JsonObject = {
            "analyzing_run_count": count,
            "analyzing_oldest_age_s": oldest_age_s,
        }
        if oldest_started_at is not None:
            result["analyzing_oldest_started_at"] = oldest_started_at
        return result

    def verify_run_integrity(self, run_id: str) -> list[str]:
        """Check a completed run for consistency issues. Returns problem descriptions."""
        problems: list[str] = []
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT status, sample_count, analysis_json FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
            if row is None:
                return ["run not found"]
            status, stored_count, analysis_raw = row[0], row[1], row[2]
            if status == "complete" and not analysis_raw:
                problems.append("complete run missing analysis_json")
            if stored_count is not None:
                cur.execute(
                    "SELECT COUNT(*) FROM samples_v2 WHERE run_id = ?",
                    (run_id,),
                )
                actual_count = int(cur.fetchone()[0])
                stored_int = int(stored_count)
                if actual_count != stored_int:
                    problems.append(
                        f"sample_count mismatch: stored={stored_int}, actual={actual_count}",
                    )
        return problems
