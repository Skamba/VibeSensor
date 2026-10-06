"""The background post-analysis worker: loading, queueing, retries and failure recording.

The worker is driven through its public seams (``schedule``/``wait``/``shutdown``
and an injected ``analysis_runner``) against a small in-memory history store.
"""

from __future__ import annotations

import math
import sqlite3
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from test_support.history_db_lifecycle import (
    build_history_db,
    create_analyzing_run,
    create_recording_run,
    make_stored_run,
)
from test_support.history_db_sql import fetch_all
from test_support.persisted_analysis import make_persisted_analysis
from test_support.raw_capture_fixtures import post_analysis_metadata

from vibesensor.analysis.post_analysis import PostAnalysisWorker
from vibesensor.analysis.post_analysis_failures import UnexpectedPostAnalysisBugRecorder
from vibesensor.analysis.post_analysis_input import PostAnalysisRunInput
from vibesensor.history.history_db import HistoryDB
from vibesensor.history.sample_store import SampleSelectionColumns
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

    def get_run(self, run_id: str):
        metadata = post_analysis_metadata(run_id, fft_n=256, language=self.language)
        return make_stored_run(metadata, sample_count=len(self.rows))

    def load_raw_capture(self, _run_id: str):
        return None

    def begin_analysis_attempt(self, _run_id: str, *, boot_id: str | None) -> int:
        return 0

    def run_sample_selection_columns(self, _run_id: str) -> SampleSelectionColumns:
        return SampleSelectionColumns.from_rows(
            [
                (row_id, frame.t_s, frame.vibration_strength_db, math.nan, math.nan)
                for row_id, frame in enumerate(self._frames(), start=1)
            ]
        )

    def load_run_samples_by_id(self, _run_id: str, row_ids: Sequence[int]):
        frames = self._frames()
        return [frames[row_id - 1] for row_id in row_ids]

    def _frames(self):
        return sensor_frames_from_mappings(self.rows)

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


def _store_recorded_run(db: HistoryDB, run_id: str) -> None:
    metadata = create_recording_run(db, run_id)
    db.append_samples(run_id, sensor_frames_from_mappings(_ROWS))
    db.finalize_run(run_id, "2026-01-01T00:01:00Z", metadata=metadata)


def test_a_run_that_twice_crashed_the_server_mid_analysis_is_marked_failed(
    tmp_path: Path,
) -> None:
    # Each attempt is recorded before the analysis starts and cleared when its result
    # (or error) is stored, so one left behind in the same boot means the server died
    # mid-analysis, most likely out of memory. A third try would only crash it again.
    db = build_history_db(tmp_path)
    _store_recorded_run(db, "run-oom")
    assert db.begin_analysis_attempt("run-oom", boot_id="boot-a") == 0
    assert db.begin_analysis_attempt("run-oom", boot_id="boot-a") == 1
    db.close()
    db = build_history_db(tmp_path)  # the record survives the restart
    seen: list[str] = []

    worker = PostAnalysisWorker(
        history_db=db, analysis_runner=_runner(seen.append), boot_id=lambda: "boot-a"
    )
    worker.schedule("run-oom")

    assert worker.wait(timeout_s=5.0)
    assert seen == []
    run = db.get_run("run-oom")
    assert run is not None
    assert run.status == "error"
    assert run.error_message == (
        "Analysis did not finish in 2 attempts: the server stopped during analysis each "
        "time, most likely out of memory. Record a shorter run."
    )
    assert worker.snapshot().last_completed_error == run.error_message


def test_one_crashed_attempt_is_retried_and_the_record_cleared(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    _store_recorded_run(db, "run-retry")
    db.begin_analysis_attempt("run-retry", boot_id="boot-a")
    seen: list[str] = []

    worker = PostAnalysisWorker(
        history_db=db, analysis_runner=_runner(seen.append), boot_id=lambda: "boot-a"
    )
    worker.schedule("run-retry")

    assert worker.wait(timeout_s=5.0)
    assert seen == ["run-retry"]
    run = db.get_run("run-retry")
    assert run is not None
    assert run.status == "complete"
    assert fetch_all(db, "SELECT * FROM unfinished_analyses") == []


def test_attempts_a_power_cut_ended_are_not_counted_as_crashes(tmp_path: Path) -> None:
    # The ignition went off twice during the analysis: each attempt ended with the
    # boot, not with a crash, so the run is analysed again on the next start.
    db = build_history_db(tmp_path)
    _store_recorded_run(db, "run-cut")
    assert db.begin_analysis_attempt("run-cut", boot_id="boot-a") == 0
    assert db.begin_analysis_attempt("run-cut", boot_id="boot-b") == 0
    # One crash, then a power cut: the crash still counts, the cut does not.
    assert db.begin_analysis_attempt("run-cut", boot_id="boot-b") == 1
    db.close()
    db = build_history_db(tmp_path)
    seen: list[str] = []

    worker = PostAnalysisWorker(
        history_db=db, analysis_runner=_runner(seen.append), boot_id=lambda: "boot-c"
    )
    worker.schedule("run-cut")

    assert worker.wait(timeout_s=5.0)
    assert seen == ["run-cut"]
    run = db.get_run("run-cut")
    assert run is not None
    assert run.status == "complete"
    assert fetch_all(db, "SELECT * FROM unfinished_analyses") == []


def test_attempts_are_only_recorded_for_runs_awaiting_analysis(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_analyzing_run(db, "run-a")

    assert db.begin_analysis_attempt("run-missing", boot_id="boot-a") == 0
    assert db.begin_analysis_attempt("run-a", boot_id="boot-a") == 0
    assert fetch_all(db, "SELECT run_id FROM unfinished_analyses") == [("run-a",)]
    db.store_analysis_error("run-a", "boom")
    assert fetch_all(db, "SELECT run_id FROM unfinished_analyses") == []
    assert db.begin_analysis_attempt("run-a", boot_id="boot-a") == 0
    assert fetch_all(db, "SELECT run_id FROM unfinished_analyses") == []
