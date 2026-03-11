"""Integration test for MetricsLogger full lifecycle with a real HistoryDB."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_support.core import wait_until

from vibesensor.history_db import HistoryDB

# -- Test ----------------------------------------------------------------------


def test_start_append_stop_produces_complete_run_in_db(
    make_logger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full lifecycle: start -> append -> stop -> analyze -> complete with a real DB."""
    history_db = HistoryDB(tmp_path / "history.db")
    logger = make_logger(history_db=history_db)

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    logger._append_records(run_id, start_time_utc, start_mono)

    fake_analysis = {"score": 42, "details": "looks good"}

    def _fast_summary(metadata, samples, lang=None, file_name="run", include_samples=False):
        return dict(fake_analysis)

    monkeypatch.setattr("vibesensor.analysis.summarize_run_data", _fast_summary)
    logger.stop_logging()

    def _status():
        return (history_db.get_run(run_id) or {}).get("status")

    assert wait_until(lambda: _status() == "complete", timeout_s=3.0)

    stored = history_db.get_run(run_id).get("analysis")
    assert stored is not None
    assert stored["score"] == 42
    assert stored["details"] == "looks good"
    assert "analysis_metadata" in stored
