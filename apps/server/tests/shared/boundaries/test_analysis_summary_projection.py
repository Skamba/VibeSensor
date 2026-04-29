"""Tests for projecting reconstructed analysis summaries back to boundary payloads."""

from __future__ import annotations

from dataclasses import replace

from test_support.findings import make_finding_payload

from vibesensor.domain import Finding, VibrationSource
from vibesensor.shared.boundaries.analysis_payloads import (
    project_analysis_summary,
    project_persisted_analysis,
)
from vibesensor.shared.boundaries.summary_fields.finding import finding_payload_from_domain
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis


def _canonical_metadata() -> dict[str, object]:
    return {
        "active_car_snapshot": {
            "name": "Guard Car",
            "type": "sedan",
        }
    }


def test_project_analysis_summary_projects_run_suitability_from_reconstructed_test_run() -> None:
    summary = {
        "case_id": "case-001",
        "run_id": "run-001",
        "metadata": _canonical_metadata(),
        "findings": [make_finding_payload(finding_id="F001", confidence=0.8)],
        "top_causes": [make_finding_payload(finding_id="F001", confidence=0.8)],
        "test_plan": [
            {
                "action_id": "check-wheel",
                "what": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHAT"},
                "why": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHY"},
            }
        ],
        "run_suitability": [
            {"check_key": "speed_profile", "state": "warn"},
        ],
    }

    projected, test_run = project_analysis_summary(summary)

    assert test_run.suitability is not None
    assert projected["run_suitability"] == [
        {
            "check_key": "speed_profile",
            "state": "warn",
            "explanation": test_run.suitability.checks[0].explanation_i18n_ref(),
        }
    ]


def test_project_analysis_summary_drops_persisted_origin_without_primary_finding() -> None:
    summary = {
        "case_id": "case-001",
        "run_id": "run-001",
        "metadata": _canonical_metadata(),
        "findings": [],
        "top_causes": [],
        "test_plan": [],
        "run_suitability": [],
        "most_likely_origin": {
            "location": "rear left",
            "suspected_source": "wheel/tire",
            "weak_spatial_separation": True,
        },
    }

    projected, test_run = project_analysis_summary(summary)

    assert test_run.primary_finding is None
    assert projected["most_likely_origin"] == {}


def test_project_analysis_summary_preserves_persisted_confidence_reason() -> None:
    finding = Finding(
        finding_id="F001",
        suspected_source=VibrationSource.WHEEL_TIRE,
        confidence=0.66,
        strongest_location="front-left",
        weak_spatial_separation=True,
    ).with_confidence_assessment(
        strength_band_key="moderate",
        steady_speed=True,
        has_reference_gaps=False,
        sensor_count=4,
    )
    assert finding.confidence_assessment is not None
    finding = replace(
        finding,
        confidence_assessment=replace(
            finding.confidence_assessment,
            reason="Wheel and driveline evidence overlap; inspect both areas.",
        ),
    )
    payload = finding_payload_from_domain(finding)
    summary = {
        "case_id": "case-001",
        "run_id": "run-001",
        "metadata": _canonical_metadata(),
        "findings": [payload],
        "top_causes": [payload],
        "test_plan": [],
        "run_suitability": [],
        "sensor_locations": ["front-left", "front-right", "rear-left", "rear-right"],
    }

    projected, _ = project_analysis_summary(summary)

    assert projected["top_causes"][0]["confidence_reason"] == payload["confidence_reason"]


def test_project_analysis_summary_uses_list_sensor_locations_for_fallback_confidence() -> None:
    summary = {
        "case_id": "case-001",
        "run_id": "run-001",
        "metadata": _canonical_metadata(),
        "findings": [
            make_finding_payload(
                finding_id="F001",
                confidence=0.66,
                strongest_location="front-left",
                weak_spatial_separation=True,
            )
        ],
        "top_causes": [
            make_finding_payload(
                finding_id="F001",
                confidence=0.66,
                strongest_location="front-left",
                weak_spatial_separation=True,
            )
        ],
        "test_plan": [],
        "run_suitability": [],
        "sensor_locations": ["front-left", "front-right", "rear-left", "rear-right"],
    }

    projected, test_run = project_analysis_summary(summary)

    assert test_run.sensor_count == 4
    assert (
        projected["top_causes"][0]["confidence_reason"]
        == "Vibration spread across multiple locations"
    )


def test_project_persisted_analysis_projects_persisted_payload_contract() -> None:
    analysis = PersistedAnalysis.from_json_object(
        {
            "case_id": "case-001",
            "run_id": "run-001",
            "metadata": _canonical_metadata(),
            "findings": [make_finding_payload(finding_id="F001", confidence=0.8)],
            "top_causes": [make_finding_payload(finding_id="F001", confidence=0.8)],
            "test_plan": [],
            "run_suitability": [],
            "warnings": [],
        }
    )

    projected, test_run = project_persisted_analysis(analysis)

    assert test_run.capture.run_id == "run-001"
    assert projected["top_causes"][0]["finding_id"] == "F001"
