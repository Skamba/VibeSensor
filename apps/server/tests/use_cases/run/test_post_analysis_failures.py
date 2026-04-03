from __future__ import annotations

import sqlite3

from vibesensor.use_cases.run.post_analysis_failures import UnexpectedPostAnalysisFailureRecorder


def test_unexpected_failure_recorder_persists_and_notifies() -> None:
    stored_errors: list[tuple[str, str]] = []
    callbacks: list[str] = []

    class FakeDB:
        def store_analysis_error(self, run_id: str, message: str) -> None:
            stored_errors.append((run_id, message))

    recorder = UnexpectedPostAnalysisFailureRecorder(
        history_db=FakeDB(),
        error_callback=callbacks.append,
    )

    completed_error = recorder.record(run_id="run-bug", exc=RuntimeError("worker boom"))

    assert completed_error == "worker boom"
    assert stored_errors == [("run-bug", "worker boom")]
    assert callbacks == ["post-analysis failed for run run-bug: worker boom"]


def test_unexpected_failure_recorder_tolerates_store_failures() -> None:
    callbacks: list[str] = []

    class FakeDB:
        def store_analysis_error(self, run_id: str, message: str) -> None:
            raise sqlite3.OperationalError("db locked")

    recorder = UnexpectedPostAnalysisFailureRecorder(
        history_db=FakeDB(),
        error_callback=callbacks.append,
    )

    completed_error = recorder.record(run_id="run-bug", exc=RuntimeError("worker boom"))

    assert completed_error == "worker boom"
    assert callbacks == ["post-analysis failed for run run-bug: worker boom"]
