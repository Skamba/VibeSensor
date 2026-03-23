"""Read/query helpers for ``HistoryDB``."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import AbstractContextManager
from datetime import UTC, datetime

from vibesensor.domain.run_status import RunStatus
from vibesensor.shared.json_utils import safe_json_loads
from vibesensor.shared.types.history_records import (
    AnalyzingRunHealth,
    HistoryRunListEntry,
    StoredHistoryRun,
)
from vibesensor.shared.types.json_types import is_json_object
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.run_schema import RunMetadata

LOGGER = logging.getLogger(__name__)


class _HistoryDBQueryMixin:
    def _cursor(self, *, commit: bool = True) -> AbstractContextManager[sqlite3.Cursor]:
        raise NotImplementedError

    @staticmethod
    def _fallback_run_metadata(
        *,
        run_id: str,
        start_time_utc: str,
        end_time_utc: str | None,
    ) -> RunMetadata:
        return RunMetadata.from_dict(
            {
                "run_id": run_id,
                "start_time_utc": start_time_utc,
                "end_time_utc": end_time_utc,
                "sensor_model": "unknown",
            }
        )

    def list_runs(self, limit: int = 500) -> list[HistoryRunListEntry]:
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
        result: list[HistoryRunListEntry] = []
        for row in rows:
            run_id, status_raw, start, end, created, error, sample_count = row
            result.append(
                HistoryRunListEntry(
                    run_id=str(run_id),
                    status=RunStatus(status_raw),
                    start_time_utc=str(start),
                    end_time_utc=str(end) if end is not None else None,
                    created_at=str(created),
                    sample_count=int(sample_count or 0),
                    error_message=str(error) if error else None,
                )
            )
        return result

    def get_run(self, run_id: str) -> StoredHistoryRun | None:
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
        parsed_metadata = safe_json_loads(meta_json, context=f"run {run_id} metadata")
        if is_json_object(parsed_metadata):
            metadata = RunMetadata.from_dict(parsed_metadata)
        else:
            if parsed_metadata is not None:
                LOGGER.warning(
                    "get_run: metadata for run %s parsed to %s; using fallback metadata object",
                    run_id,
                    type(parsed_metadata).__name__,
                )
            metadata = self._fallback_run_metadata(
                run_id=str(rid),
                start_time_utc=str(start),
                end_time_utc=str(end) if end is not None else None,
            )
        analysis: PersistedAnalysis | None = None
        analysis_corrupt = False
        if analysis_json:
            parsed_analysis = safe_json_loads(analysis_json, context=f"run {run_id} analysis")
            if is_json_object(parsed_analysis):
                try:
                    analysis = PersistedAnalysis.from_storage_json_object(parsed_analysis)
                except ValueError:
                    LOGGER.warning(
                        "get_run: analysis for run %s used an unsupported storage schema version",
                        run_id,
                        exc_info=True,
                    )
                    analysis_corrupt = True
            else:
                analysis_corrupt = True
        return StoredHistoryRun(
            run_id=str(rid),
            case_id=str(case_id) if case_id is not None else None,
            status=status,
            start_time_utc=str(start),
            end_time_utc=str(end) if end is not None else None,
            metadata=metadata,
            analysis=analysis,
            analysis_corrupt=analysis_corrupt,
            error_message=str(error) if error else None,
            created_at=str(created),
            sample_count=int(sample_count or 0),
            analysis_started_at=str(analysis_started) if analysis_started else None,
            analysis_completed_at=str(analysis_completed) if analysis_completed else None,
        )

    def get_run_metadata(self, run_id: str) -> RunMetadata | None:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT start_time_utc, end_time_utc, metadata_json FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        start_time_utc, end_time_utc, metadata_json = row
        parsed = safe_json_loads(metadata_json, context=f"run {run_id} metadata")
        if not is_json_object(parsed):
            if parsed is not None:
                LOGGER.warning(
                    "get_run_metadata: run %s metadata_json parsed to %s, expected dict; "
                    "returning None",
                    run_id,
                    type(parsed).__name__,
                )
            return None
        if "start_time_utc" not in parsed:
            parsed["start_time_utc"] = str(start_time_utc)
        if end_time_utc and "end_time_utc" not in parsed:
            parsed["end_time_utc"] = str(end_time_utc)
        return RunMetadata.from_dict(parsed)

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

    def analyzing_run_health(self) -> AnalyzingRunHealth:
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
        return AnalyzingRunHealth(
            analyzing_run_count=count,
            analyzing_oldest_age_s=oldest_age_s,
            analyzing_oldest_started_at=oldest_started_at,
        )

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
