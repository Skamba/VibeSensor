from __future__ import annotations

from test_support.report_helpers import recapture_guidance_summary

from vibesensor.report.document.document_context import (
    build_report_document_context,
)
from vibesensor.report.document.document_sections import (
    build_report_document_sections,
)
from vibesensor.report.preparation import prepare_report_input


def _build_sections(mode: str):
    context = build_report_document_context(prepare_report_input(recapture_guidance_summary(mode)))
    return context, build_report_document_sections(context)


def test_build_report_document_sections_keeps_recapture_guidance_in_sync() -> None:
    _context, sections = _build_sections("overlap")

    assert sections.appendix_a.mode == "recapture"
    assert sections.appendix_a.capture_changes
    assert [step.action for step in sections.next_steps] == sections.appendix_a.capture_changes
    assert sections.verdict_page.reason_sentence == sections.appendix_a.capture_issues[0]


def test_build_report_document_sections_aligns_verdict_and_appendix_b() -> None:
    _context, sections = _build_sections("steady")

    assert sections.appendix_b.coverage_label == sections.verdict_page.coverage_label
    assert sections.appendix_b.runner_up_corner == sections.verdict_page.runner_up_corner
