"""Focused invariant and multi-run reconciliation tests.

Tests cross-object behaviors:
- TestRun top_causes ⊆ findings invariant
- DiagnosticCase.reconcile across realistic multi-run scenarios
- Case completeness lifecycle
- Finding identity normalisation
"""

from __future__ import annotations

from vibesensor.domain import (
    ConfigurationSnapshot,
    DiagnosticCase,
    DiagnosticCaseEpistemicRule,
    Finding,
    Hypothesis,
    HypothesisStatus,
    RecommendedAction,
    Run,
    RunSuitability,
    SuitabilityCheck,
    TestPlan,
    TestRun,
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
        assert len(case.findings) == 1
        assert case.findings[0].finding_id == "F002"

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
        finding_y_r2 = _finding(
            "FY-1", source="driveline", confidence=0.7, location="center"
        )

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
        assert len(case.findings) == 2
        confidence_map = {f.source_normalized: f.confidence for f in case.findings}
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
