"""Synchronous SQLite history repository: runs, samples, settings, and client names.

One process, a few threads. A writer connection and a ``query_only`` reader
connection (WAL lets reads proceed during a write) are each guarded by a
``threading.Lock``. Async callers offload calls with ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vibesensor.common.json_utils import safe_json_dumps
from vibesensor.common.time_utils import utc_now_iso
from vibesensor.domain.run_status import RunStatus, is_run_deletable, transition_run
from vibesensor.history.db_projection import (
    coerce_raw_capture_manifest,
    coerce_run_metadata,
    project_run_list_entry,
    project_stored_run,
)
from vibesensor.history.db_schema import (
    ensure_schema,
    quick_check_problems,
)
from vibesensor.history.raw_capture_store import (
    HistoryRawCaptureStore,
)
from vibesensor.history.records import (
    AnalyzingRunHealth,
    HistoryRunListEntry,
    StoredHistoryRun,
)
from vibesensor.history.run_clock_correction import StoredRunTimes, correct_run_times
from vibesensor.history.sample_store import (
    SELECTION_SELECT_SQL_COLS,
    V2_INSERT_SQL,
    V2_SELECT_SQL_COLS,
    SampleSelectionColumns,
    sample_to_v2_row,
    selection_row_values,
    v2_row_to_sensor_frame,
)
from vibesensor.recording.raw_capture import (
    RawCaptureChunk,
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawRunCapture,
)
from vibesensor.recording.run_metadata import run_metadata_to_json_object
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.recording.sensor_frame_values import SensorFrameDecodeError
from vibesensor.settings.settings_snapshot import SettingsSnapshotPayload
from vibesensor.settings.snapshot_codec import (
    settings_snapshot_from_json,
    settings_snapshot_to_json,
)
from vibesensor.summary.persisted_analysis import (
    PERSISTED_ANALYSIS_SCHEMA_VERSION,
    STORAGE_SCHEMA_VERSION_KEY,
    PersistedAnalysis,
)
from vibesensor.summary.persisted_codec import (
    persisted_analysis_to_storage_json_object,
)

LOGGER = logging.getLogger(__name__)

__all__ = ["HistoryDB"]

_RECOMMENDED_METADATA_KEYS: frozenset[str] = frozenset({"sensor_model", "raw_sample_rate_hz"})
_EXPECTED_ANALYSIS_KEYS: frozenset[str] = frozenset({"findings", "top_causes", "warnings"})
_APPEND_CHUNK_SIZE = 256
_RUN_LIST_COLUMNS = (
    "r.run_id, r.status, r.start_time_utc, r.end_time_utc, "
    "r.created_at, r.error_message, r.sample_count, r.car_name, "
    "r.metadata_json, r.analysis_json, r.raw_capture_manifest_json"
)
_STORED_RUN_COLUMNS = (
    "run_id, case_id, status, start_time_utc, end_time_utc, "
    "metadata_json, raw_capture_manifest_json, "
    "analysis_json, error_message, created_at, "
    "sample_count, analysis_started_at, analysis_completed_at"
)


class HistoryDB:
    """Own the history SQLite file plus the raw-capture sidecar files.

    Constructing it opens the database, enforces the current schema (backing up and
    rejecting incompatible files), and runs ``PRAGMA quick_check``. If corruption is
    found, reads stay available and every write raises ``sqlite3.DatabaseError``.
    """

    __slots__ = (
        "db_path",
        "_conn",
        "_corruption_details",
        "_corruption_reporter",
        "_raw_capture_store",
        "_read_conn",
        "_read_lock",
        "_write_lock",
    )

    def __init__(
        self,
        db_path: Path,
        *,
        corruption_reporter: Callable[[str], None] | None = None,
    ) -> None:
        self.db_path = db_path
        self._corruption_reporter = corruption_reporter
        self._corruption_details: str | None = None
        self._write_lock = threading.Lock()
        self._read_lock = threading.Lock()
        self._raw_capture_store = HistoryRawCaptureStore(data_dir=db_path.parent)
        # Whole-run sidecars are no longer produced; drop any left by older versions.
        shutil.rmtree(db_path.parent / "whole-run-artifacts", ignore_errors=True)
        self._conn: sqlite3.Connection | None = None
        self._read_conn: sqlite3.Connection | None = None
        self._open()

    # -- connection lifecycle -------------------------------------------------

    def _connect(self, *, read_only: bool) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        if not read_only:
            conn.execute("PRAGMA wal_autocheckpoint=500")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        if read_only:
            conn.execute("PRAGMA query_only=ON")
        return conn

    def _open(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect(read_only=False)
        read_conn: sqlite3.Connection | None = None
        try:
            ensure_schema(conn, self.db_path)
            self._run_startup_quick_check(conn)
            if str(self.db_path) != ":memory:":
                read_conn = self._connect(read_only=True)
        except BaseException:
            if read_conn is not None:
                read_conn.close()
            conn.close()
            raise
        self._conn = conn
        self._read_conn = read_conn

    def _run_startup_quick_check(self, conn: sqlite3.Connection) -> None:
        try:
            problems = quick_check_problems(conn)
        except sqlite3.Error:
            LOGGER.critical(
                "History DB quick_check failed during startup for %s",
                self.db_path,
                exc_info=True,
            )
            raise
        if problems:
            details = "; ".join(problems)
            self._corruption_details = details
            if self._corruption_reporter is not None:
                self._corruption_reporter(details)
            LOGGER.critical(
                "History DB quick_check reported corruption for %s: %s",
                self.db_path,
                details,
            )

    def close(self) -> None:
        with self._write_lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
        with self._read_lock:
            if self._read_conn is not None:
                self._read_conn.close()
                self._read_conn = None

    @property
    def corruption_detected(self) -> bool:
        return self._corruption_details is not None

    def _assert_write_allowed(self) -> None:
        if self._corruption_details is None:
            return
        raise sqlite3.DatabaseError(
            "History DB quick_check reported corruption for "
            f"{self.db_path}: {self._corruption_details}. Writes are disabled until "
            "the database is repaired or replaced."
        )

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Cursor]:
        """Cursor on the reader connection (the writer when the DB is in-memory)."""
        use_reader = self._read_conn is not None
        lock = self._read_lock if use_reader else self._write_lock
        with lock:
            conn = self._read_conn if use_reader else self._conn
            if conn is None:
                raise RuntimeError("HistoryDB is closed")
            cur = conn.cursor()
            try:
                yield cur
            finally:
                cur.close()
                _rollback_open_transaction(conn, context="read")

    @contextmanager
    def _write(self, *, immediate: bool = False) -> Iterator[sqlite3.Cursor]:
        """Writer cursor committed on success and rolled back on any exception.

        ``immediate=True`` takes the write lock up front with ``BEGIN IMMEDIATE`` for
        multi-statement sequences that must read and write one consistent state.
        """
        with self._write_lock:
            conn = self._conn
            if conn is None:
                raise RuntimeError("HistoryDB is closed")
            self._assert_write_allowed()
            cur = conn.cursor()
            completed = False
            try:
                if immediate:
                    cur.execute("BEGIN IMMEDIATE")
                yield cur
                conn.commit()
                completed = True
            finally:
                if not completed:
                    _rollback_open_transaction(conn, context="write")
                cur.close()

    # -- run lifecycle writes -------------------------------------------------

    def create_run(
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
        with self._write() as cur:
            cur.execute(
                "INSERT INTO runs (run_id, case_id, status, start_time_utc, metadata_json, "
                "car_name, created_at) VALUES (?, ?, 'recording', ?, ?, ?, ?)",
                (
                    run_id,
                    case_id,
                    start_time_utc,
                    safe_json_dumps(metadata_payload),
                    metadata.car_name,
                    utc_now_iso(),
                ),
            )

    def append_samples(self, run_id: str, samples: list[SensorFrame]) -> int:
        if not samples:
            return 0
        if not run_id or not run_id.strip():
            raise ValueError("append_samples: run_id must be a non-empty string")
        with self._write(immediate=True) as cur:
            current_status = _run_status(cur, run_id)
            if current_status != RunStatus.RECORDING.value:
                LOGGER.warning(
                    "append_samples for run %s: rejected %d sample(s) because status is %s",
                    run_id,
                    len(samples),
                    current_status or "missing",
                )
                return 0
            for start in range(0, len(samples), _APPEND_CHUNK_SIZE):
                batch = samples[start : start + _APPEND_CHUNK_SIZE]
                cur.executemany(V2_INSERT_SQL, [sample_to_v2_row(run_id, s) for s in batch])
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

    def append_raw_capture_chunk(self, run_id: str, chunk: RawCaptureChunk) -> None:
        self._raw_capture_store.append_chunk(run_id, chunk)

    def finalize_raw_capture(
        self,
        run_id: str,
        *,
        run_start_monotonic_us: int | None = None,
        sensor_clock_sync: Mapping[str, RawCaptureSensorClockSync] | None = None,
        sensor_losses: Mapping[str, RawCaptureLossStats] | None = None,
    ) -> RawCaptureManifest | None:
        manifest = self._raw_capture_store.finalize_run(
            run_id,
            run_start_monotonic_us=run_start_monotonic_us,
            sensor_clock_sync=sensor_clock_sync,
            sensor_losses=sensor_losses,
        )
        if manifest is None:
            return None
        with self._write() as cur:
            cur.execute(
                "UPDATE runs SET raw_capture_manifest_json = ? WHERE run_id = ?",
                (safe_json_dumps(manifest.to_json_object()), run_id),
            )
            updated = int(cur.rowcount) > 0
        if not updated:
            self._raw_capture_store.delete_run_artifacts(run_id)
            return None
        return manifest

    def finalize_run(
        self,
        run_id: str,
        end_time_utc: str,
        metadata: RunMetadata | None = None,
        case_id: str | None = None,
    ) -> bool:
        now = utc_now_iso()
        with self._write() as cur:
            current_status = _run_status(cur, run_id)
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
                    metadata.car_name,
                ]
            if case_id is not None:
                assignments.insert(0, "case_id = ?")
                params.insert(0, case_id)
            params.append(run_id)
            cur.execute(f"UPDATE runs SET {', '.join(assignments)} WHERE run_id = ?", params)
            return int(cur.rowcount) > 0

    def update_run_metadata(self, run_id: str, metadata: RunMetadata) -> bool:
        with self._write() as cur:
            cur.execute(
                "UPDATE runs SET metadata_json = ?, car_name = ? WHERE run_id = ?",
                (
                    safe_json_dumps(run_metadata_to_json_object(metadata)),
                    metadata.car_name,
                    run_id,
                ),
            )
            return int(cur.rowcount) > 0

    def store_analysis(self, run_id: str, analysis: PersistedAnalysis) -> bool:
        missing = _EXPECTED_ANALYSIS_KEYS - analysis.payload.keys()
        if missing:
            LOGGER.warning(
                "store_analysis %s: persisted analysis missing expected keys: %s",
                run_id,
                ", ".join(sorted(missing)),
            )
        now = utc_now_iso()
        with self._write() as cur:
            current_status = _run_status(cur, run_id)
            if current_status == RunStatus.COMPLETE:
                LOGGER.warning("store_analysis for run %s: skipped — already complete", run_id)
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
            cur.execute("DELETE FROM analysis_attempts WHERE run_id = ?", (run_id,))
            cur.execute(
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

    def begin_analysis_attempt(self, run_id: str) -> int:
        """Count one more started analysis of an ``analyzing`` run and return the count.

        The count survives a server restart and is cleared when the analysis or its
        error is stored, so it counts the attempts that never finished. Returns 0
        when the run is not ``analyzing``.
        """
        with self._write() as cur:
            cur.execute(
                "INSERT INTO analysis_attempts (run_id, attempt_count) "
                "SELECT run_id, 1 FROM runs WHERE run_id = ? AND status = 'analyzing' "
                "ON CONFLICT (run_id) DO UPDATE SET attempt_count = attempt_count + 1 "
                "RETURNING attempt_count",
                (run_id,),
            )
            rows = cur.fetchall()
        return int(rows[0][0]) if rows else 0

    def store_analysis_error(self, run_id: str, error: str) -> bool:
        now = utc_now_iso()
        with self._write() as cur:
            current_status = _run_status(cur, run_id)
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
            cur.execute("DELETE FROM analysis_attempts WHERE run_id = ?", (run_id,))
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ?, "
                "analysis_completed_at = ?, end_time_utc = COALESCE(end_time_utc, ?) "
                "WHERE run_id = ?",
                (error, now, now, run_id),
            )
            return int(cur.rowcount) > 0

    def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
        """Delete a terminal run and its sidecars; return ``(deleted, refusal_reason)``."""
        with self._write() as cur:
            status_raw = _run_status(cur, run_id)
            if status_raw is None:
                return False, "not_found"
            status = RunStatus(status_raw)
            if not is_run_deletable(status):
                return False, "active" if status == RunStatus.RECORDING else status.value
            cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            deleted = int(cur.rowcount) > 0
        if deleted:
            self._raw_capture_store.delete_run_artifacts(run_id)
        return deleted, None

    def recover_stale_recording_runs(self) -> int:
        with self._write() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE status = 'recording'",
                (f"Recovered stale recording during startup at {utc_now_iso()}",),
            )
            return int(cur.rowcount)

    def prune_terminal_runs_older_than_days(self, retention_days: int) -> int:
        run_ids = self._terminal_run_ids_older_than(_retention_cutoff_utc(retention_days))
        if not run_ids:
            return 0
        LOGGER.warning(
            "Pruning %d terminal run(s) older than %d day(s) during startup retention maintenance",
            len(run_ids),
            retention_days,
        )
        with self._write(immediate=True) as cur:
            cur.executemany("DELETE FROM runs WHERE run_id = ?", [(run_id,) for run_id in run_ids])
        for run_id in run_ids:
            self._raw_capture_store.delete_run_artifacts(run_id)
        return len(run_ids)

    def _terminal_run_ids_older_than(self, cutoff_utc: str) -> list[str]:
        with self._read() as cur:
            cur.execute(
                "SELECT run_id FROM runs WHERE status IN ('complete', 'error') "
                "AND COALESCE(analysis_completed_at, end_time_utc, created_at) < ?",
                (cutoff_utc,),
            )
            return [str(row[0]) for row in cur.fetchall()]

    # -- run queries ----------------------------------------------------------

    def list_runs(self, limit: int = 500) -> list[HistoryRunListEntry]:
        """Newest runs first; ``limit <= 0`` returns every run."""
        with self._read() as cur:
            if limit > 0:
                cur.execute(
                    f"SELECT {_RUN_LIST_COLUMNS} FROM runs r ORDER BY r.created_at DESC LIMIT ?",
                    (limit,),
                )
            else:
                cur.execute(f"SELECT {_RUN_LIST_COLUMNS} FROM runs r ORDER BY r.created_at DESC")
            rows = cur.fetchall()
        return [
            project_run_list_entry(
                row,
                raw_capture_store=self._raw_capture_store,
            )
            for row in rows
        ]

    def get_run(self, run_id: str) -> StoredHistoryRun | None:
        with self._read() as cur:
            cur.execute(f"SELECT {_STORED_RUN_COLUMNS} FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        if row is None:
            return None
        return project_stored_run(
            row,
            raw_capture_store=self._raw_capture_store,
        )

    def get_run_metadata(self, run_id: str) -> RunMetadata | None:
        with self._read() as cur:
            cur.execute(
                "SELECT start_time_utc, end_time_utc, metadata_json FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        start_time_utc, end_time_utc, metadata_json = row
        return coerce_run_metadata(
            run_id=run_id,
            start_time_utc=str(start_time_utc),
            end_time_utc=str(end_time_utc) if end_time_utc is not None else None,
            metadata_json=str(metadata_json) if metadata_json is not None else None,
            source="get_run_metadata",
            allow_fallback=False,
        )

    def get_raw_capture_manifest(self, run_id: str) -> RawCaptureManifest | None:
        with self._read() as cur:
            cur.execute("SELECT raw_capture_manifest_json FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        return coerce_raw_capture_manifest(
            run_id=run_id,
            manifest_json=str(row[0]),
            source="get_raw_capture_manifest",
        )

    def load_raw_capture(self, run_id: str) -> RawRunCapture | None:
        manifest = self.get_raw_capture_manifest(run_id)
        if manifest is None or not self._raw_capture_store.has_run_artifacts(run_id):
            return None
        return self._raw_capture_store.load_capture(manifest)

    def raw_capture_files(self, run_id: str) -> tuple[Path, ...]:
        """The run's raw capture on disk: its manifest plus each sensor's data and index.

        Empty when the run recorded no raw capture or its files were pruned.
        """
        manifest = self.get_raw_capture_manifest(run_id)
        if manifest is None:
            return ()
        return self._raw_capture_store.artifact_files(manifest)

    def requeue_outdated_analyses(self) -> list[str]:
        """Send complete runs analysed under an older schema back to analysis.

        Their stored analysis lacks fields the UI and the report now require, so
        it is cleared and the run returns to ``analyzing``; startup re-queues
        analyzing runs. Returns the affected run ids.
        """
        now = utc_now_iso()
        with self._write() as cur:
            cur.execute(
                "SELECT run_id FROM runs WHERE status = 'complete' "
                "AND analysis_json IS NOT NULL "
                f"AND COALESCE(json_extract(analysis_json, '$.{STORAGE_SCHEMA_VERSION_KEY}'), 0)"
                " != ?",
                (PERSISTED_ANALYSIS_SCHEMA_VERSION,),
            )
            run_ids = [str(row[0]) for row in cur.fetchall()]
            cur.executemany(
                "UPDATE runs SET status = 'analyzing', analysis_json = NULL, "
                "analysis_started_at = ?, analysis_completed_at = NULL WHERE run_id = ?",
                [(now, run_id) for run_id in run_ids],
            )
        return run_ids

    def correct_unverified_run_times(
        self,
        *,
        boot_id: str,
        wall_now_s: float,
        monotonic_now_s: float,
        time_zone: str | None,
    ) -> list[str]:
        """Re-date finished runs that started on an unset clock earlier in this boot.

        See ``run_clock_correction``; *time_zone* is the browser's, for the
        fallback UTC offset. Recording and analyzing runs are left for later:
        their metadata and analysis are still being written. Returns the
        corrected run ids.
        """
        with self._write(immediate=True) as cur:
            cur.execute(
                "SELECT run_id, start_time_utc, end_time_utc, created_at, analysis_started_at, "
                "analysis_completed_at, metadata_json, analysis_json "
                "FROM runs WHERE status IN (?, ?) AND metadata_json LIKE ?",
                (RunStatus.COMPLETE, RunStatus.ERROR, '%"start_clock"%'),
            )
            stored = [
                StoredRunTimes(
                    run_id=str(run_id),
                    start_time_utc=str(start),
                    end_time_utc=_str_or_none(end),
                    created_at=str(created_at),
                    analysis_started_at=_str_or_none(analysis_started_at),
                    analysis_completed_at=_str_or_none(analysis_completed_at),
                    metadata_json=str(metadata_json),
                    analysis_json=_str_or_none(analysis_json),
                )
                for (
                    run_id,
                    start,
                    end,
                    created_at,
                    analysis_started_at,
                    analysis_completed_at,
                    metadata_json,
                    analysis_json,
                ) in cur.fetchall()
            ]
            corrected: list[str] = []
            for run in stored:
                times = correct_run_times(
                    run,
                    boot_id=boot_id,
                    wall_now_s=wall_now_s,
                    monotonic_now_s=monotonic_now_s,
                    time_zone=time_zone,
                )
                if times is None:
                    continue
                cur.execute(
                    "UPDATE runs SET start_time_utc = ?, end_time_utc = ?, created_at = ?, "
                    "analysis_started_at = ?, analysis_completed_at = ?, metadata_json = ?, "
                    "analysis_json = ? WHERE run_id = ?",
                    (
                        times.start_time_utc,
                        times.end_time_utc,
                        times.created_at,
                        times.analysis_started_at,
                        times.analysis_completed_at,
                        times.metadata_json,
                        times.analysis_json,
                        run.run_id,
                    ),
                )
                corrected.append(run.run_id)
        return corrected

    def stale_analyzing_run_ids(self) -> list[str]:
        with self._read() as cur:
            cur.execute(
                "SELECT run_id FROM runs WHERE status = 'analyzing' "
                "ORDER BY created_at ASC LIMIT 1000",
            )
            return [str(row[0]) for row in cur.fetchall()]

    def analyzing_run_health(self) -> AnalyzingRunHealth:
        with self._read() as cur:
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
                oldest_age_s = max(0.0, (datetime.now(UTC) - started).total_seconds())
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

    def iter_run_samples(self, run_id: str, batch_size: int = 1000) -> Iterator[list[SensorFrame]]:
        """Yield a run's samples in id order, one keyset-paginated batch per read.

        Corrupt rows are skipped and logged; the read lock is released between batches.
        """
        size = max(1, batch_size)
        last_id = 0
        total_skipped = 0
        while True:
            with self._read() as cur:
                cur.execute(
                    f"SELECT {V2_SELECT_SQL_COLS} FROM samples_v2"
                    " WHERE run_id = ? AND id > ? ORDER BY id LIMIT ?",
                    (run_id, last_id, size),
                )
                rows = [tuple(row) for row in cur.fetchall()]
            if not rows:
                if total_skipped:
                    LOGGER.warning(
                        "run_id=%s: skipped %d corrupt v2 sample row(s) in total",
                        run_id,
                        total_skipped,
                    )
                return
            last_id = int(rows[-1][0])
            batch: list[SensorFrame] = []
            for row in rows:
                try:
                    batch.append(v2_row_to_sensor_frame(row))
                except SensorFrameDecodeError as exc:
                    total_skipped += 1
                    LOGGER.warning("Skipping corrupt v2 sample row id=%s: %s", row[0], exc)
            if batch:
                yield batch

    def run_sample_selection_columns(
        self,
        run_id: str,
        batch_size: int = 4096,
    ) -> SampleSelectionColumns:
        """Decode only the columns that pick post-analysis rows, for every run row.

        A light pass over a long run: no :class:`SensorFrame` is built, so memory
        stays a few numbers per row. Rows whose selection columns are corrupt are
        skipped and logged, like :meth:`iter_run_samples` skips corrupt rows.
        """
        size = max(1, batch_size)
        last_id = 0
        skipped = 0
        parts: list[SampleSelectionColumns] = []
        while True:
            with self._read() as cur:
                cur.execute(
                    f"SELECT {SELECTION_SELECT_SQL_COLS} FROM samples_v2"
                    " WHERE run_id = ? AND id > ? ORDER BY id LIMIT ?",
                    (run_id, last_id, size),
                )
                rows = cur.fetchall()
            if not rows:
                break
            last_id = int(rows[-1][0])
            decoded: list[tuple[int, float, float, float, float]] = []
            for row in rows:
                try:
                    decoded.append(selection_row_values(row))
                except SensorFrameDecodeError as exc:
                    skipped += 1
                    LOGGER.warning("Skipping corrupt v2 sample row id=%s: %s", row[0], exc)
            parts.append(SampleSelectionColumns.from_rows(decoded))
        if skipped:
            LOGGER.warning(
                "run_id=%s: skipped %d corrupt v2 sample row(s) in total", run_id, skipped
            )
        return SampleSelectionColumns.concatenate(parts)

    def load_run_samples_by_id(
        self,
        run_id: str,
        row_ids: Sequence[int],
        batch_size: int = 500,
    ) -> list[SensorFrame]:
        """Decode the given ``samples_v2`` rows (ascending ids) in id order.

        Corrupt rows are skipped and logged; the read lock is released between batches.
        """
        size = max(1, batch_size)
        frames: list[SensorFrame] = []
        for offset in range(0, len(row_ids), size):
            batch_ids = [int(row_id) for row_id in row_ids[offset : offset + size]]
            placeholders = ", ".join("?" * len(batch_ids))
            with self._read() as cur:
                cur.execute(
                    f"SELECT {V2_SELECT_SQL_COLS} FROM samples_v2"
                    f" WHERE run_id = ? AND id IN ({placeholders}) ORDER BY id",
                    (run_id, *batch_ids),
                )
                rows = [tuple(row) for row in cur.fetchall()]
            for row in rows:
                try:
                    frames.append(v2_row_to_sensor_frame(row))
                except SensorFrameDecodeError as exc:
                    LOGGER.warning("Skipping corrupt v2 sample row id=%s: %s", row[0], exc)
        return frames

    # -- settings snapshot ----------------------------------------------------

    def get_settings_snapshot(self) -> SettingsSnapshotPayload | None:
        with self._read() as cur:
            cur.execute("SELECT value_json FROM settings_snapshot WHERE id = 1")
            row = cur.fetchone()
        return None if row is None else settings_snapshot_from_json(row[0])

    def set_settings_snapshot(self, snapshot: SettingsSnapshotPayload) -> None:
        with self._write() as cur:
            cur.execute(
                "INSERT INTO settings_snapshot (id, value_json, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (settings_snapshot_to_json(snapshot), utc_now_iso()),
            )

    # -- client names ---------------------------------------------------------

    def list_client_names(self) -> dict[str, str]:
        with self._read() as cur:
            cur.execute("SELECT client_id, name FROM client_names")
            return {row[0]: row[1] for row in cur.fetchall()}

    def upsert_client_name(self, client_id: str, name: str) -> None:
        with self._write() as cur:
            cur.execute(
                "INSERT INTO client_names (client_id, name, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(client_id) DO UPDATE SET name = excluded.name, "
                "updated_at = excluded.updated_at",
                (client_id, name, utc_now_iso()),
            )

    def delete_client_name(self, client_id: str) -> bool:
        with self._write() as cur:
            cur.execute("DELETE FROM client_names WHERE client_id = ?", (client_id,))
            return int(cur.rowcount) > 0


def _str_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


def _run_status(cur: sqlite3.Cursor, run_id: str) -> str | None:
    cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
    row = cur.fetchone()
    return None if row is None else str(row[0])


def _rollback_open_transaction(conn: sqlite3.Connection, *, context: str) -> None:
    if not conn.in_transaction:
        return
    try:
        conn.rollback()
    except sqlite3.Error:
        LOGGER.critical("History DB rollback failed during %s", context, exc_info=True)


def _retention_cutoff_utc(retention_days: int) -> str:
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")
    return (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()


def _has_recommended_metadata_value(key: str, value: object) -> bool:
    if key == "sensor_model":
        text = str(value or "").strip().lower()
        return bool(text and text != "unknown")
    return value is not None
