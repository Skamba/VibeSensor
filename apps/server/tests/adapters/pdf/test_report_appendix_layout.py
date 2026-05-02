"""Appendix layout regressions for rendered report PDFs."""

from __future__ import annotations

import json

import pytest
from _paths import SERVER_ROOT
from test_support.core import extract_pdf_text

from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixCData,
    EvidenceChainRow,
    NextStep,
    ProofWindowRow,
    RankedCandidateRow,
    ReportDocument,
)

_I18N_JSON = SERVER_ROOT / "vibesensor" / "data" / "report_i18n.json"


@pytest.mark.parametrize("lang", ["en", "nl"])
def test_report_pdf_workflow_appendix_a_headings_render(lang: str) -> None:
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    data = ReportDocument(
        title="Diagnostic worksheet",
        run_id=f"workflow-headings-{lang}",
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


def test_report_pdf_marks_appendix_table_overflow_instead_of_silent_omission() -> None:
    data = ReportDocument(
        title="Overflow review",
        run_id="appendix-overflow-review",
        appendix_c=AppendixCData(
            evidence_summary="Dense evidence chain.",
            evidence_chain_rows=[
                EvidenceChainRow(
                    source_name=f"Source {index}",
                    supporting_signal_label="order trace",
                    measurement_refs=[f"M{index}"],
                    matched_evidence_window_count=index,
                    speed_window="50-70 km/h",
                    dominant_location="Front-Right",
                    ambiguity_note="Dense row that forces a compact appendix table.",
                )
                for index in range(1, 9)
            ],
            proof_window_rows=[
                ProofWindowRow(
                    window_id=f"P{index}",
                    time_s=float(index),
                    speed_kmh=50.0 + index,
                    matched_hz=22.0 + index,
                    dominant_location="Front-Right",
                    phase="accel",
                )
                for index in range(1, 11)
            ],
        ),
    )

    text = extract_pdf_text(build_report_pdf(data))

    assert text.count("+ 3 more rows not shown") >= 2


def test_report_pdf_ranked_source_stack_has_room_for_four_candidates() -> None:
    data = ReportDocument(
        title="Ranked stack review",
        run_id="ranked-stack-review",
        appendix_a=AppendixAData(
            mode="workflow",
            primary_source="Engine",
            alternative_source="Wheel / Tire",
            ranked_candidates=[
                RankedCandidateRow("Engine", inspect_first="Front-Right", path_role="Primary"),
                RankedCandidateRow("Wheel / Tire", inspect_first="Front-Left", path_role="Alt"),
                RankedCandidateRow("Driveline", inspect_first="Rear-Left", path_role="Third"),
                RankedCandidateRow(
                    "Body resonance",
                    inspect_first="Front cabin",
                    path_role="Watch",
                ),
            ],
        ),
    )

    text = extract_pdf_text(build_report_pdf(data))

    assert "Driveline" in text
    assert "Body resonance" in text


def test_report_pdf_worksheet_pagination_does_not_skip_action_after_ranked_stack() -> None:
    data = ReportDocument(
        title="Worksheet pagination review",
        run_id="worksheet-pagination-review",
        appendix_a=AppendixAData(
            mode="workflow",
            primary_source="Engine",
            alternative_source="Wheel / Tire",
            ranked_candidates=[
                RankedCandidateRow("Engine", inspect_first="Front-Right", path_role="Primary"),
                RankedCandidateRow("Wheel / Tire", inspect_first="Front-Left", path_role="Alt"),
                RankedCandidateRow("Driveline", inspect_first="Rear-Left", path_role="Third"),
                RankedCandidateRow("Body resonance", inspect_first="Cabin", path_role="Watch"),
            ],
        ),
        next_steps=[
            NextStep(
                action=f"Action {index}: inspect a unique worksheet item.",
                confirm=f"Confirm action {index}.",
                falsify=f"Falsify action {index}.",
            )
            for index in range(1, 9)
        ],
    )

    text = extract_pdf_text(build_report_pdf(data))

    for index in range(1, 9):
        assert f"Action {index}: inspect a unique worksheet item." in text
