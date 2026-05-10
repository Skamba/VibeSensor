"""Read/query helpers for ``HistoryDB``."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Protocol, TypeVar

import aiosqlite

from vibesensor.adapters.persistence.history_db._run_projection import (
    _HistoryDBRunProjectionMixin,
)
from vibesensor.shared.types.history_records import (
    AnalyzingRunHealth,
    HistoryRunListEntry,
    StoredHistoryRun,
)
from vibesensor.shared.types.raw_capture import (
    RawCaptureManifest,
    RawCaptureSensorRange,
    RawRunCapture,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest

LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")


class _HistoryDBQueryMixin(_HistoryDBRunProjectionMixin, Protocol):
    def _cursor(self, *, commit: bool = True) -> AbstractAsyncContextManager[aiosqlite.Cursor]: ...

    def _run_sync(self, coro: Awaitable[_T]) -> _T: ...

    def list_runs(self, limit: int = 500) -> list[HistoryRunListEntry]:
        return self._run_sync(self.alist_runs(limit))

    async def alist_runs(self, limit: int = 500) -> list[HistoryRunListEntry]:
        async with self._cursor(commit=False) as cur:
            limit = max(limit, 0)
            if limit > 0:
                await cur.execute(
                    "SELECT r.run_id, r.status, r.start_time_utc, r.end_time_utc, "
                    "r.created_at, r.error_message, r.sample_count, r.car_name, "
                    "r.metadata_json, r.analysis_json, r.raw_capture_manifest_json, "
                    "r.whole_run_artifact_manifest_json "
                    "FROM runs r ORDER BY r.created_at DESC LIMIT ?",
                    (limit,),
                )
            else:
                await cur.execute(
                    "SELECT r.run_id, r.status, r.start_time_utc, r.end_time_utc, "
                    "r.created_at, r.error_message, r.sample_count, r.car_name, "
                    "r.metadata_json, r.analysis_json, r.raw_capture_manifest_json, "
                    "r.whole_run_artifact_manifest_json "
                    "FROM runs r ORDER BY r.created_at DESC",
                )
            rows = await cur.fetchall()
        return [self._project_run_list_entry(row) for row in rows]

    def get_run(self, run_id: str) -> StoredHistoryRun | None:
        return self._run_sync(self.aget_run(run_id))

    async def aget_run(self, run_id: str) -> StoredHistoryRun | None:
        async with self._cursor(commit=False) as cur:
            await cur.execute(
                "SELECT run_id, case_id, status, start_time_utc, end_time_utc, "
                "metadata_json, raw_capture_manifest_json, whole_run_artifact_manifest_json, "
                "analysis_json, "
                "error_message, created_at, "
                "sample_count, analysis_started_at, analysis_completed_at "
                "FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return self._project_stored_run(row)

    async def aget_raw_capture_manifest(self, run_id: str) -> RawCaptureManifest | None:
        async with self._cursor(commit=False) as cur:
            await cur.execute(
                "SELECT raw_capture_manifest_json FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = await cur.fetchone()
        if row is None or row[0] is None:
            return None
        return self._coerce_raw_capture_manifest(
            run_id=run_id,
            manifest_json=str(row[0]),
            source="get_raw_capture_manifest",
        )

    async def aget_whole_run_artifact_manifest(
        self,
        run_id: str,
    ) -> WholeRunArtifactManifest | None:
        async with self._cursor(commit=False) as cur:
            await cur.execute(
                "SELECT whole_run_artifact_manifest_json FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = await cur.fetchone()
        if row is None or row[0] is None:
            return None
        return self._coerce_whole_run_artifact_manifest(
            run_id=run_id,
            manifest_json=str(row[0]),
            source="get_whole_run_artifact_manifest",
        )

    async def aload_raw_capture(self, run_id: str) -> RawRunCapture | None:
        manifest = await self.aget_raw_capture_manifest(run_id)
        if manifest is None:
            return None
        if not await asyncio.to_thread(self._raw_capture_store.has_run_artifacts, run_id):
            return None
        return await asyncio.to_thread(self._raw_capture_store.load_capture, manifest)

    async def aload_whole_run_artifact(
        self,
        run_id: str,
        artifact_key: str,
    ) -> bytes | None:
        manifest = await self.aget_whole_run_artifact_manifest(run_id)
        if manifest is None:
            return None
        if not await asyncio.to_thread(self._whole_run_artifact_store.has_run_artifacts, run_id):
            return None
        return await asyncio.to_thread(
            self._whole_run_artifact_store.load_artifact_bytes,
            manifest,
            artifact_key=artifact_key,
        )

    async def aload_raw_capture_sensor_range(
        self,
        run_id: str,
        client_id: str,
        *,
        sample_start: int,
        sample_count: int,
    ) -> RawCaptureSensorRange | None:
        manifest = await self.aget_raw_capture_manifest(run_id)
        if manifest is None:
            return None
        if not await asyncio.to_thread(self._raw_capture_store.has_run_artifacts, run_id):
            return None
        return await asyncio.to_thread(
            self._raw_capture_store.load_sensor_range,
            manifest,
            client_id=client_id,
            sample_start=sample_start,
            sample_count=sample_count,
        )

    def get_run_metadata(self, run_id: str) -> RunMetadata | None:
        return self._run_sync(self.aget_run_metadata(run_id))

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
        return self._run_sync(self.aget_active_run_id())

    async def aget_active_run_id(self) -> str | None:
        async with self._cursor(commit=False) as cur:
            await cur.execute(
                "SELECT run_id FROM runs WHERE status = 'recording' "
                "ORDER BY created_at DESC LIMIT 1",
            )
            row = await cur.fetchone()
        return str(row[0]) if row else None

    def stale_analyzing_run_ids(self) -> list[str]:
        return self._run_sync(self.astale_analyzing_run_ids())

    async def astale_analyzing_run_ids(self) -> list[str]:
        async with self._cursor(commit=False) as cur:
            await cur.execute(
                "SELECT run_id FROM runs WHERE status = 'analyzing' "
                "ORDER BY created_at ASC LIMIT 1000",
            )
            return [str(row[0]) for row in await cur.fetchall()]

    def analyzing_run_health(self) -> AnalyzingRunHealth:
        return self._run_sync(self.aanalyzing_run_health())

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
        return self._run_sync(self.averify_run_integrity(run_id))

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
