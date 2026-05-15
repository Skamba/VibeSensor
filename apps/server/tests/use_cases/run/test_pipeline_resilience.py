"""Tests for recording pipeline error visibility and resilience.

Covers:
- Drop counting in RunRecorder persistence coordination
- Retry cooldown after max DB create failures
- Last analysis outcome tracking in PostAnalysisWorker
- Queue depth warning in PostAnalysisWorker
- Enriched RecordingStatusResponse fields
- Health endpoint degradation reasons for dropped samples and analysis errors
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from unittest.mock import patch

import pytest

from vibesensor.domain import Run
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frame_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.use_cases.run.logger import (
    _MAX_HISTORY_CREATE_RETRIES,
    _RETRY_COOLDOWN_BASE_S,
    RunRecorder,
)
from vibesensor.use_cases.run.post_analysis import _WARN_QUEUE_DEPTH, PostAnalysisWorker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_metadata(run_id: str, *, language: str = "en") -> RunMetadata:
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 800,
            "sample_rate_hz": 800,
            "feature_interval_s": 1.0,
            "language": language,
        }
    )


def _make_persist_logger(make_logger, *, history_db: object, run_id: str = "run-1") -> RunRecorder:
    """Build a RunRecorder with the given DB and set up persistence for *run_id*."""
    logger = make_logger(history_db=history_db)
    logger._lifecycle.current_run = Run(run_id=run_id)
    logger._persistence.reset()
    return logger


def _sample_rows(count: int) -> list[SensorFrame]:
    return [sensor_frame_from_mapping({"t_s": float(i)}) for i in range(count)]


class _FailingDB:
    """History DB that always fails on create_run."""

    async def acreate_run(self, run_id: str, start_time_utc: str, metadata: RunMetadata) -> None:
        raise sqlite3.OperationalError("db locked")


class _FailingAppendDB:
    """History DB that succeeds on create_run but fails on append."""

    async def acreate_run(self, run_id: str, start_time_utc: str, metadata: RunMetadata) -> None:
        pass

    async def aappend_samples(self, run_id: str, samples: list[SensorFrame]) -> int:
        raise sqlite3.OperationalError("disk full")


class _FailNAppendThenSucceedDB:
    """History DB that fails append_samples N times then succeeds."""

    def __init__(self, fail_count: int) -> None:
        self._remaining = fail_count
        self.appended: list[tuple[str, int]] = []

    async def acreate_run(self, run_id: str, start_time_utc: str, metadata: RunMetadata) -> None:
        pass

    async def aappend_samples(self, run_id: str, samples: list[SensorFrame]) -> int:
        if self._remaining > 0:
            self._remaining -= 1
            raise sqlite3.OperationalError("db locked")
        self.appended.append((run_id, len(samples)))
        return len(samples)


class _SucceedingDB:
    """History DB that always succeeds."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.appended: list[tuple[str, int]] = []

    async def acreate_run(self, run_id: str, start_time_utc: str, metadata: RunMetadata) -> None:
        self.created.append(run_id)

    async def aappend_samples(self, run_id: str, samples: list[SensorFrame]) -> int:
        self.appended.append((run_id, len(samples)))
        return len(samples)


class _FailNThenSucceedDB:
    """Fails create_run N times then succeeds."""

    def __init__(self, fail_count: int) -> None:
        self._remaining = fail_count
        self.created: list[str] = []

    async def acreate_run(self, run_id: str, start_time_utc: str, metadata: RunMetadata) -> None:
        if self._remaining > 0:
            self._remaining -= 1
            raise sqlite3.OperationalError("transient error")
        self.created.append(run_id)

    async def aappend_samples(self, run_id: str, samples: list[SensorFrame]) -> int:
        return len(samples)


# ---------------------------------------------------------------------------
# Persistence coordination drop tracking
# ---------------------------------------------------------------------------


