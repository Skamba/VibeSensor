"""Section assembly for report document composition."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    DataTrustItem,
    NextStep,
    PatternEvidence,
    PeakRow,
    ReportLabelValueRow,
    SystemFindingCard,
    VerdictPageData,
)

from ._card_builder import build_system_cards
from .appendix_c import build_appendix_c_data
from .document_context import ReportDocumentContext
from .location_appendix import build_appendix_b_data
from .measurements import _measurement_rows
from .next_steps import build_document_next_steps
from .pattern_evidence import build_pattern_evidence
from .peak_table import build_peak_rows
from .report_sections import build_data_trust
from .traceability import build_traceability_rows
from .verdict_page import build_verdict_page
from .workflow_appendix import build_appendix_a_data

__all__ = ["ReportDocumentSections", "build_report_document_sections"]


@dataclass(frozen=True, slots=True)
class ReportDocumentSections:
    """Prebuilt document sections ready for final ReportDocument assembly."""

    system_cards: tuple[SystemFindingCard, ...]
    next_steps: tuple[NextStep, ...]
    data_trust: tuple[DataTrustItem, ...]
    pattern_evidence: PatternEvidence
    peak_rows: tuple[PeakRow, ...]
    verdict_page: VerdictPageData
    appendix_a: AppendixAData
    appendix_b: AppendixBData
    appendix_c: AppendixCData
    traceability_rows: tuple[ReportLabelValueRow, ...]


def build_report_document_sections(
    context: ReportDocumentContext,
) -> ReportDocumentSections:
    """Assemble the report-document sections from shared prepared context."""

    appendix_a = build_appendix_a_data(
        aggregate=context.test_run,
        appendix_context=context.appendix_a_context,
        tr=context.tr,
    )
    appendix_b = build_appendix_b_data(
        aggregate=context.test_run,
        primary_candidate_facts=context.decision_facts.primary_candidate,
        active_sensor_intensity=context.sensor_facts.proof_intensity,
        proof_basis=context.sensor_facts.proof_basis,
        diagnosis_summary=context.report_facts.primary_diagnosis,
        appendix_context=context.appendix_b_context,
        tr=context.tr,
    )
    data_trust = tuple(
        build_data_trust(
            suitability_checks=context.decision_facts.suitability_checks,
            warnings=context.decision_facts.warnings,
            lang=context.lang,
            tr=context.tr,
        )
    )
    return ReportDocumentSections(
        system_cards=tuple(
            build_system_cards(
                context.test_run,
                context.primary,
                context.lang,
                context.tr,
            )
        ),
        next_steps=build_document_next_steps(
            context=context,
            appendix_a=appendix_a,
        ),
        data_trust=data_trust,
        pattern_evidence=build_pattern_evidence(
            aggregate=context.test_run,
            origin=context.run_facts.origin,
            primary=context.primary,
            diagnosis_summaries=context.report_facts.whole_run_diagnosis_summaries,
            lang=context.lang,
            tr=context.tr,
        ),
        peak_rows=tuple(
            build_peak_rows(
                context.run_facts.peak_table_rows,
                findings=list(context.findings),
                lang=context.lang,
                tr=context.tr,
            )
        ),
        verdict_page=build_verdict_page(context=context),
        appendix_a=appendix_a,
        appendix_b=appendix_b,
        appendix_c=build_appendix_c_data(
            primary=context.primary,
            aggregate=context.test_run,
            measurements=_measurement_rows(
                context.run_facts,
                aggregate=context.test_run,
                tr=context.tr,
            ),
            report_facts=context.report_facts,
            appendix_context=context.appendix_c_context,
            data_trust=list(data_trust),
            tr=context.tr,
        ),
        traceability_rows=tuple(
            build_traceability_rows(
                date_str=context.run_datetime,
                run_id=context.run_facts.run_id,
                tire_spec_text=context.run_facts.tire_spec_text,
                sensor_model=context.run_facts.sensor_model,
                firmware_version=context.run_facts.firmware_version,
                sample_count=context.run_facts.sample_count,
                sample_rate_hz=context.run_facts.sample_rate_hz,
                tr=context.tr,
            )
        ),
    )
