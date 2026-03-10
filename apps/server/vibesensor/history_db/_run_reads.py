"""Run-history read/query helpers for HistoryDB."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime

from ..analysis_persistence import persisted_analysis_is_current, unwrap_persisted_analysis
from ..json_types import JsonObject, is_json_object
from ..json_utils import safe_json_loads
from ._samples import ALLOWED_SAMPLE_TABLES, V2_SELECT_SQL_COLS, v2_row_to_dict
from ._schema import ANALYSIS_SCHEMA_VERSION, HistoryCursorProvider

LOGGER = logging.getLogger(__name__)


class HistoryRunReadMixin:
    """Mixin providing run query and sample-read methods."""

    __slots__ = ()

    def analysis_is_current(self: HistoryCursorProvider, run_id: str) -> bool:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT analysis_version, analysis_json FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return False
        analysis_version, analysis_json = row
        parsed_analysis = safe_json_loads(analysis_json, context=f"run {run_id} analysis")
        if parsed_analysis is not None and not is_json_object(parsed_analysis):
            LOGGER.warning(
                "analysis_is_current: run %s analysis_json parsed to %s, expected dict; "
                "treating as outdated",
                run_id,
                type(parsed_analysis).__name__,
            )
            return False
        if is_json_object(parsed_analysis):
            return bool(persisted_analysis_is_current(analysis_version, parsed_analysis))
        try:
            return int(analysis_version) >= ANALYSIS_SCHEMA_VERSION
        except (ValueError, TypeError):
            LOGGER.warning(
                "analysis_is_current: invalid analysis_version value %r for run %s; "
                "treating as outdated",
                analysis_version,
                run_id,
            )
            return False

    def list_runs(self: HistoryCursorProvider, limit: int = 500) -> list[JsonObject]:
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

    def get_run(self: HistoryCursorProvider, run_id: str) -> JsonObject | None:
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
                entry["analysis"] = unwrap_persisted_analysis(parsed_analysis).summary
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

    def get_run_samples(self: HistoryCursorProvider, run_id: str) -> list[JsonObject]:
        rows: list[JsonObject] = []
        for batch in self.iter_run_samples(run_id):
            rows.extend(batch)
        return rows

    def iter_run_samples(
        self: HistoryCursorProvider,
        run_id: str,
        batch_size: int = 1000,
        offset: int = 0,
    ) -> Iterator[list[JsonObject]]:
        if offset < 0:
            raise ValueError(f"iter_run_samples: offset must be >= 0, got {offset}")
        yield from self._iter_v2_samples(run_id, batch_size, offset)

    def _resolve_keyset_offset(
        self: HistoryCursorProvider,
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
        self: HistoryCursorProvider,
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

    def get_run_metadata(self: HistoryCursorProvider, run_id: str) -> JsonObject | None:
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

    def get_run_analysis(self: HistoryCursorProvider, run_id: str) -> JsonObject | None:
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
        return unwrap_persisted_analysis(parsed).summary

    def get_run_status(self: HistoryCursorProvider, run_id: str) -> str | None:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        return str(row[0]) if row else None

    def get_active_run_id(self: HistoryCursorProvider) -> str | None:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT run_id FROM runs WHERE status = 'recording' "
                "ORDER BY created_at DESC LIMIT 1",
            )
            row = cur.fetchone()
        return str(row[0]) if row else None

    def stale_analyzing_run_ids(self: HistoryCursorProvider) -> list[str]:
        with self._cursor(commit=False) as cur:
            cur.execute(
                "SELECT run_id FROM runs WHERE status = 'analyzing' "
                "ORDER BY created_at ASC LIMIT 1000",
            )
            return [str(row[0]) for row in cur.fetchall()]

    def analyzing_run_health(self: HistoryCursorProvider) -> JsonObject:
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

    def verify_run_integrity(self: HistoryCursorProvider, run_id: str) -> list[str]:
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
