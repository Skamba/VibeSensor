"""Focused invariant tests for aggregate domain objects.

Tests cross-object behaviors:
- TestRun top_causes ⊆ findings invariant
- DiagnosticCase case lifecycle
- Finding identity normalisation
"""

from __future__ import annotations

import pytest

from vibesensor.domain import (
    ConfigurationSnapshot,
    DiagnosticCase,
    Finding,
    FindingKind,
    RecommendedAction,
    RunCapture,
    RunSuitability,
    SuitabilityCheck,
    TestPlan,
    TestRun,
    VibrationSource,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _finding(
    finding_id: str,
    *,
    source: str = "wheel/tire",
    confidence: float = 0.8,
    location: str | None = "front_left",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        suspected_source=source,
        confidence=confidence,
        strongest_location=location,
    )


def _run(
    run_id: str,
    *,
    findings: tuple[Finding, ...] = (),
    top_causes: tuple[Finding, ...] | None = None,
    suitability: RunSuitability | None = None,
    actions: tuple[RecommendedAction, ...] = (),
    snapshot: ConfigurationSnapshot | None = None,
) -> TestRun:
    if top_causes is None:
        top_causes = findings
    from vibesensor.domain import RunSetup

    setup = RunSetup(configuration_snapshot=snapshot) if snapshot else RunSetup()
    return TestRun(
        capture=RunCapture(run_id=run_id, setup=setup),
        findings=findings,
        top_causes=top_causes,
        suitability=suitability,
        test_plan=TestPlan(actions=actions),
    )


def _action(action_id: str, what: str) -> RecommendedAction:
    return RecommendedAction(action_id=action_id, what=what)


def _passing_suitability() -> RunSuitability:
    return RunSuitability(
        checks=(SuitabilityCheck(check_key="test", state="pass"),),
    )


def _failing_suitability() -> RunSuitability:
    return RunSuitability(
        checks=(SuitabilityCheck(check_key="test", state="fail"),),
    )


# ── Case lifecycle ───────────────────────────────────────────────────────────


class TestCaseLifecycle:
    def test_case_start_with_default_symptom(self) -> None:
        """DiagnosticCase.start() with no symptoms creates unspecified symptom."""
        case = DiagnosticCase.start()
        assert len(case.symptoms) == 1
        assert case.symptoms[0].is_unspecified

    def test_add_run_snapshots_accessible_via_capture(self) -> None:
        """Snapshots are accessible via capture.setup.configuration_snapshot."""
        snap_a = ConfigurationSnapshot(sensor_model="MPU6050")
        snap_b = ConfigurationSnapshot(sensor_model="ADXL345")

        case = DiagnosticCase.start()
        case = case.add_run(_run("run-1", snapshot=snap_a))
        case = case.add_run(_run("run-2", snapshot=snap_b))

        assert case.test_runs[0].capture.setup.configuration_snapshot == snap_a
        assert case.test_runs[1].capture.setup.configuration_snapshot == snap_b

    def test_case_with_no_runs_has_no_primary(self) -> None:
        case = DiagnosticCase.start()
        assert case.primary_run is None

    def test_primary_run_advances_without_mutating_previous_case(self) -> None:
        first = _run(
            "run-1",
            findings=(_finding("F001"),),
            actions=(_action("inspect-wheel", "Inspect wheel balance"),),
            suitability=_passing_suitability(),
        )
        second = _run(
            "run-2",
            findings=(_finding("F002", source="driveline", location="center"),),
            actions=(_action("inspect-driveline", "Inspect driveline joints"),),
            suitability=_failing_suitability(),
        )

        initial_case = DiagnosticCase.start()
        first_case = initial_case.add_run(first)
        latest_case = first_case.add_run(second)

        assert initial_case.test_runs == ()
        assert first_case.test_runs == (first,)
        assert first_case.primary_run == first
        assert latest_case.test_runs == (first, second)
        assert latest_case.primary_run == second
        assert latest_case.primary_run.primary_source is VibrationSource.DRIVELINE
        assert latest_case.primary_run.primary_location == "center"
        assert latest_case.primary_run.recommended_actions == (
            _action("inspect-driveline", "Inspect driveline joints"),
        )
        assert latest_case.primary_run.suitability == _failing_suitability()


# ── Impossible aggregate state tests ────────────────────────────────────────


class TestImpossibleTestRunStates:
    """TestRun __post_init__ must reject impossible field combinations."""

    def test_top_causes_with_empty_findings_raises(self) -> None:
        """top_causes present but findings empty → ValueError."""
        tc = _finding("F001")
        with pytest.raises(ValueError, match="top_causes must be drawn from findings"):
            TestRun(
                capture=RunCapture(run_id="r1"),
                findings=(),
                top_causes=(tc,),
            )

    def test_top_causes_not_matching_any_finding_raises(self) -> None:
        """top_causes whose finding_id is not in findings → ValueError."""
        f1 = _finding("F001")
        orphan = _finding("F099", source="driveline", location="center")
        with pytest.raises(ValueError, match="unmatched top causes"):
            TestRun(
                capture=RunCapture(run_id="r1"),
                findings=(f1,),
                top_causes=(orphan,),
            )

    def test_top_causes_subset_of_findings_ok(self) -> None:
        """top_causes that are a strict subset of findings → no error."""
        f1 = _finding("F001")
        f2 = _finding("F002", source="driveline", location="center")
        tr = TestRun(
            capture=RunCapture(run_id="r1"),
            findings=(f1, f2),
            top_causes=(f1,),
        )
        assert tr.top_causes == (f1,)

    def test_empty_top_causes_with_empty_findings_ok(self) -> None:
        """Both empty → valid (no-evidence run)."""
        tr = TestRun(
            capture=RunCapture(run_id="r1"),
            findings=(),
            top_causes=(),
        )
        assert tr.findings == ()
        assert tr.top_causes == ()

    def test_top_cause_matched_by_finding_id_only(self) -> None:
        """top_cause differs in fields but shares finding_id → accepted."""
        f1 = _finding("F001", confidence=0.9)
        tc = _finding("F001", confidence=0.5)  # same id, different confidence
        tr = TestRun(
            capture=RunCapture(run_id="r1"),
            findings=(f1,),
            top_causes=(tc,),
        )
        assert tr.top_causes[0].confidence == 0.5

    def test_multiple_unmatched_top_causes_lists_all(self) -> None:
        """Error message includes all unmatched finding IDs."""
        f_real = _finding("F001")
        orphan_a = _finding("F888")
        orphan_b = _finding("F999", source="engine")
        with pytest.raises(ValueError, match="F888") as exc_info:
            TestRun(
                capture=RunCapture(run_id="r1"),
                findings=(f_real,),
                top_causes=(orphan_a, orphan_b),
            )
        assert "F999" in str(exc_info.value)


class TestImpossibleFindingStates:
    """Finding __post_init__ must reject contradictory field values."""

    def test_confidence_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            Finding(finding_id="F001", confidence=-0.1)

    def test_confidence_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            Finding(finding_id="F001", confidence=1.01)

    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [
            pytest.param(0.0, 0.0, id="zero"),
            pytest.param(1.0, 1.0, id="one"),
            pytest.param(None, None, id="none"),
        ],
    )
    def test_confidence_boundary_cases_ok(
        self,
        confidence: float | None,
        expected: float | None,
    ) -> None:
        f = Finding(finding_id="F001", confidence=confidence)
        assert f.confidence == expected

    def test_cruise_fraction_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="cruise_fraction must be in"):
            Finding(finding_id="F001", cruise_fraction=-0.01)

    def test_cruise_fraction_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="cruise_fraction must be in"):
            Finding(finding_id="F001", cruise_fraction=1.5)

    def test_ranking_score_nan_raises(self) -> None:
        with pytest.raises(ValueError, match="ranking_score must be finite"):
            Finding(finding_id="F001", ranking_score=float("nan"))

    def test_ranking_score_inf_raises(self) -> None:
        with pytest.raises(ValueError, match="ranking_score must be finite"):
            Finding(finding_id="F001", ranking_score=float("inf"))

    def test_unknown_source_string_coerced_to_unknown(self) -> None:
        """An unrecognised source string is auto-coerced to VibrationSource.UNKNOWN."""
        f = Finding(finding_id="F001", suspected_source="banana_motor")
        assert f.suspected_source is VibrationSource.UNKNOWN

    def test_kind_auto_derived_reference(self) -> None:
        """REF_ prefix → FindingKind.REFERENCE."""
        f = Finding(finding_id="REF_NOISE")
        assert f.kind is FindingKind.REFERENCE

    def test_kind_auto_derived_informational(self) -> None:
        """severity='info' → FindingKind.INFORMATIONAL."""
        f = Finding(finding_id="F001", severity="info")
        assert f.kind is FindingKind.INFORMATIONAL


