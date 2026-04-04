from __future__ import annotations

from test_support.report_helpers import recapture_guidance_summary

from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.use_cases.history.report_document.document_context import (
    build_report_document_context,
)


def _build_context(mode: str):
    return build_report_document_context(prepare_report_input(recapture_guidance_summary(mode)))


def test_build_report_document_context_shares_verdict_and_appendix_inputs() -> None:
    context = _build_context("steady")

    assert (
        context.verdict_page_context.action_status_key
        == context.appendix_a_context.action_status_key
    )
    assert context.verdict_page_context.coverage_label == context.appendix_b_context.coverage_label
    assert (
        context.verdict_page_context.runner_up_corner == context.appendix_b_context.runner_up_corner
    )


def test_build_report_document_context_keeps_one_recapture_assessment() -> None:
    context = _build_context("overlap")

    assert context.verdict_page_context.recapture.issues
    assert context.verdict_page_context.recapture == context.appendix_a_context.recapture
