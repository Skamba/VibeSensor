"""The background post-analysis worker: loading, queueing, retries and failure recording.

The worker is driven through its public seams (``schedule``/``wait``/``shutdown``
and an injected ``analysis_runner``) against a small in-memory history store.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable

import pytest
from test_support.history_db_lifecycle import make_stored_run
from test_support.persisted_analysis import make_persisted_analysis
from test_support.raw_capture_fixtures import post_analysis_metadata

from vibesensor.analysis.post_analysis import PostAnalysisWorker
from vibesensor.analysis.post_analysis_failures import UnexpectedPostAnalysisBugRecorder
from vibesensor.analysis.post_analysis_input import PostAnalysisRunInput
from vibesensor.analysis.post_analysis_loader import load_post_analysis_run
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings

_ROWS = [{"t_s": 1.0, "vibration_strength_db": 10.0}, {"t_s": 2.0, "vibration_strength_db": 11.0}]


class _HistoryStore:
    """In-memory stand-in for the HistoryDB methods post-analysis uses."""

    def __init__(self, rows: list[dict[str, object]] = _ROWS, *, language: str = "en") -> None:
        self.rows = rows
        self.language = language
        self.stored: dict[str, object] = {}
        self.errors: list[tuple[str, str]] = []
        self.store_failure: Exception | None = None
        self.transient_store_failures: list[Exception] = []
        self.iter_calls: list[tuple[int, int]] = []

    def get_run(self, run_id: str):
        metadata = post_analysis_metadata(run_id, fft_n=256, language=self.language)
        return make_stored_run(metadata, sample_count=len(self.rows))

    def load_raw_capture(self, _run_id: str):
        return None

    def iter_run_samples(self, _run_id: str, batch_size: int = 1024, *, stride: int = 1):
        self.iter_calls.append((batch_size, stride))
        yield sensor_frames_from_mappings(self.rows)

    def store_analysis(self, run_id: str, analysis) -> None:
        if self.store_failure is not None:
            raise self.store_failure
        if self.transient_store_failures:
            raise self.transient_store_failures.pop(0)
        self.stored[run_id] = analysis

    def store_analysis_error(self, run_id: str, message: str) -> bool:
        self.errors.append((run_id, message))
        return True


def _runner(on_run: Callable[[str], None] = lambda _run_id: None):
    def run(analysis_input: PostAnalysisRunInput):
        on_run(analysis_input.run_id)
        return make_persisted_analysis({"run_suitability": []})

    return run


def test_scheduling_a_run_twice_analyses_it_once() -> None:
    seen: list[str] = []
    release = threading.Event()

    def slow(run_id: str) -> None:
        release.wait(timeout=2.0)
        seen.append(run_id)

    worker = PostAnalysisWorker(history_db=_HistoryStore(), analysis_runner=_runner(slow))
    worker.schedule("run-dup")
    worker.schedule("run-dup")
    release.set()

    assert worker.wait(timeout_s=3.0)
    assert seen == ["run-dup"]


def test_many_scheduled_runs_are_all_analysed_in_order() -> None:
    seen: list[str] = []
    worker = PostAnalysisWorker(history_db=_HistoryStore(), analysis_runner=_runner(seen.append))

    for index in range(105):
        worker.schedule(f"run-{index}")

    assert worker.wait(timeout_s=10.0)
    assert seen == [f"run-{index}" for index in range(105)]


def test_the_active_run_is_reported_while_it_is_analysed() -> None:
    started, release = threading.Event(), threading.Event()

    def block(_run_id: str) -> None:
        started.set()
        release.wait(timeout=5.0)

    worker = PostAnalysisWorker(history_db=_HistoryStore(), analysis_runner=_runner(block))
    worker.schedule("run-active")
    assert started.wait(timeout=2.0)

    assert worker.is_active
    assert worker.active_run_id == "run-active"
    release.set()
    assert worker.wait(timeout_s=2.0)
    assert not worker.is_active


def test_shutdown_drops_runs_still_waiting_in_the_queue() -> None:
    started, release = threading.Event(), threading.Event()
    seen: list[str] = []

    def block(run_id: str) -> None:
        started.set()
        release.wait(timeout=5.0)
        seen.append(run_id)

    worker = PostAnalysisWorker(history_db=_HistoryStore(), analysis_runner=_runner(block))
    worker.schedule("run-1")
    assert started.wait(timeout=2.0)
    worker.schedule("run-2")

    assert worker.shutdown(timeout_s=0.01) is False
    release.set()
    assert worker.wait(timeout_s=2.0)
    assert seen == ["run-1"]


def test_the_runner_gets_the_stored_run_and_its_result_is_stored() -> None:
    store = _HistoryStore(language="nl")
    received: list[PostAnalysisRunInput] = []

    def runner(analysis_input: PostAnalysisRunInput):
        received.append(analysis_input)
        return make_persisted_analysis({"lang": analysis_input.language, "run_suitability": []})

    worker = PostAnalysisWorker(history_db=store, analysis_runner=runner)
    worker.schedule("run-ok")
    assert worker.wait(timeout_s=3.0)

    (analysis_input,) = received
    assert analysis_input.run_id == "run-ok"
    assert analysis_input.language == "nl"
    assert analysis_input.total_summary_row_count == 2
    assert analysis_input.stride == 1
    assert len(analysis_input.samples) == 2
    assert analysis_input.context.run_id == "run-ok"
    assert store.stored["run-ok"].payload["lang"] == "nl"
    assert store.errors == []


def test_a_transient_store_failure_is_retried_and_the_analysis_is_stored() -> None:
    # Runs on the production retry policy (first retry after 0.5 s): a database that
    # is briefly locked must not cost the user the analysis of their run.
    store = _HistoryStore()
    store.transient_store_failures.append(sqlite3.OperationalError("database is locked"))
    cleared: list[None] = []

    worker = PostAnalysisWorker(
        history_db=store,
        analysis_runner=_runner(),
        clear_error_callback=lambda: cleared.append(None),
    )
    worker.schedule("run-transient")

    assert worker.wait(timeout_s=10.0)
    assert "run-transient" in store.stored
    assert store.errors == []
    snapshot = worker.snapshot()
    assert snapshot.last_completed_run_id == "run-transient"
    assert snapshot.last_completed_error is None
    assert cleared


def test_a_store_that_keeps_failing_is_retried_then_recorded_as_the_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("vibesensor.analysis.post_analysis._RETRY_DELAYS_S", (0.0, 0.0, 0.0))
    store = _HistoryStore()
    store.store_failure = sqlite3.OperationalError("db locked")
    errors: list[str] = []

    worker = PostAnalysisWorker(
        history_db=store, analysis_runner=_runner(), error_callback=errors.append
    )
    worker.schedule("run-exhausted")

    assert worker.wait(timeout_s=10.0)
    assert len(errors) > 1
    assert set(errors) == {"post-analysis failed for run run-exhausted: db locked"}
    assert store.errors == [("run-exhausted", "db locked")]
    snapshot = worker.snapshot()
    assert snapshot.last_completed_run_id == "run-exhausted"
    assert snapshot.last_completed_error == "db locked"


def test_without_a_history_db_scheduling_does_nothing() -> None:
    worker = PostAnalysisWorker(history_db=None)
    worker.schedule("run-noop")
    assert worker.wait(timeout_s=2.0)


def test_a_worker_bug_is_reported_even_when_storing_it_fails() -> None:
    callbacks: list[str] = []

    class _LockedStore(_HistoryStore):
        def store_analysis_error(self, run_id: str, message: str) -> bool:
            raise sqlite3.OperationalError("db locked")

    recorder = UnexpectedPostAnalysisBugRecorder(
        history_db=_LockedStore(), error_callback=callbacks.append
    )

    recorded = recorder.record_bug(run_id="run-bug", exc=RuntimeError("worker boom"))

    assert recorded.completed_error == "Unexpected post-analysis worker bug: worker boom"
    assert callbacks == ["post-analysis worker bug for run run-bug: worker boom"]


def test_long_runs_keep_loud_events_when_thinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vibesensor.analysis.post_analysis_loader._MAX_POST_ANALYSIS_SAMPLES", 2)
    store = _HistoryStore(
        [
            {"t_s": 1.0, "vibration_strength_db": 10.0},
            {"t_s": 2.0, "vibration_strength_db": 11.0},
            {"t_s": 3.0, "vibration_strength_db": 48.0},
            {"t_s": 4.0, "vibration_strength_db": 12.0},
        ]
    )

    result = load_post_analysis_run(run_id="run-capped", db=store)

    assert result.total_summary_row_count == 4
    assert result.summary_duration_s == pytest.approx(3.0)
    assert result.stride == 2
    assert result.sampling_method == "event_preserving"
    assert result.event_sample_count == 1
    assert [sample.t_s for sample in result.samples] == [1.0, 3.0]
    assert store.iter_calls == [(1024, 1)]
