"""SQLite-backed persistence for the VibeSensor server.

Stores run history (metadata, samples, analysis), application settings
and client names in a single file – lightweight enough for a
Raspberry Pi 3A+.

Schema v5 stores time-series samples as typed columns instead of JSON
blobs, dramatically improving write speed, read speed and storage size
on Raspberry Pi class hardware.  Legacy v4 ``samples`` rows (JSON) are
read transparently for old runs that have not been migrated.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from .domain_models import SensorFrame

LOGGER = logging.getLogger(__name__)

# -- Schema -------------------------------------------------------------------

_SCHEMA_VERSION = 5
ANALYSIS_SCHEMA_VERSION = 1

# Typed scalar columns in samples_v2 that map 1:1 to SensorFrame dict keys.
_V2_TYPED_COLS: tuple[str, ...] = (
    "run_id",
    "record_type",
    "schema_version",
    "timestamp_utc",
    "t_s",
    "client_id",
    "client_name",
    "location",
    "sample_rate_hz",
    "speed_kmh",
    "gps_speed_kmh",
    "speed_source",
    "engine_rpm",
    "engine_rpm_source",
    "gear",
    "final_drive_ratio",
    "accel_x_g",
    "accel_y_g",
    "accel_z_g",
    "dominant_freq_hz",
    "dominant_axis",
    "vibration_strength_db",
    "strength_bucket",
    "strength_peak_amp_g",
    "strength_floor_amp_g",
    "frames_dropped_total",
    "queue_overflow_drops",
)

# Peak-list columns stored as compact JSON arrays.
_V2_PEAK_COLS: tuple[str, ...] = (
    "top_peaks",
    "top_peaks_x",
    "top_peaks_y",
    "top_peaks_z",
)

# All known SensorFrame dict keys.
_V2_KNOWN_KEYS: frozenset[str] = frozenset(_V2_TYPED_COLS) | frozenset(_V2_PEAK_COLS)

# Full column list for INSERT (typed + peaks + extra_json).
_V2_INSERT_COLS: tuple[str, ...] = _V2_TYPED_COLS + _V2_PEAK_COLS + ("extra_json",)
_V2_INSERT_SQL: str = (
    f"INSERT INTO samples_v2 ({', '.join(_V2_INSERT_COLS)}) "
    f"VALUES ({', '.join('?' * len(_V2_INSERT_COLS))})"
)

# SELECT column list (id first, then all insert cols).
_V2_SELECT_COLS: tuple[str, ...] = ("id",) + _V2_INSERT_COLS
_V2_SELECT_SQL_COLS: str = ", ".join(_V2_SELECT_COLS)

# -- Schema DDL ---------------------------------------------------------------

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id                  TEXT PRIMARY KEY,
    status                  TEXT NOT NULL DEFAULT 'recording',
    start_time_utc          TEXT NOT NULL,
    end_time_utc            TEXT,
    metadata_json           TEXT NOT NULL,
    analysis_json           TEXT,
    error_message           TEXT,
    sample_count            INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT NOT NULL,
    analysis_version        INTEGER,
    analysis_started_at     TEXT,
    analysis_completed_at   TEXT
);

CREATE TABLE IF NOT EXISTS samples_v2 (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    record_type           TEXT,
    schema_version        TEXT,
    timestamp_utc         TEXT,
    t_s                   REAL,
    client_id             TEXT,
    client_name           TEXT,
    location              TEXT,
    sample_rate_hz        INTEGER,
    speed_kmh             REAL,
    gps_speed_kmh         REAL,
    speed_source          TEXT,
    engine_rpm            REAL,
    engine_rpm_source     TEXT,
    gear                  REAL,
    final_drive_ratio     REAL,
    accel_x_g             REAL,
    accel_y_g             REAL,
    accel_z_g             REAL,
    dominant_freq_hz      REAL,
    dominant_axis         TEXT,
    vibration_strength_db REAL,
    strength_bucket       TEXT,
    strength_peak_amp_g   REAL,
    strength_floor_amp_g  REAL,
    frames_dropped_total  INTEGER DEFAULT 0,
    queue_overflow_drops  INTEGER DEFAULT 0,
    top_peaks             TEXT,
    top_peaks_x           TEXT,
    top_peaks_y           TEXT,
    top_peaks_z           TEXT,
    extra_json            TEXT
);

CREATE INDEX IF NOT EXISTS idx_samples_v2_run_id ON samples_v2(run_id);
CREATE INDEX IF NOT EXISTS idx_samples_v2_run_time ON samples_v2(run_id, t_s);

CREATE TABLE IF NOT EXISTS settings_kv (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS client_names (
    client_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

# DDL applied when migrating an existing v4 database to v5.
_MIGRATION_V4_TO_V5_SQL = """\
CREATE TABLE IF NOT EXISTS samples_v2 (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    record_type           TEXT,
    schema_version        TEXT,
    timestamp_utc         TEXT,
    t_s                   REAL,
    client_id             TEXT,
    client_name           TEXT,
    location              TEXT,
    sample_rate_hz        INTEGER,
    speed_kmh             REAL,
    gps_speed_kmh         REAL,
    speed_source          TEXT,
    engine_rpm            REAL,
    engine_rpm_source     TEXT,
    gear                  REAL,
    final_drive_ratio     REAL,
    accel_x_g             REAL,
    accel_y_g             REAL,
    accel_z_g             REAL,
    dominant_freq_hz      REAL,
    dominant_axis         TEXT,
    vibration_strength_db REAL,
    strength_bucket       TEXT,
    strength_peak_amp_g   REAL,
    strength_floor_amp_g  REAL,
    frames_dropped_total  INTEGER DEFAULT 0,
    queue_overflow_drops  INTEGER DEFAULT 0,
    top_peaks             TEXT,
    top_peaks_x           TEXT,
    top_peaks_y           TEXT,
    top_peaks_z           TEXT,
    extra_json            TEXT
);

