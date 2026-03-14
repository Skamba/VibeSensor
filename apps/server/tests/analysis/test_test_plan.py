from __future__ import annotations

import vibesensor.domain.services.test_planning as domain_test_planning
from vibesensor.analysis.test_plan import (
    _merge_test_plan,
    build_domain_test_plan,
    build_domain_test_plan_from_findings,
)
from vibesensor.domain import Finding
from vibesensor.domain import TestPlan as DomainTestPlan


def test_merge_test_plan_deduplicates_action_ids_case_insensitively() -> None:
    findings = [
        {
            "actions": [
                {"action_id": " WHEEL_BALANCE_AND_RUNOUT ", "what": "A"},
                {"action_id": "wheel_balance_and_runout", "what": "B"},
            ],
        },
    ]

    merged = _merge_test_plan(findings, "en")
    assert len(merged) == 1
    assert str(merged[0]["action_id"]).strip().lower() == "wheel_balance_and_runout"


def test_merge_test_plan_generated_steps_inherit_normalized_metadata() -> None:
    findings = [
        {
            "suspected_source": " WHEEL/TIRE ",
            "strongest_location": "front-left wheel",
            "strongest_speed_band": " 90-100 km/h ",
            "frequency_hz_or_order": " 12.4 Hz ",
            "confidence": 0.82,
        },
    ]

    merged = _merge_test_plan(findings, "en")
    assert len(merged) > 0
    for step in merged:
        assert step.get("certainty_0_to_1") == "0.8200"
        assert step.get("speed_band") == "90-100 km/h"
        assert step.get("frequency_hz_or_order") == "12.4 Hz"


def test_build_domain_test_plan_normalizes_boundary_step_values() -> None:
    findings = [
        {
            "actions": [
                {
                    "action_id": " wheel_balance_and_runout ",
                    "what": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHAT"},
                    "why": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHY"},
                    "confirm": {"_i18n_key": "ACTION_WHEEL_BALANCE_CONFIRM"},
                    "falsify": {"_i18n_key": "ACTION_WHEEL_BALANCE_FALSIFY"},
                    "eta": " 10 min ",
                }
            ]
        }
    ]

    plan = build_domain_test_plan(findings, "en")

    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.action_id == "wheel_balance_and_runout"
    assert action.what == "ACTION_WHEEL_BALANCE_WHAT"
    assert action.why == "ACTION_WHEEL_BALANCE_WHY"
    assert action.confirm == "ACTION_WHEEL_BALANCE_CONFIRM"
    assert action.falsify == "ACTION_WHEEL_BALANCE_FALSIFY"
    assert action.eta == "10 min"
    assert plan.requires_additional_data is False


def test_build_domain_test_plan_from_findings_delegates_to_domain_service(
    monkeypatch,
) -> None:
    findings = [
        Finding(
            suspected_source="wheel/tire",
            strongest_location="front-left wheel",
            strongest_speed_band="90-100 km/h",
            order="1x wheel",
            confidence=0.82,
            weak_spatial_separation=True,
        )
    ]

    delegated_plan = DomainTestPlan()

    def _fake_plan_test_actions(
        domain_findings: list[Finding], hypotheses: object, *, lang: str
    ) -> DomainTestPlan:
        assert domain_findings == findings
        assert hypotheses == ()
        assert lang == "en"
        return delegated_plan

    monkeypatch.setattr(domain_test_planning, "plan_test_actions", _fake_plan_test_actions)

    plan = build_domain_test_plan_from_findings(findings, "en")

    assert plan is delegated_plan
