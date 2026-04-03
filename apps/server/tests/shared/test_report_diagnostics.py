from __future__ import annotations

import pytest

from vibesensor.domain import RunSuitability, SuitabilityCheck
from vibesensor.shared.report_diagnostics import report_suitability_checks, report_warnings
from vibesensor.shared.run_context_warning import RunContextWarning


def test_report_warnings_prefers_explicit_override() -> None:
    payload = {
        "warnings": [
            {
                "code": "PAYLOAD",
                "severity": "warn",
                "applies_to": "report",
                "title": "Payload warning",
                "detail": "payload detail",
            }
        ]
    }
    override = [
        RunContextWarning(
            code="OVERRIDE",
            severity="warn",
            applies_to="report",
            title="Override warning",
            detail="override detail",
        )
    ]

    warnings = report_warnings(payload, warnings=override)

    assert warnings == (override[0],)


def test_report_warnings_falls_back_to_payload_warnings() -> None:
    payload = {
        "warnings": [
            {
                "code": "PAYLOAD",
                "severity": "warn",
                "applies_to": "report",
                "title": "Payload warning",
                "detail": "payload detail",
            }
        ]
    }

    warnings = report_warnings(payload)

    assert warnings == (
        RunContextWarning(
            code="PAYLOAD",
            severity="warn",
            applies_to="report",
            title="Payload warning",
            detail="payload detail",
        ),
    )


def test_report_warnings_rejects_incomplete_payloads() -> None:
    payload = {
        "warnings": [
            {
                "code": "PAYLOAD",
                "severity": "warn",
                "applies_to": "report",
            }
        ]
    }

    with pytest.raises(ValueError, match="title"):
        report_warnings(payload)


def test_report_suitability_checks_returns_domain_checks_as_tuple() -> None:
    suitability = RunSuitability(
        checks=(SuitabilityCheck(check_key="speed_profile", state="warn"),)
    )

    checks = report_suitability_checks(suitability)

    assert checks == suitability.checks


def test_report_suitability_checks_handles_none() -> None:
    assert report_suitability_checks(None) == ()
