"""Unit tests for vibesensor.metrics_log.post_analysis.PostAnalysisWorker.

These tests exercise the background analysis worker independently of
MetricsLogger, validating queue management, threading, and error handling.
"""

from __future__ import annotations

import threading
import time

from vibesensor.metrics_log.post_analysis import PostAnalysisWorker


class TestPostAnalysisWorkerSchedule:
    def test_schedule_and_process(self) -> None:
        """Worker processes a scheduled run."""
        seen: list[str] = []

        worker = PostAnalysisWorker(history_db=object())
        worker._run_post_analysis = lambda rid: seen.append(rid)  # type: ignore[assignment]

        worker.schedule("run-1")
        assert worker.wait(timeout_s=2.0)
        assert seen == ["run-1"]

    def test_schedule_multiple(self) -> None:
        """Multiple runs are processed in order."""
        seen: list[str] = []

        worker = PostAnalysisWorker(history_db=object())
        worker._run_post_analysis = lambda rid: seen.append(rid)  # type: ignore[assignment]

        for i in range(5):
            worker.schedule(f"run-{i}")
        assert worker.wait(timeout_s=3.0)
        assert seen == [f"run-{i}" for i in range(5)]

    def test_duplicate_run_id_ignored(self) -> None:
        """Scheduling the same run_id twice is a no-op."""
        seen: list[str] = []
        barrier = threading.Event()

        def _slow(rid: str) -> None:
            barrier.wait(timeout=2.0)
            seen.append(rid)

        worker = PostAnalysisWorker(history_db=object())
        worker._run_post_analysis = _slow  # type: ignore[assignment]

        worker.schedule("run-dup")
        worker.schedule("run-dup")  # duplicate
        barrier.set()
        assert worker.wait(timeout_s=3.0)
        assert seen == ["run-dup"]


class TestPostAnalysisWorkerIsActive:
    def test_inactive_when_idle(self) -> None:
        worker = PostAnalysisWorker(history_db=None)
        assert not worker.is_active

    def test_active_during_work(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def _block(rid: str) -> None:
            started.set()
            release.wait(timeout=5.0)

        worker = PostAnalysisWorker(history_db=object())
        worker._run_post_analysis = _block  # type: ignore[assignment]

        worker.schedule("run-active")
        started.wait(timeout=2.0)
        assert worker.is_active
        assert worker.active_run_id == "run-active"
        release.set()
        assert worker.wait(timeout_s=2.0)
        assert not worker.is_active


class TestPostAnalysisWorkerWait:
    def test_wait_no_work_returns_immediately(self) -> None:
        worker = PostAnalysisWorker(history_db=None)
        assert worker.wait(timeout_s=0.1)

    def test_wait_timeout(self) -> None:
        release = threading.Event()

        def _block(rid: str) -> None:
            release.wait(timeout=5.0)

        worker = PostAnalysisWorker(history_db=object())
        worker._run_post_analysis = _block  # type: ignore[assignment]

        worker.schedule("run-slow")
        result = worker.wait(timeout_s=0.1)
        assert result is False
        release.set()
        worker.wait(timeout_s=2.0)


class TestPostAnalysisWorkerErrorHandling:
    def test_error_callback_on_failure(self) -> None:
        """Error callback is invoked when analysis raises."""
        errors: list[str] = []

        class FakeDB:
            def get_run_metadata(self, run_id):
                return {"language": "en"}

            def iter_run_samples(self, run_id, batch_size=1024):
                raise RuntimeError("boom")

            def store_analysis_error(self, run_id, msg):
                pass

        worker = PostAnalysisWorker(
            history_db=FakeDB(),
            error_callback=lambda msg: errors.append(msg),
        )
        worker.schedule("run-err")
        assert worker.wait(timeout_s=3.0)
        assert any("boom" in e for e in errors)

    def test_worker_continues_after_failure(self) -> None:
        """A failing run does not block subsequent runs."""
        seen: list[str] = []
        call_count = 0

        def _sometimes_fail(rid: str) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first run fails")
            seen.append(rid)

        worker = PostAnalysisWorker(history_db=object())
        worker._run_post_analysis = _sometimes_fail  # type: ignore[assignment]

        worker.schedule("run-fail")
        worker.schedule("run-ok")
        assert worker.wait(timeout_s=3.0)
        assert seen == ["run-ok"]


class TestPostAnalysisWorkerThreadClearing:
    def test_thread_cleared_after_completion(self) -> None:
        """Worker thread reference is cleared after all work completes."""
        worker = PostAnalysisWorker(history_db=object())
        worker._run_post_analysis = lambda rid: None  # type: ignore[assignment]

        worker.schedule("run-1")
        assert worker.wait(timeout_s=2.0)

        with worker._lock:
            assert worker._analysis_thread is None

    def test_single_worker_thread(self) -> None:
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

        worker = PostAnalysisWorker(history_db=object())
        worker._run_post_analysis = _track  # type: ignore[assignment]

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