CREATE INDEX IF NOT EXISTS idx_samples_v2_run_id ON samples_v2(run_id);
CREATE INDEX IF NOT EXISTS idx_samples_v2_run_time ON samples_v2(run_id, t_s);
"""


class HistoryDB:
    """Thin wrapper around a SQLite database for run history."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = RLock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA wal_autocheckpoint=500")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()
        self._has_legacy_samples: bool = self._table_exists("samples")

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _cursor(self, *, commit: bool = True):
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                if commit:
                    self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    @contextmanager
    def read_transaction(self):
        """Hold a single read transaction across multi-step read operations."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN")
                yield
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    @staticmethod
    def _sanitize_for_json(value: Any) -> Any:
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, dict):
            return {k: HistoryDB._sanitize_for_json(v) for k, v in value.items()}
        if isinstance(value, list):
            return [HistoryDB._sanitize_for_json(v) for v in value]
        if isinstance(value, tuple):
            return [HistoryDB._sanitize_for_json(v) for v in value]
        return value

    @classmethod
    def _safe_json_dumps(cls, value: Any) -> str:
        return json.dumps(cls._sanitize_for_json(value), ensure_ascii=False, allow_nan=False)

    @staticmethod
    def _safe_json_loads(value: str | None, *, context: str) -> Any | None:
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            LOGGER.warning("Skipping invalid JSON payload while reading %s", context, exc_info=True)
            return None

    def _ensure_schema(self) -> None:
        with self._cursor() as cur:
            cur.executescript(_SCHEMA_SQL)
        with self._cursor() as cur:
            cur.execute("SELECT value FROM schema_meta WHERE key = ?", ("version",))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
                    ("version", str(_SCHEMA_VERSION)),
                )
                return
            version = int(str(row[0]))
            if version == _SCHEMA_VERSION:
                return
            if version == 4:
                self._migrate_v4_to_v5()
                return
            raise RuntimeError(
                f"Unsupported history DB schema version {version}; "
                f"expected {_SCHEMA_VERSION}. Delete the database file to recreate."
            )

    def _migrate_v4_to_v5(self) -> None:
        """Create the structured samples_v2 table alongside the legacy samples table."""
        LOGGER.info("Migrating history DB from schema v4 to v5 (structured samples)")
        with self._cursor() as cur:
            cur.executescript(_MIGRATION_V4_TO_V5_SQL)
            cur.execute(
                "UPDATE schema_meta SET value = ? WHERE key = 'version'",
                (str(_SCHEMA_VERSION),),
            )
        LOGGER.info("Migration v4→v5 complete; legacy sample rows remain readable")

    def _table_exists(self, name: str) -> bool:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            )
            return cur.fetchone() is not None

    # -- write ----------------------------------------------------------------

    def create_run(
        self,
        run_id: str,
        start_time_utc: str,
        metadata: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE status = 'recording'",
                ("Recovered stale recording on new run creation",),
            )
            cur.execute(
                "INSERT INTO runs (run_id, status, start_time_utc, metadata_json, created_at) "
                "VALUES (?, 'recording', ?, ?, ?)",
                (run_id, start_time_utc, self._safe_json_dumps(metadata), now),
            )

    def append_samples(
        self, run_id: str, samples: list[dict[str, Any]] | list[SensorFrame]
    ) -> None:
        if not samples:
            return

        chunk_size = 256
        with self._cursor() as cur:
            for start in range(0, len(samples), chunk_size):
                batch = samples[start : start + chunk_size]
                cur.executemany(
                    _V2_INSERT_SQL,
                    (self._sample_to_v2_row(run_id, s) for s in batch),
                )
            cur.execute(
                "UPDATE runs SET sample_count = sample_count + ? WHERE run_id = ?",
                (len(samples), run_id),
            )

    # -- v2 row conversion helpers --------------------------------------------

    @classmethod
    def _sample_to_v2_row(cls, run_id: str, item: dict[str, Any] | SensorFrame) -> tuple[Any, ...]:
        """Convert a sample dict or SensorFrame to a row tuple for samples_v2."""
        d: dict[str, Any] = item.to_dict() if isinstance(item, SensorFrame) else item

        typed_vals: list[Any] = []
        for col in _V2_TYPED_COLS:
            val = d.get(col)
            if col == "run_id":
                val = run_id
            if isinstance(val, float) and not math.isfinite(val):
                val = None
            typed_vals.append(val)

        peak_vals: list[str | None] = []
        for col in _V2_PEAK_COLS:
            raw = d.get(col)
            if raw:
                peak_vals.append(
                    json.dumps(
                        cls._sanitize_for_json(raw),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                )
            else:
                peak_vals.append(None)

        extra = {k: v for k, v in d.items() if k not in _V2_KNOWN_KEYS}
        extra_json: str | None = None
        if extra:
            extra_json = json.dumps(
                cls._sanitize_for_json(extra), ensure_ascii=False, allow_nan=False
            )

        return tuple(typed_vals) + tuple(peak_vals) + (extra_json,)

    @classmethod
    def _v2_row_to_dict(cls, row: tuple[Any, ...]) -> dict[str, Any]:
        """Reconstruct a sample dict from a samples_v2 row.

        *row* layout: ``(id, <typed cols>, <peak cols>, extra_json)``.
        """
        d: dict[str, Any] = {}
        offset = 1  # skip autoincrement id

        for i, col in enumerate(_V2_TYPED_COLS):
            val = row[offset + i]
            if val is not None:
                d[col] = val

        offset += len(_V2_TYPED_COLS)
        for i, col in enumerate(_V2_PEAK_COLS):
            raw = row[offset + i]
            if raw:
                parsed = cls._safe_json_loads(raw, context=f"peak column {col}")
                d[col] = parsed if isinstance(parsed, list) else []
            else:
                d[col] = []

        extra_json = row[offset + len(_V2_PEAK_COLS)]
        if extra_json:
            extra = cls._safe_json_loads(extra_json, context="extra_json")
            if isinstance(extra, dict):
                d.update(extra)

        return d

    def finalize_run(self, run_id: str, end_time_utc: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'analyzing', end_time_utc = ?, "
                "analysis_started_at = ? WHERE run_id = ? AND status = 'recording'",
                (end_time_utc, now, run_id),
            )
            if cur.rowcount == 0:
                LOGGER.warning(
                    "finalize_run for run %s: no rows updated "
                    "(run missing or not in 'recording' state)",
                    run_id,
                )

    def update_run_metadata(self, run_id: str, metadata: dict[str, Any]) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET metadata_json = ? WHERE run_id = ?",
                (self._safe_json_dumps(metadata), run_id),
            )
            return cur.rowcount > 0

    def finalize_run_with_metadata(
        self, run_id: str, end_time_utc: str, metadata: dict[str, Any]
    ) -> None:
        """Atomically update metadata and transition status to 'analyzing'.

        Combines :meth:`update_run_metadata` and :meth:`finalize_run` into a
        single transaction so that a crash between the two cannot leave the
        run in an inconsistent state.
        """
        now = datetime.now(UTC).isoformat()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET metadata_json = ?, status = 'analyzing', "
                "end_time_utc = ?, analysis_started_at = ? "
                "WHERE run_id = ? AND status = 'recording'",
                (self._safe_json_dumps(metadata), end_time_utc, now, run_id),
            )
            if cur.rowcount == 0:
                LOGGER.warning(
                    "finalize_run_with_metadata for run %s: no rows updated "
                    "(run missing or not in 'recording' state)",
                    run_id,
                )

    def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
        """Atomically check status and delete a run.

        Returns ``(True, None)`` on success, ``(False, reason)`` if the
        run cannot be deleted because it is recording or analyzing.
        """
        with self._cursor() as cur:
            cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
            if row is None:
                return False, "not_found"
            status = row[0]
            if status == "recording":
                return False, "active"
            if status == "analyzing":
                return False, "analyzing"
            cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return cur.rowcount > 0, None

    def store_analysis(self, run_id: str, analysis: dict[str, Any]) -> None:
        now = datetime.now(UTC).isoformat()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'complete', analysis_json = ?, "
                "analysis_version = ?, analysis_completed_at = ? "
                "WHERE run_id = ? AND status NOT IN ('complete')",
                (
                    self._safe_json_dumps(analysis),
                    ANALYSIS_SCHEMA_VERSION,
                    now,
                    run_id,
                ),
            )
            if cur.rowcount == 0:
                cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
                row = cur.fetchone()
                if row is not None and row[0] == "complete":
                    LOGGER.warning(
                        "store_analysis for run %s: skipped — already complete",
                        run_id,
                    )

    def store_analysis_error(self, run_id: str, error: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ?, "
                "analysis_completed_at = ? "
                "WHERE run_id = ? AND status NOT IN ('complete')",
                (error, now, run_id),
            )

    def analysis_is_current(self, run_id: str) -> bool:
        """Return *True* when the persisted analysis version matches the current schema."""
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT analysis_version FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None or row[0] is None:
            return False
        return int(row[0]) >= ANALYSIS_SCHEMA_VERSION

    # -- read -----------------------------------------------------------------

    def list_runs(self) -> list[dict[str, Any]]:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT r.run_id, r.status, r.start_time_utc, r.end_time_utc, "
                "r.created_at, r.error_message, r.sample_count, r.analysis_version "
                "FROM runs r ORDER BY r.created_at DESC"
            )
            rows = cur.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            run_id, status, start, end, created, error, sample_count, analysis_ver = row
            entry: dict[str, Any] = {
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

    def get_run(self, run_id: str) -> dict[str, Any] | None:
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
        entry: dict[str, Any] = {
            "run_id": rid,
            "status": status,
            "start_time_utc": start,
            "end_time_utc": end,
            "metadata": self._safe_json_loads(meta_json, context=f"run {run_id} metadata") or {},
            "created_at": created,
            "sample_count": sample_count,
        }
        if analysis_json:
            parsed_analysis = self._safe_json_loads(analysis_json, context=f"run {run_id} analysis")
            if isinstance(parsed_analysis, dict):
                entry["analysis"] = parsed_analysis
        if error:
            entry["error_message"] = error
        if analysis_ver is not None:
            entry["analysis_version"] = analysis_ver
        if analysis_started:
            entry["analysis_started_at"] = analysis_started
        if analysis_completed:
            entry["analysis_completed_at"] = analysis_completed
        return entry

    def get_run_samples(self, run_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for batch in self.iter_run_samples(run_id):
            rows.extend(batch)
        return rows

    def iter_run_samples(
        self, run_id: str, batch_size: int = 1000, offset: int = 0
    ) -> Iterator[list[dict[str, Any]]]:
        if self._run_has_v2_samples(run_id):
            yield from self._iter_v2_samples(run_id, batch_size, offset)
        elif self._has_legacy_samples:
            yield from self._iter_legacy_samples(run_id, batch_size, offset)

    def _run_has_v2_samples(self, run_id: str) -> bool:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT 1 FROM samples_v2 WHERE run_id = ? LIMIT 1",
                (run_id,),
            )
            return cur.fetchone() is not None

    def _iter_v2_samples(
        self, run_id: str, batch_size: int = 1000, offset: int = 0
    ) -> Iterator[list[dict[str, Any]]]:
        size = max(1, int(batch_size))
        last_id: int | None = None
        if offset > 0:
            with self._cursor(commit=False) as cur:
                cur.execute(
                    "SELECT id FROM samples_v2 WHERE run_id = ? ORDER BY id LIMIT 1 OFFSET ?",
                    (run_id, max(0, int(offset)) - 1),
                )
                row = cur.fetchone()
                if row:
                    last_id = row[0]
                else:
                    return
        while True:
            with self._cursor(commit=False) as cur:
                if last_id is None:
                    cur.execute(
                        f"SELECT {_V2_SELECT_SQL_COLS} FROM samples_v2"
                        " WHERE run_id = ? ORDER BY id LIMIT ?",
                        (run_id, size),
                    )
                else:
                    cur.execute(
                        f"SELECT {_V2_SELECT_SQL_COLS} FROM samples_v2"
                        " WHERE run_id = ? AND id > ? ORDER BY id LIMIT ?",
                        (run_id, last_id, size),
                    )
                batch_rows = cur.fetchall()
            if not batch_rows:
                return
            last_id = batch_rows[-1][0]
            parsed_batch: list[dict[str, Any]] = []
            for row in batch_rows:
                try:
                    parsed_batch.append(self._v2_row_to_dict(row))
                except Exception:
                    LOGGER.warning("Skipping corrupt v2 sample row id=%s", row[0], exc_info=True)
            if parsed_batch:
                yield parsed_batch

    def _iter_legacy_samples(
        self, run_id: str, batch_size: int = 1000, offset: int = 0
    ) -> Iterator[list[dict[str, Any]]]:
        """Read samples from the legacy v4 JSON-blob ``samples`` table."""
        size = max(1, int(batch_size))
        last_id: int | None = None
        if offset > 0:
            with self._cursor(commit=False) as cur:
                cur.execute(
                    "SELECT id FROM samples WHERE run_id = ? ORDER BY id LIMIT 1 OFFSET ?",
                    (run_id, max(0, int(offset)) - 1),
                )
                row = cur.fetchone()
                if row:
                    last_id = row[0]
                else:
                    return
        while True:
            with self._cursor(commit=False) as cur:
                if last_id is None:
                    cur.execute(
                        "SELECT id, sample_json FROM samples WHERE run_id = ? ORDER BY id LIMIT ?",
                        (run_id, size),
                    )
                else:
                    cur.execute(
                        "SELECT id, sample_json FROM samples"
                        " WHERE run_id = ? AND id > ? ORDER BY id LIMIT ?",
                        (run_id, last_id, size),
                    )
                batch_rows = cur.fetchall()
            if not batch_rows:
                return
            last_id = batch_rows[-1][0]
            parsed_batch: list[dict[str, Any]] = []
            for sample_id, sample_json in batch_rows:
                parsed = self._safe_json_loads(sample_json, context=f"sample {sample_id}")
                if isinstance(parsed, dict):
                    parsed_batch.append(parsed)
            if parsed_batch:
                yield parsed_batch

    def get_run_metadata(self, run_id: str) -> dict[str, Any] | None:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT metadata_json FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        if row is None:
            return None
        parsed = self._safe_json_loads(row[0], context=f"run {run_id} metadata")
        return parsed if isinstance(parsed, dict) else None

    def get_run_analysis(self, run_id: str) -> dict[str, Any] | None:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT analysis_json FROM runs WHERE run_id = ? AND status = 'complete'",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        parsed = self._safe_json_loads(row[0], context=f"run {run_id} analysis")
        return parsed if isinstance(parsed, dict) else None

    def get_run_status(self, run_id: str) -> str | None:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        return row[0] if row else None

    def delete_run(self, run_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return cur.rowcount > 0

    def get_active_run_id(self) -> str | None:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT run_id FROM runs WHERE status = 'recording' "
                "ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
        return row[0] if row else None

    def recover_stale_recording_runs(self) -> int:
        """Mark stale 'recording' runs as error and return count.

        Runs still in 'analyzing' state are left alone; the analysis
        worker will pick them up for re-processing.
        """
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE status = 'recording'",
                ("Recovered stale recording during startup",),
            )
            return cur.rowcount

    def stale_analyzing_run_ids(self) -> list[str]:
        """Return run IDs stuck in 'analyzing' state (e.g. after a crash)."""
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT run_id FROM runs WHERE status = 'analyzing' ORDER BY created_at ASC"
            )
            return [row[0] for row in cur.fetchall()]

    # -- settings KV ----------------------------------------------------------

    def get_setting(self, key: str) -> Any | None:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT value_json FROM settings_kv WHERE key = ?", (key,))
            row = cur.fetchone()
        if row is None:
            return None
        return self._safe_json_loads(row[0], context=f"setting {key}")

    def set_setting(self, key: str, value: Any) -> None:
        now = datetime.now(UTC).isoformat()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO settings_kv (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (key, self._safe_json_dumps(value), now),
            )

    def get_settings_snapshot(self) -> dict[str, Any] | None:
        return self.get_setting("settings_snapshot")

    def set_settings_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.set_setting("settings_snapshot", snapshot)

    # -- client names ---------------------------------------------------------

    def list_client_names(self) -> dict[str, str]:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT client_id, name FROM client_names")
            rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}

    def upsert_client_name(self, client_id: str, name: str) -> None:
        now = datetime.now(UTC).isoformat()
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
            return cur.rowcount > 0
