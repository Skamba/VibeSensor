from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.use_cases.run.test_metrics_log_helpers import _started_snapshot_with_sample
from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters


def test_stop_recording_continues_when_raw_capture_finalize_degrades(
    make_logger,
    fake_history_db,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from vibesensor.use_cases.run.raw_capture_writer import RawCaptureFinalizeResult

    scheduled: list[str] = []
    logger = make_logger(history_db=fake_history_db)
    snapshot = _started_snapshot_with_sample(logger)
    # Raw-capture fault injection is the narrow private seam needed to prove
    # recorder finalization behavior for degraded/late capture outcomes.
    logger._raw_capture = SimpleNamespace(
        finalize_run=lambda run_id, *, sensor_losses=None: RawCaptureFinalizeResult(
            status="timeout",
            error="raw capture finalize timed out",
            queue_depth=3,
        ),
        shutdown=lambda timeout_s=5.0: True,
    )
    monkeypatch.setattr(logger, "schedule_post_analysis", scheduled.append)

    with caplog.at_level(logging.WARNING, logger="vibesensor.use_cases.run.logger"):
        status = logger.stop_recording()

    assert status.enabled is False
    assert fake_history_db.finalize_calls == [snapshot.run_id]
    updated_run_id, metadata = fake_history_db.updated_metadata[-1]
    assert updated_run_id == snapshot.run_id
    assert metadata.raw_capture_finalize is not None
    assert metadata.raw_capture_finalize.status == "timeout"
    assert metadata.raw_capture_finalize.queue_depth == 3
    assert metadata.raw_capture_finalize.error_summary == "raw capture finalize timed out"
    assert scheduled == []
    assert "raw_capture_finalize_degraded" in caplog.text


class _DelegatingHistoryDB:
    def __init__(self, repository) -> None:
        self._repository = repository

    def __getattr__(self, name: str):
        return getattr(self._repository, name)


class _FinalizeSkippedHistoryDB(_DelegatingHistoryDB):
    async def afinalize_run(
        self,
        run_id: str,
        end_time_utc: str,
        metadata=None,
        case_id=None,
    ) -> bool:
        return False


class _ZeroAppendHistoryDB(_DelegatingHistoryDB):
    async def aappend_samples(self, run_id: str, samples) -> int:
        return 0


@pytest.mark.parametrize(
    ("history_db_factory", "raw_capture_status", "expected_statuses", "expected_resolve_reason"),
    [
        (
            lambda repository: repository,
            "completed",
            {
                "FlushPendingRowsStage": "skipped",
                "FinalizeRawCaptureStage": "ok",
                "FinalizePersistenceStage": "ok",
                "ResolvePostAnalysisCandidateStage": "ok",
            },
            "ready",
        ),
        (
            lambda repository: repository,
            "timeout",
            {
                "FlushPendingRowsStage": "skipped",
                "FinalizeRawCaptureStage": "degraded",
                "FinalizePersistenceStage": "ok",
                "ResolvePostAnalysisCandidateStage": "skipped",
            },
            "raw_capture_finalize_unsettled",
        ),
        (
            _FinalizeSkippedHistoryDB,
            "completed",
            {
                "FlushPendingRowsStage": "skipped",
                "FinalizeRawCaptureStage": "ok",
                "FinalizePersistenceStage": "degraded",
                "ResolvePostAnalysisCandidateStage": "skipped",
            },
            "persistence_finalize_unsettled",
        ),
        (
            _ZeroAppendHistoryDB,
            "not_configured",
            {
                "FlushPendingRowsStage": "skipped",
                "FinalizeRawCaptureStage": "skipped",
                "FinalizePersistenceStage": "ok",
                "ResolvePostAnalysisCandidateStage": "skipped",
            },
            "history_not_ready",
        ),
    ],
)
def test_stop_recording_persists_finalization_stages_in_history_metadata(
    make_logger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    history_db_factory,
    raw_capture_status: str,
    expected_statuses: dict[str, str],
    expected_resolve_reason: str,
) -> None:
    from vibesensor.use_cases.run.raw_capture_writer import RawCaptureFinalizeResult

    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    logger = make_logger(history_db=history_db_factory(history_db.run_repository))
    snapshot = _started_snapshot_with_sample(logger)
    logger._raw_capture = SimpleNamespace(
        finalize_run=lambda run_id, *, sensor_losses=None: RawCaptureFinalizeResult(
            status=raw_capture_status,
            error=("raw capture finalize timed out" if raw_capture_status == "timeout" else None),
            queue_depth=(3 if raw_capture_status == "timeout" else None),
        ),
        shutdown=lambda timeout_s=5.0: True,
    )
    monkeypatch.setattr(logger, "schedule_post_analysis", lambda run_id: None)

    logger.stop_recording()

    stored_metadata = history_db.run_repository.get_run_metadata(snapshot.run_id)
    assert stored_metadata is not None
    stage_by_name = {stage.stage_name: stage for stage in stored_metadata.finalization_stages}
    assert {name: stage.status for name, stage in stage_by_name.items()} == expected_statuses
    assert (
        stage_by_name["ResolvePostAnalysisCandidateStage"].diagnostic_context["reason"]
        == expected_resolve_reason
    )


def test_late_raw_capture_finalize_schedules_post_analysis_after_metadata_update(
    make_logger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vibesensor.use_cases.run.raw_capture_writer import RawCaptureFinalizeResult

    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    scheduled: list[str] = []
    logger = make_logger(history_db=history_db.run_repository)
    snapshot = _started_snapshot_with_sample(logger)
    # Raw-capture fault injection keeps the test on recorder finalization
    # behavior without running the asynchronous raw writer.
    logger._raw_capture = SimpleNamespace(
        finalize_run=lambda run_id, *, sensor_losses=None: RawCaptureFinalizeResult(
            status="timeout",
            error="raw capture finalize timed out",
        ),
        shutdown=lambda timeout_s=5.0: True,
    )
    monkeypatch.setattr(logger, "schedule_post_analysis", scheduled.append)

    logger.stop_recording()
    logger._handle_late_raw_capture_finalize_result(
        snapshot.run_id,
        RawCaptureFinalizeResult(status="completed"),
    )

    assert scheduled == [snapshot.run_id]
    stored_metadata = history_db.run_repository.get_run_metadata(snapshot.run_id)
    assert stored_metadata is not None
    assert stored_metadata.raw_capture_finalize is not None
    assert stored_metadata.raw_capture_finalize.status == "completed"


def test_permanent_raw_capture_finalize_failure_schedules_with_degraded_metadata(
    make_logger,
    fake_history_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vibesensor.use_cases.run.raw_capture_writer import RawCaptureFinalizeResult

    scheduled: list[str] = []
    logger = make_logger(history_db=fake_history_db)
    snapshot = _started_snapshot_with_sample(logger)
    # Raw-capture fault injection keeps the test focused on degraded metadata
    # and scheduling behavior instead of raw writer internals.
    logger._raw_capture = SimpleNamespace(
        finalize_run=lambda run_id, *, sensor_losses=None: RawCaptureFinalizeResult(
            status="failed",
            error="raw capture finalize failed",
            queue_depth=0,
        ),
        shutdown=lambda timeout_s=5.0: True,
    )
    monkeypatch.setattr(logger, "schedule_post_analysis", scheduled.append)

    logger.stop_recording()

    updated_run_id, metadata = fake_history_db.updated_metadata[-1]
    assert updated_run_id == snapshot.run_id
    assert metadata.raw_capture_finalize is not None
    assert metadata.raw_capture_finalize.status == "failed"
    assert metadata.raw_capture_finalize.error_summary == "raw capture finalize failed"
    assert scheduled == [snapshot.run_id]
