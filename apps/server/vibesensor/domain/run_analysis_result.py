"""Post-analysis aggregate for a diagnostic run.

``RunAnalysisResult`` is the canonical domain object that represents the
finalized output of analyzing a diagnostic run.  It owns the ranked
domain ``Finding`` objects and provides core queries for downstream
ranking, selection, and report generation.

Boundary types (``AnalysisSummary``, ``FindingPayload``) remain for
serialization and persistence; this aggregate is the domain-first
source of truth inside the core pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from .finding import Finding

__all__ = ["RunAnalysisResult"]


@dataclass(frozen=True, slots=True)
class RunAnalysisResult:
    """Finalized analysis result — the domain aggregate for post-analysis state.

    Constructed by the analysis orchestration layer after findings are
    ranked and top causes selected.  Downstream consumers (report
    mapping, API serialization, history persistence) use this object
    for core decisions and fall back to the boundary ``AnalysisSummary``
    dict only for evidence-level rendering detail.
    """

    run_id: str
    findings: tuple[Finding, ...]
    top_causes: tuple[Finding, ...]
    duration_s: float = 0.0
    sample_count: int = 0
    sensor_count: int = 0
    lang: str = "en"

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must be non-empty")

    # -- finding queries ---------------------------------------------------

    @property
    def diagnostic_findings(self) -> tuple[Finding, ...]:
        """All diagnostic (non-reference, non-informational) findings."""
        return tuple(f for f in self.findings if f.is_diagnostic)

    @property
    def reference_findings(self) -> tuple[Finding, ...]:
        """All reference (``REF_*``) findings."""
        return tuple(f for f in self.findings if f.is_reference)

    @property
    def informational_findings(self) -> tuple[Finding, ...]:
        """All informational findings."""
        return tuple(f for f in self.findings if f.is_informational)

    @property
    def non_reference_findings(self) -> tuple[Finding, ...]:
        """All findings excluding reference checks."""
        return tuple(f for f in self.findings if not f.is_reference)

    @property
    def surfaceable_findings(self) -> tuple[Finding, ...]:
        """Findings suitable for user-facing display."""
        return tuple(f for f in self.findings if f.should_surface)

    @property
    def actionable_findings(self) -> tuple[Finding, ...]:
        """Non-reference findings that identify a meaningful component."""
        return tuple(f for f in self.findings if f.is_actionable and not f.is_reference)

    @property
    def primary_finding(self) -> Finding | None:
        """The strongest top cause, or the strongest diagnostic finding."""
        if self.top_causes:
            return self.top_causes[0]
        diagnostics = self.diagnostic_findings
        return diagnostics[0] if diagnostics else None

    @property
    def has_findings(self) -> bool:
        return len(self.findings) > 0

    @property
    def has_diagnostic_findings(self) -> bool:
        return any(f.is_diagnostic for f in self.findings)

    def effective_top_causes(self) -> tuple[Finding, ...]:
        """Return the most useful cause list for reporting.

        Preference order (matches ``diagnosis_candidates`` logic):
        1. Actionable non-reference top causes
        2. Non-reference findings
        3. Non-reference top causes
        4. All top causes
        """
        actionable_tc = tuple(f for f in self.top_causes if not f.is_reference and f.is_actionable)
        if actionable_tc:
            return actionable_tc
        non_ref = self.non_reference_findings
        if non_ref:
            return non_ref
        non_ref_tc = tuple(f for f in self.top_causes if not f.is_reference)
        if non_ref_tc:
            return non_ref_tc
        return self.top_causes
