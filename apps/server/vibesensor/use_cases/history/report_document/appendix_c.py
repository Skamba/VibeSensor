"""Appendix-C evidence builders for report document composition."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.domain import Finding, TestRun
from vibesensor.shared.boundaries.reporting import PreparedReportFacts
from vibesensor.shared.boundaries.reporting.document import (
    AppendixCData,
    DataTrustItem,
    DenseEvidenceRow,
    MeasurementRow,
    ProofWindowRow,
)
from vibesensor.shared.boundaries.reporting.summary import ReportWholeRunOrderSummary
from vibesensor.shared.report_presentation import (
    display_phase_label,
    display_speed_band,
    human_source,
    order_label_human,
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
    evidence_rows = _evidence_chain_rows(aggregate, measurements=measurements, tr=tr)[:1]
    dense_evidence_rows = _build_dense_evidence_rows(report_facts, tr=tr)
    proof_window_rows = _build_proof_window_rows(primary, tr=tr)
    speed_windows = [row.speed_window for row in evidence_rows if row.speed_window]
    speed_summary = (
        ", ".join(dict.fromkeys(speed_windows))
        if speed_windows
        else tr("REPORT_SPEED_SUMMARY_NONE")
    )
    return AppendixCData(
        evidence_chain_rows=evidence_rows,
        dense_evidence_rows=dense_evidence_rows,
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


def _build_dense_evidence_rows(
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> list[DenseEvidenceRow]:
    rows: list[DenseEvidenceRow] = []
    for summary in report_facts.whole_run_order_summaries[:4]:
        rows.append(
            DenseEvidenceRow(
                source_name=human_source(summary.suspected_source, tr=tr),
                order_label=order_label_human(_display_lang(tr), summary.order_label),
                confidence_label=_dense_confidence_label(report_facts, summary, tr=tr),
                support=_dense_support_text(summary, tr=tr),
                support_ratio=summary.support_ratio,
                reference_coverage_ratio=summary.reference_coverage_ratio,
                frequency_band=_dense_frequency_band(summary, tr=tr),
                peak_db=(
                    summary.peak_intensity_db
                    if summary.peak_intensity_db is not None
                    else summary.mean_vibration_strength_db
                ),
                strongest_location=summary.strongest_location,
                caveat=_dense_caveat_text(summary, tr=tr),
            )
        )
    return rows


def _dense_confidence_label(
    report_facts: PreparedReportFacts,
    summary: ReportWholeRunOrderSummary,
    *,
    tr: Callable[..., str],
) -> str:
    finding = next(
        (
            candidate
            for candidate in report_facts.findings.all_findings
            if candidate.suspected_source == summary.suspected_source
            and candidate.order == summary.order_label
        ),
        None,
    )
    if finding is None:
        finding = next(
            (
                candidate
                for candidate in report_facts.findings.all_findings
                if candidate.suspected_source == summary.suspected_source
            ),
            None,
        )
    if finding is None:
        return tr("UNKNOWN")
    label_key, _tone, pct_text = Finding.classify_confidence(finding.effective_confidence)
    return f"{tr(label_key)} ({pct_text})"


def _display_lang(tr: Callable[..., str]) -> str:
    return "nl" if tr("UNKNOWN") == "Onbekend" else "en"


def _dense_support_text(summary: ReportWholeRunOrderSummary, *, tr: Callable[..., str]) -> str:
    return tr(
        "REPORT_DENSE_EVIDENCE_SUPPORT_VALUE",
        matched=summary.matched_window_count,
        eligible=summary.eligible_window_count,
        pct=f"{summary.support_ratio * 100:.0f}%",
        lock=f"{summary.lock_score * 100:.0f}%",
    )


def _dense_frequency_band(summary: ReportWholeRunOrderSummary, *, tr: Callable[..., str]) -> str:
    low = summary.stable_frequency_min_hz
    high = summary.stable_frequency_max_hz
    if low is not None and high is not None:
        return tr(
            "REPORT_DENSE_EVIDENCE_FREQUENCY_BAND",
            low=f"{low:.1f}",
            high=f"{high:.1f}",
        )
    if low is not None:
        return f"{low:.1f} Hz"
    if high is not None:
        return f"{high:.1f} Hz"
    return tr("UNKNOWN")


def _dense_caveat_text(
    summary: ReportWholeRunOrderSummary,
    *,
    tr: Callable[..., str],
) -> str | None:
    if summary.reference_coverage_ratio <= 0.0:
        return tr("REPORT_DENSE_EVIDENCE_CAVEAT_REFERENCE_MISSING")
    if summary.reference_coverage_ratio < 0.95:
        return tr(
            "REPORT_DENSE_EVIDENCE_CAVEAT_REFERENCE_PARTIAL",
            pct=f"{summary.reference_coverage_ratio * 100:.0f}%",
        )
    if summary.sensor_clipping_window_count > 0:
        return tr(
            "REPORT_DENSE_EVIDENCE_CAVEAT_SENSOR_CLIPPING_WINDOWS",
            count=str(summary.sensor_clipping_window_count),
        )
    if summary.shock_transient_window_count > 0:
        return tr(
            "REPORT_DENSE_EVIDENCE_CAVEAT_SHOCK_TRANSIENT_WINDOWS",
            count=str(summary.shock_transient_window_count),
        )
    if summary.mean_quality_score is not None and (
        summary.mean_quality_score < 0.75
        or summary.limited_window_count > 0
        or summary.excluded_window_count > 0
    ):
        return tr(
            "REPORT_DENSE_EVIDENCE_CAVEAT_WINDOW_QUALITY_LIMITED",
            pct=f"{summary.mean_quality_score * 100:.0f}%",
            limited=str(summary.limited_window_count),
            excluded=str(summary.excluded_window_count),
        )
    if summary.support_ratio < 0.5:
        return tr("REPORT_DENSE_EVIDENCE_CAVEAT_LIMITED_SUPPORT")
    if summary.lock_score < 0.5:
        return tr("REPORT_DENSE_EVIDENCE_CAVEAT_LOW_LOCK")
    if summary.drift_score > 0.25:
        return tr("REPORT_DENSE_EVIDENCE_CAVEAT_DRIFT")
    return None


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
