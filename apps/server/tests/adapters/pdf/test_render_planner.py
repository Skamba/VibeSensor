from __future__ import annotations

from vibesensor.adapters.pdf.render_planner import build_report_render_plan
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    NextStep,
    ReportDocument,
    ReportLabelValueRow,
)


def _document(**overrides: object) -> ReportDocument:
    defaults: dict[str, object] = {
        "title": "VibeSensor Diagnostic Report",
        "lang": "en",
        "next_steps": [NextStep(action="Inspect wheel/tire condition")],
        "appendix_a": AppendixAData(mode="workflow"),
        "appendix_b": AppendixBData(dominant_corner="Front Left"),
        "appendix_c": AppendixCData(),
        "traceability_rows": [ReportLabelValueRow(label="Run ID", value="run-001")],
    }
    defaults.update(overrides)
    return ReportDocument(**defaults)


def test_build_report_render_plan_counts_workflow_pages_from_page_sequence() -> None:
    plan = build_report_render_plan(_document())

    assert plan.recapture_mode is False
    assert plan.appendix_b is not None
    assert len(plan.appendix_a_pages) == 1
    assert plan.total_pages == 4


def test_build_report_render_plan_omits_empty_appendix_b() -> None:
    plan = build_report_render_plan(_document(appendix_b=AppendixBData()))

    assert plan.appendix_b is None
    assert plan.total_pages == 3


def test_build_report_render_plan_uses_recapture_sequence_without_appendix_c_page_count() -> None:
    plan = build_report_render_plan(
        _document(
            next_steps=[],
            appendix_a=AppendixAData(mode="recapture", capture_issues=["Speed was unstable"]),
            appendix_b=AppendixBData(),
        )
    )

    assert plan.recapture_mode is True
    assert plan.appendix_b is None
    assert len(plan.appendix_a_pages) == 1
    assert plan.total_pages == 2
