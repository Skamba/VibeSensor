"""Focused invariant and multi-run reconciliation tests.

Tests cross-object behaviors:
- TestRun top_causes ⊆ findings invariant
- DiagnosticCase.reconcile across realistic multi-run scenarios
- Case completeness lifecycle
- Finding identity normalisation
"""

from __future__ import annotations

import pytest

from vibesensor.domain import (
    ConfigurationSnapshot,
    DiagnosticCase,
    DiagnosticCaseEpistemicRule,
    Finding,
    FindingKind,
    Hypothesis,
    HypothesisStatus,
    RecommendedAction,
    Run,
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


def _hypothesis(
    hyp_id: str,
    *,
    source: str = "engine",
    support: float = 0.7,
    contradiction: float = 0.0,
    status: HypothesisStatus = HypothesisStatus.SUPPORTED,
    signature_keys: tuple[str, ...] = ("key1",),
) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=hyp_id,
        source=source,
        support_score=support,
        contradiction_score=contradiction,
        status=status,
        signature_keys=signature_keys,
    )


def _run(
    run_id: str,
    *,
    hypotheses: tuple[Hypothesis, ...] = (),
    findings: tuple[Finding, ...] = (),
    top_causes: tuple[Finding, ...] | None = None,
    suitability: RunSuitability | None = None,
    actions: tuple[RecommendedAction, ...] = (),
    snapshot: ConfigurationSnapshot | None = None,
) -> TestRun:
    if top_causes is None:
        top_causes = findings
    return TestRun(
        run=Run(run_id=run_id),
        configuration_snapshot=snapshot or ConfigurationSnapshot(),
        hypotheses=hypotheses,
        findings=findings,
        top_causes=top_causes,
        suitability=suitability,
        test_plan=TestPlan(actions=actions),
    )


def _passing_suitability() -> RunSuitability:
    return RunSuitability(
        checks=(SuitabilityCheck(check_key="test", state="pass"),),
    )


def _failing_suitability() -> RunSuitability:
    return RunSuitability(
        checks=(SuitabilityCheck(check_key="test", state="fail"),),
    )


# ── Multi-run reconciliation ────────────────────────────────────────────────


