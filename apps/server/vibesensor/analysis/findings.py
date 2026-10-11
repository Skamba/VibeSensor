"""Findings orchestration for diagnostics."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.analysis import _reference_findings
from vibesensor.analysis._analysis_models import FindingsBuildRequest
from vibesensor.analysis._reference_resolution import _tire_reference_from_context
from vibesensor.analysis._sensor_locations import _locations_connected_throughout_run
from vibesensor.analysis.orders.pipeline import (
    OrderAnalysisRequest,
    _build_order_findings,
)
from vibesensor.analysis.peaks.findings import (
    PeakFindingAnalyzer,
    _build_persistent_peak_findings,
    collect_order_frequencies,
    prepare_analysis_samples,
)
from vibesensor.domain.finding import Finding as DomainFinding

__all__ = [
    "PeakFindingAnalyzer",
    "collect_order_frequencies",
    "finalize_findings",
    "prepare_analysis_samples",
]


def finalize_findings(
    findings: Sequence[DomainFinding],
) -> tuple[DomainFinding, ...]:
    """Partition, rank by confidence, and assign stable ``F###`` IDs.

    Returns domain ``Finding`` objects in canonical order: references first,
    then diagnostics sorted by confidence/score, then informational.
    """
    refs = [finding for finding in findings if finding.is_reference]
    diags = sorted(
        [finding for finding in findings if finding.is_diagnostic],
        key=lambda finding: finding.rank_key,
        reverse=True,
    )
    infos = sorted(
        [finding for finding in findings if finding.is_informational],
        key=lambda finding: finding.rank_key,
        reverse=True,
    )
    counter = 0
    result: list[DomainFinding] = []
    for finding in refs + diags + infos:
        if not finding.is_reference:
            counter += 1
            finding = finding.with_id(f"F{counter:03d}")
        result.append(finding)
    return tuple(result)


def _build_findings(request: FindingsBuildRequest) -> tuple[DomainFinding, ...]:
    """Build and rank all findings for a completed run.

    Coordinates reference checks (speed, wheel, engine, sample-rate), order
    analysis, and persistent-peak detection.  Results are partitioned into
    reference / diagnostic / informational buckets and sorted so the most
    confident diagnostic finding appears first.
    """
    context = request.context
    samples = request.samples
    tire_circumference_m, _ = _tire_reference_from_context(context)
    findings: list[DomainFinding]
    findings, engine_ref_sufficient = _reference_findings.build_reference_findings(
        context=context,
        table=request.table,
        speed_sufficient=request.speed_sufficient,
        tire_circumference_m=tire_circumference_m,
        raw_sample_rate_hz=request.raw_sample_rate_hz,
    )
    analysis_samples, analysis_rows, analysis_phases = prepare_analysis_samples(
        samples,
        per_sample_phases=request.per_sample_phases,
    )
    analysis_table = (
        request.table.subset(analysis_rows) if analysis_rows is not None else request.table
    )

    order_findings = _build_order_findings(
        OrderAnalysisRequest(
            context=context,
            samples=analysis_samples,
            table=analysis_table,
            speed_sufficient=request.speed_sufficient,
            steady_speed=request.steady_speed,
            speed_steadiness=request.speed_steadiness,
            speed_constancy=request.speed_constancy,
            tire_circumference_m=(tire_circumference_m if request.speed_sufficient else None),
            engine_ref_sufficient=engine_ref_sufficient,
            raw_sample_rate_hz=request.raw_sample_rate_hz,
            connected_locations=_locations_connected_throughout_run(analysis_samples),
            lang=request.lang,
            per_sample_phases=list(analysis_phases),
        ),
    )
    findings.extend(order_findings)
    order_freqs = collect_order_frequencies(order_findings)
    findings.extend(
        _build_persistent_peak_findings(
            table=analysis_table,  # IDLE-filtered; issue #191
            order_finding_freqs=order_freqs,
            per_sample_phases=analysis_phases,
            run_noise_baseline_g=(request.run_noise_baseline_g if analysis_rows is None else None),
        ),
    )
    return finalize_findings(findings)
