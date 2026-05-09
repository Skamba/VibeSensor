from __future__ import annotations

from test_support.findings import make_finding_payload
from test_support.scenario_ground_truth import (
    PhaseStep,
    ScenarioSpec,
    build_summary_from_scenario,
    idle_phase,
    jitter_noise_phase,
    road_noise_phase,
)

from vibesensor.shared.boundaries.reporting import PreparedReportInput, prepare_report_input
from vibesensor.shared.boundaries.reporting.document import ReportDocument
from vibesensor.use_cases.history import report_document
from vibesensor.use_cases.history.report_document.composition import compose_report_document


def _prepared_report_input() -> PreparedReportInput:
    finding = make_finding_payload(finding_id="F001")
    return prepare_report_input(
        {
            "run_id": "report-context",
            "file_name": "report-context.csv",
            "rows": 32,
            "duration_s": 12.5,
            "sensor_count_used": 2,
            "lang": "en",
            "metadata": {},
            "report_date": "2026-01-01T00:00:00Z",
            "record_length": "",
            "start_time_utc": "",
            "end_time_utc": "",
            "warnings": [],
            "sensor_locations": ["front-left", "rear-right"],
            "sensor_locations_connected_throughout": ["rear-right"],
            "sensor_intensity_by_location": [],
            "most_likely_origin": {},
            "run_suitability": [],
            "plots": {},
            "test_plan": [],
            "findings": [finding],
            "top_causes": [finding],
        }
    )


def test_compose_report_document_returns_canonical_document() -> None:
    prepared = _prepared_report_input()

    document = compose_report_document(prepared)

    assert isinstance(document, ReportDocument)
    assert document.sensor_locations == ["rear-right"]
    assert document == report_document.build_report_document(prepared)


def test_weak_location_report_does_not_repeat_same_runner_up_corner() -> None:
    summary = build_summary_from_scenario(
        ScenarioSpec(
            case_id="weak-location-nl",
            language="nl",
            file_name="weak-location-nl",
            phases=(
                PhaseStep(idle_phase, 10.0, {"duration_s": 10.0}),
                PhaseStep(
                    jitter_noise_phase,
                    36.0,
                    {
                        "base_speed_kmh": 85.0,
                        "duration_s": 36.0,
                        "jitter_amplitude": 12.0,
                        "noise_amp": 0.005,
                        "vib_db": 12.0,
                    },
                ),
                PhaseStep(
                    road_noise_phase,
                    12.0,
                    {
                        "speed_kmh": 70.0,
                        "duration_s": 12.0,
                        "noise_amp": 0.005,
                        "road_vib_db": 12.0,
                    },
                ),
            ),
            scenario_group="nuisance",
            assert_mode="tolerant_no_fault",
        )
    )

    document = report_document.build_report_document(prepare_report_input(summary))

    assert document.verdict_page.runner_up_corner != document.verdict_page.dominant_corner
    assert document.appendix_b.runner_up_corner != document.appendix_b.dominant_corner
    assert document.verdict_page.dominance_ratio_label is None
    assert document.verdict_page.action_status_note == (
        "Sommige ordereferenties ontbreken of zijn onzeker afgeleid"
    )
    assert document.verdict_page.proof_summary == (
        "Locatiebewijs bleef verdeeld; gebruik vooral de bron als richting, niet één exacte hoek."
    )
