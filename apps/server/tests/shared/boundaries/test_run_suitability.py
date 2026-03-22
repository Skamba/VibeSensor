from __future__ import annotations

from vibesensor.domain import RunSuitability, SuitabilityCheck
from vibesensor.shared.boundaries.run_suitability import (
    run_suitability_from_payload,
    run_suitability_payload,
)


def test_run_suitability_from_payload_accepts_canonical_and_legacy_check_keys() -> None:
    suitability = run_suitability_from_payload(
        [
            {"check_key": "speed_profile", "state": "warn"},
            {"check": "legacy_gap", "state": "pass"},
            "ignore-me",
        ]
    )

    assert suitability.checks == (
        SuitabilityCheck(check_key="speed_profile", state="warn"),
        SuitabilityCheck(check_key="legacy_gap", state="pass"),
    )


def test_run_suitability_payload_projects_domain_checks() -> None:
    suitability = RunSuitability(
        checks=(
            SuitabilityCheck(check_key="speed_profile", state="warn"),
            SuitabilityCheck(check_key="steady_cruise", state="pass"),
        )
    )

    payload = run_suitability_payload(suitability)

    assert payload[0]["check"] == "speed_profile"
    assert payload[0]["check_key"] == "speed_profile"
    assert payload[0]["state"] == "warn"
    assert "explanation" in payload[0]
    assert payload[1]["check_key"] == "steady_cruise"


def test_run_suitability_payload_handles_none() -> None:
    assert run_suitability_payload(None) == []
