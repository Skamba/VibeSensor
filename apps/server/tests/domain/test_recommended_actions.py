"""Test-plan domain: action selection, fallback plans and plan/action queries."""

from __future__ import annotations

from vibesensor.domain.finding import Finding
from vibesensor.domain.test_plan import RecommendedAction as DomainRecommendedAction
from vibesensor.domain.test_plan import TestPlan as DomainTestPlan
from vibesensor.domain.test_plan import plan_test_actions


def test_plan_test_actions_accepts_domain_findings() -> None:
    findings = [
        Finding(
            suspected_source="engine",
            strongest_location="engine bay",
            strongest_speed_band="50-60 km/h",
            frequency_hz=32.0,
            confidence=0.74,
        )
    ]

    plan = plan_test_actions(findings)

    assert len(plan.prioritized_actions) > 0
    assert plan.prioritized_actions[0].action_id == "engine_mounts_and_accessories"
    assert plan.requires_additional_data is False


def test_plan_test_actions_prioritizes_and_deduplicates_domain_actions() -> None:
    findings = [
        Finding(
            suspected_source="wheel/tire",
            strongest_location="front-left wheel",
            strongest_speed_band="90-100 km/h",
            confidence=0.82,
        ),
        Finding(
            suspected_source="wheel/tire",
            strongest_location="rear-right wheel",
            strongest_speed_band="80-90 km/h",
            confidence=0.61,
        ),
        Finding(
            suspected_source="driveline",
            strongest_location="rear floor",
            strongest_speed_band="70-80 km/h",
            confidence=0.73,
        ),
    ]

    plan = plan_test_actions(findings)

    assert [action.action_id for action in plan.actions] == [
        "wheel_tire_condition",
        "wheel_balance_and_runout",
        "driveline_mounts_and_fasteners",
        "driveline_inspection",
    ]
    assert [action.priority for action in plan.actions] == [1, 2, 3, 4]
    assert plan.prioritized_actions == plan.actions


def test_plan_test_actions_returns_fallback_when_no_findings_exist() -> None:
    plan = plan_test_actions(())

    assert plan.requires_additional_data is True
    assert plan.supports_case_completion is False
    assert plan.needs_more_data() is True
    assert [action.action_id for action in plan.actions] == ["general_mechanical_inspection"]
    fallback = plan.actions[0]
    assert fallback.what == "COLLECT_A_LONGER_RUN_WITH_STABLE_DRIVING_CONDITIONS"
    assert fallback.why == "NO_ACTIONABLE_FINDINGS_WERE_GENERATED_FROM_CURRENT_DATA"
    assert fallback.priority == 1


def test_plan_test_actions_uses_weak_spatial_fallback_for_unknown_findings() -> None:
    findings = [
        Finding(
            suspected_source="unknown",
            strongest_location="front floor",
            weak_spatial_separation=True,
            confidence=0.4,
        )
    ]

    plan = plan_test_actions(findings)

    assert [action.action_id for action in plan.actions] == ["general_mechanical_inspection"]
    assert plan.actions[0].why == "ACTION_GENERAL_WEAK_SPATIAL_WHY"


class TestRecommendedAction:
    def test_render_queries_normalize_blank_optional_fields(self) -> None:
        action = DomainRecommendedAction(
            action_id="inspect_mount",
            what="  ACTION_ENGINE_MOUNTS_WHAT  ",
            why="   ",
            confirm=" movement increases ",
            falsify="  ",
            eta=" 15-30 min ",
        )

        assert action.instruction == "ACTION_ENGINE_MOUNTS_WHAT"
        assert action.rationale is None
        assert action.confirmation_signal == "movement increases"
        assert action.falsification_signal is None
        assert action.estimated_duration == "15-30 min"
        assert action.has_supporting_detail is True

    def test_render_queries_report_no_supporting_detail(self) -> None:
        action = DomainRecommendedAction(
            action_id="inspect_mount",
            what="ACTION_ENGINE_MOUNTS_WHAT",
        )

        assert action.rationale is None
        assert action.confirmation_signal is None
        assert action.falsification_signal is None
        assert action.estimated_duration is None
        assert action.has_supporting_detail is False


class TestTestPlan:
    def test_supports_case_completion_without_pending_actions(self) -> None:
        plan = DomainTestPlan()

        assert plan.has_actions is False
        assert plan.supports_case_completion is True
        assert plan.is_complete is True
        assert plan.needs_more_data() is False

    def test_pending_actions_do_not_imply_more_data(self) -> None:
        plan = DomainTestPlan(
            actions=(
                DomainRecommendedAction(
                    action_id="wheel_balance_and_runout",
                    what="ACTION_WHEEL_BALANCE_WHAT",
                ),
            ),
        )

        assert plan.has_actions is True
        assert plan.supports_case_completion is True
        assert plan.is_complete is False
        assert plan.needs_more_data() is False

    def test_requires_additional_data_blocks_case_completion(self) -> None:
        plan = DomainTestPlan(
            actions=(
                DomainRecommendedAction(
                    action_id="general_mechanical_inspection",
                    what="COLLECT_A_LONGER_RUN_WITH_STABLE_DRIVING_CONDITIONS",
                ),
            ),
            requires_additional_data=True,
        )

        assert plan.supports_case_completion is False
        assert plan.needs_more_data() is True
