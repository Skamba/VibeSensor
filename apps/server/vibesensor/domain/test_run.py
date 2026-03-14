"""Run-level aggregate within a diagnostic case."""

from __future__ import annotations

from dataclasses import dataclass

from .configuration_snapshot import ConfigurationSnapshot
from .driving_segment import DrivingSegment
from .finding import Finding, VibrationSource
from .hypothesis import Hypothesis
from .observation import Observation
from .recommended_action import RecommendedAction
from .run import Run
from .run_suitability import RunSuitability
from .signature import Signature
from .speed_profile import SpeedProfile
from .test_plan import TestPlan

__all__ = ["TestRun"]


@dataclass(frozen=True, slots=True)
class TestRun:
    """Canonical run-level diagnostic aggregate."""

    run: Run
    configuration_snapshot: ConfigurationSnapshot
    driving_segments: tuple[DrivingSegment, ...] = ()
    observations: tuple[Observation, ...] = ()
    signatures: tuple[Signature, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    findings: tuple[Finding, ...] = ()
    top_causes: tuple[Finding, ...] = ()
    speed_profile: SpeedProfile | None = None
    suitability: RunSuitability | None = None
    test_plan: TestPlan = TestPlan()

    @property
    def run_id(self) -> str:
        return self.run.run_id

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
    def recommended_actions(self) -> tuple[RecommendedAction, ...]:
        return self.test_plan.prioritized_actions
