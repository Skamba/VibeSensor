from __future__ import annotations

from test_support.report_helpers import minimal_summary

from vibesensor.adapters.pdf.mapping import map_summary

_ORDER_TOP_CAUSE: dict = {
    "finding_id": "F_ORDER",
    "suspected_source": "wheel/tire",
    "strongest_location": "front-left",
    "strongest_speed_band": "40-60 km/h",
    "confidence": 0.8,
    "signatures_observed": ["1x wheel order"],
}

_BASE_ORDER_FINDING: dict = {
    "finding_id": "F_ORDER",
    "amplitude_metric": {"value": 0.015, "units": "g"},
    "evidence_metrics": {"vibration_strength_db": 23.4},
}


def _summary_with_top_order(finding: dict, *, sensor_rows: list[dict] | None = None) -> dict:
    return minimal_summary(
        top_causes=[_ORDER_TOP_CAUSE],
        findings=[finding],
        sensor_intensity_by_location=sensor_rows or [],
    )


def test_map_summary_strength_label_uses_finding_db_when_sensor_rows_missing() -> None:
    summary = _summary_with_top_order(_BASE_ORDER_FINDING)

    data = map_summary(summary)

    assert data.observed.strength_label is not None
    assert "23.4 dB" in data.observed.strength_label
    assert " g" not in data.observed.strength_label


def test_map_summary_prefers_non_ref_top_cause_for_observed_location() -> None:
    summary = _summary_with_top_order(_BASE_ORDER_FINDING)
    summary["top_causes"] = [
        {
            "finding_id": "REF_GAP_1",
            "suspected_source": "unknown_resonance",
            "strongest_location": "unknown",
            "strongest_speed_band": "100-110 km/h",
            "confidence": 0.95,
            "signatures_observed": ["reference gap"],
        },
        {
            "finding_id": "F_ORDER",
            "suspected_source": "wheel/tire",
            "strongest_location": "rear-left",
            "strongest_speed_band": "40-60 km/h",
            "confidence": 0.8,
            "signatures_observed": ["1x wheel order"],
        },
    ]

    data = map_summary(summary)

    assert data.observed.strongest_location.lower() == "rear-left"


def test_map_summary_falls_back_to_actionable_findings_when_top_cause_is_placeholder() -> None:
    summary = _summary_with_top_order(
        {
            **_BASE_ORDER_FINDING,
            "suspected_source": "wheel/tire",
            "strongest_location": "rear-left",
            "strongest_speed_band": "40-60 km/h",
        },
    )
    summary["top_causes"] = [
        {
            "suspected_source": "unknown_resonance",
            "strongest_location": "unknown",
            "strongest_speed_band": "100-110 km/h",
            "confidence": 0.95,
        },
    ]

    data = map_summary(summary)

    assert data.observed.strongest_location.lower() == "rear-left"


def test_map_summary_pattern_evidence_uses_same_primary_candidate_as_observed() -> None:
    summary = _summary_with_top_order(
        {
            **_BASE_ORDER_FINDING,
            "suspected_source": "wheel/tire",
            "strongest_location": "rear-left",
            "strongest_speed_band": "40-60 km/h",
            "signatures_observed": ["1x wheel order"],
        },
    )
    summary["top_causes"] = [
        {
            "suspected_source": "unknown_resonance",
            "strongest_location": "unknown",
            "strongest_speed_band": "100-110 km/h",
            "confidence": 0.95,
            "weak_spatial_separation": False,
            "signatures_observed": ["reference gap"],
        },
    ]

    data = map_summary(summary)

    assert data.observed.strongest_location.lower() == "rear-left"
    assert data.observed.speed_band == "40-60 km/h"
    assert data.pattern_evidence.strongest_location.lower() == "rear-left"
    assert data.pattern_evidence.speed_band == "40-60 km/h"
    assert data.pattern_evidence.why_parts_text is not None
    assert "wheel" in data.pattern_evidence.why_parts_text.lower()


def test_map_summary_peak_rows_render_missing_values_as_dashes() -> None:
    summary = minimal_summary(
        plots={
            "peaks_table": [
                {
                    "order_label": "",
                    "peak_classification": "persistent",
                    "typical_speed_band": "any",
                },
            ],
        },
    )

    data = map_summary(summary)

    assert data.peak_rows
    row = data.peak_rows[0]
    assert row.rank == "—"
    assert row.freq_hz == "—"
    assert row.peak_db == "—"


def test_map_summary_peak_rows_use_source_hint_for_system_label() -> None:
    summary = minimal_summary(
        lang="en",
        plots={
            "peaks_table": [
                {
                    "rank": 1,
                    "frequency_hz": 33.0,
                    "order_label": "",
                    "p95_intensity_db": 18.4,
                    "strength_db": 18.4,
                    "presence_ratio": 0.85,
                    "persistence_score": 0.0867,
                    "peak_classification": "patterned",
                    "source": "wheel/tire",
                    "typical_speed_band": "60-80 km/h",
                },
            ],
        },
    )

    data = map_summary(summary)

    assert data.peak_rows
    assert data.peak_rows[0].system == "Wheel / Tire"
