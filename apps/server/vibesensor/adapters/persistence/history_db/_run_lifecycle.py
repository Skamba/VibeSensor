"""Run lifecycle and analysis-write helpers for ``HistoryDB``."""

from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import aiosqlite

from vibesensor.adapters.persistence.history_db._samples import V2_INSERT_SQL, sample_to_v2_row
from vibesensor.domain.run_status import RunStatus, is_run_deletable, transition_run
from vibesensor.shared.async_bridge import run_coro_blocking
from vibesensor.shared.boundaries.analysis_payloads import (
    persisted_analysis_to_storage_json_object,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_to_json_object
from vibesensor.shared.json_utils import safe_json_dumps
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame

LOGGER = logging.getLogger(__name__)

_RECOMMENDED_METADATA_KEYS: frozenset[str] = frozenset({"sensor_model", "raw_sample_rate_hz"})
_EXPECTED_ANALYSIS_KEYS: frozenset[str] = frozenset({"findings", "top_causes", "warnings"})


class _HistoryDBRunLifecycleMixin:
    def _cursor(self, *, commit: bool = True) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        raise NotImplementedError

    def write_transaction_cursor(self) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        raise NotImplementedError

    @staticmethod
    async def _run_status(cur: aiosqlite.Cursor, run_id: str) -> str | None:
        await cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
        row = await cur.fetchone()
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
        run_coro_blocking(self.acreate_run(run_id, start_time_utc, metadata, case_id))

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
                "created_at) VALUES (?, ?, 'recording', ?, ?, ?)",
                (run_id, case_id, start_time_utc, safe_json_dumps(metadata_payload), now),
            )

    def append_samples(
        self,
        run_id: str,
        samples: list[SensorFrame],
    ) -> int:
        return run_coro_blocking(self.aappend_samples(run_id, samples))

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

    def finalize_run(
        self,
        run_id: str,
        end_time_utc: str,
        metadata: RunMetadata | None = None,
        case_id: str | None = None,
    ) -> bool:
        return run_coro_blocking(self.afinalize_run(run_id, end_time_utc, metadata, case_id))

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
                assignments.insert(0, "metadata_json = ?")
                params.insert(0, safe_json_dumps(run_metadata_to_json_object(metadata)))
            if case_id is not None:
                assignments.insert(0, "case_id = ?")
                params.insert(0, case_id)
            params.append(run_id)
            await cur.execute(
                f"UPDATE runs SET {', '.join(assignments)} WHERE run_id = ?",
                params,
            )
            return int(cur.rowcount) > 0

    def update_run_metadata(
        self,
        run_id: str,
        metadata: RunMetadata,
    ) -> bool:
        return run_coro_blocking(self.aupdate_run_metadata(run_id, metadata))

    async def aupdate_run_metadata(
        self,
        run_id: str,
        metadata: RunMetadata,
    ) -> bool:
        async with self._cursor() as cur:
            await cur.execute(
                "UPDATE runs SET metadata_json = ? WHERE run_id = ?",
                (safe_json_dumps(run_metadata_to_json_object(metadata)), run_id),
            )
            return bool(int(cur.rowcount) > 0)

    def delete_run_if_safe(
        self,
        run_id: str,
    ) -> tuple[bool, str | None]:
        return run_coro_blocking(self.adelete_run_if_safe(run_id))

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
            return bool(int(cur.rowcount) > 0), None

    def store_analysis(
        self,
        run_id: str,
        analysis: PersistedAnalysis,
    ) -> bool:
        return run_coro_blocking(self.astore_analysis(run_id, analysis))

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
        return run_coro_blocking(self.astore_analysis_error(run_id, error))

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
        return run_coro_blocking(self.adelete_run(run_id))

    async def adelete_run(self, run_id: str) -> bool:
        async with self._cursor() as cur:
            await cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return bool(int(cur.rowcount) > 0)

    def recover_stale_recording_runs(self) -> int:
        return run_coro_blocking(self.arecover_stale_recording_runs())

    async def arecover_stale_recording_runs(self) -> int:
        now = utc_now_iso()
        async with self._cursor() as cur:
            await cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE status = 'recording'",
                (f"Recovered stale recording during startup at {now}",),
            )
            return int(cur.rowcount)

    def prune_terminal_runs_older_than_days(self, retention_days: int) -> int:
        return run_coro_blocking(self.aprune_terminal_runs_older_than_days(retention_days))

    async def aprune_terminal_runs_older_than_days(self, retention_days: int) -> int:
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        cutoff_utc = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        async with self._cursor() as cur:
            await cur.execute(
                """
                DELETE FROM runs
                WHERE status IN ('complete', 'error')
                  AND COALESCE(analysis_completed_at, end_time_utc, created_at) < ?
                """,
                (cutoff_utc,),
            )
            return int(cur.rowcount)


def _has_recommended_metadata_value(key: str, value: object) -> bool:
    if key == "sensor_model":
        text = str(value or "").strip().lower()
        return bool(text and text != "unknown")
    return value is not None
