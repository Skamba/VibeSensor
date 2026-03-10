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

from ..domain_models import SensorFrame
from ..json_types import JsonObject, JsonValue, is_json_object
from ..json_utils import safe_json_dumps, safe_json_loads
from ..runlog import utc_now_iso
from ._samples import (
    ALLOWED_SAMPLE_TABLES,
    V2_INSERT_SQL,
    V2_SELECT_SQL_COLS,
    sample_to_v2_row,
    v2_row_to_dict,
)
from ._schema import (
    ANALYSIS_SCHEMA_VERSION,
    SCHEMA_SQL,
    SCHEMA_VERSION,
    RunStatus,
    can_transition_run,
)

# Re-export for public API.
__all__ = ["ANALYSIS_SCHEMA_VERSION", "HistoryDB", "RunStatus"]

LOGGER = logging.getLogger(__name__)

_RECOMMENDED_METADATA_KEYS: frozenset[str] = frozenset({"sensor_model", "sample_rate_hz"})
_EXPECTED_ANALYSIS_KEYS: frozenset[str] = frozenset({"findings", "top_causes", "warnings"})


def _sanitize_for_storage(summary: JsonObject) -> JsonObject:
    """Strip internal-only keys before persisting an analysis summary."""
    cleaned = dict(summary)
    cleaned.pop("_report_template_data", None)
    return cleaned


