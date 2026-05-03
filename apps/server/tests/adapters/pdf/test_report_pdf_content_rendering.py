"""Rendered PDF content smoke tests for unique appendix/content labels."""

from __future__ import annotations

import json
from io import BytesIO

from _paths import SERVER_ROOT
from pypdf import PdfReader
from test_support.core import extract_pdf_text

from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixCData,
    MeasurementRow,
    NextStep,
    PatternEvidence,
    ProofWindowRow,
    RankedCandidateRow,
    ReportDocument,
    ReportLabelValueRow,
    VerdictPageData,
)

_I18N_JSON = SERVER_ROOT / "vibesensor" / "data" / "report_i18n.json"


def test_full_report_template_contains_peak_db_column_labels() -> None:
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    data = ReportDocument(
        title="Diagnostic worksheet",
        run_id="peak-db-columns",
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
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    data = ReportDocument(
        title="Diagnostic worksheet",
        run_id="additional-observations",
        pattern_evidence=PatternEvidence(),
        lang="en",
        appendix_c=AppendixCData(
            observations=["Transient impact evidence was also seen near Front-Left."]
        ),
    )

    pdf = build_report_pdf(data)
    text = extract_pdf_text(pdf)

    assert i18n["ADDITIONAL_OBSERVATIONS"]["en"] in text
    assert "(22%)" not in text


def test_dutch_proof_window_speed_uses_km_u_unit() -> None:
    data = ReportDocument(
        title="VibeSensor-diagnoserapport",
        run_id="dutch-proof-window-speed",
        lang="nl",
        appendix_c=AppendixCData(
            proof_window_rows=[
                ProofWindowRow(
                    window_id="P1",
                    time_s=12.0,
                    speed_kmh=67.0,
                    matched_hz=14.3,
                    dominant_location="Front-Left",
                    phase="constant",
                )
            ]
        ),
    )

    text = extract_pdf_text(build_report_pdf(data))

    assert "67 km/u" in text
    assert "67 km/h" not in text


def test_worksheet_keeps_freeform_inspect_targets_verbatim() -> None:
    data = ReportDocument(
        title="Diagnostic worksheet",
        run_id="freeform-inspect-target",
        lang="en",
        appendix_a=AppendixAData(
            mode="workflow",
            primary_source="Engine",
            why_primary_first="Engine-order evidence leads the workflow.",
            ranked_candidates=[
                RankedCandidateRow(
                    source_name="Engine",
                    inspect_first="Front-Right engine mount/accessory area",
                    path_role="Primary path",
                    reason="Best RPM lock.",
                )
            ],
        ),
        next_steps=[NextStep(action="Inspect the front-right engine mount.")],
    )

    text = " ".join(extract_pdf_text(build_report_pdf(data)).split())

    assert "Front-Right engine mount/accessory area" in text
    assert "Front Right Engine Mount/accessory Area" not in text


def test_page_one_does_not_render_support_duration_as_elapsed_runtime() -> None:
    support_row = ReportLabelValueRow(
        label="Support",
        value="263 supporting windows across 65.8 s",
    )
    pdf = build_report_pdf(
        ReportDocument(
            title="VibeSensor Diagnostic Report",
            run_id="support-duration-page-one",
            duration_text="00:20.3",
            verdict_page=VerdictPageData(
                suspected_source="Wheel / Tire",
                inspect_first="Front-Left",
                action_status="Action-ready",
                reason_sentence="Wheel / Tire stayed strongest near Front-Left.",
                dominant_corner="Front-Left",
                runner_up_corner="Front-Right",
                dominance_ratio_label="2.8x stronger",
                location_confidence="Strong",
                coverage_label="4 of 4 expected positions stayed connected.",
                proof_snapshot_rows=(support_row,),
            ),
            appendix_c=AppendixCData(evidence_snapshot_rows=[support_row]),
            next_steps=[NextStep(action="Check Front-Left wheel and tire first.")],
        )
    )
    reader = PdfReader(BytesIO(pdf))
    page_one_text = " ".join((reader.pages[0].extract_text() or "").split()).lower()
    all_text = " ".join((page.extract_text() or "") for page in reader.pages).lower()

    assert "00:20.3" in page_one_text
    assert "supporting windows across 65.8 s" not in page_one_text
    assert "263 supporting windows across 65.8 s" in all_text
