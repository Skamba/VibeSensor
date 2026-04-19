"""Behavior tests for HistoryDB analysis state transitions."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata


def _metadata(run_id: str, **overrides: object) -> RunMetadata:
    payload: dict[str, object] = {
        "run_id": run_id,
        "start_time_utc": "2026-01-01T00:00:00Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "source": "test",
    }
    payload.update(overrides)
    return run_metadata_from_mapping(payload)


@pytest.fixture
def history_db(tmp_path: Path) -> Iterator[HistoryDB]:
    db = HistoryDB(tmp_path / "test.db")
    try:
        yield db
    finally:
        db.close()


class TestHistoryDBAnalysisIdempotency:
    """Cover store_analysis idempotency, error transitions, and stored-analysis readback."""

    def test_store_analysis_twice_keeps_first(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis("r1", make_persisted_analysis({"findings": ["a"]}))
        history_db.store_analysis("r1", make_persisted_analysis({"findings": ["b"]}))
        run = history_db.get_run("r1")
        assert run is not None
        assert run.analysis is not None
        assert run.analysis["findings"] == ["a"]

    def test_store_analysis_error_transitions_to_error(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis_error("r1", "pipeline crash")
        run = history_db.get_run("r1")
        assert run is not None
        assert run.status.value == "error"
        assert run.error_message == "pipeline crash"

    def test_get_run_analysis_returns_stored_analysis(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        run = history_db.get_run("r1")
        assert run is not None
        assert run.analysis is None
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis("r1", make_persisted_analysis({"result": "ok"}))
        run = history_db.get_run("r1")
        assert run is not None
        result = run.analysis
        assert result is not None
        assert result["result"] == "ok"


class TestHistoryDBFinalizeNoOp:
    """Cover finalize_run no-op behavior for complete, missing, and non-recording runs."""

    def test_finalize_run_noop_on_already_complete(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis("r1", make_persisted_analysis({"ok": True}))
        history_db.finalize_run("r1", "2026-01-01T00:10:00Z")
        run = history_db.get_run("r1")
        assert run is not None
        assert run.status.value == "complete"

    def test_finalize_run_noop_on_missing_run(self, history_db: HistoryDB) -> None:
        history_db.finalize_run("nonexistent", "2026-01-01T00:00:00Z")
        assert history_db.get_run("nonexistent") is None

    def test_finalize_run_with_metadata_noop_when_not_recording(
        self,
        history_db: HistoryDB,
    ) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1", v=1))
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.finalize_run("r1", "2026-01-01T00:10:00Z", metadata=_metadata("r1", v=2))
        run = history_db.get_run("r1")
        assert run is not None
        assert run.status.value == "analyzing"

    def test_get_run_missing_returns_none(self, history_db: HistoryDB) -> None:
        assert history_db.get_run("nonexistent") is None

    def test_get_active_run_id(self, history_db: HistoryDB) -> None:
        assert history_db.get_active_run_id() is None
        history_db.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        assert history_db.get_active_run_id() == "r1"
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        assert history_db.get_active_run_id() is None