def _sanitize_for_read(raw: JsonObject) -> JsonObject:
    """Strip internal-only keys when returning a persisted analysis."""
    cleaned = dict(raw)
    cleaned.pop("_report_template_data", None)
    return cleaned


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

    @contextmanager
    def read_transaction(self) -> Iterator[None]:
        """Hold a single read transaction across multi-step read operations."""
        with self._lock:
            if self._conn is None:
                raise RuntimeError("HistoryDB is closed")
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN")
                yield
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
        with self._cursor() as cur:
            cur.execute("SELECT value FROM schema_meta WHERE key = ?", ("version",))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
                    ("version", str(SCHEMA_VERSION)),
                )
                return
            try:
                version = int(str(row[0]))
            except (ValueError, TypeError):
                LOGGER.error(
                    "Corrupted schema_meta version value %r; resetting to %s",
                    row[0],
                    SCHEMA_VERSION,
                )
                cur.execute(
                    "UPDATE schema_meta SET value = ? WHERE key = 'version'",
                    (str(SCHEMA_VERSION),),
                )
                return
            if version == SCHEMA_VERSION:
                return
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"History DB schema version {version} is newer than "
                    f"supported {SCHEMA_VERSION}. Cannot downgrade.",
                )
            msg = (
                f"Database schema v{version} is incompatible with "
                f"current v{SCHEMA_VERSION}. "
                f"Delete the database file at {self.db_path} to recreate it."
            )
            raise RuntimeError(msg)

    # -- settings_kv persistence ----------------------------------------------

    def get_setting(self, key: str) -> JsonValue | None:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT value_json FROM settings_kv WHERE key = ?", (key,))
            row = cur.fetchone()
        if row is None:
            return None
        return safe_json_loads(row[0], context=f"setting {key}")

    def set_setting(self, key: str, value: JsonValue) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO settings_kv (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (key, safe_json_dumps(value), now),
            )

    def get_settings_snapshot(self) -> JsonObject | None:
        snapshot = self.get_setting("settings_snapshot")
        return snapshot if is_json_object(snapshot) else None

    def set_settings_snapshot(self, snapshot: JsonObject) -> None:
        self.set_setting("settings_snapshot", snapshot)

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

    @staticmethod
    def _log_transition_skip(run_id: str, current_status: str | None, target_status: str) -> None:
        if current_status is None:
            LOGGER.warning(
                "Skipping run transition to %s for %s: run not found",
                target_status,
                run_id,
            )
            return
        LOGGER.warning(
            "Skipping run transition for %s: %s -> %s is not allowed",
            run_id,
            current_status,
            target_status,
        )

    def create_run(
        self,
        run_id: str,
        start_time_utc: str,
        metadata: JsonObject,
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
                "INSERT INTO runs (run_id, status, start_time_utc, metadata_json, created_at) "
                "VALUES (?, 'recording', ?, ?, ?)",
                (run_id, start_time_utc, safe_json_dumps(metadata), now),
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

    def finalize_run(self, run_id: str, end_time_utc: str) -> bool:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'analyzing', end_time_utc = ?, "
                "analysis_started_at = ? WHERE run_id = ? AND status = 'recording'",
                (end_time_utc, now, run_id),
            )
            if int(cur.rowcount) > 0:
                return True
            current_status = self._run_status(cur, run_id)
            if not can_transition_run(current_status, RunStatus.ANALYZING):
                self._log_transition_skip(run_id, current_status, RunStatus.ANALYZING)
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

    def finalize_run_with_metadata(
        self,
        run_id: str,
        end_time_utc: str,
        metadata: JsonObject,
    ) -> bool:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET metadata_json = ?, status = 'analyzing', "
                "end_time_utc = ?, analysis_started_at = ? "
                "WHERE run_id = ? AND status = 'recording'",
                (safe_json_dumps(metadata), end_time_utc, now, run_id),
            )
            if int(cur.rowcount) > 0:
                return True
            current_status = self._run_status(cur, run_id)
            if not can_transition_run(current_status, RunStatus.ANALYZING):
                self._log_transition_skip(run_id, current_status, RunStatus.ANALYZING)
            return False

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
            cur.execute(
                "UPDATE runs SET status = 'complete', analysis_json = ?, "
                "analysis_version = ?, analysis_completed_at = ? "
                "WHERE run_id = ? AND status IN ('recording', 'analyzing')",
                (
                    safe_json_dumps(_sanitize_for_storage(analysis)),
                    ANALYSIS_SCHEMA_VERSION,
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
            elif not can_transition_run(current_status, RunStatus.COMPLETE):
                self._log_transition_skip(run_id, current_status, RunStatus.COMPLETE)
            return False

    def store_analysis_error(self, run_id: str, error: str) -> bool:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ?, "
                "analysis_completed_at = ? "
                "WHERE run_id = ? AND status IN ('recording', 'analyzing')",
                (error, now, run_id),
            )
            if int(cur.rowcount) > 0:
                return True
            current_status = self._run_status(cur, run_id)
            if current_status == RunStatus.COMPLETE:
                LOGGER.warning(
                    "store_analysis_error for run %s: skipped — already complete",
                    run_id,
                )
            elif not can_transition_run(current_status, RunStatus.ERROR):
                self._log_transition_skip(run_id, current_status, RunStatus.ERROR)
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

    def analysis_is_current(self, run_id: str) -> bool:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT analysis_version FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return False
        try:
            return int(row[0]) >= ANALYSIS_SCHEMA_VERSION
        except (ValueError, TypeError):
            return False

    def list_runs(self, limit: int = 500) -> list[JsonObject]:
        with self._cursor(commit=False) as cur:
            limit = max(limit, 0)
            if limit > 0:
                cur.execute(
                    "SELECT r.run_id, r.status, r.start_time_utc, r.end_time_utc, "
                    "r.created_at, r.error_message, r.sample_count, r.analysis_version "
                    "FROM runs r ORDER BY r.created_at DESC LIMIT ?",
                    (limit,),
                )
            else:
                cur.execute(
                    "SELECT r.run_id, r.status, r.start_time_utc, r.end_time_utc, "
                    "r.created_at, r.error_message, r.sample_count, r.analysis_version "
                    "FROM runs r ORDER BY r.created_at DESC",
                )
            rows = cur.fetchall()
        result: list[JsonObject] = []
        for row in rows:
            run_id, status, start, end, created, error, sample_count, analysis_ver = row
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
            if analysis_ver is not None:
                entry["analysis_version"] = analysis_ver
            result.append(entry)
        return result

    def get_run(self, run_id: str) -> JsonObject | None:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT run_id, status, start_time_utc, end_time_utc, "
                "metadata_json, analysis_json, error_message, created_at, "
                "sample_count, analysis_version, analysis_started_at, analysis_completed_at "
                "FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        (
            rid,
            status,
            start,
            end,
            meta_json,
            analysis_json,
            error,
            created,
            sample_count,
            analysis_ver,
            analysis_started,
            analysis_completed,
        ) = row
        entry: JsonObject = {
            "run_id": rid,
            "status": status,
            "start_time_utc": start,
            "end_time_utc": end,
            "metadata": safe_json_loads(meta_json, context=f"run {run_id} metadata") or {},
            "created_at": created,
            "sample_count": sample_count,
        }
        if analysis_json:
            parsed_analysis = safe_json_loads(analysis_json, context=f"run {run_id} analysis")
            if is_json_object(parsed_analysis):
                entry["analysis"] = _sanitize_for_read(parsed_analysis)
            else:
                entry["analysis_corrupt"] = True
        if error:
            entry["error_message"] = error
        if analysis_ver is not None:
            entry["analysis_version"] = analysis_ver
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

    def get_run_analysis(self, run_id: str) -> JsonObject | None:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT analysis_json FROM runs WHERE run_id = ? AND status = 'complete'",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        parsed = safe_json_loads(row[0], context=f"run {run_id} analysis")
        if parsed is not None and not is_json_object(parsed):
            LOGGER.warning(
                "get_run_analysis: run %s analysis_json parsed to %s, expected dict; "
                "treating as missing",
                run_id,
                type(parsed).__name__,
            )
            return None
        if parsed is None:
            return None
        return _sanitize_for_read(parsed)

    def get_run_status(self, run_id: str) -> str | None:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        return str(row[0]) if row else None

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
