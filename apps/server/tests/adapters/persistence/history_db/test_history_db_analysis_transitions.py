"""Behavior tests for HistoryDB analysis state transitions."""

from __future__ import annotations

from test_support.history_db_lifecycle import create_recording_run
from test_support.history_db_lifecycle import make_run_metadata as _metadata
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.persistence.history_db._history_db import HistoryDB


class TestHistoryDBAnalysisIdempotency:
    """Cover store_analysis idempotency, error transitions, and stored-analysis readback."""

    def test_store_analysis_twice_keeps_first(self, db: HistoryDB) -> None:
        create_recording_run(db, "r1")
        db.finalize_run("r1", "2026-01-01T00:05:00Z")
        db.store_analysis("r1", make_persisted_analysis({"findings": ["a"]}))
        db.store_analysis("r1", make_persisted_analysis({"findings": ["b"]}))
        run = db.get_run("r1")
        assert run is not None
        assert run.analysis is not None
        assert run.analysis["findings"] == ["a"]

    def test_store_analysis_error_transitions_to_error(self, db: HistoryDB) -> None:
        create_recording_run(db, "r1")
        db.finalize_run("r1", "2026-01-01T00:05:00Z")
        db.store_analysis_error("r1", "pipeline crash")
        run = db.get_run("r1")
        assert run is not None
        assert run.status.value == "error"
        assert run.error_message == "pipeline crash"

    def test_get_run_analysis_returns_stored_analysis(self, db: HistoryDB) -> None:
        create_recording_run(db, "r1")
        run = db.get_run("r1")
        assert run is not None
        assert run.analysis is None
        db.finalize_run("r1", "2026-01-01T00:05:00Z")
        db.store_analysis("r1", make_persisted_analysis({"result": "ok"}))
        run = db.get_run("r1")
        assert run is not None
        result = run.analysis
        assert result is not None
        assert result["result"] == "ok"


class TestHistoryDBFinalizeNoOp:
    """Cover finalize_run no-op behavior for complete, missing, and non-recording runs."""

    def test_finalize_run_noop_on_already_complete(self, db: HistoryDB) -> None:
        create_recording_run(db, "r1")
        db.finalize_run("r1", "2026-01-01T00:05:00Z")
        db.store_analysis("r1", make_persisted_analysis({"ok": True}))
        db.finalize_run("r1", "2026-01-01T00:10:00Z")
        run = db.get_run("r1")
        assert run is not None
        assert run.status.value == "complete"

    def test_finalize_run_noop_on_missing_run(self, db: HistoryDB) -> None:
        db.finalize_run("nonexistent", "2026-01-01T00:00:00Z")
        assert db.get_run("nonexistent") is None

    def test_finalize_run_with_metadata_noop_when_not_recording(
        self,
        db: HistoryDB,
    ) -> None:
        create_recording_run(db, "r1", v=1)
        db.finalize_run("r1", "2026-01-01T00:05:00Z")
        db.finalize_run("r1", "2026-01-01T00:10:00Z", metadata=_metadata("r1", v=2))
        run = db.get_run("r1")
        assert run is not None
        assert run.status.value == "analyzing"

    def test_get_run_missing_returns_none(self, db: HistoryDB) -> None:
        assert db.get_run("nonexistent") is None
