"""Tests for report-facts projection helpers that prepare warnings and suitability payloads."""

from __future__ import annotations

from vibesensor.domain import RunSuitability, SuitabilityCheck
from vibesensor.shared.boundaries.report_facts_projection import (
    report_suitability_checks,
    report_warning_payloads,
)


def test_report_warning_payloads_prefers_explicit_override() -> None:
    payload = {"warnings": [{"code": "PAYLOAD", "severity": "warn", "applies_to": "report"}]}
    override = [{"code": "OVERRIDE", "severity": "warn", "applies_to": "report"}]

    warnings = report_warning_payloads(payload, warnings=override)

    assert [warning["code"] for warning in warnings] == ["OVERRIDE"]


def test_report_warning_payloads_falls_back_to_payload_warnings() -> None:
    payload = {"warnings": [{"code": "PAYLOAD", "severity": "warn", "applies_to": "report"}]}

    warnings = report_warning_payloads(payload)

    assert [warning["code"] for warning in warnings] == ["PAYLOAD"]


def test_report_suitability_checks_wraps_boundary_payloads_as_tuple() -> None:
    suitability = RunSuitability(
        checks=(SuitabilityCheck(check_key="speed_profile", state="warn"),)
    )

    payload = report_suitability_checks(suitability)

    assert payload == (
        {
            "check_key": "speed_profile",
            "state": "warn",
            "explanation": "",
        },
    )


def test_report_suitability_checks_handles_none() -> None:
    assert report_suitability_checks(None) == ()