class TestMultiRunReconciliation:
    def test_three_run_progressive_strengthening(self) -> None:
        """Three runs where the same hypothesis increases support across runs."""
        case = DiagnosticCase.start()
        case = case.add_run(
            _run("run-1", hypotheses=(_hypothesis("hyp-A", support=0.3),)),
        )
        case = case.add_run(
            _run("run-2", hypotheses=(_hypothesis("hyp-A", support=0.5),)),
        )
        case = case.add_run(
            _run("run-3", hypotheses=(_hypothesis("hyp-A", support=0.8),)),
        )

        # Latest (run-3) value is kept
        assert len(case.hypotheses) == 1
        assert case.hypotheses[0].support_score == 0.8

        # Epistemic classification is STRENGTHENING
        rule = DiagnosticCase.classify_hypothesis_sequence(
            (
                _hypothesis("hyp-A", support=0.3),
                _hypothesis("hyp-A", support=0.5),
                _hypothesis("hyp-A", support=0.8),
            ),
        )
        assert rule is DiagnosticCaseEpistemicRule.STRENGTHENING

    def test_three_run_weakening_then_strengthening(self) -> None:
        """Run1: high. Run2: lower. Run3: highest. Latest kept; STRENGTHENING."""
        case = DiagnosticCase.start()
        case = case.add_run(
            _run("run-1", hypotheses=(_hypothesis("hyp-A", support=0.7),)),
        )
        case = case.add_run(
            _run("run-2", hypotheses=(_hypothesis("hyp-A", support=0.4),)),
        )
        case = case.add_run(
            _run("run-3", hypotheses=(_hypothesis("hyp-A", support=0.9),)),
        )

        # Latest kept
        assert case.hypotheses[0].support_score == 0.9

        # Latest > prior best (0.7) → STRENGTHENING
        rule = DiagnosticCase.classify_hypothesis_sequence(
            (
                _hypothesis("hyp-A", support=0.7),
                _hypothesis("hyp-A", support=0.4),
                _hypothesis("hyp-A", support=0.9),
            ),
        )
        assert rule is DiagnosticCaseEpistemicRule.STRENGTHENING

    def test_hypothesis_retirement_mid_case(self) -> None:
        """Run1: hypothesis supported. Run2: same hypothesis RETIRED. Excluded from case."""
        surviving = _hypothesis("hyp-B", support=0.6)
        case = DiagnosticCase.start()
        case = case.add_run(
            _run(
                "run-1",
                hypotheses=(_hypothesis("hyp-A", support=0.7),),
            ),
        )
        case = case.add_run(
            _run(
                "run-2",
                hypotheses=(
                    _hypothesis("hyp-A", support=0.0, status=HypothesisStatus.RETIRED),
                    surviving,
                ),
            ),
        )

        hyp_ids = {h.hypothesis_id for h in case.hypotheses}
        assert "hyp-A" not in hyp_ids
        assert "hyp-B" in hyp_ids

    def test_finding_identity_normalization(self) -> None:
        """Findings with same source (different case) and same location are treated identically."""
        f1 = _finding("F001", source="Wheel Bearing", location="front_left")
        f2 = _finding("F002", source="wheel_bearing", location="front_left")
        case = DiagnosticCase.start()
        case = case.add_run(_run("run-1", findings=(f1,), top_causes=(f1,)))
        case = case.add_run(_run("run-2", findings=(f2,), top_causes=(f2,)))

        # The two are treated as same identity → latest kept
        assert len(case.diagnoses) == 1
        assert case.diagnoses[0].representative_finding.finding_id == "F002"

    def test_reconcile_preserves_action_priority_ordering(self) -> None:
        """Multiple runs with overlapping actions — lowest priority wins and sorted."""
        action_a_high = RecommendedAction(action_id="act-A", what="A", priority=50)
        action_a_low = RecommendedAction(action_id="act-A", what="A", priority=10)
        action_b = RecommendedAction(action_id="act-B", what="B", priority=30)
        action_c = RecommendedAction(action_id="act-C", what="C", priority=20)

        case = DiagnosticCase.start(test_plan=TestPlan(actions=(action_a_high,)))
        case = case.add_run(
            _run("run-1", actions=(action_b,)),
        )
        case = case.add_run(
            _run("run-2", actions=(action_a_low, action_c)),
        )

        # act-A: lowest priority = 10 wins
        act_a = next(a for a in case.recommended_actions if a.action_id == "act-A")
        assert act_a.priority == 10

        # All three present
        ids = [a.action_id for a in case.recommended_actions]
        assert set(ids) == {"act-A", "act-B", "act-C"}

        # Sorted by priority ascending
        priorities = [a.priority for a in case.recommended_actions]
        assert priorities == sorted(priorities)

    def test_multi_run_mixed_findings_and_hypotheses(self) -> None:
        """Realistic: two runs with overlapping hypotheses and findings."""
        hyp_a_r1 = _hypothesis("hyp-A", support=0.7)
        finding_x_r1 = _finding("FX-1", source="wheel/tire", confidence=0.8)

        hyp_a_r2 = _hypothesis("hyp-A", support=0.5)
        hyp_b_r2 = _hypothesis("hyp-B", support=0.6)
        finding_x_r2 = _finding("FX-2", source="wheel/tire", confidence=0.6)
        finding_y_r2 = _finding("FY-1", source="driveline", confidence=0.7, location="center")

        case = DiagnosticCase.start()
        case = case.add_run(
            _run(
                "run-1",
                hypotheses=(hyp_a_r1,),
                findings=(finding_x_r1,),
                top_causes=(finding_x_r1,),
            ),
        )
        case = case.add_run(
            _run(
                "run-2",
                hypotheses=(hyp_a_r2, hyp_b_r2),
                findings=(finding_x_r2, finding_y_r2),
                top_causes=(finding_x_r2, finding_y_r2),
            ),
        )

        # Hypothesis A: latest=0.5, B: 0.6
        hyp_map = {h.hypothesis_id: h for h in case.hypotheses}
        assert hyp_map["hyp-A"].support_score == 0.5
        assert hyp_map["hyp-B"].support_score == 0.6

        # Finding X (same source+location) → latest = 0.6; Finding Y → 0.7
        assert len(case.diagnoses) == 2
        confidence_map = {
            d.representative_finding.source_normalized: d.representative_finding.confidence
            for d in case.diagnoses
        }
        assert confidence_map["wheel/tire"] == 0.6
        assert confidence_map["driveline"] == 0.7


# ── Case lifecycle ──────────────────────────────────────────────────────────


