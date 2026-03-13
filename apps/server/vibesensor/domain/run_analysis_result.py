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

from collections.abc import Mapping
from dataclasses import dataclass

from .finding import Finding, VibrationSource

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

    # -- factories ---------------------------------------------------------

    @classmethod
    def from_summary(cls, summary: Mapping[str, object]) -> RunAnalysisResult:
        """Construct from an ``AnalysisSummary`` dict (boundary adapter).

        This factory allows the report pipeline and other downstream
        consumers to obtain a domain aggregate from a persisted or
        transported summary dict, so that domain queries
        (``effective_top_causes``, ``has_relevant_reference_gap``, etc.)
        work identically whether the analysis was just run in-process or
        loaded from history.
        """
        raw_findings = summary.get("findings")
        raw_top_causes = summary.get("top_causes")

        findings_list = list(raw_findings) if isinstance(raw_findings, list) else []
        top_causes_list = list(raw_top_causes) if isinstance(raw_top_causes, list) else []

        domain_findings = tuple(
            Finding.from_payload(f) for f in findings_list if isinstance(f, dict)
        )
        domain_top_causes = tuple(
            Finding.from_payload(tc) for tc in top_causes_list if isinstance(tc, dict)
        )

        run_id = str(summary.get("run_id", "")) or "unknown"

        duration_raw = summary.get("duration_s")
        duration_s = 0.0
        if duration_raw is not None:
            try:
                duration_s = float(duration_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass

        rows_raw = summary.get("rows")
        sample_count = int(rows_raw) if isinstance(rows_raw, (int, float, str)) else 0

        sensor_raw = summary.get("sensor_count_used")
        sensor_count = int(sensor_raw) if isinstance(sensor_raw, (int, float, str)) else 0

        lang = str(summary.get("lang", "en"))

        return cls(
            run_id=run_id,
            findings=domain_findings,
            top_causes=domain_top_causes,
            duration_s=duration_s,
            sample_count=sample_count,
            sensor_count=sensor_count,
            lang=lang,
        )

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

        Preference order:
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

    # -- domain queries ----------------------------------------------------

    def has_relevant_reference_gap(self, primary_source: VibrationSource | str) -> bool:
        """Whether relevant reference data is missing for *primary_source*.

        A reference gap is relevant when the missing reference input
        would materially affect the analysis of the suspected source.
        """
        source = str(primary_source).strip().lower()
        for f in self.findings:
            if not f.is_reference:
                continue
            fid = f.finding_id.strip().upper()
            if fid in {"REF_SPEED", "REF_SAMPLE_RATE"}:
                return True
            if fid == "REF_WHEEL" and source in {
                VibrationSource.WHEEL_TIRE,
                VibrationSource.DRIVELINE,
            }:
                return True
            if fid == "REF_ENGINE" and source == VibrationSource.ENGINE:
                return True
        return False

    def top_strength_db(self) -> float | None:
        """Return the best available vibration strength (dB) from findings.

        Checks effective top causes first, then all findings.
        """
        for f in self.effective_top_causes():
            if f.vibration_strength_db is not None:
                return f.vibration_strength_db
        for f in self.findings:
            if f.vibration_strength_db is not None:
                return f.vibration_strength_db
        return None
