from __future__ import annotations

from vibesensor.adapters.pdf.mapping import (
    prepare_report_input,
    prepare_report_mapping_context,
    resolve_primary_report_candidate,
)


def test_prepare_report_mapping_context_prefers_connected_sensor_locations() -> None:
    prepared = prepare_report_input(
        {
            "lang": "en",
            "metadata": {},
            "report_date": "",
            "record_length": "",
            "start_time_utc": "",
            "end_time_utc": "",
            "findings": [],
            "top_causes": [],
            "sensor_locations": ["front-left", "rear-right"],
            "sensor_locations_connected_throughout": ["rear-right"],
            "speed_stats": {},
            "most_likely_origin": {},
            "run_suitability": [],
        },
    )
    assert prepared.domain_test_run is not None
    assert prepared.report_facts is not None
    context = prepare_report_mapping_context(
        prepared.analysis_summary,
        report_facts=prepared.report_facts,
        test_run=prepared.domain_test_run,
    )

    assert context.sensor_locations_active == ["rear-right"]


def test_resolve_primary_report_candidate_keeps_summary_confidence_context() -> None:
    prepared = prepare_report_input(
        {
            "sensor_count_used": 0,
            "sensor_intensity_by_location": [{"p95_intensity_db": 21.0}],
            "lang": "en",
            "metadata": {},
            "report_date": "",
            "record_length": "",
            "start_time_utc": "",
            "end_time_utc": "",
            "findings": [
                {
                    "finding_id": "F001",
                    "suspected_source": "wheel/tire",
                    "strongest_location": "front-left",
                    "strongest_speed_band": "50-80 km/h",
                    "confidence": 0.71,
                    "evidence_metrics": {"vibration_strength_db": 21.0},
                },
            ],
            "top_causes": [
                {
                    "finding_id": "F001",
                    "suspected_source": "wheel/tire",
                    "strongest_location": "front-left",
                    "strongest_speed_band": "50-80 km/h",
                    "confidence": 0.71,
                },
            ],
            "speed_stats": {"steady_speed": False},
            "most_likely_origin": {},
            "sensor_locations": [],
            "sensor_locations_connected_throughout": [],
            "run_suitability": [],
        },
    )
    assert prepared.domain_test_run is not None
    assert prepared.report_facts is not None
    context = prepare_report_mapping_context(
        prepared.analysis_summary,
        report_facts=prepared.report_facts,
        test_run=prepared.domain_test_run,
    )

    def tr(key: str, **_kw: object) -> str:
        return key

    primary = resolve_primary_report_candidate(
        context=context,
        facts=prepared.report_facts.primary_candidate_facts,
        tr=tr,
        lang="en",
    )

    assert primary.primary_system
    assert primary.primary_location == "front-left"
    assert primary.strength_db == 21.0
    assert primary.tier in {"B", "C"}
