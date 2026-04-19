"""Direct behavior tests for phase timelines and phase-aware scoring."""

from __future__ import annotations

import pytest

from vibesensor.domain import Finding
from vibesensor.shared.boundaries.summary_fields.finding import finding_from_payload
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase
from vibesensor.use_cases.diagnostics.run_analysis_projection import (
    build_phase_timeline as _build_phase_timeline,
)


class _FakeSeg:
    def __init__(
        self,
        phase: DrivingPhase = DrivingPhase.CRUISE,
        start: float = 0.0,
        end: float = 10.0,
        speed_min: float = 50.0,
        speed_max: float = 60.0,
    ) -> None:
        self.phase = phase
        self.start_t_s = start
        self.end_t_s = end
        self.speed_min_kmh = speed_min
        self.speed_max_kmh = speed_max


class TestBuildPhaseTimeline:
    """Direct unit tests for _build_phase_timeline."""

    def test_empty_segments_returns_empty(self) -> None:
        assert _build_phase_timeline([], [], min_confidence=0.25) == []

    def test_basic_segment_output(self) -> None:
        segs = [
            _FakeSeg(DrivingPhase.CRUISE, 0.0, 30.0, speed_min=40.0, speed_max=80.0),
            _FakeSeg(DrivingPhase.ACCELERATION, 30.0, 45.0, speed_min=40.0, speed_max=80.0),
        ]
        findings = [Finding(finding_id="F001", confidence=0.60)]
        entries = _build_phase_timeline(segs, findings, min_confidence=0.25)
        assert len(entries) == 2
        assert entries[0].phase == DrivingPhase.CRUISE
        assert entries[0].has_fault_evidence is False
        assert entries[1].has_fault_evidence is False

    def test_matching_findings_mark_matching_phases(self) -> None:
        segs = [
            _FakeSeg(DrivingPhase.CRUISE, 0.0, 30.0, speed_min=40.0, speed_max=80.0),
            _FakeSeg(DrivingPhase.ACCELERATION, 30.0, 45.0, speed_min=40.0, speed_max=80.0),
            _FakeSeg(DrivingPhase.DECELERATION, 45.0, 55.0, speed_min=30.0, speed_max=50.0),
        ]
        finding = Finding(
            finding_id="F001",
            confidence=0.60,
            phases_detected=("acceleration", "cruise"),
        )

        entries = _build_phase_timeline(segs, [finding], min_confidence=0.25)

        assert [entry.has_fault_evidence for entry in entries] == [True, True, False]

    @pytest.mark.parametrize(
        "finding",
        [
            pytest.param(
                Finding(finding_id="REF_SPEED", confidence=0.90),
                id="ref_finding_ignored",
            ),
            pytest.param(
                Finding(finding_id="F001", confidence=0.01),
                id="low_confidence_ignored",
            ),
        ],
    )
    def test_finding_does_not_mark_phase(self, finding: Finding) -> None:
        entries = _build_phase_timeline([_FakeSeg()], [finding], min_confidence=0.25)
        assert entries[0].has_fault_evidence is False


class TestPhaseRankingScore:
    """Direct unit tests for Finding.phase_adjusted_score."""

    def test_no_phase_evidence(self) -> None:
        score = finding_from_payload({"confidence": 0.80}).phase_adjusted_score
        assert score == pytest.approx(0.80 * 0.85, rel=1e-3)

    def test_full_cruise_phase(self) -> None:
        finding: dict[str, object] = {
            "confidence": 0.80,
            "phase_evidence": {"cruise_fraction": 1.0},
        }
        score = finding_from_payload(finding).phase_adjusted_score
        assert score == pytest.approx(0.80 * 1.0, rel=1e-3)

    def test_half_cruise(self) -> None:
        finding: dict[str, object] = {
            "confidence": 0.80,
            "phase_evidence": {"cruise_fraction": 0.50},
        }
        score = finding_from_payload(finding).phase_adjusted_score
        expected = 0.80 * (0.85 + 0.15 * 0.50)
        assert score == pytest.approx(expected, rel=1e-3)

    @pytest.mark.parametrize(
        "finding",
        [
            pytest.param({"confidence": None}, id="none_confidence"),
            pytest.param({}, id="missing_confidence_key"),
        ],
    )
    def test_degenerate_confidence_returns_zero(self, finding: dict[str, object]) -> None:
        assert finding_from_payload(finding).phase_adjusted_score == 0.0
