"""SQLite-backed persistence for the VibeSensor server.

Stores run history (metadata, samples, analysis), application settings
and client names in a single file – lightweight enough for a
Raspberry Pi 3A+.

Schema v5 stores time-series samples as typed columns in ``samples_v2``,
providing fast write/read and compact storage on Raspberry Pi class
hardware.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from vibesensor.adapters.persistence.history_db._samples import (
    ALLOWED_SAMPLE_TABLES,
    V2_INSERT_SQL,
    V2_SELECT_SQL_COLS,
    sample_to_v2_row,
    v2_row_to_dict,
)
from vibesensor.adapters.persistence.history_db._schema import (
    SCHEMA_SQL,
    SCHEMA_VERSION,
)
from vibesensor.adapters.persistence.runlog import utc_now_iso
from vibesensor.adapters.udp.protocol import SensorFrame
from vibesensor.domain.run_status import (
    RunStatus,
    transition_run,
)
from vibesensor.shared.types.json_types import JsonObject, is_json_object
from vibesensor.shared.utils.json_utils import safe_json_dumps, safe_json_loads

# Re-export for public API.
__all__ = ["HistoryDB", "RunStatus"]

LOGGER = logging.getLogger(__name__)

_RECOMMENDED_METADATA_KEYS: frozenset[str] = frozenset({"sensor_model", "sample_rate_hz"})
_EXPECTED_ANALYSIS_KEYS: frozenset[str] = frozenset({"findings", "top_causes", "warnings"})
_CASE_ID_MIGRATION_SOURCE_VERSION = 8


class HistoryDB:
    """Thin wrapper around a SQLite database for run history."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = RLock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = sqlite3.connect(db_path, check_same_thread=False)
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA wal_autocheckpoint=500")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._ensure_schema()
        except sqlite3.Error:
            self._conn.close()
            raise

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @contextmanager
    def _cursor(self, *, commit: bool = True) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            if self._conn is None:
                raise RuntimeError("HistoryDB is closed")
            cur = self._conn.cursor()
            try:
                yield cur
                if commit:
                    self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    @contextmanager
    def write_transaction_cursor(self) -> Iterator[sqlite3.Cursor]:
        """Run a multi-step write sequence as one explicit transaction."""
        with self._lock:
            if self._conn is None:
                raise RuntimeError("HistoryDB is closed")
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                yield cur
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    # -- schema ---------------------------------------------------------------

    def _ensure_schema(self) -> None:
        with self._cursor() as cur:
            cur.executescript(SCHEMA_SQL)

        with self._cursor(commit=False) as cur:
            cur.execute("PRAGMA user_version")
            version = cur.fetchone()[0]

        if version == 0:
            # Check for legacy schema_meta table (pre-v5 databases).
            with self._cursor(commit=False) as cur:
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_meta'"
                )
                if cur.fetchone() is not None:
                    raise RuntimeError(
                        f"Database at {self.db_path} uses a legacy "
                        "schema_meta table incompatible with the current "
                        f"v{SCHEMA_VERSION} format. Delete it to recreate."
                    )
            # Fresh database — stamp with current version.
            with self._cursor() as cur:
                cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return

        if version == SCHEMA_VERSION:
            return
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"History DB schema version {version} is newer than "
                f"supported {SCHEMA_VERSION}. Cannot downgrade.",
            )
        if version == _CASE_ID_MIGRATION_SOURCE_VERSION:
            self._migrate_v8_to_v9_case_id()
            return
        msg = (
            f"Database schema v{version} is incompatible with "
            f"current v{SCHEMA_VERSION}. "
            f"Delete the database file at {self.db_path} to recreate it."
        )
        raise RuntimeError(msg)

    @staticmethod
    def _has_runs_column(cur: sqlite3.Cursor, column_name: str) -> bool:
        cur.execute("PRAGMA table_info(runs)")
        return any(str(row[1]) == column_name for row in cur.fetchall())

    def _migrate_v8_to_v9_case_id(self) -> None:
        LOGGER.info("Migrating history DB at %s from schema v8 to v9", self.db_path)
        with self._cursor() as cur:
            if not self._has_runs_column(cur, "case_id"):
                cur.execute("ALTER TABLE runs ADD COLUMN case_id TEXT")

            cur.execute(
                "SELECT run_id, analysis_json FROM runs "
                "WHERE case_id IS NULL AND analysis_json IS NOT NULL"
            )
            updates: list[tuple[str, str]] = []
            for run_id, analysis_json in cur.fetchall():
                parsed_analysis = safe_json_loads(
                    analysis_json,
                    context=f"run {run_id} analysis during schema migration",
                )
                if not is_json_object(parsed_analysis):
                    continue
                case_id = parsed_analysis.get("case_id")
                if isinstance(case_id, str) and case_id.strip():
                    updates.append((case_id, str(run_id)))

            if updates:
                cur.executemany(
                    "UPDATE runs SET case_id = ? WHERE run_id = ? AND case_id IS NULL",
                    updates,
                )

            cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # -- settings_kv persistence ----------------------------------------------

    _SETTINGS_SNAPSHOT_KEY = "settings_snapshot"

    def get_settings_snapshot(self) -> JsonObject | None:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT value_json FROM settings_kv WHERE key = ?",
                (self._SETTINGS_SNAPSHOT_KEY,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        snapshot = safe_json_loads(row[0], context="settings_snapshot")
        return snapshot if is_json_object(snapshot) else None

    def set_settings_snapshot(self, snapshot: JsonObject) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO settings_kv (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (self._SETTINGS_SNAPSHOT_KEY, safe_json_dumps(snapshot), now),
            )

    # -- client_names persistence ---------------------------------------------

    def list_client_names(self) -> dict[str, str]:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT client_id, name FROM client_names")
            rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}

    def upsert_client_name(self, client_id: str, name: str) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO client_names (client_id, name, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(client_id) DO UPDATE SET name = excluded.name, "
                "updated_at = excluded.updated_at",
                (client_id, name, now),
            )

    def delete_client_name(self, client_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM client_names WHERE client_id = ?", (client_id,))
            return bool(int(cur.rowcount) > 0)

    # -- run writes -----------------------------------------------------------

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
        metadata: JsonObject,
        case_id: str | None = None,
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
                "INSERT INTO runs (run_id, case_id, status, start_time_utc, metadata_json, "
                "created_at) VALUES (?, ?, 'recording', ?, ?, ?)",
                (run_id, case_id, start_time_utc, safe_json_dumps(metadata), now),
            )

    def append_samples(
        self,
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

    def finalize_run(
        self,
        run_id: str,
        end_time_utc: str,
        metadata: JsonObject | None = None,
        case_id: str | None = None,
    ) -> bool:
        now = utc_now_iso()
        with self._cursor() as cur:
            assignments = ["status = 'analyzing'", "end_time_utc = ?", "analysis_started_at = ?"]
            params: list[object] = [end_time_utc, now]
            if metadata is not None:
                assignments.insert(0, "metadata_json = ?")
                params.insert(0, safe_json_dumps(metadata))
            if case_id is not None:
                assignments.insert(0, "case_id = ?")
                params.insert(0, case_id)
            params.append(run_id)
            cur.execute(
                f"UPDATE runs SET {', '.join(assignments)} "
                "WHERE run_id = ? AND status = 'recording'",
                params,
            )
            if int(cur.rowcount) > 0:
                return True
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

    def update_run_metadata(
        self,
        run_id: str,
        metadata: JsonObject,
    ) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET metadata_json = ? WHERE run_id = ?",
                (safe_json_dumps(metadata), run_id),
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
            status = row[0]
            if status == RunStatus.RECORDING:
                return False, "active"
            if status == RunStatus.ANALYZING:
                return False, RunStatus.ANALYZING
            cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return bool(int(cur.rowcount) > 0), None

    def store_analysis(
        self,
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
            # Include 'recording' to handle the case where finalize_run()
            # failed (e.g. DB unavailable at that moment).  store_analysis
            # still succeeds via the RECORDING → COMPLETE shortcut path
            # defined in RUN_TRANSITIONS.
            cur.execute(
                "UPDATE runs SET status = 'complete', analysis_json = ?, "
                "analysis_completed_at = ?, end_time_utc = COALESCE(end_time_utc, ?) "
                "WHERE run_id = ? AND status IN ('recording', 'analyzing')",
                (
                    safe_json_dumps(analysis),
                    now,
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

    def store_analysis_error(self, run_id: str, error: str) -> bool:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ?, "
                "analysis_completed_at = ?, end_time_utc = COALESCE(end_time_utc, ?) "
                "WHERE run_id = ? AND status IN ('recording', 'analyzing')",
                (error, now, now, run_id),
            )
            if int(cur.rowcount) > 0:
                return True
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

    # -- run reads ------------------------------------------------------------

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

    def get_run_samples(self, run_id: str) -> list[JsonObject]:
        rows: list[JsonObject] = []
        for batch in self.iter_run_samples(run_id):
            rows.extend(batch)
        return rows

    def iter_run_samples(
        self,
        run_id: str,
        batch_size: int = 1000,
        offset: int = 0,
    ) -> Iterator[list[JsonObject]]:
        if offset < 0:
            raise ValueError(f"iter_run_samples: offset must be >= 0, got {offset}")
        yield from self._iter_v2_samples(run_id, batch_size, offset)

    def _resolve_keyset_offset(
        self,
        table: str,
        run_id: str,
        offset: int,
    ) -> int | None:
        if table not in ALLOWED_SAMPLE_TABLES:
            raise ValueError(
                f"_resolve_keyset_offset: invalid table name {table!r}; "
                f"must be one of {sorted(ALLOWED_SAMPLE_TABLES)}",
            )
        with self._cursor(commit=False) as cur:
            cur.execute(
                f"SELECT id FROM {table} WHERE run_id = ? ORDER BY id LIMIT 1 OFFSET ?",
                (run_id, offset - 1),
            )
            row = cur.fetchone()
        return int(row[0]) if row else None

    def _iter_v2_samples(
        self,
        run_id: str,
        batch_size: int = 1000,
        offset: int = 0,
    ) -> Iterator[list[JsonObject]]:
        size = max(1, batch_size)
        last_id: int | None = None
        if offset > 0:
            last_id = self._resolve_keyset_offset("samples_v2", run_id, offset)
            if last_id is None:
                return
        total_skipped = 0
        while True:
            with self._cursor(commit=False) as cur:
                if last_id is None:
                    cur.execute(
                        f"SELECT {V2_SELECT_SQL_COLS} FROM samples_v2"
                        " WHERE run_id = ? ORDER BY id LIMIT ?",
                        (run_id, size),
                    )
                else:
                    cur.execute(
                        f"SELECT {V2_SELECT_SQL_COLS} FROM samples_v2"
                        " WHERE run_id = ? AND id > ? ORDER BY id LIMIT ?",
                        (run_id, last_id, size),
                    )
                batch_rows = cur.fetchall()
            if not batch_rows:
                if total_skipped:
                    LOGGER.warning(
                        "run_id=%s: skipped %d corrupt v2 sample row(s) in total",
                        run_id,
                        total_skipped,
                    )
                return
            last_id = batch_rows[-1][0]
            parsed_batch: list[JsonObject] = []
            for row in batch_rows:
                try:
                    parsed_batch.append(v2_row_to_dict(row))
                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                    total_skipped += 1
                    LOGGER.warning("Skipping corrupt v2 sample row id=%s", row[0], exc_info=True)
            if parsed_batch:
                yield parsed_batch

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
        """Check a completed run for consistency issues. Returns a list of problem descriptions."""
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
