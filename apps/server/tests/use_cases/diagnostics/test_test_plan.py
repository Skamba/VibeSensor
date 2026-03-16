from __future__ import annotations

from typing import Any

from tests.test_support.findings import make_finding_payload
from vibesensor.domain import Finding
from vibesensor.use_cases.diagnostics.findings import finalize_findings
from vibesensor.use_cases.diagnostics.summary_builder import summarize_run_data

_MINIMAL_META: dict[str, Any] = {
    "run_id": "test-plan-domain-projection",
    "start_time_utc": "2025-01-01T00:00:00Z",
    "end_time_utc": "2025-01-01T00:01:00Z",
    "sensor_model": "ADXL345",
    "raw_sample_rate_hz": 800,
}


def test_summary_test_plan_ignores_payload_actions_and_projects_domain_plan() -> None:
    payload = make_finding_payload(
        suspected_source="wheel/tire",
        confidence=0.82,
        strongest_location="front-left wheel",
        strongest_speed_band="90-100 km/h",
        actions=[
            {
                "action_id": "engine_mounts_and_accessories",
                "what": "PAYLOAD_ONLY_WHAT",
                "why": "PAYLOAD_ONLY_WHY",
                "confirm": "PAYLOAD_ONLY_CONFIRM",
                "falsify": "PAYLOAD_ONLY_FALSIFY",
                "eta": "99 min",
            }
        ],
    )

    def _findings_builder(**_: object) -> tuple[Finding, ...]:
        return finalize_findings([payload])

    summary = summarize_run_data(
        _MINIMAL_META,
        [],
        lang="en",
        findings_builder=_findings_builder,
    )

    action_ids = [str(step.get("action_id") or "") for step in summary["test_plan"]]

    assert action_ids[:2] == ["wheel_tire_condition", "wheel_balance_and_runout"]
    assert "engine_mounts_and_accessories" not in action_ids
    assert all(step.get("what") != "PAYLOAD_ONLY_WHAT" for step in summary["test_plan"])


def test_summary_test_plan_uses_boundary_step_shape_from_domain_actions() -> None:
    summary = summarize_run_data(
        _MINIMAL_META,
        [],
        lang="en",
        findings_builder=lambda **_: finalize_findings(
            [make_finding_payload(suspected_source="engine")]
        ),
    )

    assert summary["test_plan"]
    for step in summary["test_plan"]:
        assert set(step) == {"action_id", "what", "why", "confirm", "falsify", "eta"}
        assert "certainty_0_to_1" not in step
        assert "speed_band" not in step
        assert "frequency_hz_or_order" not in step
