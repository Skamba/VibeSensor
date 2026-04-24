"""Tests for converting run-suitability checks to and from boundary payloads."""

from __future__ import annotations

from vibesensor.domain import RunSuitability, SuitabilityCheck
from vibesensor.shared.boundaries.runs.suitability import (
    run_suitability_from_payload,
    run_suitability_payload,
)


def test_run_suitability_from_payload_uses_canonical_check_key() -> None:
    suitability = run_suitability_from_payload(
        [
            {"check_key": "speed_profile", "state": "warn"},
            "ignore-me",
        ]
    )

    assert suitability.checks == (SuitabilityCheck(check_key="speed_profile", state="warn"),)


def test_run_suitability_from_payload_recovers_numeric_details_from_i18n_explanation() -> None:
    suitability = run_suitability_from_payload(
        [
            {
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "warn",
                "explanation": {
                    "_i18n_key": "SUITABILITY_FRAME_INTEGRITY_WARN",
                    "total_dropped": "4",
                    "total_overflow": 7,
                },
            }
        ]
    )

    assert suitability.checks == (
        SuitabilityCheck(
            check_key="SUITABILITY_CHECK_FRAME_INTEGRITY",
            state="warn",
            details=(("total_dropped", 4), ("total_overflow", 7)),
        ),
    )


def test_run_suitability_payload_projects_domain_checks() -> None:
    suitability = RunSuitability(
        checks=(
            SuitabilityCheck(check_key="speed_profile", state="warn"),
            SuitabilityCheck(check_key="SUITABILITY_CHECK_RUN_DURATION", state="warn"),
            SuitabilityCheck(check_key="steady_cruise", state="pass"),
        )
    )

    payload = run_suitability_payload(suitability)

    assert payload[0]["check_key"] == "speed_profile"
    assert payload[0]["state"] == "warn"
    assert "explanation" in payload[0]
    assert payload[1]["check_key"] == "SUITABILITY_CHECK_RUN_DURATION"
    assert payload[1]["explanation"] == {"_i18n_key": "SUITABILITY_RUN_DURATION_WARNING"}
    assert payload[2]["check_key"] == "steady_cruise"


def test_run_suitability_payload_handles_none() -> None:
    assert run_suitability_payload(None) == []