class TestDropCounting:
    def test_initial_drop_count_is_zero(self, make_logger) -> None:
        logger = _make_persist_logger(make_logger, history_db=_SucceedingDB())
        assert logger._persistence.dropped_sample_count == 0

    def test_drops_counted_when_create_run_exhausted(self, make_logger) -> None:
        """After max create retries, appending rows counts them as dropped."""
        logger = _make_persist_logger(make_logger, history_db=_FailingDB())

        # Exhaust retries
        for _ in range(_MAX_HISTORY_CREATE_RETRIES):
            logger._persistence.ensure_history_run("run-1", "2025-01-01T00:00:00Z")

        assert logger._persistence.history_create_fail_count >= _MAX_HISTORY_CREATE_RETRIES

        # Now append — should be dropped and counted
        result = logger._persistence.append_rows(
            run_id="run-1",
            start_time_utc="2025-01-01T00:00:00Z",
            rows=_sample_rows(3),
        )
        assert result.rows_written == 0
        assert logger._persistence.dropped_sample_count == 3

    def test_drops_counted_on_append_failure(self, make_logger) -> None:
        """When append_samples throws on all retries, dropped count is incremented."""
        logger = _make_persist_logger(make_logger, history_db=_FailingAppendDB())

        logger._persistence.ensure_history_run("run-1", "2025-01-01T00:00:00Z")
        assert logger._persistence.history_run_created

        result = logger._persistence.append_rows(
            run_id="run-1",
            start_time_utc="2025-01-01T00:00:00Z",
            rows=_sample_rows(2),
        )
        assert result.rows_written == 0
        assert logger._persistence.dropped_sample_count == 2

    def test_append_retries_on_transient_failure(self, make_logger) -> None:
        """Append retries on transient SQLite errors and succeeds."""
        db = _FailNAppendThenSucceedDB(fail_count=1)
        logger = _make_persist_logger(make_logger, history_db=db)

        logger._persistence.ensure_history_run("run-1", "2025-01-01T00:00:00Z")
        assert logger._persistence.history_run_created

        result = logger._persistence.append_rows(
            run_id="run-1",
            start_time_utc="2025-01-01T00:00:00Z",
            rows=_sample_rows(2),
        )
        assert result.rows_written == 2
        assert logger._persistence.dropped_sample_count == 0
        assert db.appended == [("run-1", 2)]

    def test_drops_accumulate_across_calls(self, make_logger) -> None:
        """Drop count accumulates across multiple append calls."""
        logger = _make_persist_logger(make_logger, history_db=_FailingAppendDB())
        logger._persistence.ensure_history_run("run-1", "2025-01-01T00:00:00Z")

        for _ in range(3):
            logger._persistence.append_rows(
                run_id="run-1",
                start_time_utc="2025-01-01T00:00:00Z",
                rows=_sample_rows(1),
            )
        assert logger._persistence.dropped_sample_count == 3

    def test_drops_reset_on_new_session(self, make_logger) -> None:
        """Drop count resets to 0 when a new session starts."""
        logger = _make_persist_logger(make_logger, history_db=_FailingAppendDB())
        logger._persistence.ensure_history_run("run-1", "2025-01-01T00:00:00Z")
        logger._persistence.append_rows(
            run_id="run-1",
            start_time_utc="2025-01-01T00:00:00Z",
            rows=_sample_rows(2),
        )
        assert logger._persistence.dropped_sample_count == 2

        logger._persistence.reset()
        assert logger._persistence.dropped_sample_count == 0

    def test_successful_writes_do_not_increment_drops(self, make_logger) -> None:
        """Normal successful writes don't affect drop counter."""
        logger = _make_persist_logger(make_logger, history_db=_SucceedingDB())
        logger._persistence.ensure_history_run("run-1", "2025-01-01T00:00:00Z")
        result = logger._persistence.append_rows(
            run_id="run-1",
            start_time_utc="2025-01-01T00:00:00Z",
            rows=_sample_rows(2),
        )
        assert result.rows_written == 2
        assert logger._persistence.dropped_sample_count == 0


# ---------------------------------------------------------------------------
# Retry cooldown
# ---------------------------------------------------------------------------


class TestRetryCooldown:
    def test_retries_after_cooldown_expires(self, make_logger) -> None:
        """After hitting max retries, logger retries when cooldown expires."""
        # Fail 5 times, then succeed
        db = _FailNThenSucceedDB(fail_count=_MAX_HISTORY_CREATE_RETRIES)
        logger = _make_persist_logger(make_logger, history_db=db)

        # Exhaust retries
        for _ in range(_MAX_HISTORY_CREATE_RETRIES):
            logger._persistence.ensure_history_run("run-1", "2025-01-01T00:00:00Z")

        assert not logger._persistence.history_run_created
        assert logger._persistence.history_create_fail_count >= _MAX_HISTORY_CREATE_RETRIES

        # Before cooldown — should still be blocked
        logger._persistence.ensure_history_run("run-1", "2025-01-01T00:00:00Z")
        assert not logger._persistence.history_run_created

        # Fast-forward past cooldown
        with patch("vibesensor.use_cases.run.logger.time") as mock_time:
            # First call: check if past cooldown (return time after cooldown)
            mock_time.monotonic.return_value = time.monotonic() + _RETRY_COOLDOWN_BASE_S + 1
            logger._persistence.ensure_history_run("run-1", "2025-01-01T00:00:00Z")

        assert logger._persistence.history_run_created
        assert db.created == ["run-1"]

    def test_no_cooldown_during_initial_retries(self, make_logger) -> None:
        """Within the retry budget, retries happen immediately."""
        db = _FailNThenSucceedDB(fail_count=3)
        logger = _make_persist_logger(make_logger, history_db=db)

        for _ in range(4):
            logger._persistence.ensure_history_run("run-1", "2025-01-01T00:00:00Z")

        assert logger._persistence.history_run_created

    def test_cooldown_resets_on_new_session(self, make_logger) -> None:
        """Cooldown state resets when a new session starts."""
        logger = _make_persist_logger(make_logger, history_db=_FailingDB())

        # Exhaust retries
        for _ in range(_MAX_HISTORY_CREATE_RETRIES):
            logger._persistence.ensure_history_run("run-1", "2025-01-01T00:00:00Z")

        logger._lifecycle.current_run = Run(run_id="run-2")
        logger._persistence.reset()
        assert logger._persistence.history_create_fail_count == 0
        # Should be able to retry immediately after reset
        logger._persistence.ensure_history_run("run-2", "2025-01-01T00:00:00Z")
        # Will fail (DB still failing), but it should attempt (count incremented)
        assert logger._persistence.history_create_fail_count == 1


