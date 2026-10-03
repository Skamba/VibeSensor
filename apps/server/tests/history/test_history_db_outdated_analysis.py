"""History DBs with analyses stored under an older schema are re-analysed, not served."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from test_support.analysis import run_analysis
from test_support.history_db_lifecycle import create_recording_run
from test_support.report_helpers import report_sample

from vibesensor.domain.run_status import RunStatus
from vibesensor.history.history_db import HistoryDB
from vibesensor.summary.persisted_analysis import PersistedAnalysis

_OLD_RUN = "legacy-run"
_CURRENT_RUN = "current-run"


def _store_complete_run(db: HistoryDB, run_id: str) -> None:
    create_recording_run(db, run_id)
    db.finalize_run(run_id, "2026-01-01T00:05:00Z")
    summary = run_analysis(
        [
            report_sample(index, speed_kmh=60.0 + index, dominant_freq_hz=15.0, peak_amp_g=0.12)
            for index in range(4)
        ],
        language="en",
    )
    db.store_analysis(run_id, PersistedAnalysis.from_json_object(summary))


def _write_db_with_outdated_run(tmp_path: Path) -> Path:
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    _store_complete_run(db, _OLD_RUN)
    _store_complete_run(db, _CURRENT_RUN)
    db.close()
    conn = sqlite3.connect(db_path)
    try:
        # Older versions also left whole-run columns and sidecars behind.
        conn.execute("ALTER TABLE runs ADD COLUMN whole_run_artifact_manifest_json TEXT")
        (analysis_json,) = conn.execute(
            "SELECT analysis_json FROM runs WHERE run_id = ?", (_OLD_RUN,)
        ).fetchone()
        stored = json.loads(analysis_json)
        stored["_schema_version"] = 1
        stored.pop("diagnosis")
        stored["whole_run_diagnosis_summaries"] = []
        conn.execute(
            "UPDATE runs SET analysis_json = ? WHERE run_id = ?", (json.dumps(stored), _OLD_RUN)
        )
        conn.commit()
    finally:
        conn.close()
    sidecar = tmp_path / "whole-run-artifacts" / _OLD_RUN
    sidecar.mkdir(parents=True)
    (sidecar / "manifest.json").write_text("{}", encoding="utf-8")
    return db_path


def test_outdated_analyses_are_cleared_and_requeued(tmp_path: Path) -> None:
    db = HistoryDB(_write_db_with_outdated_run(tmp_path))
    try:
        assert not (tmp_path / "whole-run-artifacts").exists()

        assert db.requeue_outdated_analyses() == [_OLD_RUN]
        assert db.requeue_outdated_analyses() == []
        assert db.stale_analyzing_run_ids() == [_OLD_RUN]

        old = db.get_run(_OLD_RUN)
        assert old is not None
        assert old.status == RunStatus.ANALYZING
        assert old.analysis is None

        current = db.get_run(_CURRENT_RUN)
        assert current is not None
        assert current.status == RunStatus.COMPLETE
        assert current.analysis is not None
        assert current.analysis.payload["diagnosis"]["verdict"] in {
            "fault",
            "weak_evidence",
            "no_fault",
        }
    finally:
        db.close()
