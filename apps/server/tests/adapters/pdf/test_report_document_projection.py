"""Projection tests for report document assembly and origin wording."""

from __future__ import annotations

from pathlib import Path

from test_support.findings import make_finding_payload
from test_support.report_helpers import (
    RUN_END,
    minimal_summary,
    write_jsonl,
)
from test_support.report_helpers import report_run_metadata as _run_metadata
from test_support.report_helpers import report_sample as _base_sample

from vibesensor.adapters.analysis_summary import summarize_log
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.shared.boundaries.reporting.document import ReportDocument
from vibesensor.use_cases.history.report_document import build_report_document


def _sample(
    idx: int,
    *,
    speed_kmh: float,
    dominant_freq_hz: float,
    peak_amp_g: float,
) -> dict[str, object]:
    return _base_sample(
        idx,
        speed_kmh=speed_kmh,
        dominant_freq_hz=dominant_freq_hz,
        peak_amp_g=peak_amp_g,
    )


def test_build_report_document_basic(tmp_path: Path) -> None:
    run_path = tmp_path / "build_report_document.jsonl"
    records: list[dict[str, object]] = [_run_metadata(tire_circumference_m=2.2)]
    for idx in range(20):
        speed = 50 + idx
        wheel_hz = (speed * (1000.0 / 3600.0)) / 2.2
        records.append(
            _sample(idx, speed_kmh=float(speed), dominant_freq_hz=wheel_hz, peak_amp_g=0.09),
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    summary = summarize_log(run_path)

    data = build_report_document(prepare_report_input(summary))
    assert isinstance(data, ReportDocument)
    assert data.title
    assert data.run_datetime
    assert data.observed.primary_system
    assert data.observed.certainty_label
    assert data.observed.certainty_reason


def test_build_report_document_no_top_causes() -> None:
    summary = minimal_summary()
    data = build_report_document(prepare_report_input(summary))
    assert isinstance(data, ReportDocument)
    assert data.system_cards == []
    assert data.certainty_tier_key == "A"
    assert len(data.next_steps) >= 1


def test_build_report_document_formats_report_timestamps_for_header() -> None:
    summary = minimal_summary(
        report_date="2026-03-25T10:00:00Z",
        start_time_utc="2026-03-25T09:55:00.536855+00:00",
        end_time_utc="2026-03-25T10:00:11.901770+00:00",
        metadata={"recorded_utc_offset_seconds": 7200},
    )

    data = build_report_document(prepare_report_input(summary))

    assert data.run_datetime == "2026-03-25 12:00:00 UTC+02:00"
    assert data.start_time_utc == "2026-03-25 09:55:00 UTC"
    assert data.end_time_utc == "2026-03-25 10:00:11 UTC"


def test_build_report_document_backfills_peak_system_from_matching_finding() -> None:
    summary = minimal_summary(
        findings=[
            make_finding_payload(
                finding_id="F_PEAK",
                suspected_source="wheel/tire",
                confidence=0.82,
                strongest_location="front-left wheel",
                frequency_hz=41.0,
                frequency_hz_or_order="41.0 Hz",
            )
        ],
        top_causes=[
            make_finding_payload(
                finding_id="F_PEAK",
                suspected_source="wheel/tire",
                confidence=0.82,
                strongest_location="front-left wheel",
                frequency_hz=41.0,
                frequency_hz_or_order="41.0 Hz",
            )
        ],
        plots={
            "peaks_table": [
                {
                    "rank": 1,
                    "frequency_hz": 41.0,
                    "order_label": "",
                    "suspected_source": "",
                    "p95_intensity_db": 18.0,
                    "strength_db": 18.0,
                    "presence_ratio": 0.8,
                    "peak_classification": "persistent",
                    "typical_speed_band": "50-80 km/h",
                }
            ]
        },
    )

    data = build_report_document(prepare_report_input(summary))

    assert len(data.peak_rows) == 1
    assert data.peak_rows[0].system == "Wheel / Tire"


def test_build_report_document_uses_connected_sensors_for_report_evidence() -> None:
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
        sensor_locations_connected_throughout=["Front Left", "Rear Left"],
        sensor_intensity_by_location=[
            {"location": "Front Left", "p95_intensity_db": 10.0},
            {"location": "Rear Left", "p95_intensity_db": 9.0},
            {"location": "Front Right", "p95_intensity_db": 18.0},
        ],
    )

    data = build_report_document(prepare_report_input(summary))
    assert data.sensor_count == 2
    assert data.sensor_locations == ["Front Left", "Rear Left"]
    assert [row.location for row in data.sensor_intensity_by_location] == [
        "Front Left",
        "Rear Left",
    ]


