"""Findings bundling for the canonical typed diagnostics analysis context."""

from __future__ import annotations

from vibesensor.analysis._analysis_models import (
    FindingsBundle,
    PreparedAnalysisContext,
)
from vibesensor.analysis.findings import _build_findings
from vibesensor.analysis.run_analysis_projection import build_phase_timeline
from vibesensor.analysis.top_cause_selection import select_top_causes
from vibesensor.domain.vibration_origin import VibrationOrigin

__all__ = ["build_findings_bundle"]


def build_findings_bundle(context: PreparedAnalysisContext) -> FindingsBundle:
    """Build findings plus derived diagnosis narrative fields."""

    domain_findings = _build_findings(context.findings_request())
    domain_findings = tuple(
        finding.with_strength_band(context.overall_strength_band_key) for finding in domain_findings
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
