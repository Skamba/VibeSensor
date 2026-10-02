"""Findings bundling for the canonical typed diagnostics analysis context."""

from __future__ import annotations

from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.use_cases.diagnostics._analysis_models import (
    FindingsBundle,
    PreparedAnalysisContext,
)
from vibesensor.use_cases.diagnostics.findings import _build_findings
from vibesensor.use_cases.diagnostics.run_analysis_projection import build_phase_timeline
from vibesensor.use_cases.diagnostics.top_cause_selection import select_top_causes

__all__ = ["build_findings_bundle"]


def build_findings_bundle(context: PreparedAnalysisContext) -> FindingsBundle:
    """Build findings plus derived diagnosis narrative fields."""

    domain_findings = _build_findings(context.findings_request())
    domain_findings = tuple(
        finding
        if finding.confidence_assessment is not None
        else finding.with_confidence_assessment(
            strength_band_key=context.overall_strength_band_key or "",
            steady_speed=context.prepared.is_steady_speed,
            has_reference_gaps=not context.reference_complete,
            sensor_count=len(context.sensor_locations),
        )
        for finding in domain_findings
    )
    diagnostic_findings = tuple(finding for finding in domain_findings if not finding.is_reference)
    phase_timeline = build_phase_timeline(
        context.prepared.phase_segments,
        domain_findings,
        min_confidence=0.25,
    )
    return FindingsBundle(
        most_likely_origin=VibrationOrigin.from_ranked_findings(diagnostic_findings),
        phase_timeline=tuple(phase_timeline),
        domain_findings=domain_findings,
        domain_top_causes=select_top_causes(domain_findings),
    )
