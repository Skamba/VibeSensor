from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from vibesensor.shared.types.raw_capture import RawCaptureLossStats
from vibesensor.use_cases.run.finalize_stages import finalize_active_run
from vibesensor.use_cases.run.persistence_writer import PersistenceStatusSnapshot
from vibesensor.use_cases.run.raw_capture_writer import RawCaptureFinalizeResult


def test_finalize_active_run_reports_successful_stage_results() -> None:
    append_calls: list[tuple[str, str, float, bool]] = []
    raw_finalize_calls: list[tuple[str, object | None]] = []
    recorded_finalize_statuses: list[str] = []

    sample_flush = SimpleNamespace(
        pending_flush_snapshot=lambda: SimpleNamespace(
            run_id="run-1",
            start_time_utc="2026-04-25T06:40:00Z",
            start_mono_s=12.5,
        ),
        append_records=lambda run_id, start_time_utc, start_mono_s, refresh_metrics: (
            append_calls.append((run_id, start_time_utc, start_mono_s, refresh_metrics))
        ),
    )
    persistence = SimpleNamespace(
        status_snapshot=lambda: PersistenceStatusSnapshot(
            write_error=None,
            written_sample_count=12,
            dropped_sample_count=1,
        ),
        ready_for_analysis=lambda run_id: run_id,
        history_run_created=True,
        finalize_run=lambda run_id, start_time_utc, end_time_utc: True,
    )
    raw_capture = SimpleNamespace(
        finalize_run=lambda run_id, *, sensor_losses=None: (
            raw_finalize_calls.append((run_id, sensor_losses))
            or RawCaptureFinalizeResult(status="completed")
        )
    )

    result = finalize_active_run(
        run_id="run-1",
        start_time_utc="2026-04-25T06:39:00Z",
        stop_reason="manual",
        ingest_drop_losses={
            "sensor-a": RawCaptureLossStats(udp_ingest_queue_drop_count=2),
        },
        sample_flush=sample_flush,
        persistence=persistence,
        raw_capture=raw_capture,
        record_raw_capture_finalize_result=lambda run_id, result: recorded_finalize_statuses.append(
            result.status
        ),
        logger=logging.getLogger("test.finalize.success"),
    )

    assert append_calls == [("run-1", "2026-04-25T06:40:00Z", 12.5, True)]
    assert raw_finalize_calls == [
        (
            "run-1",
            {"sensor-a": RawCaptureLossStats(udp_ingest_queue_drop_count=2)},
        )
    ]
    assert recorded_finalize_statuses == ["completed"]
    assert result.run_id_to_analyze == "run-1"
    assert [stage.stage_name for stage in result.stage_results] == [
        "FlushPendingRowsStage",
        "ResolvePostAnalysisCandidateStage",
        "FinalizeRawCaptureStage",
        "FinalizePersistenceStage",
    ]
    assert [stage.status for stage in result.stage_results] == ["ok", "ok", "ok", "ok"]


def test_finalize_active_run_marks_skipped_and_degraded_stages(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.finalize.degraded")

    sample_flush = SimpleNamespace(pending_flush_snapshot=lambda: None)
    persistence = SimpleNamespace(
        status_snapshot=lambda: PersistenceStatusSnapshot(
            write_error=None,
            written_sample_count=0,
            dropped_sample_count=0,
        ),
        ready_for_analysis=lambda run_id: None,
        history_run_created=False,
        finalize_run=lambda run_id, start_time_utc, end_time_utc: False,
    )
    raw_capture = SimpleNamespace(
        finalize_run=lambda run_id, *, sensor_losses=None: RawCaptureFinalizeResult(
            status="timeout",
            error="raw capture finalize timed out",
            queue_depth=3,
        )
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        result = finalize_active_run(
            run_id="run-2",
            start_time_utc="2026-04-25T06:41:00Z",
            stop_reason="manual",
            ingest_drop_losses=None,
            sample_flush=sample_flush,
            persistence=persistence,
            raw_capture=raw_capture,
            record_raw_capture_finalize_result=lambda run_id, result: None,
            logger=logger,
        )

    assert [stage.status for stage in result.stage_results] == [
        "skipped",
        "skipped",
        "degraded",
        "degraded",
    ]
    stage_logs = {
        getattr(record, "stage_name", ""): record
        for record in caplog.records
        if hasattr(record, "stage_name")
    }
    assert stage_logs["FinalizeRawCaptureStage"].stage_status == "degraded"
    assert stage_logs["FinalizeRawCaptureStage"].diagnostic_context["queue_depth"] == 3
    assert stage_logs["FinalizePersistenceStage"].stage_status == "degraded"


def test_finalize_active_run_logs_failed_stage_and_reraises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.finalize.failed")

    sample_flush = SimpleNamespace(pending_flush_snapshot=lambda: None)
    persistence = SimpleNamespace(
        status_snapshot=lambda: PersistenceStatusSnapshot(
            write_error=None,
            written_sample_count=0,
            dropped_sample_count=0,
        ),
        ready_for_analysis=lambda run_id: None,
        history_run_created=False,
        finalize_run=lambda run_id, start_time_utc, end_time_utc: True,
    )
    raw_capture = SimpleNamespace(
        finalize_run=lambda run_id, *, sensor_losses=None: (_ for _ in ()).throw(
            RuntimeError("raw finalize boom")
        )
    )

    with caplog.at_level(logging.WARNING, logger=logger.name):
        with pytest.raises(RuntimeError, match="raw finalize boom"):
            finalize_active_run(
                run_id="run-3",
                start_time_utc="2026-04-25T06:42:00Z",
                stop_reason="manual",
                ingest_drop_losses=None,
                sample_flush=sample_flush,
                persistence=persistence,
                raw_capture=raw_capture,
                record_raw_capture_finalize_result=lambda run_id, result: None,
                logger=logger,
            )

    failed_stage = next(
        record
        for record in caplog.records
        if getattr(record, "stage_name", "") == "FinalizeRawCaptureStage"
    )
    assert failed_stage.stage_status == "failed"
    assert failed_stage.diagnostic_context["error_message"] == "raw finalize boom"


def test_stop_recording_logs_finalize_stage_results(
    make_logger,
    fake_history_db,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = make_logger(history_db=fake_history_db)
    started = recorder.start_recording()
    assert started.run_id is not None

    snapshot = recorder._session_snapshot()
    assert snapshot is not None
    recorder._sample_flush.append_records(
        snapshot.run_id,
        snapshot.start_time_utc,
        snapshot.start_mono_s,
    )
    recorder._raw_capture = SimpleNamespace(
        finalize_run=lambda run_id, *, sensor_losses=None: RawCaptureFinalizeResult(
            status="timeout",
            error="raw capture finalize timed out",
            queue_depth=4,
        ),
        shutdown=lambda timeout_s=5.0: True,
    )
    monkeypatch.setattr(recorder, "schedule_post_analysis", lambda run_id: None)

    with caplog.at_level(logging.WARNING):
        stopped = recorder.stop_recording()

    assert stopped.enabled is False
    stage_logs = [
        record
        for record in caplog.records
        if getattr(record, "event", "") == "run_finalize_stage_result"
    ]
    assert any(record.stage_name == "FinalizeRawCaptureStage" for record in stage_logs)
    assert any(record.stage_status == "degraded" for record in stage_logs)
