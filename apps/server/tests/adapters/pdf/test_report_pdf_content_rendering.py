"""Rendered PDF content tests for headings, labels, and appendix wording."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _paths import SERVER_ROOT
from test_support.core import extract_pdf_text
from test_support.findings import make_finding_payload
from test_support.report_helpers import (
    RUN_END,
    minimal_summary,
    write_jsonl,
)
from test_support.report_helpers import report_run_metadata as _run_metadata
from test_support.report_helpers import report_sample as _base_sample

from vibesensor.adapters.analysis_summary import summarize_log
from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.shared.boundaries.reporting import (
    prepare_persisted_report_input,
    prepare_report_input,
)
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixCData,
    MeasurementRow,
    NextStep,
    PatternEvidence,
    RankedCandidateRow,
    ReportDocument,
    ReportLabelValueRow,
    VerdictPageData,
)
from vibesensor.shared.constants.units import KMH_TO_MPS
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.report_document import build_report_document

_I18N_JSON = SERVER_ROOT / "vibesensor" / "data" / "report_i18n.json"


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
        add_index_accel_offset=True,
    )


def _make_run_jsonl(tmp_path: Path, *, tire_circumference_m: float = 2.20) -> Path:
    run_path = tmp_path / "run_content.jsonl"
    records: list[dict[str, object]] = [_run_metadata(tire_circumference_m=tire_circumference_m)]
    for idx in range(30):
        speed = 40 + idx
        wheel_hz = (speed * KMH_TO_MPS) / tire_circumference_m
        records.append(
            _sample(idx, speed_kmh=float(speed), dominant_freq_hz=wheel_hz, peak_amp_g=0.09),
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    return run_path


_RECAPTURE_SECTION_HEADING_KEYS = [
    "REPORT_ACTIONS_PANEL_TITLE",
    "REPORT_PROOF_PANEL_TITLE_INCONCLUSIVE",
    "REPORT_RECAPTURE_GUIDANCE_TITLE",
    "REPORT_CAPTURE_ISSUES_TITLE",
    "REPORT_CAPTURE_CHANGES_TITLE",
    "REPORT_CAPTURE_CONDITIONS_TITLE",
    "REPORT_TRACEABILITY_PANEL_TITLE",
]


@pytest.mark.parametrize(
    ("lang", "i18n_keys"),
    [
        pytest.param("en", _RECAPTURE_SECTION_HEADING_KEYS, id="en_recapture_section_headings"),
        pytest.param("nl", _RECAPTURE_SECTION_HEADING_KEYS, id="nl_recapture_section_headings"),
    ],
)
def test_pdf_contains_i18n_labels(
    tmp_path: Path,
    lang: str,
    i18n_keys: list[str],
) -> None:
    run_path = _make_run_jsonl(tmp_path)
    summary = summarize_log(run_path, lang=lang)
    pdf = build_report_pdf(build_report_document(prepare_report_input(summary)))
    text = extract_pdf_text(pdf)
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    missing = []
    for key in i18n_keys:
        label = i18n[key][lang]
        if label not in text:
            missing.append(f"{key} ({label!r})")
    assert missing == [], f"Missing {lang} labels in PDF: {missing}"


def test_full_report_template_contains_peak_db_column_labels() -> None:
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    data = ReportDocument(
        title="Diagnostic worksheet",
        lang="en",
        verdict_page=VerdictPageData(
            suspected_source="Wheel / Tire",
            inspect_first="Front-Left",
            action_status="Action-ready",
            reason_sentence=(
                "Wheel / Tire remains the strongest source because the repeated pattern "
                "stayed strongest near Front-Left."
            ),
            dominant_corner="Front-Left",
            location_confidence="Strong",
            coverage_label="4 of 4 expected positions stayed connected.",
            proof_summary=(
                "Front-Left outranked the next location by 2.1x on "
                "matched-window linear intensity evidence."
            ),
        ),
        appendix_a=AppendixAData(
            mode="workflow",
            primary_source="Wheel / Tire",
            why_primary_first="Wheel / Tire stayed strongest near Front-Left.",
            ranked_candidates=[
                RankedCandidateRow(
                    source_name="Wheel / Tire",
                    inspect_first="Front-Left",
                    path_role="Primary path",
                    reason="Wheel / Tire stayed strongest near Front-Left.",
                )
            ],
        ),
        appendix_c=AppendixCData(
            measurement_rows=[
                MeasurementRow(
                    measurement_id="M-01",
                    source_name="Wheel / Tire",
                    signal_label="1x wheel order",
                    peak_db=32.0,
                    strength_db=24.0,
                    speed_window="50-60 km/h",
                    dominant_location="Front-Left",
                )
            ],
            speed_band_summary="Repeated energy stayed strongest in the 50-60 km/h window.",
        ),
        traceability_rows=[ReportLabelValueRow(label="Run ID", value="run-1")],
        next_steps=[NextStep(action="Check wheel balance")],
    )

    text = extract_pdf_text(build_report_pdf(data))

    assert i18n["REPORT_PEAK_DB_COLUMN"]["en"] in text
    assert i18n["REPORT_STRENGTH_DB_COLUMN"]["en"] in text


def test_pdf_additional_observations_heading_for_transient_findings() -> None:
    data = ReportDocument(
        title="Diagnostic worksheet",
        pattern_evidence=PatternEvidence(),
        lang="en",
        appendix_c=AppendixCData(
            observations=["Transient impact evidence was also seen near Front-Left."]
        ),
    )

    pdf = build_report_pdf(data)
    text = extract_pdf_text(pdf)
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    assert i18n["ADDITIONAL_OBSERVATIONS"]["en"] in text
    assert "(22%)" not in text


def test_pdf_renders_evidence_snapshot_labels_for_raw_backed_report() -> None:
    primary = make_finding_payload(
        finding_id="F_PRIMARY",
        suspected_source="wheel/tire",
        confidence=0.76,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        matched_points=[
            {
                "t_s": 1.0,
                "speed_kmh": 64.0,
                "predicted_hz": 15.0,
                "matched_hz": 15.1,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.11,
            },
            {
                "t_s": 1.5,
                "speed_kmh": 66.0,
                "predicted_hz": 15.2,
                "matched_hz": 15.2,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.10,
            },
            {
                "t_s": 2.0,
                "speed_kmh": 68.0,
                "predicted_hz": 15.3,
                "matched_hz": 15.4,
                "location": "Rear Left",
                "phase": "cruise",
                "amp": 0.09,
            },
        ],
    )
    pdf = build_report_pdf(
        build_report_document(
            prepare_persisted_report_input(
                PersistedAnalysis.from_json_object(
                    minimal_summary(
                        run_id="evidence-run",
                        lang="en",
                        metadata={
                            "run_id": "evidence-run",
                            "record_type": "metadata",
                            "schema_version": "v2-jsonl",
                            "start_time_utc": "2026-03-23T07:31:01Z",
                            "sensor_model": "ADXL345",
                            "raw_sample_rate_hz": 800,
                            "feature_interval_s": 0.5,
                            "fft_window_size_samples": 256,
                            "peak_picker_method": "fft",
                            "incomplete_for_order_analysis": False,
                        },
                        sensor_count_used=2,
                        sensor_locations=["Front Left", "Rear Left"],
                        sensor_locations_connected_throughout=["Front Left", "Rear Left"],
                        findings=[primary],
                        top_causes=[primary],
                        analysis_metadata={
                            "raw_capture_available": True,
                            "raw_backed_sample_count": 24,
                            "raw_capture_mode": "raw_backed",
                        },
                    )
                )
            )
        )
    )

    text = extract_pdf_text(pdf)

    assert "Evidence basis" in text
    assert "Support" in text
    assert "Stable frequency" in text
    assert "Strongest sensors" in text
    assert "Raw-backed replay" in text


def test_pdf_renders_appendix_c_supporting_windows_for_primary_diagnosis() -> None:
    primary = make_finding_payload(
        finding_id="F_PRIMARY_PROOF",
        suspected_source="wheel/tire",
        confidence=0.79,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        frequency_hz_or_order="1x wheel order",
        matched_points=[
            {
                "t_s": 1.0,
                "speed_kmh": 64.0,
                "predicted_hz": 15.0,
                "matched_hz": 15.1,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.11,
            },
            {
                "t_s": 1.5,
                "speed_kmh": 66.0,
                "predicted_hz": 15.2,
                "matched_hz": 15.2,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.10,
            },
            {
                "t_s": 2.0,
                "speed_kmh": 68.0,
                "predicted_hz": 15.3,
                "matched_hz": 15.4,
                "location": "Rear Left",
                "phase": "decel",
                "amp": 0.09,
            },
        ],
    )
    alternative = make_finding_payload(
        finding_id="F_ALT_PROOF",
        suspected_source="driveline",
        confidence=0.71,
        strongest_location="Rear Left",
        strongest_speed_band="60-80 km/h",
        frequency_hz_or_order="1x driveshaft",
    )
    pdf = build_report_pdf(
        build_report_document(
            prepare_persisted_report_input(
                PersistedAnalysis.from_json_object(
                    minimal_summary(
                        run_id="appendix-c-proof-run",
                        lang="en",
                        metadata={
                            "run_id": "appendix-c-proof-run",
                            "record_type": "metadata",
                            "schema_version": "v2-jsonl",
                            "start_time_utc": "2026-03-23T07:31:01Z",
                            "sensor_model": "ADXL345",
                            "raw_sample_rate_hz": 800,
                            "feature_interval_s": 0.5,
                            "fft_window_size_samples": 256,
                            "peak_picker_method": "fft",
                            "incomplete_for_order_analysis": False,
                        },
                        sensor_count_used=2,
                        sensor_locations=["Front Left", "Rear Left"],
                        sensor_locations_connected_throughout=["Front Left", "Rear Left"],
                        findings=[primary, alternative],
                        top_causes=[primary, alternative],
                        analysis_metadata={
                            "raw_capture_available": True,
                            "raw_backed_sample_count": 24,
                            "raw_capture_mode": "raw_backed",
                        },
                    )
                )
            )
        )
    )

    text = extract_pdf_text(pdf)

    assert "Supporting windows" in text
    assert "Supporting measurements" not in text
    assert "W01" in text
    assert "64 km/h" in text
    assert "15.1 Hz" in text
    assert "Decel" in text


def test_pdf_renders_location_proof_basis_from_supporting_windows() -> None:
    primary = make_finding_payload(
        finding_id="F_LOCATION_PROOF",
        suspected_source="wheel/tire",
        confidence=0.81,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        matched_points=[
            {
                "t_s": 1.0,
                "speed_kmh": 64.0,
                "predicted_hz": 15.0,
                "matched_hz": 15.1,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.11,
            },
            {
                "t_s": 1.5,
                "speed_kmh": 66.0,
                "predicted_hz": 15.2,
                "matched_hz": 15.2,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.10,
            },
            {
                "t_s": 2.0,
                "speed_kmh": 68.0,
                "predicted_hz": 15.4,
                "matched_hz": 15.3,
                "location": "Rear Left",
                "phase": "cruise",
                "amp": 0.03,
            },
        ],
    )
    pdf = build_report_pdf(
        build_report_document(
            prepare_persisted_report_input(
                PersistedAnalysis.from_json_object(
                    minimal_summary(
                        run_id="appendix-b-location-proof-run",
                        lang="en",
                        metadata={
                            "run_id": "appendix-b-location-proof-run",
                            "record_type": "metadata",
                            "schema_version": "v2-jsonl",
                            "start_time_utc": "2026-03-23T07:31:01Z",
                            "sensor_model": "ADXL345",
                            "raw_sample_rate_hz": 800,
                            "feature_interval_s": 0.5,
                            "fft_window_size_samples": 256,
                            "peak_picker_method": "fft",
                            "incomplete_for_order_analysis": False,
                        },
                        sensor_count_used=2,
                        sensor_locations=["Front Left", "Rear Left"],
                        sensor_locations_connected_throughout=["Front Left", "Rear Left"],
                        sensor_intensity_by_location=[
                            {
                                "location": "Front Left",
                                "p95_intensity_db": 11.0,
                                "peak_intensity_db": 16.0,
                            },
                            {
                                "location": "Rear Left",
                                "p95_intensity_db": 24.0,
                                "peak_intensity_db": 30.0,
                            },
                        ],
                        findings=[primary],
                        top_causes=[primary],
                        analysis_metadata={
                            "raw_capture_available": True,
                            "raw_backed_sample_count": 24,
                            "raw_capture_mode": "raw_backed",
                        },
                    )
                )
            )
        )
    )

    text = extract_pdf_text(pdf)

    assert "Dominant corner" in text
    assert "Front-Left" in text
    assert "Location proof uses retained diagnosis-supporting windows rebuilt" in text
    assert "from raw-backed replay." in text


@pytest.mark.parametrize("lang", ["en", "nl"])
def test_pdf_workflow_appendix_a_headings_render(lang: str) -> None:
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    data = ReportDocument(
        title="Diagnostic worksheet",
        lang=lang,
        appendix_a=AppendixAData(
            mode="workflow",
            primary_source="Wheel / Tire",
            alternative_source="Driveline",
            why_primary_first="Wheel / Tire stayed strongest near Front-Left.",
            next_if_clean="Move to the driveline path next and inspect Front-Right.",
            ranked_candidates=[
                RankedCandidateRow(
                    source_name="Wheel / Tire",
                    inspect_first="Front-Left",
                    path_role="Primary path",
                    reason="Wheel / Tire stayed strongest near Front-Left.",
                )
            ],
        ),
        next_steps=[
            NextStep(
                action="Check wheel balance",
                why="The strongest repeated pattern stayed near Front-Left.",
                confirm="If confirmed, repeat the run to confirm the reduction.",
                falsify="If balance is clean, move to the driveline path.",
            )
        ],
    )

    text = extract_pdf_text(build_report_pdf(data))

    assert i18n["REPORT_PRIMARY_VS_ALTERNATIVE_TITLE"][lang] in text
    assert i18n["REPORT_ACTION_MATRIX_TITLE"][lang] in text
