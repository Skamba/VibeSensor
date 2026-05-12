"""Focused report document projection contracts."""

from __future__ import annotations

import pytest
from test_support.findings import make_finding_payload
from test_support.report_helpers import (
    minimal_summary,
    recapture_guidance_summary,
    sequential_same_source_summary,
    trunk_primary_guidance_summary,
)

from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.use_cases.history.report_document import build_report_document


def test_build_report_document_uses_domain_action_render_queries_for_next_steps() -> None:
    summary = minimal_summary(
        findings=[
            {
                "finding_id": "F001",
                "suspected_source": "engine",
                "confidence": 0.74,
            }
        ],
        top_causes=[
            {
                "finding_id": "F001",
                "suspected_source": "engine",
                "confidence": 0.74,
            }
        ],
        test_plan=[
            {
                "action_id": "engine_mounts_and_accessories",
                "what": "  ACTION_ENGINE_MOUNTS_WHAT  ",
                "why": "  ACTION_ENGINE_MOUNTS_WHY  ",
                "confirm": "  ACTION_ENGINE_MOUNTS_CONFIRM  ",
                "falsify": "   ",
                "eta": " 15-30 min ",
            }
        ],
    )

    data = build_report_document(prepare_report_input(summary))

    assert data.next_steps[0].action
    assert "engine mount" in data.next_steps[0].action.lower()
    assert data.next_steps[0].why
    assert data.next_steps[0].confirm
    assert data.next_steps[0].falsify is None
    assert data.next_steps[0].eta is None


def test_build_report_document_next_steps_do_not_leak_placeholder_tokens() -> None:
    summary = minimal_summary(
        findings=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.74,
                "strongest_location": "front-left wheel",
            }
        ],
        top_causes=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.74,
                "strongest_location": "front-left wheel",
            }
        ],
        test_plan=[
            {
                "action_id": "wheel_balance_and_runout",
                "what": "ACTION_WHEEL_BALANCE_WHAT",
                "why": "ACTION_WHEEL_BALANCE_WHY",
                "confirm": "ACTION_WHEEL_BALANCE_CONFIRM",
                "falsify": "ACTION_WHEEL_BALANCE_FALSIFY",
                "eta": "20-45 min",
            },
            {
                "action_id": "wheel_tire_condition",
                "what": "ACTION_TIRE_CONDITION_WHAT",
                "why": "ACTION_TIRE_CONDITION_WHY",
                "confirm": "ACTION_TIRE_CONDITION_CONFIRM",
                "falsify": "ACTION_TIRE_CONDITION_FALSIFY",
                "eta": "10-20 min",
            },
            {
                "action_id": "driveline_inspection",
                "what": "ACTION_DRIVELINE_INSPECTION_WHAT",
                "why": "ACTION_DRIVELINE_INSPECTION_WHY",
                "confirm": "ACTION_DRIVELINE_INSPECTION_CONFIRM",
                "falsify": "ACTION_DRIVELINE_INSPECTION_FALSIFY",
                "eta": "20-35 min",
            },
        ],
    )

    data = build_report_document(prepare_report_input(summary))
    assert len(data.next_steps) == 2
    assert all(step.eta is None for step in data.next_steps)
    assert all("front-left" in step.action.lower() for step in data.next_steps)
    rendered = " ".join(
        part
        for step in data.next_steps
        for part in (step.action, step.why, step.confirm, step.falsify)
        if part
    )

    assert "{wheel_focus}" not in rendered
    assert "{speed_hint}" not in rendered
    assert "{location_hint}" not in rendered
    assert "{driveline_focus}" not in rendered
    assert "{" not in rendered
    assert "}" not in rendered


@pytest.mark.parametrize(
    ("primary_source", "expected_text", "unexpected_text"),
    [
        pytest.param(
            "engine",
            "check engine mounts and accessory drive",
            "tire damage",
            id="engine-trunk-hotspot",
        ),
        pytest.param(
            "driveline",
            "inspect propshaft runout/balance",
            "check driveline components near trunk",
            id="driveline-trunk-hotspot",
        ),
    ],
)
def test_build_report_document_keeps_generated_next_steps_on_primary_source_path_for_trunk_hotspots(
    primary_source: str,
    expected_text: str,
    unexpected_text: str,
) -> None:
    data = build_report_document(
        prepare_report_input(trunk_primary_guidance_summary(primary_source=primary_source))
    )

    rendered = " ".join(
        part
        for step in data.next_steps
        for part in (step.action, step.why, step.confirm, step.falsify)
        if part
    ).lower()

    assert expected_text in rendered
    assert unexpected_text not in rendered
    assert "check trunk for tire damage" not in rendered
    assert "imbalance or radial/lateral runout" not in rendered


