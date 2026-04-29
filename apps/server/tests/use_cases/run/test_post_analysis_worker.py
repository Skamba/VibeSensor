"""Unit tests for vibesensor.use_cases.run.post_analysis.PostAnalysisWorker.

These tests exercise the background analysis worker independently of
RunRecorder, validating queue management, threading, and error handling.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass

import pytest

from tests.test_support.persisted_analysis import make_persisted_analysis
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.run.post_analysis import PostAnalysisWorker

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_worker():
    """Factory for PostAnalysisWorker with an optional mock ``_run_post_analysis``."""
    _sentinel = object()

    def _factory(*, run_fn=None, history_db=_sentinel, **kwargs):
        worker = PostAnalysisWorker(history_db=history_db, **kwargs)
        if run_fn is not None:
            worker._run_post_analysis = run_fn
        return worker

    return _factory


# ---------------------------------------------------------------------------
# Tests
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


@dataclass(frozen=True, slots=True)
class _StoredRun:
    metadata: RunMetadata
    sample_count: int


def _patch_fast_retry_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis._RETRY_DELAYS_S",
        (0.01, 0.02, 0.03),
    )


class TestPostAnalysisWorkerSchedule:
    def test_schedule_and_process(self, make_worker) -> None:
        """Worker processes a scheduled run."""
        seen: list[str] = []
        worker = make_worker(run_fn=lambda rid: seen.append(rid))

        worker.schedule("run-1")
        assert worker.wait(timeout_s=2.0)
        assert seen == ["run-1"]

    def test_schedule_multiple(self, make_worker) -> None:
        """Multiple runs are processed in order."""
        seen: list[str] = []
        worker = make_worker(run_fn=lambda rid: seen.append(rid))

        for i in range(5):
            worker.schedule(f"run-{i}")
        assert worker.wait(timeout_s=3.0)
        assert seen == [f"run-{i}" for i in range(5)]

    def test_duplicate_run_id_ignored(self, make_worker) -> None:
        """Scheduling the same run_id twice is a no-op."""
        seen: list[str] = []
        barrier = threading.Event()

        def _slow(rid: str) -> None:
            barrier.wait(timeout=2.0)
            seen.append(rid)

        worker = make_worker(run_fn=_slow)

        worker.schedule("run-dup")
        worker.schedule("run-dup")  # duplicate
        barrier.set()
        assert worker.wait(timeout_s=3.0)
        assert seen == ["run-dup"]

    def test_queue_does_not_evict_when_many_runs_are_scheduled(self, make_worker) -> None:
        seen: list[str] = []
        worker = make_worker(run_fn=lambda rid: seen.append(rid))

        for index in range(105):
            worker.schedule(f"run-{index}")

        assert worker.wait(timeout_s=5.0)
        assert seen == [f"run-{index}" for index in range(105)]


class TestPostAnalysisWorkerIsActive:
    def test_inactive_when_idle(self) -> None:
        worker = PostAnalysisWorker(history_db=None)
        assert not worker.is_active

    def test_active_during_work(self, make_worker) -> None:
        started = threading.Event()
        release = threading.Event()

        def _block(rid: str) -> None:
            started.set()
            release.wait(timeout=5.0)

        worker = make_worker(run_fn=_block)

        worker.schedule("run-active")
        started.wait(timeout=2.0)
        assert worker.is_active
        assert worker.active_run_id == "run-active"
        release.set()
        assert worker.wait(timeout_s=2.0)
        assert not worker.is_active


class TestPostAnalysisWorkerSnapshot:
    def test_snapshot_tracks_queue_depth_and_max_depth(self, make_worker) -> None:
        started = threading.Event()
        release = threading.Event()

        def _block(_rid: str) -> None:
            started.set()
            release.wait(timeout=5.0)

        worker = make_worker(run_fn=_block)

        worker.schedule("run-1")
        started.wait(timeout=2.0)
        worker.schedule("run-2")

        snapshot = worker.snapshot()

        assert snapshot.queue_depth == 1
        assert snapshot.active_run_id == "run-1"
        assert snapshot.max_queue_depth >= 1
        assert snapshot.oldest_queued_at is not None
        release.set()
        assert worker.wait(timeout_s=2.0)


class TestPostAnalysisWorkerWait:
    def test_wait_no_work_returns_immediately(self) -> None:
        worker = PostAnalysisWorker(history_db=None)
        assert worker.wait(timeout_s=0.1)

    def test_wait_timeout(self, make_worker) -> None:
        release = threading.Event()
        worker = make_worker(run_fn=lambda rid: release.wait(timeout=5.0))

        worker.schedule("run-slow")
        result = worker.wait(timeout_s=0.1)
        assert result is False
        release.set()
        worker.wait(timeout_s=2.0)

    def test_shutdown_clears_pending_queue_after_timeout(self, make_worker) -> None:
        started = threading.Event()
        release = threading.Event()
        seen: list[str] = []

        def _block(rid: str) -> None:
            started.set()
            release.wait(timeout=5.0)
            seen.append(rid)

        worker = make_worker(run_fn=_block)
        worker.schedule("run-1")
        started.wait(timeout=2.0)
        worker.schedule("run-2")

        assert worker.shutdown(timeout_s=0.01) is False

        release.set()
        assert worker.wait(timeout_s=2.0)
        assert seen == ["run-1"]


class TestPostAnalysisWorkerErrorHandling:
    def test_injected_analysis_runner_receives_loaded_run_inputs(self) -> None:
        captured: dict[str, object] = {}
        stored: dict[str, object] = {}

        class FakeDB:
            async def aget_run_metadata(self, run_id):
                assert run_id == "run-ok"
                return _run_metadata(run_id, language="nl")

            async def aiter_run_samples(self, run_id, batch_size=1024):
                assert run_id == "run-ok"
                yield sensor_frames_from_mappings(
                    [
                        {"t_s": 1.0, "vibration_strength_db": 10.0},
                        {"t_s": 2.0, "vibration_strength_db": 11.0},
                    ]
                )

            async def astore_analysis(self, run_id, analysis):
                stored["run_id"] = run_id
                stored["analysis"] = analysis

            async def astore_analysis_error(self, run_id, msg):
                raise AssertionError(f"unexpected error storage for {run_id}: {msg}")

        def _analysis_runner(run):
            captured.update(
                {
                    "run_id": run.run_id,
                    "context": run.context,
                    "samples": run.samples,
                    "language": run.language,
                    "total_sample_count": run.total_summary_row_count,
                    "stride": run.stride,
                }
            )
            return {
                "lang": run.language,
                "row_count": len(run.samples),
                "analysis_metadata": {
                    "analyzed_sample_count": len(run.samples),
                    "total_sample_count": run.total_summary_row_count,
                    "sampling_method": ("full" if run.stride == 1 else f"stride_{run.stride}"),
                },
                "run_suitability": [],
            }

        worker = PostAnalysisWorker(
            history_db=FakeDB(),
            analysis_runner=_analysis_runner,
        )
        worker.schedule("run-ok")
        assert worker.wait(timeout_s=3.0)

        assert captured["run_id"] == "run-ok"
        assert captured["language"] == "nl"
        assert captured["total_sample_count"] == 2
        assert captured["stride"] == 1
        assert len(captured["samples"]) == 2
        assert captured["context"].run_id == "run-ok"
        assert stored["run_id"] == "run-ok"
        assert stored["analysis"]["lang"] == "nl"

    def test_error_callback_on_failure(self) -> None:
        """Error callback is invoked when analysis raises."""
        errors: list[str] = []

        class FakeDB:
            async def aget_run_metadata(self, run_id):
                return _run_metadata(run_id, language="en")

            async def aiter_run_samples(self, run_id, batch_size=1024):
                if False:
                    yield []
                raise RuntimeError("boom")

            async def astore_analysis_error(self, run_id, msg):
                pass

        worker = PostAnalysisWorker(
            history_db=FakeDB(),
            error_callback=lambda msg: errors.append(msg),
        )
        worker.schedule("run-err")
        assert worker.wait(timeout_s=3.0)
        assert any("boom" in e for e in errors)

    def test_unexpected_worker_failure_clears_current_batch_but_allows_reschedule(
        self,
        make_worker,
    ) -> None:
        """Unexpected worker bugs stop the current batch instead of masking the fault."""
        seen: list[str] = []
        errors: list[str] = []
        failing_run_started = threading.Event()
        release_failure = threading.Event()

        def _sometimes_fail(rid: str) -> None:
            if rid == "run-fail":
                failing_run_started.set()
                assert release_failure.wait(timeout=1.0)
                raise RuntimeError("first run fails")
            seen.append(rid)

        worker = make_worker(run_fn=_sometimes_fail, error_callback=errors.append)

        worker.schedule("run-fail")
        assert failing_run_started.wait(timeout=1.0)
        worker.schedule("run-dropped")
        release_failure.set()
        assert worker.wait(timeout_s=3.0)
        assert seen == []
        assert errors == ["post-analysis worker bug for run run-fail: first run fails"]

        snapshot = worker.snapshot()
        assert snapshot.last_completed_run_id == "run-fail"
        assert (
            snapshot.last_completed_error == "Unexpected post-analysis worker bug: first run fails"
        )
        assert snapshot.queue_depth == 0

        worker.schedule("run-recovered")
        assert worker.wait(timeout_s=3.0)
        assert seen == ["run-recovered"]

    def test_unexpected_worker_failure_updates_snapshot_and_error_callback(
        self,
        make_worker,
    ) -> None:
        errors: list[str] = []
        stored_errors: list[tuple[str, str]] = []

        class FakeDB:
            async def astore_analysis_error(self, run_id, msg):
                stored_errors.append((run_id, msg))

        def _fail(_rid: str) -> None:
            raise RuntimeError("worker boom")

        worker = make_worker(
            run_fn=_fail,
            history_db=FakeDB(),
            error_callback=errors.append,
        )

        worker.schedule("run-unexpected")
        assert worker.wait(timeout_s=3.0)

        snapshot = worker.snapshot()
        assert snapshot.last_completed_run_id == "run-unexpected"
        assert snapshot.last_completed_error == "Unexpected post-analysis worker bug: worker boom"
        assert errors == ["post-analysis worker bug for run run-unexpected: worker boom"]
        assert stored_errors == [
            ("run-unexpected", "Unexpected post-analysis worker bug: worker boom")
        ]

    def test_worker_retries_retryable_failure_until_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_fast_retry_delays(monkeypatch)
        errors: list[str] = []
        cleared: list[str] = []
        stored: list[tuple[str, object]] = []

        class FakeDB:
            def __init__(self) -> None:
                self._store_attempts = 0

            async def aget_run(self, run_id):
                return _StoredRun(metadata=_run_metadata(run_id), sample_count=2)

            async def aiter_run_samples(self, run_id, batch_size=1024):
                assert run_id == "run-retry"
                yield sensor_frames_from_mappings(
                    [
                        {"t_s": 1.0, "vibration_strength_db": 10.0},
                        {"t_s": 2.0, "vibration_strength_db": 11.0},
                    ]
                )

            async def astore_analysis(self, run_id, analysis):
                self._store_attempts += 1
                if self._store_attempts == 1:
                    raise sqlite3.OperationalError("db locked")
                stored.append((run_id, analysis))

            async def astore_analysis_error(self, run_id, msg):
                raise AssertionError(f"unexpected persisted error for {run_id}: {msg}")

        worker = PostAnalysisWorker(
            history_db=FakeDB(),
            analysis_runner=lambda _run: make_persisted_analysis({"run_suitability": []}),
            error_callback=errors.append,
            clear_error_callback=lambda: cleared.append("cleared"),
        )
        worker.schedule("run-retry")

        assert worker.wait(timeout_s=3.0)
        assert errors == ["post-analysis failed for run run-retry: db locked"]
        assert cleared == ["cleared"]
        assert stored and stored[0][0] == "run-retry"
        snapshot = worker.snapshot()
        assert snapshot.last_completed_run_id == "run-retry"
        assert snapshot.last_completed_error is None

    def test_worker_retries_until_budget_exhausted(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_fast_retry_delays(monkeypatch)
        errors: list[str] = []
        stored_errors: list[tuple[str, str]] = []

        class FakeDB:
            async def aget_run(self, run_id):
                return _StoredRun(metadata=_run_metadata(run_id), sample_count=2)

            async def aiter_run_samples(self, run_id, batch_size=1024):
                assert run_id == "run-exhausted"
                yield sensor_frames_from_mappings(
                    [
                        {"t_s": 1.0, "vibration_strength_db": 10.0},
                        {"t_s": 2.0, "vibration_strength_db": 11.0},
                    ]
                )

            async def astore_analysis(self, run_id, analysis):
                raise sqlite3.OperationalError("db locked")

            async def astore_analysis_error(self, run_id, msg):
                stored_errors.append((run_id, msg))

        worker = PostAnalysisWorker(
            history_db=FakeDB(),
            analysis_runner=lambda _run: make_persisted_analysis({"run_suitability": []}),
            error_callback=errors.append,
        )
        worker.schedule("run-exhausted")

        assert worker.wait(timeout_s=3.0)
        assert len(errors) > 1
        assert set(errors) == {"post-analysis failed for run run-exhausted: db locked"}
        assert stored_errors == [("run-exhausted", "db locked")]
        snapshot = worker.snapshot()
        assert snapshot.last_completed_run_id == "run-exhausted"
        assert snapshot.last_completed_error == "db locked"


class TestPostAnalysisWorkerThreadClearing:
    def test_single_worker_thread(self, make_worker) -> None:
        """Only one worker thread runs at a time, even with many schedules."""
        max_active = 0
        active = 0
        lock = threading.Lock()

        def _track(rid: str) -> None:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.01)
            with lock:
                active -= 1

        worker = make_worker(run_fn=_track)

        for i in range(10):
            worker.schedule(f"run-{i}")
        assert worker.wait(timeout_s=5.0)
        assert max_active == 1


class TestPostAnalysisWorkerNoHistoryDB:
    def test_no_history_db_is_noop(self) -> None:
        """When history_db is None, _run_post_analysis is a no-op."""
        worker = PostAnalysisWorker(history_db=None)
        worker.schedule("run-noop")
        assert worker.wait(timeout_s=2.0)
