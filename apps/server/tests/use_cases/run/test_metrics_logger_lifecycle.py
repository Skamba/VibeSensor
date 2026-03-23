"""Integration test for RunRecorder full lifecycle with a real HistoryDB."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_support.core import wait_until
from test_support.persisted_analysis import make_persisted_analysis

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
        lambda **_: make_persisted_analysis(
            {
                **fake_analysis,
                "analysis_metadata": {},
                "case_id": "mock-case",
            }
        ),
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


class _SpyLock:
    def __init__(self) -> None:
        self.enter_count = 0

    def __enter__(self) -> None:
        self.enter_count += 1
        return None

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_session_snapshot_uses_recorder_lock(make_logger) -> None:
    logger = make_logger()
    logger.start_recording()

    spy = _SpyLock()
    logger._lock = spy

    snapshot = logger._session_snapshot()

    assert snapshot is not None
    assert spy.enter_count == 1


def test_start_recording_holds_lock_during_flush_and_finalize(make_logger) -> None:
    logger = make_logger()
    logger.start_recording()
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 1

    flush_lock_owned: list[bool] = []
    finalize_lock_owned: list[bool] = []

    def fake_append_records(*args, **kwargs) -> bool:
        flush_lock_owned.append(logger._lock._is_owned())
        return False

    def fake_finalize_run(*args, **kwargs) -> bool:
        finalize_lock_owned.append(logger._lock._is_owned())
        return True

    logger._sample_flush.append_records = fake_append_records
    logger._persistence.finalize_run = fake_finalize_run

    logger.start_recording()

    assert flush_lock_owned == [True]
    assert finalize_lock_owned == [True]


def test_stop_recording_holds_lock_during_flush_and_finalize(make_logger) -> None:
    logger = make_logger()
    logger.start_recording()
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 1

    flush_lock_owned: list[bool] = []
    finalize_lock_owned: list[bool] = []

    def fake_append_records(*args, **kwargs) -> bool:
        flush_lock_owned.append(logger._lock._is_owned())
        return False

    def fake_finalize_run(*args, **kwargs) -> bool:
        finalize_lock_owned.append(logger._lock._is_owned())
        return True

    logger._sample_flush.append_records = fake_append_records
    logger._persistence.finalize_run = fake_finalize_run

    logger.stop_recording()

    assert flush_lock_owned == [True]
    assert finalize_lock_owned == [True]
