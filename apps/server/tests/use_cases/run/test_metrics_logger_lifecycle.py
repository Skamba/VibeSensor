"""Integration test for RunRecorder full lifecycle with a real HistoryDB."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from test_support.core import wait_until
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters

# -- Test ----------------------------------------------------------------------


def test_start_append_stop_produces_complete_run_in_db(
    make_logger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full lifecycle: start -> append -> stop -> analyze -> complete with a real DB."""
    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    fake_analysis = {
        "findings": [],
        "top_causes": [],
        "warnings": [],
        "score": 42,
        "details": "looks good",
    }
    monkeypatch.setattr(
        "vibesensor.use_cases.run.logger.build_post_analysis_summary",
        lambda _run: make_persisted_analysis(
            {
                **fake_analysis,
                "analysis_metadata": {},
                "case_id": "mock-case",
            }
        ),
    )
    logger = make_logger(history_db=history_db.run_repository)

    logger.start_recording()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    logger._sample_flush.append_records(run_id, start_time_utc, start_mono)

    logger.stop_recording()

    def _status():
        run = history_db.run_repository.get_run(run_id)
        return run.status.value if run is not None else None

    assert wait_until(lambda: _status() == "complete", timeout_s=3.0)

    stored = history_db.run_repository.get_run(run_id).analysis
    assert stored is not None
    assert stored["score"] == 42
    assert stored["details"] == "looks good"
    assert "analysis_metadata" in stored


def test_start_and_stop_recording_emit_structured_run_lifecycle_events(
    make_logger,
    fake_history_db,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = make_logger(history_db=fake_history_db)
    monkeypatch.setattr(logger, "schedule_post_analysis", lambda _run_id: None)

    with caplog.at_level(logging.INFO, logger="vibesensor.use_cases.run.logger"):
        started = logger.start_recording()
        assert started.run_id is not None
        snapshot = logger._session_snapshot()
        assert snapshot is not None
        logger._sample_flush.append_records(
            snapshot.run_id,
            snapshot.start_time_utc,
            snapshot.start_mono_s,
        )
        logger.stop_recording()

    lifecycle_records = [rec for rec in caplog.records if rec.message == "run_lifecycle"]
    assert [rec.run_action for rec in lifecycle_records] == ["started", "stopped"]

    start_record, stop_record = lifecycle_records
    assert start_record.event == "run_lifecycle"
    assert start_record.run_id == snapshot.run_id
    assert start_record.start_time_utc == snapshot.start_time_utc
    assert not hasattr(start_record, "stop_reason")

    assert stop_record.event == "run_lifecycle"
    assert stop_record.run_id == snapshot.run_id
    assert stop_record.start_time_utc == snapshot.start_time_utc
    assert stop_record.stop_reason == "manual"
    assert stop_record.samples_written > 0
    assert stop_record.samples_dropped == 0
    assert isinstance(stop_record.end_time_utc, str)


def test_restart_recording_emits_stop_then_start_lifecycle_events(
    make_logger,
    fake_history_db,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = make_logger(history_db=fake_history_db)
    monkeypatch.setattr(logger, "schedule_post_analysis", lambda _run_id: None)
    first_status = logger.start_recording()
    assert first_status.run_id is not None
    first_snapshot = logger._session_snapshot()
    assert first_snapshot is not None
    logger._sample_flush.append_records(
        first_snapshot.run_id,
        first_snapshot.start_time_utc,
        first_snapshot.start_mono_s,
    )

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="vibesensor.use_cases.run.logger"):
        second_status = logger.start_recording()

    assert second_status.run_id is not None
    assert second_status.run_id != first_snapshot.run_id
    second_snapshot = logger._session_snapshot()
    assert second_snapshot is not None
    lifecycle_records = [rec for rec in caplog.records if rec.message == "run_lifecycle"]
    assert [rec.run_action for rec in lifecycle_records] == ["stopped", "started"]

    stop_record, start_record = lifecycle_records
    assert stop_record.event == "run_lifecycle"
    assert stop_record.run_id == first_snapshot.run_id
    assert stop_record.stop_reason == "restart"
    assert stop_record.samples_written > 0
    assert stop_record.samples_dropped == 0

    assert start_record.event == "run_lifecycle"
    assert start_record.run_id == second_status.run_id
    assert start_record.start_time_utc == second_snapshot.start_time_utc


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


def test_start_recording_flushes_active_signal_buffers(
    make_logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger()
    flush_calls: list[tuple[str, str]] = []

    def fake_flush_client_buffer(
        client_id: str,
        *,
        reason: str = "sensor reset",
    ) -> None:
        flush_calls.append((client_id, reason))

    monkeypatch.setattr(logger.processor, "flush_client_buffer", fake_flush_client_buffer)

    logger.start_recording()
    logger.start_recording()

    assert flush_calls == [
        ("active", "recording run start"),
        ("active", "recording run start"),
    ]


def test_stop_recording_refreshes_recent_metrics_before_final_flush(
    make_logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger()
    logger.start_recording()
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 1
    active.latest_metrics = {"combined": {"peaks": []}}

    compute_calls: list[tuple[str, int | None]] = []
    captured_rows = []
    original_append_rows = logger._persistence.append_rows

    refreshed_metrics = {
        "combined": {
            "peaks": [{"hz": 15.0, "amp": 0.12}],
            "strength_metrics": {
                "vibration_strength_db": 18.0,
                "strength_bucket": "l2",
                "peak_amp_g": 0.12,
                "noise_floor_amp_g": 0.003,
                "top_peaks": [
                    {
                        "hz": 15.0,
                        "amp": 0.12,
                        "vibration_strength_db": 18.0,
                        "strength_bucket": "l2",
                    },
                ],
            },
        },
    }

    def fake_compute_metrics(client_id: str, sample_rate_hz: int | None = None):
        compute_calls.append((client_id, sample_rate_hz))
        active.latest_metrics = refreshed_metrics
        return refreshed_metrics

    def capture_append_rows(*, run_id: str, start_time_utc: str, rows):
        captured_rows.extend(rows)
        return original_append_rows(
            run_id=run_id,
            start_time_utc=start_time_utc,
            rows=rows,
        )

    monkeypatch.setattr(logger.processor, "compute_metrics", fake_compute_metrics)
    monkeypatch.setattr(logger._persistence, "append_rows", capture_append_rows)
    monkeypatch.setattr(logger, "schedule_post_analysis", lambda _run_id: None)

    logger.stop_recording()

    assert compute_calls == [("active", 800)]
    assert captured_rows
    assert captured_rows[-1].vibration_strength_db == 18.0
