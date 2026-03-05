"""Runtime fallback and error-guard regressions.

Covers strength_floor_amp_g fallback, wheel_focus_from_location,
store_analysis_error guard, and i18n formatting.
"""

from __future__ import annotations

import pytest

from vibesensor.history_db import HistoryDB


class TestStoreAnalysisErrorGuard:
    """Regression: store_analysis_error must not overwrite a completed run."""

    def test_error_does_not_overwrite_complete(self, tmp_path: pytest.TempPathFactory) -> None:
        db = HistoryDB(tmp_path / "test.db")
        run_id = "test-run-001"
        db.create_run(run_id, "2024-01-01T00:00:00", {"test": True})

        # Complete the analysis
        db.store_analysis(run_id, {"result": "ok"})
        status_before = db.get_run_status(run_id)
        assert status_before == "complete"

        # Try to overwrite with an error
        db.store_analysis_error(run_id, "spurious error")
        status_after = db.get_run_status(run_id)
        assert status_after == "complete", "store_analysis_error must not overwrite a completed run"
