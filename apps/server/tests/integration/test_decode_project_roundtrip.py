"""Decode/project integration tests for the persistence reload boundary.

These tests keep ownership of domain meaning across:
analysis -> persistence -> history-service reload projection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_support import (
    ALL_WHEEL_SENSORS,
    make_fault_samples,
    make_noise_samples,
    standard_metadata,
)
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.analysis_summary import analysis_result_to_summary
from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.domain import DiagnosticCase, TestRun
from vibesensor.shared.boundaries.analysis_payloads import project_analysis_summary
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.use_cases.diagnostics._run_input import build_diagnostics_run_input
from vibesensor.use_cases.diagnostics.run_analysis import AnalysisResult, RunAnalysis

# -- helpers ---------------------------------------------------------------

_RUN_ID = "integration-roundtrip"


def _run_analysis() -> tuple[RunAnalysis, AnalysisResult]:
    """Run analysis on a wheel-fault scenario and return (analysis, result)."""
    meta = standard_metadata(language="en")
    samples: list[dict[str, Any]] = []
    samples.extend(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=15, speed_kmh=60.0))
    samples.extend(
        make_fault_samples(
            fault_sensor="front-left",
            sensors=ALL_WHEEL_SENSORS,
            speed_kmh=80.0,
            n_samples=20,
        )
    )
    analysis = RunAnalysis(
        build_diagnostics_run_input(
            run_metadata_from_mapping(meta),
            sensor_frames_from_mappings(samples),
            file_name="roundtrip",
        ),
        lang="en",
        file_name="roundtrip",
    )
    result = analysis.summarize()
    return analysis, result


def _persist_and_reload(tmp_path: Path, summary: dict[str, Any]) -> StoredHistoryRun:
    """Persist summary to HistoryDB and reload as a run payload."""
    db = create_history_persistence_adapters(tmp_path / "roundtrip.db")
    try:
        db.run_repository.create_run(
            _RUN_ID,
            "2026-01-01T00:00:00Z",
            run_metadata_from_mapping(
                {
                    "run_id": _RUN_ID,
                    "start_time_utc": "2026-01-01T00:00:00Z",
                    **standard_metadata(),
                }
            ),
        )
        db.run_repository.finalize_run(_RUN_ID, "2026-01-01T00:01:00Z")
        db.run_repository.store_analysis(_RUN_ID, make_persisted_analysis(summary))
        run = db.run_repository.get_run(_RUN_ID)
    finally:
        db.lifecycle.close()
    assert run is not None
    return run


def _reproject(analysis_blob: dict[str, Any]) -> dict[str, Any]:
    """Re-serialize domain-owned fields through TestRun reconstruction."""
    projected, _ = project_analysis_summary(analysis_blob)
    return dict(projected)


def _extract_domain_meaning(summary: dict[str, Any]) -> dict[str, Any]:
    """Extract a normalised set of domain-meaning fields for comparison."""
    top_causes = summary.get("top_causes", [])
    origin = summary.get("most_likely_origin", {})
    suitability = summary.get("run_suitability", [])
    test_plan = summary.get("test_plan", [])

    first_cause = top_causes[0] if top_causes else {}
    suitability_states = {
        c["check_key"]: c["state"]
        for c in suitability
        if isinstance(c, dict) and "check_key" in c and "state" in c
    }
    action_ids = [s["action_id"] for s in test_plan if isinstance(s, dict) and "action_id" in s]
    return {
        "finding_key": first_cause.get("finding_key"),
        "suspected_source": first_cause.get("suspected_source"),
        "confidence": first_cause.get("confidence"),
        "confidence_tone": first_cause.get("confidence_tone"),
        "origin_location": origin.get("location"),
        "origin_source": origin.get("suspected_source"),
        "suitability_states": suitability_states,
        "action_ids": action_ids,
    }


# -- T9.20: Analysis produces wired domain aggregates ---------------------


def test_analysis_produces_wired_domain_aggregates() -> None:
    """Analysis must produce TestRun and DiagnosticCase with correct wiring."""
    analysis, result = _run_analysis()

    assert isinstance(analysis.test_run, TestRun)
    assert isinstance(result.diagnostic_case, DiagnosticCase)

    # diagnostic_case.primary_run is wired to the same TestRun
    assert result.diagnostic_case.primary_run is not None
    assert result.diagnostic_case.primary_run.run_id == analysis.test_run.run_id

    # domain aggregates reflect summary content
    assert len(analysis.test_run.top_causes) > 0
    assert analysis.test_run.run_id == "run-roundtrip"
    top = analysis.test_run.top_causes[0]
    summary = analysis_result_to_summary(result)
    assert str(top.suspected_source) == summary["top_causes"][0]["suspected_source"]


# -- T9.21+T9.22: Persist → reload → project preserves domain meaning -----


def test_persist_reload_project_preserves_domain_meaning(tmp_path: Path) -> None:
    """Summary persisted to DB and reloaded through domain reconstruction
    must carry the same domain meaning as the direct analysis output."""
    _analysis, result = _run_analysis()
    direct_summary = analysis_result_to_summary(result)
    run = _persist_and_reload(tmp_path, direct_summary)

    analysis_blob = run.analysis
    assert analysis_blob is not None
    reconstructed = _reproject(analysis_blob.to_json_object())

    direct_meaning = _extract_domain_meaning(direct_summary)
    reloaded_meaning = _extract_domain_meaning(reconstructed)

    assert direct_meaning["finding_key"] == reloaded_meaning["finding_key"]
    assert direct_meaning["suspected_source"] == reloaded_meaning["suspected_source"]
    assert direct_meaning["confidence"] == pytest.approx(reloaded_meaning["confidence"])
    assert direct_meaning["confidence_tone"] == reloaded_meaning["confidence_tone"]
    # Origin location may differ in casing (title-cased by projector) — compare lowered
    assert (direct_meaning["origin_location"] or "").lower() == (
        reloaded_meaning["origin_location"] or ""
    ).lower()
    assert direct_meaning["origin_source"] == reloaded_meaning["origin_source"]
    assert direct_meaning["suitability_states"] == reloaded_meaning["suitability_states"]
    assert direct_meaning["action_ids"] == reloaded_meaning["action_ids"]
