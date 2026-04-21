from __future__ import annotations

import sqlite3

from vibesensor.use_cases.run.post_analysis_failures import UnexpectedPostAnalysisBugRecorder


def test_unexpected_failure_recorder_persists_and_notifies() -> None:
    stored_errors: list[tuple[str, str]] = []
    callbacks: list[str] = []

    class FakeDB:
        async def astore_analysis_error(self, run_id: str, message: str) -> bool:
            stored_errors.append((run_id, message))
            return True

    recorder = UnexpectedPostAnalysisBugRecorder(
        history_db=FakeDB(),
        error_callback=callbacks.append,
    )

    recorded_bug = recorder.record_bug(run_id="run-bug", exc=RuntimeError("worker boom"))

    assert recorded_bug.completed_error == "Unexpected post-analysis worker bug: worker boom"
    assert recorded_bug.callback_error == "post-analysis worker bug for run run-bug: worker boom"
    assert stored_errors == [("run-bug", "Unexpected post-analysis worker bug: worker boom")]
    assert callbacks == ["post-analysis worker bug for run run-bug: worker boom"]


def test_unexpected_failure_recorder_tolerates_store_failures() -> None:
    callbacks: list[str] = []

    class FakeDB:
        async def astore_analysis_error(self, run_id: str, message: str) -> bool:
            raise sqlite3.OperationalError("db locked")

    recorder = UnexpectedPostAnalysisBugRecorder(
        history_db=FakeDB(),
        error_callback=callbacks.append,
    )

    recorded_bug = recorder.record_bug(run_id="run-bug", exc=RuntimeError("worker boom"))

    assert recorded_bug.completed_error == "Unexpected post-analysis worker bug: worker boom"
    assert callbacks == ["post-analysis worker bug for run run-bug: worker boom"]
