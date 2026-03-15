from __future__ import annotations

from vibesensor.domain import (
    Finding,
)
from vibesensor.domain import (
    RecommendedAction as DomainRecommendedAction,
)
from vibesensor.domain import (
    TestPlan as DomainTestPlan,
)
from vibesensor.domain.services import plan_test_actions


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


def test_domain_test_plan_needs_more_data_semantics_are_flag_driven() -> None:
    actionable_plan = DomainTestPlan(
        actions=(
            DomainRecommendedAction(
                action_id="wheel_tire_condition",
                what="ACTION_TIRE_CONDITION_WHAT",
                priority=1,
            ),
        ),
        requires_additional_data=False,
    )
    needs_data_plan = DomainTestPlan(
        actions=(
            DomainRecommendedAction(
                action_id="general_mechanical_inspection",
                what="COLLECT_A_LONGER_RUN_WITH_STABLE_DRIVING_CONDITIONS",
                priority=1,
            ),
        ),
        requires_additional_data=True,
    )

    assert actionable_plan.needs_more_data() is False
    assert actionable_plan.supports_case_completion is True
    assert needs_data_plan.needs_more_data() is True
    assert needs_data_plan.supports_case_completion is False