@pytest.mark.parametrize(
    ("mode", "expected_issue", "expected_step", "expected_condition"),
    [
        pytest.param(
            "steady",
            "Speed range never settled into a usable diagnostic band",
            "Repeat the same speed band with a longer steady hold",
            "Hold a repeatable steady-speed window",
            id="steady-speed-recature-guidance",
        ),
        pytest.param(
            "overlap",
            "Wheel / Tire and Driveline evidence overlapped",
            "Repeat the same speed band with separate drive/coast or load-change passes",
            "Cover the same speed band in separate drive/coast or load-change passes",
            id="source-overlap-recature-guidance",
        ),
        pytest.param(
            "weak",
            "Location evidence stayed spread across multiple positions",
            "Add sensor locations",
            "Keep all 4 expected positions connected throughout the run",
            id="weak-location-recature-guidance",
        ),
        pytest.param(
            "transient",
            "The strongest signal was transient or intermittent",
            "Repeat the same trigger several times",
            "Repeat the same trigger with enough before/after baseline",
            id="transient-recature-guidance",
        ),
    ],
)
def test_build_report_document_builds_scenario_specific_recapture_guidance(
    mode: str,
    expected_issue: str,
    expected_step: str,
    expected_condition: str,
) -> None:
    data = build_report_document(prepare_report_input(recapture_guidance_summary(mode)))

    assert data.appendix_a.mode == "recapture"
    assert any(expected_issue in line for line in data.appendix_a.capture_issues)
    assert any(expected_step in step.action for step in data.next_steps)
    assert any(expected_condition in line for line in data.appendix_a.capture_conditions)


def test_build_report_document_softens_same_corner_wheel_driveline_overlap_wording() -> None:
    overlap_reason = (
        "Wheel and driveline evidence overlap, so the system could not strongly "
        "differentiate between them; inspect both areas."
    )
    wheel = make_finding_payload(
        finding_id="F_WHEEL",
        suspected_source="wheel/tire",
        confidence=0.66,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        frequency_hz_or_order="1x wheel order",
        signatures_observed=["1x wheel order"],
        matched_points=[
            {
                "speed_kmh": 62.0,
                "predicted_hz": 13.2,
                "matched_hz": 13.4,
                "location": "Front Left",
            },
            {
                "speed_kmh": 68.0,
                "predicted_hz": 14.0,
                "matched_hz": 14.1,
                "location": "Front Left",
            },
        ],
        confidence_label_key="CONFIDENCE_MEDIUM",
        confidence_tone="warn",
        confidence_pct="66%",
        confidence_reason=overlap_reason,
    )
    driveline = make_finding_payload(
        finding_id="F_DRIVELINE",
        suspected_source="driveline",
        confidence=0.61,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        frequency_hz_or_order="1x driveshaft",
        signatures_observed=["1x driveshaft"],
        matched_points=[
            {
                "speed_kmh": 62.0,
                "predicted_hz": 26.4,
                "matched_hz": 26.8,
                "location": "Front Left",
            },
            {
                "speed_kmh": 68.0,
                "predicted_hz": 28.0,
                "matched_hz": 28.2,
                "location": "Front Left",
            },
        ],
        confidence_label_key="CONFIDENCE_MEDIUM",
        confidence_tone="warn",
        confidence_pct="61%",
        confidence_reason=overlap_reason,
    )
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
        sensor_locations_connected_throughout=[
            "Front Left",
            "Front Right",
            "Rear Left",
            "Rear Right",
        ],
        speed_stats={"steady_speed": True},
        findings=[wheel, driveline],
        top_causes=[wheel, driveline],
        test_plan=[
            {
                "action_id": "wheel_balance_and_runout",
                "what": "ACTION_WHEEL_BALANCE_WHAT",
                "why": "ACTION_WHEEL_BALANCE_WHY",
                "confirm": "ACTION_WHEEL_BALANCE_CONFIRM",
            }
        ],
    )

    data = build_report_document(prepare_report_input(summary))

    assert data.verdict_page.also_consider == "Driveline"
    assert data.verdict_page.fallback_path == "Inspect Driveline next"
    assert data.appendix_a.why_alternative_next is not None
    alternative_reason = data.appendix_a.why_alternative_next.lower()
    assert "wheel and driveline evidence overlap" in alternative_reason
    assert "stayed strongest near front-left" not in alternative_reason
    assert data.appendix_c.evidence_summary is not None
    evidence_summary = data.appendix_c.evidence_summary.lower()
    assert "wheel and driveline evidence overlap" in evidence_summary
    assert "1x driveshaft also stayed strongest near front-left" not in evidence_summary


def test_build_report_document_surfaces_temporal_shift_in_page_one_and_appendix() -> None:
    data = build_report_document(prepare_report_input(sequential_same_source_summary()))

    assert data.verdict_page.suspected_source == "Wheel / Tire"
    assert data.verdict_page.inspect_first == "Front-Left"
    assert data.verdict_page.proof_summary is not None
    proof_summary = data.verdict_page.proof_summary
    assert "Front-Left" in proof_summary
    assert "Rear-Right" in proof_summary
    assert "remained the strongest connected location" not in proof_summary

    assert data.appendix_c.phase_summary is not None
    phase_summary = data.appendix_c.phase_summary
    assert "Front-Left" in phase_summary
    assert "Rear-Right" in phase_summary
    assert "acceleration" in phase_summary
    assert "deceleration" in phase_summary

    assert data.appendix_c.evidence_summary is not None
    evidence_summary = data.appendix_c.evidence_summary
    assert "Front-Left" in evidence_summary
    assert "Rear-Right" in evidence_summary
    assert "stayed strongest at Front-Left" not in evidence_summary
