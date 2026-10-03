"""Recording pipeline error visibility: worker outcomes, queue warnings, status/health.

Retry, cooldown and drop accounting live in ``test_persistence_writer.py``.
"""

from __future__ import annotations

import logging
import threading

import pytest

from vibesensor.analysis.post_analysis import _WARN_QUEUE_DEPTH, PostAnalysisWorker
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.recording.run_schema import RunMetadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_metadata(run_id: str, *, language: str = "en") -> RunMetadata:
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 800,
            "sample_rate_hz": 800,
            "feature_interval_s": 1.0,
            "language": language,
        }
    )


# ---------------------------------------------------------------------------
# Persistence coordination drop tracking
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Retry cooldown
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# PostAnalysisWorker — last completed outcome tracking
# ---------------------------------------------------------------------------


class TestPostAnalysisOutcomeTracking:
    def test_outcome_after_no_metadata(self, history_db) -> None:
        """A run missing from history records a metadata error outcome."""
        worker = PostAnalysisWorker(history_db=history_db)
        worker.schedule("run-nometa")
        assert worker.wait(timeout_s=10.0)

        snapshot = worker.snapshot()
        assert snapshot.last_completed_run_id == "run-nometa"
        assert snapshot.last_completed_error is not None
        assert "Metadata" in snapshot.last_completed_error

    def test_outcome_after_no_samples(self, history_db) -> None:
        """A stored run without samples records a samples error outcome."""
        history_db.create_run("run-empty", "2025-01-01T00:00:00Z", _run_metadata("run-empty"))
        worker = PostAnalysisWorker(history_db=history_db)
        worker.schedule("run-empty")
        assert worker.wait(timeout_s=10.0)

        snapshot = worker.snapshot()
        assert snapshot.last_completed_run_id == "run-empty"
        assert "samples" in (snapshot.last_completed_error or "").lower()


# ---------------------------------------------------------------------------
# PostAnalysisWorker — queue depth warning
# ---------------------------------------------------------------------------


class TestQueueDepthWarning:
    def test_warning_logged_at_threshold(self, caplog: pytest.LogCaptureFixture) -> None:
        """A warning is logged when queue depth reaches the threshold."""
        started = threading.Event()
        release = threading.Event()

        def _block(_rid: str) -> None:
            started.set()
            release.wait(timeout=5.0)

        worker = PostAnalysisWorker(history_db=None)
        worker._run_post_analysis = _block

        # Schedule one to block the worker
        worker.schedule("run-0")
        assert started.wait(timeout=10.0)

        # Fill queue past threshold
        with caplog.at_level(logging.WARNING, logger="vibesensor.analysis.post_analysis"):
            for i in range(1, _WARN_QUEUE_DEPTH + 1):
                worker.schedule(f"run-{i}")

        release.set()
        worker.wait(timeout_s=5.0)

        assert any("queue depth" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# RecordingStatusResponse enrichment
# ---------------------------------------------------------------------------


class TestLoggingStatusEnrichment:
    def test_status_includes_active_run_start_time(self, make_logger, tmp_path) -> None:
        """Status response includes the active run start time when recording."""
        logger = make_logger()

        assert logger.status().start_time_utc is None

        started = logger.start_recording()
        status = logger.status()

        assert started.start_time_utc is not None
        assert status.start_time_utc == started.start_time_utc


# ---------------------------------------------------------------------------
# Health snapshot enrichment
# ---------------------------------------------------------------------------


class TestHealthSnapshotEnrichment:
    def test_drops_reflected_after_append_failure(
        self, make_logger, failing_append_once_db
    ) -> None:
        """After a failed append, health and status both show the drop count."""
        logger = make_logger(history_db=failing_append_once_db)

        logger.start_recording()
        snapshot = logger._lifecycle.snapshot()
        assert snapshot is not None

        logger._sample_flush.append_records(
            snapshot.run_id,
            snapshot.start_time_utc,
            snapshot.start_mono_s,
        )

        health = logger.health_snapshot()
        status = logger.status()

        # First append fails → drops counted
        assert health["samples_dropped"] > 0
        assert status.samples_dropped > 0
