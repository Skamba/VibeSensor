"""Domain value-object tests for confidence scoring and planning models."""

from __future__ import annotations

from vibesensor.domain import (
    ConfidenceAssessment,
)
from vibesensor.domain import (
    RecommendedAction as DomainRecommendedAction,
)
from vibesensor.domain import (
    TestPlan as DomainTestPlan,
)


class TestConfidenceAssessment:
    def test_high_confidence(self) -> None:
        ca = ConfidenceAssessment.assess(0.85)
        assert ca.label_key == "CONFIDENCE_HIGH"
        assert ca.tone == "success"
        assert ca.tier == "C"
        assert ca.is_conclusive
        assert not ca.needs_more_data

    def test_medium_confidence(self) -> None:
        ca = ConfidenceAssessment.assess(0.55)
        assert ca.label_key == "CONFIDENCE_MEDIUM"
        assert ca.tone == "warn"
        assert ca.tier == "B"
        assert not ca.is_conclusive
        assert not ca.needs_more_data

    def test_low_confidence(self) -> None:
        ca = ConfidenceAssessment.assess(0.2)
        assert ca.label_key == "CONFIDENCE_LOW"
        assert ca.tone == "neutral"
        assert ca.tier == "A"
        assert not ca.is_conclusive
        assert ca.needs_more_data

    def test_negligible_strength_downgrade(self) -> None:
        ca = ConfidenceAssessment.assess(0.85, strength_band_key="negligible")
        assert ca.label_key == "CONFIDENCE_MEDIUM"
        assert ca.tone == "warn"
        assert ca.downgraded
        assert ca.tier == "B"

    def test_reference_gaps_affect_tier(self) -> None:
        ca = ConfidenceAssessment.assess(0.85, has_reference_gaps=True)
        assert ca.tier == "B"
        assert "Missing reference data" in ca.reason

    def test_reasons_combined(self) -> None:
        ca = ConfidenceAssessment.assess(
            0.85,
            steady_speed=False,
            has_reference_gaps=True,
            weak_spatial=True,
            sensor_count=1,
        )
        assert "Speed was not steady" in ca.reason
        assert "Missing reference data" in ca.reason
        assert "Vibration spread" in ca.reason
        assert "Single sensor" in ca.reason

    def test_no_reasons_when_all_good(self) -> None:
        ca = ConfidenceAssessment.assess(0.85, sensor_count=4)
        assert ca.reason == ""


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