class TestCaseLifecycle:
    def test_case_start_with_default_symptom(self) -> None:
        """DiagnosticCase.start() with no symptoms creates unspecified symptom."""
        case = DiagnosticCase.start()
        assert len(case.symptoms) == 1
        assert case.symptoms[0].is_unspecified

    def test_add_run_accumulates_snapshots(self) -> None:
        """Two distinct snapshots → 2 accumulated. Third duplicate → still 2."""
        snap_a = ConfigurationSnapshot(sensor_model="MPU6050")
        snap_b = ConfigurationSnapshot(sensor_model="ADXL345")

        case = DiagnosticCase.start()
        case = case.add_run(_run("run-1", snapshot=snap_a))
        case = case.add_run(_run("run-2", snapshot=snap_b))

        assert len(case.configuration_snapshots) == 2

        # Third run with same snapshot as first → no new accumulation
        case = case.add_run(_run("run-3", snapshot=snap_a))
        assert len(case.configuration_snapshots) == 2

    def test_case_completeness_with_usable_evidence(self) -> None:
        """Complete case: actionable findings + usable suitability + plan done."""
        actionable = _finding("F001", source="wheel/tire", confidence=0.82)

        case = DiagnosticCase.start(test_plan=TestPlan(requires_additional_data=False))
        case = case.add_run(
            _run(
                "run-1",
                findings=(actionable,),
                top_causes=(actionable,),
                suitability=_passing_suitability(),
            ),
        )

        assert case.is_complete is True
        assert case.needs_more_data is False
        assert case.evidence_gaps == ()

    def test_case_incompleteness_due_to_suitability(self) -> None:
        """Findings present but primary run suitability is not usable → incomplete."""
        actionable = _finding("F001", source="wheel/tire", confidence=0.82)

        case = DiagnosticCase.start(test_plan=TestPlan(requires_additional_data=False))
        case = case.add_run(
            _run(
                "run-1",
                findings=(actionable,),
                top_causes=(actionable,),
                suitability=_failing_suitability(),
            ),
        )

        assert case.is_complete is False
        assert "primary_run_unusable" in case.evidence_gaps


# ── Impossible aggregate state tests ────────────────────────────────────────


class TestImpossibleTestRunStates:
    """TestRun __post_init__ must reject impossible field combinations."""

    def test_top_causes_with_empty_findings_raises(self) -> None:
        """top_causes present but findings empty → ValueError."""
        tc = _finding("F001")
        with pytest.raises(ValueError, match="top_causes must be drawn from findings"):
            TestRun(
                run=Run(run_id="r1"),
                configuration_snapshot=ConfigurationSnapshot(),
                findings=(),
                top_causes=(tc,),
            )

    def test_top_causes_not_matching_any_finding_raises(self) -> None:
        """top_causes whose finding_id is not in findings → ValueError."""
        f1 = _finding("F001")
        orphan = _finding("F099", source="driveline", location="center")
        with pytest.raises(ValueError, match="unmatched top causes"):
            TestRun(
                run=Run(run_id="r1"),
                configuration_snapshot=ConfigurationSnapshot(),
                findings=(f1,),
                top_causes=(orphan,),
            )

    def test_top_causes_subset_of_findings_ok(self) -> None:
        """top_causes that are a strict subset of findings → no error."""
        f1 = _finding("F001")
        f2 = _finding("F002", source="driveline", location="center")
        tr = TestRun(
            run=Run(run_id="r1"),
            configuration_snapshot=ConfigurationSnapshot(),
            findings=(f1, f2),
            top_causes=(f1,),
        )
        assert tr.top_causes == (f1,)

    def test_empty_top_causes_with_empty_findings_ok(self) -> None:
        """Both empty → valid (no-evidence run)."""
        tr = TestRun(
            run=Run(run_id="r1"),
            configuration_snapshot=ConfigurationSnapshot(),
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
            run=Run(run_id="r1"),
            configuration_snapshot=ConfigurationSnapshot(),
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
                run=Run(run_id="r1"),
                configuration_snapshot=ConfigurationSnapshot(),
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

    def test_confidence_boundary_zero_ok(self) -> None:
        f = Finding(finding_id="F001", confidence=0.0)
        assert f.confidence == 0.0

    def test_confidence_boundary_one_ok(self) -> None:
        f = Finding(finding_id="F001", confidence=1.0)
        assert f.confidence == 1.0

    def test_confidence_none_ok(self) -> None:
        f = Finding(finding_id="F001", confidence=None)
        assert f.confidence is None

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
        f = Finding(finding_id="F001", suspected_source="banana_motor")  # type: ignore[arg-type]
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

    def test_arbitrary_state_string_is_accepted(self) -> None:
        """SuitabilityCheck.state is a plain str, not an enum — any value is stored."""
        c = SuitabilityCheck(check_key="test", state="banana")
        assert c.state == "banana"
        assert not c.passed
        assert not c.failed
        assert not c.is_warning

    def test_overall_fail_when_any_check_fails(self) -> None:
        s = RunSuitability(
            checks=(
                SuitabilityCheck(check_key="a", state="pass"),
                SuitabilityCheck(check_key="b", state="fail"),
            )
        )
        assert s.overall == "fail"
        assert not s.is_usable

    def test_overall_caution_when_only_warnings(self) -> None:
        s = RunSuitability(
            checks=(
                SuitabilityCheck(check_key="a", state="pass"),
                SuitabilityCheck(check_key="b", state="warn"),
            )
        )
        assert s.overall == "caution"
        assert s.is_usable

    def test_overall_pass_when_all_pass(self) -> None:
        s = RunSuitability(
            checks=(
                SuitabilityCheck(check_key="a", state="pass"),
                SuitabilityCheck(check_key="b", state="pass"),
            )
        )
        assert s.overall == "pass"
        assert s.is_usable

    def test_empty_checks_is_pass(self) -> None:
        s = RunSuitability(checks=())
        assert s.overall == "pass"
        assert s.is_usable


class TestImpossibleDiagnosticCaseStates:
    """DiagnosticCase lifecycle edge cases."""

    def test_classify_hypothesis_sequence_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="requires evidence"):
            DiagnosticCase.classify_hypothesis_sequence(())

    def test_classify_finding_sequence_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="requires evidence"):
            DiagnosticCase.classify_finding_sequence(())

    def test_case_with_no_runs_has_no_primary(self) -> None:
        case = DiagnosticCase.start()
        assert case.primary_run is None
        assert case.has_usable_evidence is False
        assert case.is_complete is False

    def test_case_with_no_findings_shows_gap(self) -> None:
        case = DiagnosticCase.start()
        case = case.add_run(_run("run-1"))
        assert "no_findings" in case.evidence_gaps
        assert case.is_complete is False

    def test_case_with_non_actionable_findings_only(self) -> None:
        """Only unknown-source, unknown-location findings → not actionable."""
        f = _finding("F001", source="unknown", location="unknown")
        case = DiagnosticCase.start()
        case = case.add_run(_run("run-1", findings=(f,), top_causes=(f,)))
        assert "no_actionable_findings" in case.evidence_gaps


