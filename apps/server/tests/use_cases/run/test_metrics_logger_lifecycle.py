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
    fake_analysis = {
        "findings": [],
        "top_causes": [],
        "warnings": [],
        "score": 42,
        "details": "looks good",
    }
    monkeypatch.setattr(
        "vibesensor.use_cases.run.logger.build_post_analysis_summary",
        lambda **_: {
            **fake_analysis,
            "analysis_metadata": {},
            "case_id": "mock-case",
        },
    )
    logger = make_logger(history_db=history_db)

    logger.start_recording()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    logger._sample_flush.append_records(run_id, start_time_utc, start_mono)

    logger.stop_recording()

    def _status():
        run = history_db.get_run(run_id)
        return run.status.value if run is not None else None

    assert wait_until(lambda: _status() == "complete", timeout_s=3.0)

    stored = history_db.get_run(run_id).analysis
    assert stored is not None
    assert stored["score"] == 42
    assert stored["details"] == "looks good"
    assert "analysis_metadata" in stored
