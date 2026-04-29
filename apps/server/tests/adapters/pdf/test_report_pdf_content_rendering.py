"""Rendered PDF content smoke tests for unique appendix/content labels."""

from __future__ import annotations

import json

from _paths import SERVER_ROOT
from test_support.core import extract_pdf_text

from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
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
