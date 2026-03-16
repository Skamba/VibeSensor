"""Run-level aggregate within a diagnostic case."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain.diagnostic_reasoning import DiagnosticReasoning
from vibesensor.domain.driving_segment import DrivingSegment
from vibesensor.domain.finding import Finding, VibrationSource
from vibesensor.domain.recommended_action import RecommendedAction
from vibesensor.domain.run_capture import RunCapture
from vibesensor.domain.run_suitability import RunSuitability
from vibesensor.domain.speed_profile import SpeedProfile
from vibesensor.domain.test_plan import TestPlan

__all__ = ["TestRun"]


@dataclass(frozen=True, slots=True)
class TestRun:
    """Canonical run-level diagnostic aggregate."""

    capture: RunCapture
    reasoning: DiagnosticReasoning = DiagnosticReasoning()
    driving_segments: tuple[DrivingSegment, ...] = ()
    findings: tuple[Finding, ...] = ()
    top_causes: tuple[Finding, ...] = ()
    speed_profile: SpeedProfile | None = None
    suitability: RunSuitability | None = None
    test_plan: TestPlan = TestPlan()

    def __post_init__(self) -> None:
        if not self.top_causes:
            return
        if not self.findings:
            raise ValueError("TestRun.top_causes must be drawn from findings when present")
        unmatched = tuple(
            top_cause
            for top_cause in self.top_causes
            if not self._matches_top_cause_to_findings(top_cause, self.findings)
        )
        if unmatched:
            detail = ", ".join(
                top_cause.finding_id or str(top_cause.suspected_source) for top_cause in unmatched
            )
            raise ValueError(
                "TestRun.top_causes must be a subset or derivation of findings; "
                f"unmatched top causes: {detail}"
            )

    @staticmethod
    def _matches_top_cause_to_findings(
        top_cause: Finding,
        findings: tuple[Finding, ...],
    ) -> bool:
        for finding in findings:
            if top_cause == finding:
                return True
            if top_cause.finding_id and top_cause.finding_id == finding.finding_id:
                return True
        return False

    @property
    def run_id(self) -> str:
        return self.capture.run_id

    @property
    def sensor_count(self) -> int:
        return len(self.capture.setup.sensors)

    @property
    def diagnostic_findings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.is_diagnostic)

    @property
    def non_reference_findings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if not f.is_reference)

    @property
    def primary_finding(self) -> Finding | None:
        if self.top_causes:
            return self.top_causes[0]
        diagnostics = self.diagnostic_findings
        return diagnostics[0] if diagnostics else None

    @property
    def primary_source(self) -> VibrationSource | None:
        finding = self.primary_finding
        return finding.suspected_source if finding is not None else None

    @property
    def primary_location(self) -> str | None:
        finding = self.primary_finding
        return finding.strongest_location if finding is not None else None

    def effective_top_causes(self) -> tuple[Finding, ...]:
        actionable_tc = tuple(f for f in self.top_causes if not f.is_reference and f.is_actionable)
        if actionable_tc:
            return actionable_tc
        if self.non_reference_findings:
            return self.non_reference_findings
        non_ref_tc = tuple(f for f in self.top_causes if not f.is_reference)
        if non_ref_tc:
            return non_ref_tc
        return self.top_causes

    def has_relevant_reference_gap(self, primary_source: VibrationSource | str) -> bool:
        source_str = str(primary_source).strip().lower()
        for finding in self.findings:
            if not finding.is_reference:
                continue
            fid = finding.finding_id.strip().upper()
            if fid in {"REF_SPEED", "REF_SAMPLE_RATE"}:
                return True
            if fid == "REF_WHEEL" and source_str in {
                str(VibrationSource.WHEEL_TIRE),
                str(VibrationSource.DRIVELINE),
            }:
                return True
            if fid == "REF_ENGINE" and source_str == str(VibrationSource.ENGINE):
                return True
        return False

    def top_strength_db(self) -> float | None:
        for finding in self.effective_top_causes():
            if finding.vibration_strength_db is not None:
                return finding.vibration_strength_db
        for finding in self.findings:
            if finding.vibration_strength_db is not None:
                return finding.vibration_strength_db
        return None

    @property
    def usable_segments(self) -> tuple[DrivingSegment, ...]:
        """Segments that can contribute to diagnostic conclusions."""
        return tuple(s for s in self.driving_segments if s.is_diagnostically_usable)

    @property
    def total_usable_samples(self) -> int:
        """Total sample count across diagnostically usable segments."""
        return sum(s.sample_count for s in self.usable_segments)

    @property
    def recommended_actions(self) -> tuple[RecommendedAction, ...]:
        return self.test_plan.prioritized_actions
