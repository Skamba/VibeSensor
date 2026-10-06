"""Run-level aggregate within a diagnostic case."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from vibesensor.domain.driving_segment import DrivingSegment
from vibesensor.domain.finding import Finding, VibrationSource
from vibesensor.domain.run_capture import RunCapture
from vibesensor.domain.run_suitability import RunSuitability
from vibesensor.domain.speed_profile import SpeedProfile
from vibesensor.domain.test_plan import RecommendedAction, TestPlan

__all__ = ["TestRun"]


@dataclass(frozen=True, slots=True)
class TestRun:
    """Canonical run-level diagnostic aggregate."""

    capture: RunCapture
    driving_segments: tuple[DrivingSegment, ...] = ()
    findings: tuple[Finding, ...] = ()
    top_causes: tuple[Finding, ...] = ()
    speed_profile: SpeedProfile | None = None
    suitability: RunSuitability | None = None
    test_plan: TestPlan = field(default_factory=TestPlan)

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

    _NON_FAULT_SOURCES = frozenset(
        {VibrationSource.BASELINE_NOISE, VibrationSource.TRANSIENT_IMPACT}
    )

    @property
    def diagnosis_candidate(self) -> Finding | None:
        """The finding the verdict names: the best surfaced, actionable fault candidate."""
        for finding in self.top_causes:
            if (
                finding.is_diagnostic
                and finding.should_surface
                and finding.is_actionable
                and finding.suspected_source not in self._NON_FAULT_SOURCES
            ):
                return finding
        return None

    # A source's 2nd order names the diagnosis only when its peak is clearly louder
    # than the 1st order's in the same windows: by at least 3 dB (1.4x the amplitude).
    HARMONIC_DOMINANCE_DB: ClassVar[float] = 3.0

    @property
    def diagnosis_order_finding(self) -> Finding | None:
        """The diagnosed source's physically dominant order (T1/T2, P1/P2, E1/E2).

        ``diagnosis_candidate`` names the source and its confidence: the order of
        that source that ranked best. A harmonic often ranks above its louder
        fundamental (it tracks a little more consistently), but workshop advice
        follows the dominant order, so this compares the source's 1st and 2nd
        order by amplitude in the windows both matched, at the candidate's
        location when they share enough windows there, else at every location.
        The 1st order wins unless the 2nd is ``HARMONIC_DOMINANCE_DB`` louder.
        Without shared windows, or without the other order, the candidate stays.
        """
        candidate = self.diagnosis_candidate
        if candidate is None or candidate.order_code is None:
            return candidate
        location = (
            candidate.location.strongest_location
            if candidate.location is not None
            else candidate.strongest_location
        )
        harmonic = candidate.order_code.endswith("2")
        others = [
            finding
            for finding in self.findings
            if finding.suspected_source is candidate.suspected_source
            and finding.order_code is not None
            and finding.order_code.endswith("2") is not harmonic
            and finding.should_surface
        ]
        if not others:
            return candidate
        other = max(
            others,
            key=lambda f: (
                f.strongest_location == candidate.strongest_location,
                f.phase_adjusted_score,
            ),
        )
        first, second = (other, candidate) if harmonic else (candidate, other)
        excess_db = second.level_over_db(first, location=location)
        if excess_db is None:
            excess_db = second.level_over_db(first)
        if excess_db is None:
            return candidate
        return second if excess_db >= self.HARMONIC_DOMINANCE_DB else first

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

    @property
    def recommended_actions(self) -> tuple[RecommendedAction, ...]:
        return self.test_plan.prioritized_actions