# ── Multi-run reconciliation edge cases ─────────────────────────────────────


class TestMultiRunReconciliationEdgeCases:
    """Additional reconciliation scenarios not covered above."""

    def test_reconcile_empty_runs(self) -> None:
        """Adding a no-evidence run doesn't break reconcile."""
        case = DiagnosticCase.start()
        case = case.add_run(_run("run-1"))

        assert case.diagnoses == ()
        assert case.hypotheses == ()
        assert len(case.test_runs) == 1

    def test_reconcile_two_empty_runs(self) -> None:
        case = DiagnosticCase.start()
        case = case.add_run(_run("run-1"))
        case = case.add_run(_run("run-2"))

        assert case.diagnoses == ()
        assert case.hypotheses == ()
        assert len(case.test_runs) == 2

    def test_duplicate_finding_ids_across_runs_last_wins(self) -> None:
        """Same finding_id in two runs — second run's version is kept."""
        f1 = _finding("F001", confidence=0.6)
        f2 = _finding("F001", confidence=0.9)

        case = DiagnosticCase.start()
        case = case.add_run(_run("run-1", findings=(f1,), top_causes=(f1,)))
        case = case.add_run(_run("run-2", findings=(f2,), top_causes=(f2,)))

        # Same source+location identity → latest kept
        assert len(case.diagnoses) == 1
        assert case.diagnoses[0].representative_finding.confidence == 0.9

    def test_contradictory_findings_across_runs(self) -> None:
        """Two runs point to different actionable sources → CONTRADICTION."""
        f1 = _finding("F001", source="wheel/tire", location="front_left")
        f2 = _finding("F002", source="engine", location="center")

        rule = DiagnosticCase.classify_finding_sequence((f1, f2))
        assert rule is DiagnosticCaseEpistemicRule.CONTRADICTION

    def test_weakening_finding_score_across_runs(self) -> None:
        """Same finding identity with decreasing score → WEAKENING."""
        f1 = _finding("F001", source="wheel/tire", confidence=0.9, location="front_left")
        f2 = _finding("F002", source="wheel/tire", confidence=0.4, location="front_left")

        rule = DiagnosticCase.classify_finding_sequence((f1, f2))
        assert rule is DiagnosticCaseEpistemicRule.WEAKENING

    def test_strengthening_finding_score_across_runs(self) -> None:
        """Same finding identity with increasing score → STRENGTHENING."""
        f1 = _finding("F001", source="wheel/tire", confidence=0.3, location="front_left")
        f2 = _finding("F002", source="wheel/tire", confidence=0.8, location="front_left")

        rule = DiagnosticCase.classify_finding_sequence((f1, f2))
        assert rule is DiagnosticCaseEpistemicRule.STRENGTHENING

    def test_hypothesis_contradiction_when_mixed_support_and_rejection(self) -> None:
        """Run1 supports, Run2 contradicts same hypothesis → CONTRADICTION."""
        h1 = _hypothesis("hyp-A", support=0.7, status=HypothesisStatus.SUPPORTED)
        h2 = _hypothesis(
            "hyp-A",
            support=0.2,
            contradiction=0.8,
            status=HypothesisStatus.CONTRADICTED,
        )
        rule = DiagnosticCase.classify_hypothesis_sequence((h1, h2))
        assert rule is DiagnosticCaseEpistemicRule.CONTRADICTION

    def test_unresolved_support_single_finding(self) -> None:
        """Single finding with no prior → UNRESOLVED_SUPPORT."""
        f = _finding("F001", source="wheel/tire", location="front_left")
        rule = DiagnosticCase.classify_finding_sequence((f,))
        assert rule is DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT

    def test_reconcile_preserves_all_runs(self) -> None:
        """After 3 add_run calls, all 3 TestRun objects are retained."""
        case = DiagnosticCase.start()
        for i in range(3):
            case = case.add_run(_run(f"run-{i}"))
        assert len(case.test_runs) == 3
        assert [r.run_id for r in case.test_runs] == ["run-0", "run-1", "run-2"]

    def test_reconcile_non_actionable_finding_does_not_override_actionable(self) -> None:
        """Non-actionable finding doesn't eliminate an earlier actionable one."""
        actionable = _finding("F001", source="wheel/tire", location="front_left")
        non_actionable = _finding("F002", source="unknown", location="unknown")

        case = DiagnosticCase.start()
        case = case.add_run(
            _run("run-1", findings=(actionable,), top_causes=(actionable,)),
        )
        case = case.add_run(
            _run("run-2", findings=(non_actionable,), top_causes=(non_actionable,)),
        )
        # Both are kept since they have distinct identity
        sources = {d.representative_finding.source_normalized for d in case.diagnoses}
        assert "wheel/tire" in sources

    def test_reconcile_with_real_world_three_run_progression(self) -> None:
        """Realistic: 3 runs, first inconclusive, second finds wheel/tire, third confirms."""
        # Run 1: weak unknown finding only
        f1 = _finding("F001", source="unknown", confidence=0.3, location="unknown")
        h1 = _hypothesis("hyp-A", source="engine", support=0.2, status=HypothesisStatus.CANDIDATE)

        # Run 2: clear wheel/tire finding with supporting hypothesis
        f2 = _finding("F002", source="wheel/tire", confidence=0.7, location="front_left")
        h2a = _hypothesis(
            "hyp-A",
            source="engine",
            support=0.1,
            status=HypothesisStatus.INCONCLUSIVE,
        )
        h2b = _hypothesis(
            "hyp-B",
            source="wheel/tire",
            support=0.6,
            status=HypothesisStatus.SUPPORTED,
        )

        # Run 3: confirmed wheel/tire with higher confidence
        f3 = _finding("F003", source="wheel/tire", confidence=0.9, location="front_left")
        h3b = _hypothesis(
            "hyp-B",
            source="wheel/tire",
            support=0.85,
            status=HypothesisStatus.SUPPORTED,
        )

        case = DiagnosticCase.start()
        case = case.add_run(
            _run("run-1", findings=(f1,), top_causes=(f1,), hypotheses=(h1,)),
        )
        case = case.add_run(
            _run("run-2", findings=(f2,), top_causes=(f2,), hypotheses=(h2a, h2b)),
        )
        case = case.add_run(
            _run("run-3", findings=(f3,), top_causes=(f3,), hypotheses=(h3b,)),
        )

        # wheel/tire finding should be latest (0.9)
        wt = [
            d for d in case.diagnoses if d.representative_finding.source_normalized == "wheel/tire"
        ]
        assert len(wt) == 1
        assert wt[0].representative_finding.confidence == 0.9

        # hyp-B kept with latest support, hyp-A also kept (not retired)
        hyp_map = {h.hypothesis_id: h for h in case.hypotheses}
        assert "hyp-B" in hyp_map
        assert hyp_map["hyp-B"].support_score == 0.85
