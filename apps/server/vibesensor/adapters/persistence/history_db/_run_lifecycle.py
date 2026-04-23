"""Run lifecycle and analysis-write helpers for ``HistoryDB``."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import TypeVar, cast

import aiosqlite

from vibesensor.adapters.persistence.history_db._raw_capture_store import (
    HistoryRawCaptureStore,
)
from vibesensor.adapters.persistence.history_db._samples import V2_INSERT_SQL, sample_to_v2_row
from vibesensor.adapters.persistence.history_db._whole_run_artifact_store import (
    HistoryWholeRunArtifactStore,
)
from vibesensor.domain.run_status import RunStatus, is_run_deletable, transition_run
from vibesensor.shared.boundaries.analysis_payloads import (
    persisted_analysis_to_storage_json_object,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_to_json_object
from vibesensor.shared.json_utils import safe_json_dumps
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.raw_capture import RawCaptureChunk, RawCaptureManifest
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest

LOGGER = logging.getLogger(__name__)

_RECOMMENDED_METADATA_KEYS: frozenset[str] = frozenset({"sensor_model", "raw_sample_rate_hz"})
_EXPECTED_ANALYSIS_KEYS: frozenset[str] = frozenset({"findings", "top_causes", "warnings"})

_T = TypeVar("_T")


class _HistoryDBRunLifecycleMixin:
    _raw_capture_store: HistoryRawCaptureStore
    _whole_run_artifact_store: HistoryWholeRunArtifactStore

    def _cursor(self, *, commit: bool = True) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        raise NotImplementedError

    def write_transaction_cursor(self) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        raise NotImplementedError

    def _run_sync(self, coro: Awaitable[_T]) -> _T:
        raise NotImplementedError

    @staticmethod
    async def _run_status(cur: aiosqlite.Cursor, run_id: str) -> str | None:
        await cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
        row = await cur.fetchone()
        if row is None:
            return None
        return str(row[0])

    @staticmethod
    def _car_name_from_metadata(metadata: RunMetadata) -> str | None:
        return metadata.car_name

    def create_run(
        self,
        run_id: str,
        start_time_utc: str,
        metadata: RunMetadata,
        case_id: str | None = None,
    ) -> None:
        self._run_sync(self.acreate_run(run_id, start_time_utc, metadata, case_id))

    async def acreate_run(
        self,
        run_id: str,
        start_time_utc: str,
        metadata: RunMetadata,
        case_id: str | None = None,
    ) -> None:
        metadata_payload = run_metadata_to_json_object(metadata)
        missing = {
            key
            for key in _RECOMMENDED_METADATA_KEYS
            if not _has_recommended_metadata_value(key, metadata_payload.get(key))
        }
        if missing:
            LOGGER.warning(
                "create_run %s: metadata missing recommended keys: %s",
                run_id,
                ", ".join(sorted(missing)),
            )
        now = utc_now_iso()
        async with self._cursor() as cur:
            await cur.execute(
                "INSERT INTO runs (run_id, case_id, status, start_time_utc, metadata_json, "
                "car_name, created_at) VALUES (?, ?, 'recording', ?, ?, ?, ?)",
                (
                    run_id,
                    case_id,
                    start_time_utc,
                    safe_json_dumps(metadata_payload),
                    self._car_name_from_metadata(metadata),
                    now,
                ),
            )

    def append_samples(self, run_id: str, samples: list[SensorFrame]) -> int:
        return self._run_sync(self.aappend_samples(run_id, samples))

    async def aappend_samples(
        self,
        run_id: str,
        samples: list[SensorFrame],
    ) -> int:
        if not samples:
            return 0
        if not run_id or not run_id.strip():
            raise ValueError("append_samples: run_id must be a non-empty string")

        chunk_size = 256
        async with self.write_transaction_cursor() as cur:
            current_status = await self._run_status(cur, run_id)
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
                await cur.executemany(
                    V2_INSERT_SQL,
                    [sample_to_v2_row(run_id, sample) for sample in batch],
                )
            await cur.execute(
                "UPDATE runs SET sample_count = sample_count + ? "
                "WHERE run_id = ? AND status = 'recording'",
                (len(samples), run_id),
            )
            if int(cur.rowcount) <= 0:
                raise aiosqlite.IntegrityError(
                    f"append_samples: run {run_id} left recording during append",
                )
            return len(samples)

    async def aappend_raw_capture_chunk(self, run_id: str, chunk: RawCaptureChunk) -> None:
        await asyncio.to_thread(self._raw_capture_store.append_chunk, run_id, chunk)

    async def afinalize_raw_capture(self, run_id: str) -> RawCaptureManifest | None:
        manifest = cast(
            RawCaptureManifest | None,
            await asyncio.to_thread(self._raw_capture_store.finalize_run, run_id),
        )
        if manifest is None:
            return None
        async with self._cursor() as cur:
            await cur.execute(
                "UPDATE runs SET raw_capture_manifest_json = ? WHERE run_id = ?",
                (safe_json_dumps(manifest.to_json_object()), run_id),
            )
            if int(cur.rowcount) <= 0:
                await asyncio.to_thread(self._raw_capture_store.delete_run_artifacts, run_id)
                return None
        return manifest

    async def astore_whole_run_artifacts(
        self,
        run_id: str,
        manifest: WholeRunArtifactManifest,
        *,
        artifact_contents: dict[str, bytes],
    ) -> WholeRunArtifactManifest | None:
        if manifest.run_id != run_id:
            raise ValueError("whole-run artifact manifest run_id does not match persistence target")
        stored_manifest = cast(
            WholeRunArtifactManifest,
            await asyncio.to_thread(
                self._whole_run_artifact_store.store_run,
                manifest,
                artifact_contents=artifact_contents,
            ),
        )
        async with self._cursor() as cur:
            await cur.execute(
                "UPDATE runs SET whole_run_artifact_manifest_json = ? WHERE run_id = ?",
                (safe_json_dumps(stored_manifest.to_json_object()), run_id),
            )
            if int(cur.rowcount) <= 0:
                await asyncio.to_thread(
                    self._whole_run_artifact_store.delete_run_artifacts,
                    run_id,
                )
                return None
        return stored_manifest

    def finalize_run(
        self,
        run_id: str,
        end_time_utc: str,
        metadata: RunMetadata | None = None,
        case_id: str | None = None,
    ) -> bool:
        return self._run_sync(self.afinalize_run(run_id, end_time_utc, metadata, case_id))

    async def afinalize_run(
        self,
        run_id: str,
        end_time_utc: str,
        metadata: RunMetadata | None = None,
        case_id: str | None = None,
    ) -> bool:
        now = utc_now_iso()
        async with self._cursor() as cur:
            current_status = await self._run_status(cur, run_id)
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
                assignments[0:0] = ["metadata_json = ?", "car_name = ?"]
                params[0:0] = [
                    safe_json_dumps(run_metadata_to_json_object(metadata)),
                    self._car_name_from_metadata(metadata),
                ]
            if case_id is not None:
                assignments.insert(0, "case_id = ?")
                params.insert(0, case_id)
            params.append(run_id)
            await cur.execute(
                f"UPDATE runs SET {', '.join(assignments)} WHERE run_id = ?",
                params,
            )
            return int(cur.rowcount) > 0

    def update_run_metadata(self, run_id: str, metadata: RunMetadata) -> bool:
        return self._run_sync(self.aupdate_run_metadata(run_id, metadata))

    async def aupdate_run_metadata(
        self,
        run_id: str,
        metadata: RunMetadata,
    ) -> bool:
        async with self._cursor() as cur:
            await cur.execute(
                "UPDATE runs SET metadata_json = ?, car_name = ? WHERE run_id = ?",
                (
                    safe_json_dumps(run_metadata_to_json_object(metadata)),
                    self._car_name_from_metadata(metadata),
                    run_id,
                ),
            )
            return bool(int(cur.rowcount) > 0)

    def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
        return self._run_sync(self.adelete_run_if_safe(run_id))

    async def adelete_run_if_safe(
        self,
        run_id: str,
    ) -> tuple[bool, str | None]:
        async with self._cursor() as cur:
            await cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
            row = await cur.fetchone()
            if row is None:
                return False, "not_found"
            status = RunStatus(row[0])
            if not is_run_deletable(status):
                return False, "active" if status == RunStatus.RECORDING else status.value
            await cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            deleted = bool(int(cur.rowcount) > 0)
        if deleted:
            await asyncio.to_thread(self._raw_capture_store.delete_run_artifacts, run_id)
            await asyncio.to_thread(self._whole_run_artifact_store.delete_run_artifacts, run_id)
        return deleted, None

    def store_analysis(self, run_id: str, analysis: PersistedAnalysis) -> bool:
        return self._run_sync(self.astore_analysis(run_id, analysis))

    async def astore_analysis(
        self,
        run_id: str,
        analysis: PersistedAnalysis,
    ) -> bool:
        analysis_payload = analysis.payload
        missing = _EXPECTED_ANALYSIS_KEYS - analysis_payload.keys()
        if missing:
            LOGGER.warning(
                "store_analysis %s: persisted analysis missing expected keys: %s",
                run_id,
                ", ".join(sorted(missing)),
            )
        now = utc_now_iso()
        async with self._cursor() as cur:
            current_status = await self._run_status(cur, run_id)
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
            await cur.execute(
                "UPDATE runs SET status = 'complete', analysis_json = ?, "
                "analysis_completed_at = ?, end_time_utc = COALESCE(end_time_utc, ?) "
                "WHERE run_id = ?",
                (
                    safe_json_dumps(persisted_analysis_to_storage_json_object(analysis)),
                    now,
                    now,
                    run_id,
                ),
            )
            return int(cur.rowcount) > 0

    def store_analysis_error(self, run_id: str, error: str) -> bool:
        return self._run_sync(self.astore_analysis_error(run_id, error))

    async def astore_analysis_error(self, run_id: str, error: str) -> bool:
        now = utc_now_iso()
        async with self._cursor() as cur:
            current_status = await self._run_status(cur, run_id)
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
            await cur.execute(
                "UPDATE runs SET status = 'error', error_message = ?, "
                "analysis_completed_at = ?, end_time_utc = COALESCE(end_time_utc, ?) "
                "WHERE run_id = ?",
                (error, now, now, run_id),
            )
            return int(cur.rowcount) > 0

    def delete_run(self, run_id: str) -> bool:
        return self._run_sync(self.adelete_run(run_id))

    async def adelete_run(self, run_id: str) -> bool:
        async with self._cursor() as cur:
            await cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            deleted = bool(int(cur.rowcount) > 0)
        if deleted:
            await asyncio.to_thread(self._raw_capture_store.delete_run_artifacts, run_id)
            await asyncio.to_thread(self._whole_run_artifact_store.delete_run_artifacts, run_id)
        return deleted

    def recover_stale_recording_runs(self) -> int:
        return self._run_sync(self.arecover_stale_recording_runs())

    async def arecover_stale_recording_runs(self) -> int:
        now = utc_now_iso()
        async with self._cursor() as cur:
            await cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE status = 'recording'",
                (f"Recovered stale recording during startup at {now}",),
            )
            return int(cur.rowcount)

    def prune_terminal_runs_older_than_days(self, retention_days: int) -> int:
        return self._run_sync(self.aprune_terminal_runs_older_than_days(retention_days))

    async def aprune_terminal_runs_older_than_days(self, retention_days: int) -> int:
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        cutoff_utc = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        async with self.write_transaction_cursor() as cur:
            await cur.execute(
                """
                SELECT run_id FROM runs
                WHERE status IN ('complete', 'error')
                  AND COALESCE(analysis_completed_at, end_time_utc, created_at) < ?
                """,
                (cutoff_utc,),
            )
            run_ids = [str(row[0]) for row in await cur.fetchall()]
            if not run_ids:
                return 0
            await cur.executemany(
                "DELETE FROM runs WHERE run_id = ?",
                [(run_id,) for run_id in run_ids],
            )
        for run_id in run_ids:
            await asyncio.to_thread(self._raw_capture_store.delete_run_artifacts, run_id)
            await asyncio.to_thread(self._whole_run_artifact_store.delete_run_artifacts, run_id)
        return len(run_ids)


def _has_recommended_metadata_value(key: str, value: object) -> bool:
    if key == "sensor_model":
        text = str(value or "").strip().lower()
        return bool(text and text != "unknown")
    return value is not None
