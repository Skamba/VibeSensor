"""Runtime regressions spanning API, history, and processing boundaries."""

from __future__ import annotations

import re
from pathlib import Path

from vibesensor.history_db import HistoryDB

_SAFE_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


class TestHistoryDBAnalysisValidation:
    """Analysis stored in history must be type-checked as dict."""

    @staticmethod
    def _make_db(tmp_path: Path) -> HistoryDB:
        db = HistoryDB(tmp_path / "history.db")
        db.create_run("run-1", "2026-01-01T00:00:00Z", {"source": "test"})
        return db

    def test_rejects_non_dict_analysis(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        with db._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status='complete', analysis_json=? WHERE run_id=?",
                ("[1,2,3]", "run-1"),
            )
        run = db.get_run("run-1")
        assert run is not None
        assert "analysis" not in run

    def test_accepts_dict_analysis(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        db.store_analysis("run-1", {"findings": []})
        run = db.get_run("run-1")
        assert run is not None
        assert isinstance(run.get("analysis"), dict)
