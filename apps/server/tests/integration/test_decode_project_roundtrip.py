"""T9.20–T9.25: Decode/project integration tests.

Verifies that domain meaning is preserved across the full lifecycle:
analysis → persistence → history-service reload → report mapping → export.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_support import (
    ALL_WHEEL_SENSORS,
    make_fault_samples,
    make_noise_samples,
    standard_metadata,
)

from vibesensor.adapters.pdf.mapping import map_summary
from vibesensor.adapters.pdf.report_data import ReportTemplateData
from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.domain import DiagnosticCase, TestRun
from vibesensor.shared.boundaries._helpers import _has_structured_step_content
from vibesensor.shared.boundaries.diagnostic_case import (
    test_run_from_summary as _test_run_from_summary,
)
from vibesensor.shared.boundaries.finding import finding_payload_from_domain
from vibesensor.shared.boundaries.run_suitability import run_suitability_payload
from vibesensor.shared.boundaries.test_steps import step_payloads_from_plan
from vibesensor.shared.boundaries.vibration_origin import origin_payload_from_finding
from vibesensor.use_cases.diagnostics import RunAnalysis
from vibesensor.use_cases.history.exports import build_run_details_json

# -- helpers ---------------------------------------------------------------

_RUN_ID = "integration-roundtrip"


def _run_analysis() -> tuple[RunAnalysis, dict[str, Any]]:
    """Run analysis on a wheel-fault scenario and return (analysis, summary)."""
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
    analysis = RunAnalysis(meta, samples, lang="en", file_name="roundtrip")
    result = analysis.summarize()
    return analysis, result.summary


def _persist_and_reload(tmp_path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    """Persist summary to HistoryDB and reload as a run payload."""
    db = HistoryDB(tmp_path / "roundtrip.db")
    try:
        db.create_run(_RUN_ID, "2026-01-01T00:00:00Z", standard_metadata())
        db.finalize_run(_RUN_ID, "2026-01-01T00:01:00Z")
        db.store_analysis(_RUN_ID, summary)
        run = db.get_run(_RUN_ID)
    finally:
        db.close()
    assert run is not None
    return run


def _reproject(analysis_blob: dict[str, Any]) -> dict[str, Any]:
    """Re-serialize domain-owned fields through TestRun reconstruction."""
    test_run = _test_run_from_summary(analysis_blob)
    projected: dict[str, Any] = dict(analysis_blob)
    projected["findings"] = [finding_payload_from_domain(f) for f in test_run.findings]
    projected["top_causes"] = [
        finding_payload_from_domain(f) for f in test_run.effective_top_causes()
    ]
    primary = test_run.primary_finding
    origin_fb = analysis_blob.get("most_likely_origin")
    fb_payload = dict(origin_fb) if isinstance(origin_fb, dict) else {}
    projected["most_likely_origin"] = (
        origin_payload_from_finding(primary, fb_payload) if primary is not None else fb_payload
    )
    if not _has_structured_step_content(analysis_blob.get("test_plan")):
        projected["test_plan"] = step_payloads_from_plan(test_run.test_plan)
    projected["run_suitability"] = run_suitability_payload(test_run.suitability)
    return projected


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
    analysis, summary = _run_analysis()

    assert isinstance(analysis.test_run, TestRun)
    assert isinstance(analysis.diagnostic_case, DiagnosticCase)

    # diagnostic_case.primary_run is the same TestRun
    assert analysis.diagnostic_case.primary_run is analysis.test_run

    # domain aggregates reflect summary content
    assert len(analysis.test_run.top_causes) > 0
    assert analysis.test_run.run_id == "run-roundtrip"
    top = analysis.test_run.top_causes[0]
    assert str(top.suspected_source) == summary["top_causes"][0]["suspected_source"]


# -- T9.21+T9.22: Persist → reload → project preserves domain meaning -----


def test_persist_reload_project_preserves_domain_meaning(tmp_path: Path) -> None:
    """Summary persisted to DB and reloaded through domain reconstruction
    must carry the same domain meaning as the direct analysis output."""
    _analysis, direct_summary = _run_analysis()
    run = _persist_and_reload(tmp_path, direct_summary)

    analysis_blob = run.get("analysis")
    assert isinstance(analysis_blob, dict)
    reconstructed = _reproject(analysis_blob)

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


# -- T9.23: Report from reconstructed aggregate ---------------------------


def test_report_from_reconstructed_aggregate(tmp_path: Path) -> None:
    """Report mapping from a reconstructed (persisted → reloaded) summary
    must produce valid ReportTemplateData with the same primary system."""
    _analysis, direct_summary = _run_analysis()
    run = _persist_and_reload(tmp_path, direct_summary)

    analysis_blob = run.get("analysis")
    assert isinstance(analysis_blob, dict)
    reconstructed = _reproject(analysis_blob)

    direct_report = map_summary(direct_summary)
    reloaded_report = map_summary(reconstructed)

    assert isinstance(direct_report, ReportTemplateData)
    assert isinstance(reloaded_report, ReportTemplateData)

    # Same primary system identification
    assert direct_report.observed.primary_system == reloaded_report.observed.primary_system
    # Same certainty tier
    assert direct_report.certainty_tier_key == reloaded_report.certainty_tier_key
    # Same number of system cards and next steps
    assert len(direct_report.system_cards) == len(reloaded_report.system_cards)
    assert len(direct_report.next_steps) == len(reloaded_report.next_steps)


# -- T9.24: Export from reconstructed aggregate ----------------------------


def test_export_from_reconstructed_aggregate(tmp_path: Path) -> None:
    """build_run_details_json must produce valid JSON from a history run
    whose analysis was projected through domain."""
    _analysis, direct_summary = _run_analysis()
    run = _persist_and_reload(tmp_path, direct_summary)

    export_json = build_run_details_json(run, sample_count=35, run_id=_RUN_ID)
    export_data = json.loads(export_json)

    assert isinstance(export_data, dict)
    analysis = export_data.get("analysis")
    assert isinstance(analysis, dict)

    # Domain meaning survived export pipeline
    top_causes = analysis.get("top_causes", [])
    assert len(top_causes) > 0
    assert top_causes[0]["finding_key"] is not None

    # Internal fields stripped
    assert "_internal" not in analysis


# -- T9.25: Cross-boundary consistency assertion ---------------------------


def test_cross_boundary_domain_meaning_consistency(tmp_path: Path) -> None:
    """Same scenario through direct analysis and history-reload paths must
    produce equivalent domain meaning in summary, report, and export outputs."""
    analysis, direct_summary = _run_analysis()
    run = _persist_and_reload(tmp_path, direct_summary)

    analysis_blob = run.get("analysis")
    assert isinstance(analysis_blob, dict)
    reconstructed = _reproject(analysis_blob)

    # 1. Summary-level consistency
    direct_meaning = _extract_domain_meaning(direct_summary)
    reloaded_meaning = _extract_domain_meaning(reconstructed)
    assert direct_meaning["finding_key"] == reloaded_meaning["finding_key"]
    assert direct_meaning["suspected_source"] == reloaded_meaning["suspected_source"]
    assert direct_meaning["confidence"] == pytest.approx(reloaded_meaning["confidence"])
    assert direct_meaning["action_ids"] == reloaded_meaning["action_ids"]

    # 2. Report-level consistency
    direct_report = map_summary(direct_summary)
    reloaded_report = map_summary(reconstructed)
    assert direct_report.observed.primary_system == reloaded_report.observed.primary_system
    assert direct_report.observed.certainty_label == reloaded_report.observed.certainty_label
    direct_card_names = [c.system_name for c in direct_report.system_cards]
    reloaded_card_names = [c.system_name for c in reloaded_report.system_cards]
    assert direct_card_names == reloaded_card_names

    # 3. Export-level consistency
    export_json = build_run_details_json(run, sample_count=35, run_id=_RUN_ID)
    export_data = json.loads(export_json)
    export_analysis = export_data["analysis"]
    export_top_causes = export_analysis.get("top_causes", [])
    assert len(export_top_causes) == len(direct_summary.get("top_causes", []))
    if export_top_causes:
        assert export_top_causes[0]["finding_key"] == direct_meaning["finding_key"]
