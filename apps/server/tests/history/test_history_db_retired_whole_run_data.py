"""History DBs written before the whole-run pipeline was removed keep loading."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import cast

from test_support.analysis import run_analysis
from test_support.history_db_lifecycle import create_recording_run
from test_support.report_helpers import report_sample

from vibesensor.history.history_db import HistoryDB
from vibesensor.history.projection import project_history_insights, project_history_run_record
from vibesensor.report.document.builder import build_report_document
from vibesensor.report.pdf.pdf_engine import build_report_pdf
from vibesensor.report.preparation import prepare_persisted_report_input
from vibesensor.summary.persisted_analysis import PersistedAnalysis
from vibesensor.web.models.history import (
    HistoryListEntryResponse,
    HistoryRunResponse,
)

_RUN_ID = "legacy-run"


def _write_pre_removal_run(tmp_path: Path) -> Path:
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    create_recording_run(db, _RUN_ID)
    db.finalize_run(_RUN_ID, "2026-01-01T00:05:00Z")
    summary = run_analysis(
        [
            report_sample(index, speed_kmh=60.0 + index, dominant_freq_hz=15.0, peak_amp_g=0.12)
            for index in range(4)
        ],
        language="en",
    )
    db.store_analysis(_RUN_ID, PersistedAnalysis.from_json_object(summary))
    db.close()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("ALTER TABLE runs ADD COLUMN whole_run_artifact_manifest_json TEXT")
        (analysis_json,) = conn.execute(
            "SELECT analysis_json FROM runs WHERE run_id = ?", (_RUN_ID,)
        ).fetchone()
        stored = json.loads(analysis_json)
        stored["whole_run_diagnosis_summaries"] = [
            {"diagnosis_key": "wheel", "suspected_source": "wheel/tire", "rank": 1}
        ]
        stored["whole_run_context_intervals"] = []
        stored["whole_run_order_summaries"] = []
        stored["whole_run_spatial_summaries"] = []
        stored["analysis_metadata"] = {
            "raw_backed_sample_count": 4,
            "raw_capture_mode": "raw_backed",
            "whole_run_artifacts_available": True,
            "whole_run_spectral_window_count": 12,
            "raw_capture_loss_policy_gate_whole_run": False,
        }
        stored.setdefault("warnings", []).append(
            {
                "code": "whole_run_alignment_incomplete",
                "severity": "warn",
                "applies_to": "whole_run",
                "title": {"_i18n_key": "RUN_CONTEXT_WARNING_WHOLE_RUN_ALIGNMENT_INCOMPLETE_TITLE"},
            }
        )
        conn.execute(
            "UPDATE runs SET analysis_json = ?, whole_run_artifact_manifest_json = ? "
            "WHERE run_id = ?",
            (json.dumps(stored), json.dumps({"run_id": _RUN_ID}), _RUN_ID),
        )
        conn.commit()
    finally:
        conn.close()
    sidecar = tmp_path / "whole-run-artifacts" / _RUN_ID
    sidecar.mkdir(parents=True)
    (sidecar / "manifest.json").write_text("{}", encoding="utf-8")
    return db_path


def test_pre_removal_history_db_loads_and_projects_without_whole_run_fields(
    tmp_path: Path,
) -> None:
    db = HistoryDB(_write_pre_removal_run(tmp_path))
    try:
        assert not (tmp_path / "whole-run-artifacts").exists()

        entries = db.list_runs()
        assert [entry.run_id for entry in entries] == [_RUN_ID]
        HistoryListEntryResponse.model_validate(entries[0].to_json_object())

        run = db.get_run(_RUN_ID)
        assert run is not None
        assert run.analysis is not None
        analysis = run.analysis.to_json_object()
        assert not [key for key in analysis if key.startswith("whole_run_")]
        metadata = cast(dict[str, object], analysis["analysis_metadata"])
        assert not [key for key in metadata if "whole_run" in key]
        warnings = cast(list[dict[str, object]], analysis["warnings"])
        assert all(not str(warning["code"]).startswith("whole_run_") for warning in warnings)

        HistoryRunResponse.model_validate(project_history_run_record(run))
        insights = project_history_insights(analysis)
        assert not [key for key in insights if key.startswith("whole_run_")]

        pdf = build_report_pdf(build_report_document(prepare_persisted_report_input(run.analysis)))
        assert pdf.startswith(b"%PDF")
    finally:
        db.close()