def test_build_report_document_peak_rows_use_persistence_metrics() -> None:
    summary = minimal_summary(
        plots={
            "peaks_table": [
                {
                    "rank": 1,
                    "frequency_hz": 33.0,
                    "order_label": "",
                    "max_intensity_db": 22.0,
                    "p95_intensity_db": 18.4,
                    "strength_db": 18.4,
                    "presence_ratio": 0.85,
                    "persistence_score": 0.0867,
                    "peak_classification": "patterned",
                    "typical_speed_band": "60-80 km/h",
                },
            ],
        },
    )
    data = build_report_document(prepare_report_input(summary))
    assert data.peak_rows
    row = data.peak_rows[0]
    assert row.peak_db == "18.4"
    assert row.strength_db == "18.4"
    assert row.relevance == "Repeated pattern"
    assert "%" not in row.relevance


def test_build_report_document_peak_rows_render_baseline_noise_label() -> None:
    summary = minimal_summary(
        lang="en",
        plots={
            "peaks_table": [
                {
                    "rank": 1,
                    "frequency_hz": 18.0,
                    "order_label": "",
                    "max_intensity_db": 2.1,
                    "p95_intensity_db": 2.1,
                    "strength_db": 2.1,
                    "presence_ratio": 0.1,
                    "persistence_score": 0.001,
                    "peak_classification": "baseline_noise",
                    "typical_speed_band": "any",
                },
            ],
        },
    )
    data = build_report_document(prepare_report_input(summary))
    assert data.peak_rows
    assert data.peak_rows[0].relevance == "Near noise floor"


def test_build_report_document_data_trust_keeps_warning_detail() -> None:
    summary = minimal_summary(
        lang="nl",
        run_suitability=[
            {
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "warn",
                "explanation": {
                    "_i18n_key": "SUITABILITY_FRAME_INTEGRITY_WARN",
                    "total_dropped": 3,
                    "total_overflow": 2,
                },
            },
        ],
    )
    data = build_report_document(prepare_report_input(summary))
    assert data.data_trust
    assert data.data_trust[0].state == "warn"
    assert data.data_trust[0].check == "Frame-integriteit"
    assert data.data_trust[0].detail == "3 verloren frames, 2 wachtrijoverlopen gedetecteerd."


def test_build_report_document_data_trust_literal_check_labels() -> None:
    summary = minimal_summary(
        lang="nl",
        run_suitability=[
            {
                "check_key": "Frame integrity",
                "state": "warn",
                "explanation": "3 dropped frames, 2 queue overflows detected.",
            },
        ],
    )
    data = build_report_document(prepare_report_input(summary))
    assert data.data_trust
    assert data.data_trust[0].check == "Frame integrity"


def test_build_report_document_data_trust_includes_run_context_warnings() -> None:
    summary = minimal_summary(
        lang="en",
        warnings=[
            {
                "code": "reference_context_incomplete",
                "severity": "warn",
                "applies_to": "order_analysis",
                "title": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
                "detail": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
            },
        ],
    )
    data = build_report_document(prepare_report_input(summary))
    assert any(
        item.check == "Order-analysis reference context was incomplete for this run"
        for item in data.data_trust
    )


