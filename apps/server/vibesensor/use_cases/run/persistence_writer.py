"""History-persistence coordination extracted from ``RunRecorder``.

``RunPersistenceWriter`` owns history-run creation, sample appends,
finalization, retry/backoff handling, and persistence health counters above
the injected ``RunPersistence`` boundary.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from threading import RLock
from typing import Any

import aiosqlite

from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame


def _sync_call[T](db: Any, coro: Awaitable[T]) -> T:
    """Synchronously resolve *coro* bound to *db*.

    If *db* exposes a persistent engine loop, route through it so
    aiosqlite futures resolve on the owning loop. Otherwise fall back
    to ``asyncio.run`` (test stubs) which creates a short-lived loop.
    """
    runner = getattr(db, "_run_on_engine_loop", None)
    if callable(runner):
        return runner(coro)  # type: ignore[no-any-return]

    async def _runner() -> T:
        return await coro

    return asyncio.run(_runner())


__all__ = [
    "AppendRowsResult",
    "PersistenceStatusSnapshot",
    "RunPersistenceWriter",
    "_APPEND_RETRY_DELAYS_S",
    "_MAX_APPEND_RETRIES",
    "_MAX_HISTORY_CREATE_RETRIES",
    "_RETRY_COOLDOWN_BASE_S",
]

_MAX_HISTORY_CREATE_RETRIES = 5
_RETRY_COOLDOWN_BASE_S = 2.0
"""Base seconds for exponential backoff between retry cycles."""
_MAX_APPEND_RETRIES = 3
_APPEND_RETRY_DELAYS_S = (0.1, 0.3)

MetadataBuilder = Callable[[str, str], RunMetadata]
RunIdMatcher = Callable[[str], bool]
LoggerProvider = Callable[[], logging.Logger]
MonotonicFn = Callable[[], float]
SleepFn = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class PersistenceStatusSnapshot:
    """Bulk snapshot of persistence status fields (single lock acquisition)."""

    write_error: str | None
    written_sample_count: int
    dropped_sample_count: int


@dataclass(frozen=True, slots=True)
class AppendRowsResult:
    history_created: bool
    rows_written: int


class RunPersistenceWriter:
    """Coordinate history persistence for the active run."""

    def __init__(
        self,
        *,
        lock: RLock,
        history_db: RunPersistence | None,
        persist_history_db_enabled: bool,
        run_id_matches: RunIdMatcher,
        metadata_builder: MetadataBuilder,
        monotonic: MonotonicFn,
        sleep: SleepFn,
        logger_provider: LoggerProvider,
    ) -> None:
        self._lock = lock
        self._history_db = history_db
        self._history_db_enabled = bool(persist_history_db_enabled)
        self._run_id_matches = run_id_matches
        self._metadata_builder = metadata_builder
        self._monotonic = monotonic
        self._sleep = sleep
        self._logger_provider = logger_provider
        self._last_write_duration_s = 0.0
        self._max_write_duration_s = 0.0
        self.reset()

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

    @history_create_fail_count.setter
    def history_create_fail_count(self, value: int) -> None:
        with self._lock:
            self._history_create_fail_count = int(value)

    @property
    def written_sample_count(self) -> int:
        with self._lock:
            return self._written_sample_count

    @written_sample_count.setter
    def written_sample_count(self, value: int) -> None:
        with self._lock:
            self._written_sample_count = int(value)

    @property
    def dropped_sample_count(self) -> int:
        with self._lock:
            return self._dropped_sample_count

    @dropped_sample_count.setter
    def dropped_sample_count(self, value: int) -> None:
        with self._lock:
            self._dropped_sample_count = int(value)

    @property
    def last_write_error(self) -> str | None:
        with self._lock:
            return self._last_write_error

    @last_write_error.setter
    def last_write_error(self, value: str | None) -> None:
        with self._lock:
            self._last_write_error = value

    @property
    def last_write_duration_s(self) -> float:
        with self._lock:
            return self._last_write_duration_s

    @property
    def max_write_duration_s(self) -> float:
        with self._lock:
            return self._max_write_duration_s

    def set_last_write_error(self, message: str | None) -> None:
        with self._lock:
            self._last_write_error = message

    def clear_last_write_error(self) -> None:
        with self._lock:
            self._last_write_error = None

    def status_snapshot(self) -> PersistenceStatusSnapshot:
        with self._lock:
            return PersistenceStatusSnapshot(
                write_error=self._last_write_error,
                written_sample_count=self._written_sample_count,
                dropped_sample_count=self._dropped_sample_count,
            )

    def reset(self) -> None:
        with self._lock:
            self._history_run_created = False
            self._history_create_fail_count = 0
            self._retry_cycle_count = 0
            self._written_sample_count = 0
            self._dropped_sample_count = 0
            self._last_write_error = None
            self._retry_after_mono_s = 0.0

    def ready_for_analysis(self, run_id: str | None) -> str | None:
        with self._lock:
            ready = run_id and self._history_run_created and self._written_sample_count > 0
            if ready:
                return run_id
            return None

    def ensure_history_run(
        self,
        run_id: str,
        start_time_utc: str,
    ) -> None:
        history_db = self._history_db
        with self._lock:
            if not self._run_id_matches(run_id):
                return
            if history_db is None or self._history_run_created:
                return
            if self._history_create_fail_count >= _MAX_HISTORY_CREATE_RETRIES:
                if self._monotonic() < self._retry_after_mono_s:
                    return
                self._retry_cycle_count += 1
                self._logger_provider().info(
                    "Retry cooldown expired for run %s; resetting failure counter "
                    "and retrying (cycle %d)",
                    run_id,
                    self._retry_cycle_count,
                )
                self._history_create_fail_count = 0
        metadata = self._metadata_builder(run_id, start_time_utc)
        try:
            _sync_call(history_db, history_db.acreate_run(run_id, start_time_utc, metadata))
            with self._lock:
                if not self._run_id_matches(run_id):
                    return
                self._history_run_created = True
                self._history_create_fail_count = 0
                self._retry_cycle_count = 0
                self._retry_after_mono_s = 0.0
            self.clear_last_write_error()
        except (aiosqlite.Error, OSError) as exc:
            with self._lock:
                if not self._run_id_matches(run_id):
                    return
                self._history_create_fail_count += 1
                fail_count = self._history_create_fail_count
                if fail_count >= _MAX_HISTORY_CREATE_RETRIES:
                    cooldown = min(
                        10.0,
                        _RETRY_COOLDOWN_BASE_S * (2**self._retry_cycle_count),
                    )
                    self._retry_after_mono_s = self._monotonic() + cooldown
                else:
                    cooldown = None
            msg = (
                f"history create_run failed"
                f" (attempt {fail_count}"
                f"/{_MAX_HISTORY_CREATE_RETRIES}): {exc}"
            )
            self.set_last_write_error(msg)
            if cooldown is not None:
                self._logger_provider().error(
                    "Persistent DB failure after %d attempts for run %s — "
                    "samples will be dropped until retry in %.1fs. Error: %s",
                    fail_count,
                    run_id,
                    cooldown,
                    exc,
                    exc_info=True,
                )
            else:
                self._logger_provider().warning(
                    "Failed to create history run in DB (attempt %d)",
                    fail_count,
                    exc_info=True,
                )

    def append_rows(
        self,
        *,
        run_id: str,
        start_time_utc: str,
        rows: list[SensorFrame],
    ) -> AppendRowsResult:
        history_db = self._history_db
        if not rows:
            return AppendRowsResult(
                history_created=self.history_run_created,
                rows_written=0,
            )
        if history_db is not None and self._history_db_enabled:
            self.ensure_history_run(run_id, start_time_utc)
            with self._lock:
                if not self._run_id_matches(run_id):
                    return AppendRowsResult(history_created=False, rows_written=0)
                history_created = self._history_run_created
            if history_created:
                last_exc: Exception | None = None
                for attempt in range(_MAX_APPEND_RETRIES):
                    try:
                        write_start = self._monotonic()
                        rows_written = _sync_call(
                            history_db, history_db.aappend_samples(run_id, rows)
                        )
                        write_dur = self._monotonic() - write_start
                        with self._lock:
                            if not self._run_id_matches(run_id):
                                return AppendRowsResult(history_created=True, rows_written=0)
                            self._last_write_duration_s = write_dur
                            if write_dur > self._max_write_duration_s:
                                self._max_write_duration_s = write_dur
                            if rows_written > 0:
                                self._written_sample_count += rows_written
                            else:
                                self._dropped_sample_count += len(rows)
                        if rows_written <= 0:
                            self._logger_provider().warning(
                                "History DB rejected %d sample(s) for run %s because the run "
                                "is no longer recording",
                                len(rows),
                                run_id,
                            )
                            return AppendRowsResult(history_created=True, rows_written=0)
                        self.clear_last_write_error()
                        return AppendRowsResult(history_created=True, rows_written=rows_written)
                    except (aiosqlite.Error, OSError) as exc:
                        last_exc = exc
                        if attempt < _MAX_APPEND_RETRIES - 1:
                            self._sleep(_APPEND_RETRY_DELAYS_S[attempt])
                with self._lock:
                    self._dropped_sample_count += len(rows)
                self.set_last_write_error(f"history append_samples failed: {last_exc}")
                self._logger_provider().warning(
                    "Failed to append %d samples to history DB after %d attempts",
                    len(rows),
                    _MAX_APPEND_RETRIES,
                    exc_info=True,
                )
                return AppendRowsResult(history_created=True, rows_written=0)
            with self._lock:
                self._dropped_sample_count += len(rows)
                fail_count = self._history_create_fail_count
            self._logger_provider().warning(
                "Dropping %d sample(s) for run %s: history run not created (fail count %d/%d)",
                len(rows),
                run_id,
                fail_count,
                _MAX_HISTORY_CREATE_RETRIES,
            )
            return AppendRowsResult(history_created=False, rows_written=0)
        with self._lock:
            if not self._run_id_matches(run_id):
                return AppendRowsResult(history_created=False, rows_written=0)
            self._written_sample_count += len(rows)
        return AppendRowsResult(history_created=False, rows_written=len(rows))

    def finalize_run(self, run_id: str, start_time_utc: str, end_utc: str) -> bool:
        history_db = self._history_db
        with self._lock:
            if not self._history_run_created:
                return True
        if history_db is None:
            return True
        try:
            latest_metadata = self._metadata_builder(run_id, start_time_utc)
            latest_metadata.end_time_utc = end_utc
            finalized = _sync_call(
                history_db,
                history_db.afinalize_run(
                    run_id,
                    end_utc,
                    metadata=latest_metadata,
                ),
            )
            if finalized is False:
                self.set_last_write_error("history finalize_run skipped due to invalid state")
                self._logger_provider().warning(
                    "History DB finalize_run skipped for run %s",
                    run_id,
                )
                return False
            self.clear_last_write_error()
            return True
        except (aiosqlite.Error, OSError) as exc:
            self.set_last_write_error(f"history finalize_run failed: {exc}")
            self._logger_provider().warning(
                "Failed to finalize run in history DB",
                exc_info=True,
            )
            return False
