"""Focused history-persistence coordination for completed recording runs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import RLock

LOGGER = logging.getLogger(__name__)

_MAX_HISTORY_CREATE_RETRIES = 5


@dataclass(frozen=True, slots=True)
class AppendRowsResult:
    history_created: bool
    rows_written: int


class MetricsPersistenceCoordinator:
    """Owns history-run creation, sample appends, finalize, and write errors."""

    def __init__(
        self,
        *,
        history_db: object | None,
        persist_history_db: bool,
        metadata_builder,
        generation_matches,
    ) -> None:
        self._history_db = history_db
        self._persist_history_db = bool(persist_history_db)
        self._metadata_builder = metadata_builder
        self._generation_matches = generation_matches
        self._lock = RLock()
        self._history_run_created = False
        self._history_create_fail_count = 0
        self._written_sample_count = 0
        self._last_write_error: str | None = None

    @property
    def write_error(self) -> str | None:
        with self._lock:
            return self._last_write_error

    @property
    def history_run_created(self) -> bool:
        with self._lock:
            return self._history_run_created

    @history_run_created.setter
    def history_run_created(self, value: bool) -> None:
        with self._lock:
            self._history_run_created = bool(value)

    @property
    def history_create_fail_count(self) -> int:
        with self._lock:
            return self._history_create_fail_count

    @property
    def written_sample_count(self) -> int:
        with self._lock:
            return self._written_sample_count

    @written_sample_count.setter
    def written_sample_count(self, value: int) -> None:
        with self._lock:
            self._written_sample_count = max(0, int(value))

    def reset_for_new_session(self) -> None:
        with self._lock:
            self._history_run_created = False
            self._history_create_fail_count = 0
            self._written_sample_count = 0
            self._last_write_error = None

    def set_last_write_error(self, message: str) -> None:
        with self._lock:
            self._last_write_error = message

    def clear_last_write_error(self) -> None:
        with self._lock:
            self._last_write_error = None

    def ready_for_analysis(self, run_id: str | None) -> str | None:
        with self._lock:
            if run_id and self._history_run_created and self._written_sample_count > 0:
                return run_id
            return None

    def ensure_history_run_created(
        self, run_id: str, start_time_utc: str, *, session_generation: int
    ) -> None:
        with self._lock:
            if not self._generation_matches(session_generation):
                return
            if self._history_db is None or self._history_run_created:
                return
            if self._history_create_fail_count >= _MAX_HISTORY_CREATE_RETRIES:
                return
        metadata = self._metadata_builder(run_id, start_time_utc)
        try:
            self._history_db.create_run(run_id, start_time_utc, metadata)
            with self._lock:
                if not self._generation_matches(session_generation):
                    return
                self._history_run_created = True
                self._history_create_fail_count = 0
            self.clear_last_write_error()
        except Exception as exc:
            with self._lock:
                if not self._generation_matches(session_generation):
                    return
                self._history_create_fail_count += 1
                fail_count = self._history_create_fail_count
            msg = (
                f"history create_run failed"
                f" (attempt {fail_count}"
                f"/{_MAX_HISTORY_CREATE_RETRIES}): {exc}"
            )
            self.set_last_write_error(msg)
            if fail_count >= _MAX_HISTORY_CREATE_RETRIES:
                LOGGER.error(
                    "Persistent DB failure: giving up after %d attempts for run %s — "
                    "all subsequent samples will be dropped. Error: %s",
                    fail_count,
                    run_id,
                    exc,
                    exc_info=True,
                )
            else:
                LOGGER.warning(
                    "Failed to create history run in DB (attempt %d)",
                    fail_count,
                    exc_info=True,
                )

    def append_rows(
        self,
        *,
        run_id: str,
        start_time_utc: str,
        rows: list[dict[str, object]],
        session_generation: int,
    ) -> AppendRowsResult:
        if not rows:
            return AppendRowsResult(history_created=self.history_run_created, rows_written=0)
        if self._history_db is not None and self._persist_history_db:
            self.ensure_history_run_created(
                run_id, start_time_utc, session_generation=session_generation
            )
            with self._lock:
                if not self._generation_matches(session_generation):
                    return AppendRowsResult(history_created=False, rows_written=0)
                history_created = self._history_run_created
            if history_created:
                try:
                    self._history_db.append_samples(run_id, rows)
                    with self._lock:
                        if not self._generation_matches(session_generation):
                            return AppendRowsResult(history_created=True, rows_written=0)
                        self._written_sample_count += len(rows)
                    self.clear_last_write_error()
                    return AppendRowsResult(history_created=True, rows_written=len(rows))
                except Exception as exc:
                    self.set_last_write_error(f"history append_samples failed: {exc}")
                    LOGGER.warning("Failed to append samples to history DB", exc_info=True)
                    return AppendRowsResult(history_created=True, rows_written=0)
            with self._lock:
                fail_count = self._history_create_fail_count
            LOGGER.warning(
                "Dropping %d sample(s) for run %s: history run not created (fail count %d/%d)",
                len(rows),
                run_id,
                fail_count,
                _MAX_HISTORY_CREATE_RETRIES,
            )
            return AppendRowsResult(history_created=False, rows_written=0)
        with self._lock:
            if not self._generation_matches(session_generation):
                return AppendRowsResult(history_created=False, rows_written=0)
            self._written_sample_count += len(rows)
        return AppendRowsResult(history_created=False, rows_written=len(rows))

    def finalize_run(self, run_id: str, start_time_utc: str, end_utc: str) -> bool:
        with self._lock:
            if not self._history_run_created:
                return True
        if self._history_db is None:
            return True
        try:
            latest_metadata = self._metadata_builder(run_id, start_time_utc)
            latest_metadata["end_time_utc"] = end_utc
            finalized = self._history_db.finalize_run_with_metadata(
                run_id,
                end_utc,
                latest_metadata,
            )
            if finalized is False:
                self.set_last_write_error("history finalize_run skipped due to invalid state")
                LOGGER.warning(
                    "History DB finalize_run_with_metadata skipped for run %s",
                    run_id,
                )
                return False
            self.clear_last_write_error()
            return True
        except Exception as exc:
            self.set_last_write_error(f"history finalize_run failed: {exc}")
            LOGGER.warning("Failed to finalize run in history DB", exc_info=True)
            return False
