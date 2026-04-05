"""Next-step section assembly for report documents."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting.document import AppendixAData, NextStep

from .document_context import ReportDocumentContext
from .report_sections import build_next_steps

__all__ = ["build_document_next_steps"]


def build_document_next_steps(
    *,
    context: ReportDocumentContext,
    appendix_a: AppendixAData,
) -> tuple[NextStep, ...]:
    """Build the report next-step section from the prepared document context."""

    recapture_mode = context.decision_facts.action_status_key == "recapture_before_acting"
    if recapture_mode:
        return tuple(NextStep(action=action) for action in appendix_a.capture_changes)
    return tuple(
        build_next_steps(
            recommended_actions=context.decision_facts.recommended_actions,
            primary_source=context.primary.primary_source,
            primary_location=context.primary.primary_location,
            tier=context.primary.tier,
            cert_reason=context.primary.certainty_reason
            or context.tr("REPORT_CAPTURE_ISSUE_GENERIC"),
            recapture_mode=recapture_mode,
            lang=context.lang,
            tr=context.tr,
        )
    )