class TestImpossibleSuitabilityStates:
    """SuitabilityCheck state values and RunSuitability aggregation."""

    def test_arbitrary_state_string_is_explicitly_neutral_downstream(self) -> None:
        """Unknown states remain stored but do not count as pass/warn/fail."""
        c = SuitabilityCheck(check_key="test", state="banana", details=(("stride", 4),))
        suitability = RunSuitability(checks=(c,))

        assert c.state == "banana"
        assert not c.passed
        assert not c.failed
        assert not c.is_warning
        assert c.details_dict == {"stride": 4}
        assert c.explanation_i18n_ref() == ""
        assert suitability.overall == "pass"
        assert suitability.is_usable
        assert suitability.failed_checks == ()
        assert suitability.warning_checks == ()

    @pytest.mark.parametrize(
        ("states", "expected_overall", "expected_usable"),
        [
            pytest.param((), "pass", True, id="empty"),
            pytest.param(("pass", "pass"), "pass", True, id="all-pass"),
            pytest.param(("pass", "warn"), "caution", True, id="warning-present"),
            pytest.param(("pass", "fail"), "fail", False, id="failure-present"),
        ],
    )
    def test_overall_state_aggregation(
        self,
        states: tuple[str, ...],
        expected_overall: str,
        expected_usable: bool,
    ) -> None:
        s = RunSuitability(
            checks=tuple(
                SuitabilityCheck(check_key=f"check-{index}", state=state)
                for index, state in enumerate(states)
            )
        )
        assert s.overall == expected_overall
        assert s.is_usable is expected_usable
