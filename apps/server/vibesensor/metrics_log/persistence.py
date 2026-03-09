"""Focused history-persistence coordination for completed recording runs."""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..history_db import HistoryDB

LOGGER = logging.getLogger(__name__)

_MAX_HISTORY_CREATE_RETRIES = 5
_RETRY_COOLDOWN_BASE_S = 2.0
"""Base seconds for exponential backoff between retry cycles (doubles each cycle, capped at 10s)."""

_MAX_APPEND_RETRIES = 3
_APPEND_RETRY_DELAYS_S = (0.1, 0.3)


@dataclass(frozen=True, slots=True)
class AppendRowsResult:
    history_created: bool
    rows_written: int


class MetricsPersistenceCoordinator:
    """Owns history-run creation, sample appends, finalize, and write errors."""

    def __init__(
        self,
        *,
        history_db: HistoryDB | None,
        persist_history_db: bool,
        metadata_builder: Callable[[str, str], dict[str, object]],
        generation_matches: Callable[[int], bool],
    ) -> None:
        self._history_db = history_db
        self._persist_history_db = bool(persist_history_db)
        self._metadata_builder = metadata_builder
        self._generation_matches = generation_matches
        self._lock = RLock()
        self._history_run_created = False
        self._history_create_fail_count = 0
        self._retry_cycle_count = 0
        self._written_sample_count = 0
        self._dropped_sample_count = 0
        self._last_write_error: str | None = None
        self._retry_after_mono_s: float = 0.0
        self._last_write_duration_s: float = 0.0
        self._max_write_duration_s: float = 0.0

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

    @property
    def dropped_sample_count(self) -> int:
        with self._lock:
            return self._dropped_sample_count

    @property
    def last_write_duration_s(self) -> float:
        with self._lock:
            return self._last_write_duration_s

    @property
    def max_write_duration_s(self) -> float:
        with self._lock:
            return self._max_write_duration_s

    def reset_for_new_session(self) -> None:
        with self._lock:
            self._history_run_created = False
            self._history_create_fail_count = 0
            self._retry_cycle_count = 0
            self._written_sample_count = 0
            self._dropped_sample_count = 0
            self._last_write_error = None
            self._retry_after_mono_s = 0.0

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
        self,
        run_id: str,
        start_time_utc: str,
        *,
        session_generation: int,
    ) -> None:
        with self._lock:
            if not self._generation_matches(session_generation):
                return
            if self._history_db is None or self._history_run_created:
                return
            if self._history_create_fail_count >= _MAX_HISTORY_CREATE_RETRIES:
                # Retry after exponential backoff instead of giving up forever
                if time.monotonic() < self._retry_after_mono_s:
                    return
                self._retry_cycle_count += 1
                LOGGER.info(
                    "Retry cooldown expired for run %s; resetting "
                    "failure counter and retrying (cycle %d)",
                    run_id,
                    self._retry_cycle_count,
                )
                self._history_create_fail_count = 0
        metadata = self._metadata_builder(run_id, start_time_utc)
        try:
            self._history_db.create_run(run_id, start_time_utc, metadata)  # type: ignore[arg-type]
            with self._lock:
                if not self._generation_matches(session_generation):
                    return
                self._history_run_created = True
                self._history_create_fail_count = 0
                self._retry_cycle_count = 0
                self._retry_after_mono_s = 0.0
            self.clear_last_write_error()
        except (sqlite3.Error, OSError) as exc:
            with self._lock:
                if not self._generation_matches(session_generation):
                    return
                self._history_create_fail_count += 1
                fail_count = self._history_create_fail_count
                if fail_count >= _MAX_HISTORY_CREATE_RETRIES:
                    cooldown = min(10.0, _RETRY_COOLDOWN_BASE_S * (2**self._retry_cycle_count))
                    self._retry_after_mono_s = time.monotonic() + cooldown
            msg = (
                f"history create_run failed"
                f" (attempt {fail_count}"
                f"/{_MAX_HISTORY_CREATE_RETRIES}): {exc}"
            )
            self.set_last_write_error(msg)
            if fail_count >= _MAX_HISTORY_CREATE_RETRIES:
                cooldown = min(10.0, _RETRY_COOLDOWN_BASE_S * (2**self._retry_cycle_count))
                LOGGER.error(
                    "Persistent DB failure after %d attempts for run %s — "
                    "samples will be dropped until retry in %.1fs. Error: %s",
                    fail_count,
                    run_id,
                    cooldown,
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
                run_id,
                start_time_utc,
                session_generation=session_generation,
            )
            with self._lock:
                if not self._generation_matches(session_generation):
                    return AppendRowsResult(history_created=False, rows_written=0)
                history_created = self._history_run_created
            if history_created:
                last_exc: Exception | None = None
                for attempt in range(_MAX_APPEND_RETRIES):
                    try:
                        write_start = time.monotonic()
                        self._history_db.append_samples(run_id, rows)  # type: ignore[arg-type]
                        write_dur = time.monotonic() - write_start
                        with self._lock:
                            if not self._generation_matches(session_generation):
                                return AppendRowsResult(history_created=True, rows_written=0)
                            self._written_sample_count += len(rows)
                            self._last_write_duration_s = write_dur
                            if write_dur > self._max_write_duration_s:
                                self._max_write_duration_s = write_dur
                        self.clear_last_write_error()
                        return AppendRowsResult(history_created=True, rows_written=len(rows))
                    except (sqlite3.Error, OSError) as exc:
                        last_exc = exc
                        if attempt < _MAX_APPEND_RETRIES - 1:
                            time.sleep(_APPEND_RETRY_DELAYS_S[attempt])
                # All retries exhausted
                with self._lock:
                    self._dropped_sample_count += len(rows)
                self.set_last_write_error(f"history append_samples failed: {last_exc}")
                LOGGER.warning(
                    "Failed to append %d samples to history DB after %d attempts",
                    len(rows),
                    _MAX_APPEND_RETRIES,
                    exc_info=True,
                )
                return AppendRowsResult(history_created=True, rows_written=0)
            with self._lock:
                self._dropped_sample_count += len(rows)
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
                latest_metadata,  # type: ignore[arg-type]
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
        except (sqlite3.Error, OSError) as exc:
            self.set_last_write_error(f"history finalize_run failed: {exc}")
            LOGGER.warning("Failed to finalize run in history DB", exc_info=True)
            return False
