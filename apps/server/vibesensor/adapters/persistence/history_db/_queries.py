"""Read/query helpers for ``HistoryDB``."""

from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

import aiosqlite

from vibesensor.domain.run_status import RunStatus
from vibesensor.shared.async_bridge import run_coro_blocking
from vibesensor.shared.boundaries.analysis_payloads import (
    persisted_analysis_from_storage_json_object,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
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
    def _cursor(self, *, commit: bool = True) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        raise NotImplementedError

    @staticmethod
    def _fallback_run_metadata(
        *,
        run_id: str,
        start_time_utc: str,
        end_time_utc: str | None,
    ) -> RunMetadata:
        return run_metadata_from_mapping(
            {
                "run_id": run_id,
                "start_time_utc": start_time_utc,
                "end_time_utc": end_time_utc,
                "sensor_model": "unknown",
            }
        )

    def _coerce_run_metadata(
        self,
        *,
        run_id: str,
        start_time_utc: str,
        end_time_utc: str | None,
        metadata_json: str | None,
        source: str,
        allow_fallback: bool,
    ) -> RunMetadata | None:
        parsed = safe_json_loads(metadata_json, context=f"run {run_id} metadata")
        if not is_json_object(parsed):
            if parsed is not None:
                LOGGER.warning(
                    "%s: run %s metadata_json parsed to %s, expected dict; %s",
                    source,
                    run_id,
                    type(parsed).__name__,
                    "using fallback metadata object" if allow_fallback else "returning None",
                )
            if allow_fallback:
                return self._fallback_run_metadata(
                    run_id=run_id,
                    start_time_utc=start_time_utc,
                    end_time_utc=end_time_utc,
                )
            return None
        if "start_time_utc" not in parsed:
            parsed["start_time_utc"] = start_time_utc
        if end_time_utc and "end_time_utc" not in parsed:
            parsed["end_time_utc"] = end_time_utc
        return run_metadata_from_mapping(parsed)

    def list_runs(self, limit: int = 500) -> list[HistoryRunListEntry]:
        return run_coro_blocking(self.alist_runs(limit))

    async def alist_runs(self, limit: int = 500) -> list[HistoryRunListEntry]:
        async with self._cursor(commit=False) as cur:
            limit = max(limit, 0)
            if limit > 0:
                await cur.execute(
                    "SELECT r.run_id, r.status, r.start_time_utc, r.end_time_utc, "
                    "r.created_at, r.error_message, r.sample_count, r.metadata_json "
                    "FROM runs r ORDER BY r.created_at DESC LIMIT ?",
                    (limit,),
                )
            else:
                await cur.execute(
                    "SELECT r.run_id, r.status, r.start_time_utc, r.end_time_utc, "
                    "r.created_at, r.error_message, r.sample_count, r.metadata_json "
                    "FROM runs r ORDER BY r.created_at DESC",
                )
            rows = await cur.fetchall()
        result: list[HistoryRunListEntry] = []
        for row in rows:
            run_id, status_raw, start, end, created, error, sample_count, metadata_json = row
            normalized_run_id = str(run_id)
            normalized_start = str(start)
            normalized_end = str(end) if end is not None else None
            normalized_metadata_json = str(metadata_json) if metadata_json is not None else None
            metadata = self._coerce_run_metadata(
                run_id=normalized_run_id,
                start_time_utc=normalized_start,
                end_time_utc=normalized_end,
                metadata_json=normalized_metadata_json,
                source="list_runs",
                allow_fallback=True,
            )
            result.append(
                HistoryRunListEntry(
                    run_id=normalized_run_id,
                    status=RunStatus(status_raw),
                    start_time_utc=normalized_start,
                    end_time_utc=normalized_end,
                    created_at=str(created),
                    sample_count=int(sample_count or 0),
                    car_name=metadata.car_name if metadata is not None else None,
                    error_message=str(error) if error else None,
                )
            )
        return result

    def get_run(self, run_id: str) -> StoredHistoryRun | None:
        return run_coro_blocking(self.aget_run(run_id))

    async def aget_run(self, run_id: str) -> StoredHistoryRun | None:
        async with self._cursor(commit=False) as cur:
            await cur.execute(
                "SELECT run_id, case_id, status, start_time_utc, end_time_utc, "
                "metadata_json, analysis_json, error_message, created_at, "
                "sample_count, analysis_started_at, analysis_completed_at "
                "FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = await cur.fetchone()
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
        metadata = self._coerce_run_metadata(
            run_id=str(rid),
            start_time_utc=str(start),
            end_time_utc=str(end) if end is not None else None,
            metadata_json=str(meta_json) if meta_json is not None else None,
            source="get_run",
            allow_fallback=True,
        )
        assert metadata is not None
        analysis: PersistedAnalysis | None = None
        analysis_corrupt = False
        if analysis_json:
            parsed_analysis = safe_json_loads(analysis_json, context=f"run {run_id} analysis")
            if is_json_object(parsed_analysis):
                try:
                    analysis = persisted_analysis_from_storage_json_object(parsed_analysis)
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
        return run_coro_blocking(self.aget_run_metadata(run_id))

    async def aget_run_metadata(self, run_id: str) -> RunMetadata | None:
        async with self._cursor(commit=False) as cur:
            await cur.execute(
                "SELECT start_time_utc, end_time_utc, metadata_json FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        start_time_utc, end_time_utc, metadata_json = row
        return self._coerce_run_metadata(
            run_id=run_id,
            start_time_utc=str(start_time_utc),
            end_time_utc=str(end_time_utc) if end_time_utc is not None else None,
            metadata_json=str(metadata_json) if metadata_json is not None else None,
            source="get_run_metadata",
            allow_fallback=False,
        )

    def get_active_run_id(self) -> str | None:
        return run_coro_blocking(self.aget_active_run_id())

    async def aget_active_run_id(self) -> str | None:
        async with self._cursor(commit=False) as cur:
            await cur.execute(
                "SELECT run_id FROM runs WHERE status = 'recording' "
                "ORDER BY created_at DESC LIMIT 1",
            )
            row = await cur.fetchone()
        return str(row[0]) if row else None

    def stale_analyzing_run_ids(self) -> list[str]:
        return run_coro_blocking(self.astale_analyzing_run_ids())

    async def astale_analyzing_run_ids(self) -> list[str]:
        async with self._cursor(commit=False) as cur:
            await cur.execute(
                "SELECT run_id FROM runs WHERE status = 'analyzing' "
                "ORDER BY created_at ASC LIMIT 1000",
            )
            return [str(row[0]) for row in await cur.fetchall()]

    def analyzing_run_health(self) -> AnalyzingRunHealth:
        return run_coro_blocking(self.aanalyzing_run_health())

    async def aanalyzing_run_health(self) -> AnalyzingRunHealth:
        async with self._cursor(commit=False) as cur:
            await cur.execute(
                "SELECT COUNT(*), MIN(analysis_started_at) FROM runs WHERE status = 'analyzing'",
            )
            row = await cur.fetchone()
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
        return run_coro_blocking(self.averify_run_integrity(run_id))

    async def averify_run_integrity(self, run_id: str) -> list[str]:
        """Check a completed run for consistency issues. Returns problem descriptions."""
        problems: list[str] = []
        async with self._cursor(commit=False) as cur:
            await cur.execute(
                "SELECT status, sample_count, analysis_json FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = await cur.fetchone()
            if row is None:
                return ["run not found"]
            status, stored_count, analysis_raw = row[0], row[1], row[2]
            if status == "complete" and not analysis_raw:
                problems.append("complete run missing analysis_json")
            if stored_count is not None:
                await cur.execute(
                    "SELECT COUNT(*) FROM samples_v2 WHERE run_id = ?",
                    (run_id,),
                )
                count_row = await cur.fetchone()
                actual_count = int(count_row[0]) if count_row is not None else 0
                stored_int = int(stored_count)
                if actual_count != stored_int:
                    problems.append(
                        f"sample_count mismatch: stored={stored_int}, actual={actual_count}",
                    )
        return problems
