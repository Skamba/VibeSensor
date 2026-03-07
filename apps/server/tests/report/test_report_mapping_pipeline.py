from __future__ import annotations

from vibesensor.analysis.report_mapping_pipeline import (
    prepare_report_mapping_context,
    resolve_primary_report_candidate,
)


def test_prepare_report_mapping_context_prefers_connected_sensor_locations() -> None:
    lang, tr, context = prepare_report_mapping_context(
        {
            "lang": "en",
            "metadata": {},
            "findings": [],
            "top_causes": [],
            "sensor_locations": ["front-left", "rear-right"],
            "sensor_locations_connected_throughout": ["rear-right"],
            "speed_stats": {},
            "most_likely_origin": {},
        }
    )

    assert lang == "en"
    assert tr("UNKNOWN")
    assert context.sensor_locations_active == ["rear-right"]


def test_resolve_primary_report_candidate_keeps_summary_confidence_context() -> None:
    summary = {
        "sensor_count_used": 0,
        "sensor_intensity_by_location": [{"p95_intensity_db": 21.0}],
    }
    _lang, tr, context = prepare_report_mapping_context(
        {
            **summary,
            "lang": "en",
            "metadata": {},
            "findings": [
                {
                    "finding_id": "F001",
                    "suspected_source": "wheel/tire",
                    "strongest_location": "front-left",
                    "strongest_speed_band": "50-80 km/h",
                    "confidence_0_to_1": 0.71,
                    "evidence_metrics": {"vibration_strength_db": 21.0},
                }
            ],
            "top_causes": [
                {
                    "finding_id": "F001",
                    "source": "wheel/tire",
                    "strongest_location": "front-left",
                    "strongest_speed_band": "50-80 km/h",
                    "confidence": 0.71,
                }
            ],
            "speed_stats": {"steady_speed": False},
            "most_likely_origin": {},
        }
    )

    primary = resolve_primary_report_candidate(summary, context=context, tr=tr, lang="en")

    assert primary.primary_system
    assert primary.primary_location == "front-left"
    assert primary.strength_db == 21.0
    assert primary.tier in {"B", "C"}