def test_build_report_document_data_trust_check_labels_follow_lang_for_same_summary_data() -> None:
    base_summary = minimal_summary(
        run_suitability=[
            {
                "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
                "state": "pass",
                "explanation": (
                    "Speed range stayed in a usable diagnostic band for steady-state diagnosis "
                    "and order tracking."
                ),
            },
        ],
    )

    summary_en = {**base_summary, "lang": "en"}
    summary_nl = {**base_summary, "lang": "nl"}

    data_en = build_report_document(prepare_report_input(summary_en))
    data_nl = build_report_document(prepare_report_input(summary_nl))

    assert data_en.data_trust[0].check == "Speed variation"
    assert data_nl.data_trust[0].check == "Snelheidsvariatie"


def test_build_report_document_certainty_reason_ignores_unrelated_reference_gap() -> None:
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        top_causes=[
            {
                "suspected_source": "wheel/tire",
                "strongest_location": "Front Left",
                "strongest_speed_band": "60-80 km/h",
                "confidence": 0.82,
            },
        ],
        findings=[{"finding_id": "REF_ENGINE"}],
    )
    data = build_report_document(prepare_report_input(summary))
    assert data.observed.certainty_reason
    assert "Missing reference data" not in data.observed.certainty_reason


def test_build_report_document_certainty_reason_keeps_relevant_reference_gap() -> None:
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations={"FL": {}, "FR": {}, "RL": {}, "RR": {}},
        speed_stats={"steady_speed": True},
        run_suitability=[
            {"check_key": "SUITABILITY_CHECK_REFERENCE_COMPLETENESS", "state": "warn"},
        ],
        top_causes=[
            {
                "finding_id": "F_ENGINE",
                "suspected_source": "engine",
                "strongest_location": "Engine Bay",
                "strongest_speed_band": "60-80 km/h",
                "confidence": 0.82,
            },
        ],
        findings=[{"finding_id": "REF_ENGINE"}],
    )
    data = build_report_document(prepare_report_input(summary))
    assert "Missing reference data" in data.observed.certainty_reason


def test_build_report_document_builds_verdict_timeline_graph_from_phase_timeline() -> None:
    finding = make_finding_payload(
        finding_id="F_TIMELINE",
        suspected_source="wheel/tire",
        strongest_location="Front Left wheel",
        strongest_speed_band="60-80 km/h",
        confidence=0.82,
    )
    summary = minimal_summary(
        lang="en",
        duration_s=12.0,
        findings=[finding],
        top_causes=[finding],
        phase_timeline=[
            {
                "phase": "cruise",
                "start_t_s": 0.0,
                "end_t_s": 4.0,
                "speed_min_kmh": 58.0,
                "speed_max_kmh": 63.0,
                "has_fault_evidence": False,
            },
            {
                "phase": "cruise",
                "start_t_s": 4.0,
                "end_t_s": 9.0,
                "speed_min_kmh": 64.0,
                "speed_max_kmh": 72.0,
                "has_fault_evidence": True,
            },
            {
                "phase": "decel",
                "start_t_s": 9.0,
                "end_t_s": 12.0,
                "speed_min_kmh": 48.0,
                "speed_max_kmh": 62.0,
                "has_fault_evidence": False,
            },
        ],
    )

    data = build_report_document(prepare_report_input(summary))

    timeline = data.verdict_page.timeline_graph
    assert timeline is not None
    assert timeline.duration_s == 12.0
    assert timeline.speed_ceiling_kmh >= 72.0
    assert [(interval.start_t_s, interval.end_t_s) for interval in timeline.intervals] == [
        (0.0, 4.0),
        (4.0, 9.0),
        (9.0, 12.0),
    ]
    assert [interval.has_fault_evidence for interval in timeline.intervals] == [False, True, False]
