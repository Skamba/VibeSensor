"""Appendix-C evidence builders for report document composition."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.domain import TestRun
from vibesensor.shared.boundaries.reporting import PreparedReportFacts
from vibesensor.shared.boundaries.reporting.document import (
    AppendixCData,
    DataTrustItem,
    MeasurementRow,
)

from ._candidate_resolver import PrimaryCandidateContext
from .evidence_snapshot import build_evidence_snapshot_rows
from .measurements import _evidence_chain_rows
from .narrative_summaries import (
    _context_summary_text,
    _evidence_summary_text,
    _observation_texts,
    _phase_summary_text,
    _run_limits_summary_text,
)
from .section_context import AppendixCContext

__all__ = ["build_appendix_c_data"]


def build_appendix_c_data(
    *,
    primary: PrimaryCandidateContext,
    aggregate: TestRun,
    measurements: list[MeasurementRow],
    report_facts: PreparedReportFacts,
    appendix_context: AppendixCContext,
    data_trust: list[DataTrustItem],
    tr: Callable[..., str],
) -> AppendixCData:
    evidence_rows = _evidence_chain_rows(aggregate, measurements=measurements, tr=tr)
    speed_windows = [row.speed_window for row in evidence_rows if row.speed_window]
    speed_summary = (
        ", ".join(dict.fromkeys(speed_windows))
        if speed_windows
        else tr("REPORT_SPEED_SUMMARY_NONE")
    )
    return AppendixCData(
        evidence_chain_rows=evidence_rows,
        measurement_rows=measurements,
        evidence_snapshot_rows=list(
            build_evidence_snapshot_rows(report_facts, compact=False, tr=tr)
        ),
        evidence_summary=_evidence_summary_text(aggregate, primary, report_facts, tr=tr),
        measurement_guide=tr("REPORT_MEASUREMENT_GUIDE"),
        context_summary=_context_summary_text(primary, report_facts, tr=tr),
        limits_summary=_run_limits_summary_text(
            report_facts,
            speed_window_label=appendix_context.speed_window_label,
            proof_caveat=appendix_context.proof_caveat,
            tr=tr,
        ),
        speed_band_summary=speed_summary,
        phase_summary=_phase_summary_text(aggregate, report_facts, tr=tr),
        observations=_observation_texts(aggregate, tr=tr),
        suitability_items=data_trust,
    )