# ---------------------------------------------------------------------------
# PostAnalysisWorker — last completed outcome tracking
# ---------------------------------------------------------------------------


class TestPostAnalysisOutcomeTracking:
    @pytest.fixture
    def make_worker(self):
        _sentinel = object()

        def _factory(*, run_fn=None, history_db=_sentinel, **kwargs):
            worker = PostAnalysisWorker(history_db=history_db, **kwargs)
            if run_fn is not None:
                worker._run_post_analysis = run_fn
            return worker

        return _factory

    def test_outcome_none_initially(self) -> None:
        worker = PostAnalysisWorker(history_db=None)
        snapshot = worker.snapshot()
        assert snapshot.last_completed_run_id is None
        assert snapshot.last_completed_error is None

    def test_worker_runs_injected_post_analysis_function(self, make_worker) -> None:
        run_calls: list[str] = []
        worker = make_worker(run_fn=run_calls.append)
        worker.schedule("run-ok")
        assert worker.wait(timeout_s=2.0)

        snapshot = worker.snapshot()
        assert run_calls == ["run-ok"]
        assert snapshot.queue_depth == 0
        assert snapshot.active_run_id is None

    def test_outcome_after_real_analysis_success(self) -> None:
        """Last completed outcome is set after successful analysis."""

        class FakeDB:
            async def aget_run_metadata(self, run_id):
                return _run_metadata(run_id, language="en")

            async def aiter_run_samples(self, run_id, batch_size=1024):
                yield [
                    sensor_frame_from_mapping(
                        {
                            "x": 0.1,
                            "y": 0.2,
                            "z": 0.3,
                            "t_s": 1.0,
                            "vibration_strength_db": 10.0,
                            "strength_bucket": "l1",
                            "peak_amp_g": 0.05,
                            "noise_floor_amp_g": 0.001,
                        }
                    ),
                ]

            async def astore_analysis(self, run_id, analysis):
                pass

            async def astore_analysis_error(self, run_id, msg):
                pass

        worker = PostAnalysisWorker(history_db=FakeDB())
        worker.schedule("run-ok")
        assert worker.wait(timeout_s=5.0)

        snapshot = worker.snapshot()
        assert snapshot.last_completed_run_id == "run-ok"
        assert snapshot.last_completed_error is None

    def test_outcome_after_analysis_failure(self) -> None:
        """Last completed outcome records the error on failure."""
        errors: list[str] = []

        class FakeDB:
            async def aget_run_metadata(self, run_id):
                return _run_metadata(run_id, language="en")

            async def aiter_run_samples(self, run_id, batch_size=1024):
                if False:
                    yield []
                raise RuntimeError("sample read boom")

            async def astore_analysis_error(self, run_id, msg):
                pass

        worker = PostAnalysisWorker(
            history_db=FakeDB(),
            error_callback=lambda msg: errors.append(msg),
        )
        worker.schedule("run-fail")
        assert worker.wait(timeout_s=3.0)

        snapshot = worker.snapshot()
        assert snapshot.last_completed_run_id == "run-fail"
        assert "sample read boom" in (snapshot.last_completed_error or "")

    def test_outcome_after_no_metadata(self) -> None:
        """Missing metadata sets error outcome."""

        class FakeDB:
            async def aget_run_metadata(self, _run_id):
                return None

            async def astore_analysis_error(self, _run_id, _msg):
                pass

        worker = PostAnalysisWorker(history_db=FakeDB())
        worker.schedule("run-nometa")
        assert worker.wait(timeout_s=3.0)

        snapshot = worker.snapshot()
        assert snapshot.last_completed_run_id == "run-nometa"
        assert snapshot.last_completed_error is not None
        assert "Metadata" in snapshot.last_completed_error

    def test_outcome_after_no_samples(self) -> None:
        """Empty sample set sets error outcome."""

        class FakeDB:
            async def aget_run_metadata(self, _run_id):
                return _run_metadata("run-empty", language="en")

            async def aiter_run_samples(self, _run_id, batch_size=1024):
                if False:
                    yield []
                return

            async def astore_analysis_error(self, _run_id, _msg):
                pass

        worker = PostAnalysisWorker(history_db=FakeDB())
        worker.schedule("run-empty")
        assert worker.wait(timeout_s=3.0)

        snapshot = worker.snapshot()
        assert snapshot.last_completed_run_id == "run-empty"
        assert "samples" in (snapshot.last_completed_error or "").lower()


