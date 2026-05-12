from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_support.persisted_analysis import make_persisted_analysis
from test_support.polling import wait_until

from tests.use_cases.run.test_metrics_log_helpers import (
    _started_snapshot,
    _started_snapshot_with_sample,
)
from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.shared.types.history_records import AnalyzingRunHealth
from vibesensor.use_cases.run.post_analysis import PostAnalysisHealthSnapshot


class _NullDB:
    """Stub DB for tests that need a non-None history_db without real DB ops."""

    def analyzing_run_health(self):
        return AnalyzingRunHealth(analyzing_run_count=0, analyzing_oldest_age_s=None)


def test_stop_recording_does_not_block_on_post_analysis(
    make_logger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stopping capture should be fast even when analysis is slow.

    Post-analysis belongs in background processing because users expect stop controls to respond
    promptly. This test simulates a slow summarizer and requires stop_recording to return quickly
    while analysis completes asynchronously afterward.
    """
    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    summary_started = threading.Event()
    allow_summary_finish = threading.Event()

    def _slow_analysis_runner(_run):
        summary_started.set()
        assert allow_summary_finish.wait(timeout=5.0)
        return make_persisted_analysis(
            {
                "findings": [],
                "top_causes": [],
                "analysis_metadata": {},
                "case_id": "mock-case",
            }
        )

    monkeypatch.setattr(
        "vibesensor.use_cases.run.logger.build_post_analysis_summary",
        _slow_analysis_runner,
    )
    logger = make_logger(history_db=history_db.run_repository)

    snapshot = _started_snapshot_with_sample(logger)
    run_id = snapshot.run_id

    started = time.monotonic()
    logger.stop_recording()
    elapsed = time.monotonic() - started

    # stop_recording() must return quickly; summary runs in a worker thread.
    # 5.0s threshold guards against blocking; not a performance target.
    assert elapsed < 5.0, f"stop_recording() blocked for {elapsed:.2f}s (expected < 5.0s)"
    assert summary_started.wait(timeout=2.0)
    allow_summary_finish.set()

    def _status():
        run = history_db.run_repository.get_run(run_id)
        return run.status.value if run is not None else None

    assert wait_until(lambda: _status() == "complete", timeout_s=5.0)


def test_post_analysis_unexpected_failure_surfaces_worker_error_status(
    make_logger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_db = create_history_persistence_adapters(tmp_path / "history.db")

    def _failing_analysis_runner(_run) -> dict[str, object]:
        raise RuntimeError("analysis exploded")

    monkeypatch.setattr(
        "vibesensor.use_cases.run.logger.build_post_analysis_summary",
        _failing_analysis_runner,
    )
    logger = make_logger(history_db=history_db.run_repository)

    snapshot = _started_snapshot_with_sample(logger)
    run_id = snapshot.run_id

    logger.stop_recording()

    def _status():
        return logger.status().last_completed_run_error

    expected_worker_bug = "Unexpected post-analysis worker bug: analysis exploded"
    assert wait_until(lambda: _status() == expected_worker_bug, timeout_s=2.0)
    status = logger.status()
    assert status.last_completed_run_error == expected_worker_bug
    assert status.write_error == f"post-analysis worker bug for run {run_id}: analysis exploded"
    run = history_db.run_repository.get_run(run_id)
    assert run is not None
    assert run.analysis is None
    assert run.status.value == "error"
    assert run.error_message == expected_worker_bug


def test_shutdown_blocks_new_start_recording_until_wait_completes(
    make_logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger(history_db=_NullDB())
    logger.start_recording()
    initial_run_id = logger.status().run_id
    assert initial_run_id is not None

    allow_wait = threading.Event()

    def _wait(timeout_s: float = 30.0) -> bool:
        assert timeout_s == 30.0
        start_result = logger.start_recording()
        assert start_result.enabled is False
        assert start_result.run_id is None
        assert logger.status().run_id is None
        allow_wait.set()
        return True

    monkeypatch.setattr(logger._post_analysis, "wait", _wait)

    assert logger.shutdown() is True
    assert allow_wait.is_set()
    restarted = logger.start_recording()
    assert restarted.enabled is True
    assert restarted.run_id is not None
    assert restarted.run_id != initial_run_id


def test_shutdown_report_exposes_timeout_state(
    make_logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger()
    logger.start_recording()

    monkeypatch.setattr(logger._post_analysis, "wait", lambda timeout_s=30.0: False)
    monkeypatch.setattr(
        logger._post_analysis,
        "snapshot",
        lambda: PostAnalysisHealthSnapshot(
            queue_depth=2,
            active_run_id="run-slow",
            active_started_at=None,
            oldest_queued_at=time.time() - 5.0,
            max_queue_depth=2,
            last_completed_run_id=None,
            last_completed_error=None,
        ),
    )

    report = logger.shutdown_report(timeout_s=0.1)

    assert report.completed is False
    assert report.active_run_id_before_stop is not None
    assert report.analysis_queue_depth == 2
    assert report.analysis_active_run_id == "run-slow"
    assert report.final_status.enabled is False


def test_post_analysis_uses_run_language_from_metadata(
    make_logger,
    tmp_path: Path,
) -> None:
    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    logger = make_logger(
        history_db=history_db.run_repository,
        language_reader=SimpleNamespace(language="nl"),
    )

    snapshot = _started_snapshot_with_sample(logger)
    run_id = snapshot.run_id

    def _analysis_runner(run):
        assert run.run_id == snapshot.run_id
        assert run.context.language == "nl"
        assert run.language == "nl"
        assert run.total_summary_row_count == len(run.samples)
        assert run.stride == 1
        return make_persisted_analysis(
            {
                "lang": run.language,
                "row_count": len(run.samples),
                "analysis_metadata": {
                    "analyzed_sample_count": len(run.samples),
                    "total_sample_count": run.total_summary_row_count,
                    "sampling_method": "full",
                },
                "run_suitability": [],
            }
        )

    # Private worker injection keeps this a recorder-flow test while forcing a
    # deterministic post-analysis result; worker mechanics have their own suite.
    logger._post_analysis._analysis_runner = _analysis_runner
    logger.stop_recording()

    def _status():
        run = history_db.run_repository.get_run(run_id)
        return run.status.value if run is not None else None

    assert wait_until(lambda: _status() == "complete", timeout_s=2.0)
    stored = history_db.run_repository.get_run(run_id).analysis
    assert stored is not None
    assert stored["lang"] == "nl"


def test_post_analysis_caps_sample_count_and_stores_sampling_metadata(
    make_logger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reduce the cap so we only need ~250 iterations instead of 13 000 (28 s -> <1 s).
    cap = 200
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_loader._MAX_POST_ANALYSIS_SAMPLES",
        cap,
    )

    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    logger = make_logger(history_db=history_db.run_repository)

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    for _ in range(cap + 50):
        logger._sample_flush.append_records(run_id, start_time_utc, start_mono)

    def _analysis_runner(run):
        assert run.run_id == snapshot.run_id
        assert run.language == "en"
        return make_persisted_analysis(
            {
                "row_count": len(run.samples),
                "analysis_metadata": {
                    "analyzed_sample_count": len(run.samples),
                    "total_sample_count": run.total_summary_row_count,
                    "sampling_method": ("full" if run.stride == 1 else f"stride_{run.stride}"),
                },
                "run_suitability": (
                    [
                        {
                            "check_key": "SUITABILITY_CHECK_ANALYSIS_SAMPLING",
                            "state": "warn",
                            "explanation": f"stride={run.stride}",
                        }
                    ]
                    if run.stride > 1
                    else []
                ),
            }
        )

    # The public recorder path intentionally owns scheduling; the injected
    # runner makes the sampled-run contract observable without real analysis.
    logger._post_analysis._analysis_runner = _analysis_runner
    logger.stop_recording()

    def _status():
        run = history_db.run_repository.get_run(run_id)
        return run.status.value if run is not None else None

    assert wait_until(lambda: _status() == "complete", timeout_s=3.0)
    stored = history_db.run_repository.get_run(run_id).analysis
    assert stored is not None
    assert stored["row_count"] <= cap
    assert stored["analysis_metadata"]["total_sample_count"] >= stored["row_count"]
    assert stored["analysis_metadata"]["sampling_method"].startswith("stride_")
    suitability_checks = {str(item.get("check_key")) for item in stored.get("run_suitability", [])}
    assert "SUITABILITY_CHECK_ANALYSIS_SAMPLING" in suitability_checks
