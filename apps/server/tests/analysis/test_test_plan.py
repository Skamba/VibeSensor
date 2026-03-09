from __future__ import annotations

from vibesensor.analysis.test_plan import _merge_test_plan


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
            "confidence_0_to_1": 0.82,
        },
    ]

    merged = _merge_test_plan(findings, "en")
    assert len(merged) > 0
    for step in merged:
        assert step.get("certainty_0_to_1") == "0.8200"
        assert step.get("speed_band") == "90-100 km/h"
        assert step.get("frequency_hz_or_order") == "12.4 Hz"