# ---------------------------------------------------------------------------
# PostAnalysisWorker — queue depth warning
# ---------------------------------------------------------------------------


class TestQueueDepthWarning:
    def test_warning_logged_at_threshold(self, caplog: pytest.LogCaptureFixture) -> None:
        """A warning is logged when queue depth reaches the threshold."""
        started = threading.Event()
        release = threading.Event()

        def _block(_rid: str) -> None:
            started.set()
            release.wait(timeout=5.0)

        worker = PostAnalysisWorker(history_db=None)
        worker._run_post_analysis = _block

        # Schedule one to block the worker
        worker.schedule("run-0")
        started.wait(timeout=2.0)

        # Fill queue past threshold
        with caplog.at_level(logging.WARNING, logger="vibesensor.use_cases.run.post_analysis"):
            for i in range(1, _WARN_QUEUE_DEPTH + 1):
                worker.schedule(f"run-{i}")

        release.set()
        worker.wait(timeout_s=5.0)

        assert any("queue depth" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# RecordingStatusResponse enrichment
# ---------------------------------------------------------------------------


class TestLoggingStatusEnrichment:
    def test_status_includes_sample_counts(self, make_logger, tmp_path) -> None:
        """Status response includes samples_written and samples_dropped."""
        from tests.use_cases.run.conftest import _FakeHistoryDB

        db = _FakeHistoryDB()
        logger = make_logger(history_db=db)

        status = logger.status()
        assert status.samples_written == 0
        assert status.samples_dropped == 0

    def test_status_includes_active_run_start_time(self, make_logger, tmp_path) -> None:
        """Status response includes the active run start time when recording."""
        logger = make_logger()

        assert logger.status().start_time_utc is None

        started = logger.start_recording()
        status = logger.status()

        assert started.start_time_utc is not None
        assert status.start_time_utc == started.start_time_utc

    def test_status_includes_last_completed_fields(self, make_logger, tmp_path) -> None:
        """Status response includes last_completed_run_id and last_completed_run_error."""
        logger = make_logger()

        status = logger.status()
        assert status.last_completed_run_id is None
        assert status.last_completed_run_error is None


# ---------------------------------------------------------------------------
# Health snapshot enrichment
# ---------------------------------------------------------------------------


class TestHealthSnapshotEnrichment:
    def test_health_includes_sample_counters(self, make_logger, tmp_path) -> None:
        """Health snapshot includes samples_written and samples_dropped."""
        logger = make_logger()

        health = logger.health_snapshot()
        assert "samples_written" in health
        assert "samples_dropped" in health
        assert health["samples_written"] == 0
        assert health["samples_dropped"] == 0

    def test_health_includes_last_completed(self, make_logger, tmp_path) -> None:
        """Health snapshot includes last_completed_run_id and last_completed_run_error."""
        logger = make_logger()

        health = logger.health_snapshot()
        assert "last_completed_run_id" in health
        assert "last_completed_run_error" in health

    def test_drops_reflected_after_append_failure(self, make_logger, tmp_path) -> None:
        """After a failed append, health and status both show the drop count."""
        from tests.use_cases.run.conftest import _FailingAppendOnceHistoryDB

        db = _FailingAppendOnceHistoryDB()
        logger = make_logger(history_db=db)

        logger.start_recording()
        snapshot = logger._session_snapshot()
        assert snapshot is not None

        logger._sample_flush.append_records(
            snapshot.run_id,
            snapshot.start_time_utc,
            snapshot.start_mono_s,
        )

        health = logger.health_snapshot()
        status = logger.status()

        # First append fails → drops counted
        assert health["samples_dropped"] > 0
        assert status.samples_dropped > 0
