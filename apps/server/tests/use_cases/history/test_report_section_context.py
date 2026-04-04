from test_support.report_helpers import recapture_guidance_summary

from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.use_cases.history.report_document import build_report_document


def _report_document_for_mode(mode: str):
    return build_report_document(prepare_report_input(recapture_guidance_summary(mode)))


def test_recapture_assessment_aligns_verdict_and_appendix_a() -> None:
    document = _report_document_for_mode("overlap")

    assert document.appendix_a.mode == "recapture"
    assert document.appendix_a.capture_issues
    assert document.verdict_page.reason_sentence == document.appendix_a.capture_issues[0]
    assert document.appendix_a.capture_changes
    assert document.appendix_a.capture_conditions


def test_shared_section_context_aligns_verdict_and_appendix_b() -> None:
    document = _report_document_for_mode("steady")

    assert document.appendix_b.coverage_label == document.verdict_page.coverage_label
    assert document.appendix_b.runner_up_corner == document.verdict_page.runner_up_corner
