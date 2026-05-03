"""Appendix-C evidence builders for report document composition."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.domain import TestRun
from vibesensor.shared.boundaries.reporting import PreparedReportFacts
from vibesensor.shared.boundaries.reporting.document import (
    AppendixCData,
    DataTrustItem,
    MeasurementRow,
    ProofWindowRow,
)
from vibesensor.shared.report_presentation import display_phase_label, display_speed_band

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
    evidence_rows = _evidence_chain_rows(aggregate, measurements=measurements, tr=tr)[:1]
    proof_window_rows = _build_proof_window_rows(primary, tr=tr)
    speed_windows = [row.speed_window for row in evidence_rows if row.speed_window]
    speed_summary = (
        ", ".join(dict.fromkeys(speed_windows))
        if speed_windows
        else tr("REPORT_SPEED_SUMMARY_NONE")
    )
    return AppendixCData(
        evidence_chain_rows=evidence_rows,
        measurement_rows=measurements if not proof_window_rows else [],
        proof_window_rows=proof_window_rows,
        evidence_snapshot_rows=list(
            build_evidence_snapshot_rows(report_facts, compact=False, tr=tr)
        ),
        evidence_summary=_evidence_summary_text(aggregate, primary, report_facts, tr=tr),
        measurement_guide=(
            tr("REPORT_SUPPORTING_WINDOWS_GUIDE")
            if proof_window_rows
            else tr("REPORT_MEASUREMENT_GUIDE")
        ),
        context_summary=_context_summary_text(primary, report_facts, tr=tr),
        limits_summary=_run_limits_summary_text(
            report_facts,
        speed_window_label=display_speed_band(appendix_context.speed_window_label, tr=tr),
            proof_caveat=appendix_context.proof_caveat,
            tr=tr,
        ),
        speed_band_summary=speed_summary,
        phase_summary=_phase_summary_text(aggregate, report_facts, tr=tr),
        observations=_observation_texts(aggregate, tr=tr),
        suitability_items=data_trust,
    )


def _build_proof_window_rows(
    primary: PrimaryCandidateContext,
    *,
    tr: Callable[..., str],
) -> list[ProofWindowRow]:
    finding = primary.primary_candidate
    if finding is None or not finding.matched_points:
        return []
    rows: list[ProofWindowRow] = []
    for index, observation in enumerate(finding.matched_points[:4], start=1):
        rows.append(
            ProofWindowRow(
                window_id=f"W{index:02d}",
                time_s=observation.t_s,
                speed_kmh=observation.speed_kmh,
                matched_hz=observation.matched_hz,
                dominant_location=str(observation.location or "").strip() or None,
                phase=display_phase_label(observation.phase, tr=tr),
            )
        )
    return rows
