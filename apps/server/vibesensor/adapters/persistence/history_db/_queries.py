"""Read/query helpers for ``HistoryDB``."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import TypeVar, cast

import aiosqlite

from vibesensor.adapters.persistence.history_db._raw_capture_store import (
    HistoryRawCaptureStore,
)
from vibesensor.adapters.persistence.history_db._whole_run_artifact_store import (
    HistoryWholeRunArtifactStore,
)
from vibesensor.domain.run_status import RunStatus
from vibesensor.shared.boundaries.analysis_payloads import (
    persisted_analysis_from_storage_json_object,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.json_utils import safe_json_loads
from vibesensor.shared.types.history_records import (
    AnalyzingRunHealth,
    ArtifactAvailabilityState,
    HistoryArtifactAvailability,
    HistoryRunListEntry,
    StoredHistoryRun,
)
from vibesensor.shared.types.json_types import is_json_object
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.raw_capture import (
    RawCaptureManifest,
    RawCaptureSensorRange,
    RawRunCapture,
)
from vibesensor.shared.types.run_lifecycle import (
    RunArtifactLifecycle,
    derive_run_artifact_lifecycle,
)
from vibesensor.shared.types.run_schema import RunMetadata, RunRawCaptureFinalize
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest

LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")


class _HistoryDBQueryMixin:
    _raw_capture_store: HistoryRawCaptureStore
    _whole_run_artifact_store: HistoryWholeRunArtifactStore

    def _cursor(self, *, commit: bool = True) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        raise NotImplementedError

    def _run_sync(self, coro: Awaitable[_T]) -> _T:
        raise NotImplementedError

    @staticmethod
    def _artifact_availability_state(
        state: str,
    ) -> ArtifactAvailabilityState:
        return cast(
            ArtifactAvailabilityState,
            "available" if state == "ready" else state,
        )

    def _artifact_availability(
        self,
        *,
        lifecycle: RunArtifactLifecycle,
    ) -> HistoryArtifactAvailability:
        return HistoryArtifactAvailability(
            raw_capture=self._artifact_availability_state(lifecycle.raw_capture),
            whole_run_artifacts=self._artifact_availability_state(lifecycle.whole_run_artifacts),
        )

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

    def _coerce_raw_capture_manifest(
        self,
        *,
        run_id: str,
        manifest_json: str | None,
        source: str,
    ) -> RawCaptureManifest | None:
        parsed = safe_json_loads(manifest_json, context=f"run {run_id} raw_capture_manifest")
        if not is_json_object(parsed):
            if parsed is not None:
                LOGGER.warning(
                    "%s: run %s raw_capture_manifest_json parsed to %s, expected dict",
                    source,
                    run_id,
                    type(parsed).__name__,
                )
            return None
        return RawCaptureManifest.from_mapping(parsed)

    def _coerce_whole_run_artifact_manifest(
        self,
        *,
        run_id: str,
        manifest_json: str | None,
        source: str,
    ) -> WholeRunArtifactManifest | None:
        parsed = safe_json_loads(
            manifest_json,
            context=f"run {run_id} whole_run_artifact_manifest",
        )
        if not is_json_object(parsed):
            if parsed is not None:
                LOGGER.warning(
                    "%s: run %s whole_run_artifact_manifest_json parsed to %s, expected dict",
                    source,
                    run_id,
                    type(parsed).__name__,
                )
            return None
        return WholeRunArtifactManifest.from_mapping(parsed)

    def _coerce_raw_capture_finalize(
        self,
        *,
        run_id: str,
        metadata_json: str | None,
        source: str,
    ) -> RunRawCaptureFinalize | None:
        metadata = self._coerce_run_metadata(
            run_id=run_id,
            start_time_utc="",
            end_time_utc=None,
            metadata_json=metadata_json,
            source=source,
            allow_fallback=False,
        )
        return None if metadata is None else metadata.raw_capture_finalize

    def _coerce_analysis(
        self,
        *,
        run_id: str,
        analysis_json: str | None,
        source: str,
    ) -> tuple[PersistedAnalysis | None, bool]:
        if not analysis_json:
            return None, False
        parsed_analysis = safe_json_loads(analysis_json, context=f"run {run_id} analysis")
        if not is_json_object(parsed_analysis):
            LOGGER.warning(
                "%s: run %s analysis_json parsed to %s, expected dict",
                source,
                run_id,
                type(parsed_analysis).__name__,
            )
            return None, True
        try:
            return persisted_analysis_from_storage_json_object(parsed_analysis), False
        except ValueError:
            LOGGER.warning(
                "%s: analysis for run %s used an unsupported storage schema version",
                source,
                run_id,
                exc_info=True,
            )
            return None, True

    def _run_lifecycle(
        self,
        *,
        run_id: str,
        status: RunStatus,
        has_raw_capture_manifest: bool,
        has_whole_run_artifact_manifest: bool,
        raw_capture_finalize: RunRawCaptureFinalize | None,
        has_analysis: bool,
        analysis_corrupt: bool,
    ) -> RunArtifactLifecycle:
        return derive_run_artifact_lifecycle(
            status=status,
            has_raw_capture_manifest=has_raw_capture_manifest,
            raw_capture_artifacts_present=(
                has_raw_capture_manifest and self._raw_capture_store.has_run_artifacts(run_id)
            ),
            has_whole_run_artifact_manifest=has_whole_run_artifact_manifest,
            whole_run_artifacts_present=(
                has_whole_run_artifact_manifest
                and self._whole_run_artifact_store.has_run_artifacts(run_id)
            ),
            raw_capture_finalize=raw_capture_finalize,
            has_analysis=has_analysis,
            analysis_corrupt=analysis_corrupt,
        )

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
        result: list[HistoryRunListEntry] = []
        for row in rows:
            (
                run_id,
                status_raw,
                start,
                end,
                created,
                error,
                sample_count,
                car_name,
                metadata_json,
                analysis_json,
                raw_capture_manifest_json,
                whole_run_artifact_manifest_json,
            ) = row
            normalized_run_id = str(run_id)
            normalized_start = str(start)
            normalized_end = str(end) if end is not None else None
            raw_capture_finalize = self._coerce_raw_capture_finalize(
                run_id=normalized_run_id,
                metadata_json=str(metadata_json) if metadata_json is not None else None,
                source="list_runs",
            )
            status = RunStatus(status_raw)
            analysis, analysis_corrupt = self._coerce_analysis(
                run_id=normalized_run_id,
                analysis_json=str(analysis_json) if analysis_json is not None else None,
                source="list_runs",
            )
            lifecycle = self._run_lifecycle(
                run_id=normalized_run_id,
                status=status,
                has_raw_capture_manifest=raw_capture_manifest_json is not None,
                has_whole_run_artifact_manifest=whole_run_artifact_manifest_json is not None,
                raw_capture_finalize=raw_capture_finalize,
                has_analysis=analysis is not None,
                analysis_corrupt=analysis_corrupt,
            )
            result.append(
                HistoryRunListEntry(
                    run_id=normalized_run_id,
                    status=status,
                    start_time_utc=normalized_start,
                    end_time_utc=normalized_end,
                    created_at=str(created),
                    sample_count=int(sample_count or 0),
                    car_name=str(car_name) if car_name else None,
                    error_message=str(error) if error else None,
                    lifecycle=lifecycle,
                    artifact_availability=self._artifact_availability(lifecycle=lifecycle),
                    raw_capture_finalize=raw_capture_finalize,
                )
            )
        return result

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
        (
            rid,
            case_id,
            status_raw,
            start,
            end,
            meta_json,
            raw_capture_manifest_json,
            whole_run_artifact_manifest_json,
            analysis_json,
            error,
            created,
            sample_count,
            analysis_started,
            analysis_completed,
        ) = row
        normalized_run_id = str(rid)
        status = RunStatus(status_raw)
        metadata = self._coerce_run_metadata(
            run_id=normalized_run_id,
            start_time_utc=str(start),
            end_time_utc=str(end) if end is not None else None,
            metadata_json=str(meta_json) if meta_json is not None else None,
            source="get_run",
            allow_fallback=True,
        )
        assert metadata is not None
        has_raw_capture_manifest = raw_capture_manifest_json is not None
        raw_capture_manifest = self._coerce_raw_capture_manifest(
            run_id=normalized_run_id,
            manifest_json=str(raw_capture_manifest_json)
            if raw_capture_manifest_json is not None
            else None,
            source="get_run",
        )
        has_whole_run_artifact_manifest = whole_run_artifact_manifest_json is not None
        whole_run_artifact_manifest = self._coerce_whole_run_artifact_manifest(
            run_id=normalized_run_id,
            manifest_json=str(whole_run_artifact_manifest_json)
            if whole_run_artifact_manifest_json is not None
            else None,
            source="get_run",
        )
        analysis, analysis_corrupt = self._coerce_analysis(
            run_id=normalized_run_id,
            analysis_json=str(analysis_json) if analysis_json is not None else None,
            source="get_run",
        )
        lifecycle = self._run_lifecycle(
            run_id=normalized_run_id,
            status=status,
            has_raw_capture_manifest=has_raw_capture_manifest,
            has_whole_run_artifact_manifest=has_whole_run_artifact_manifest,
            raw_capture_finalize=metadata.raw_capture_finalize,
            has_analysis=analysis is not None,
            analysis_corrupt=analysis_corrupt,
        )
        return StoredHistoryRun(
            run_id=normalized_run_id,
            case_id=str(case_id) if case_id is not None else None,
            status=status,
            start_time_utc=str(start),
            end_time_utc=str(end) if end is not None else None,
            metadata=metadata,
            analysis=analysis,
            raw_capture_manifest=raw_capture_manifest,
            whole_run_artifact_manifest=whole_run_artifact_manifest,
            lifecycle=lifecycle,
            artifact_availability=self._artifact_availability(lifecycle=lifecycle),
            raw_capture_finalize=metadata.raw_capture_finalize,
            analysis_corrupt=analysis_corrupt,
            error_message=str(error) if error else None,
            created_at=str(created),
            sample_count=int(sample_count or 0),
            analysis_started_at=str(analysis_started) if analysis_started else None,
            analysis_completed_at=str(analysis_completed) if analysis_completed else None,
        )

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
