"""Integration test for RunRecorder full lifecycle with a real HistoryDB."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_support.core import wait_until

from vibesensor.adapters.persistence.history_db import HistoryDB

# -- Test ----------------------------------------------------------------------


def test_start_append_stop_produces_complete_run_in_db(
    make_logger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full lifecycle: start -> append -> stop -> analyze -> complete with a real DB."""
    history_db = HistoryDB(tmp_path / "history.db")
    logger = make_logger(history_db=history_db)

    logger.start_recording()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    logger._append_records(run_id, start_time_utc, start_mono)

    fake_analysis = {"score": 42, "details": "looks good"}

    class _FakeRunAnalysis:
        def __init__(self, *args, **kwargs):
            pass

        def summarize(self):
            from types import SimpleNamespace

            return SimpleNamespace(
                summary=dict(fake_analysis),
                diagnostic_case=SimpleNamespace(case_id="mock-case"),
            )

    monkeypatch.setattr("vibesensor.use_cases.diagnostics.RunAnalysis", _FakeRunAnalysis)
    logger.stop_recording()

    def _status():
        return (history_db.get_run(run_id) or {}).get("status")

    assert wait_until(lambda: _status() == "complete", timeout_s=3.0)

    stored = history_db.get_run(run_id).get("analysis")
    assert stored is not None
    assert stored["score"] == 42
    assert stored["details"] == "looks good"
    assert "analysis_metadata" in stored
