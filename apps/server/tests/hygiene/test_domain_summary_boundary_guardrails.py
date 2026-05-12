"""Behavior guardrails for summary reconstruction around domain objects."""

from __future__ import annotations


def test_boundary_decoder_builds_diagnostic_case_from_summary() -> None:
    """Catch regressions in the summary-to-domain reconstruction seam."""
    from test_support.findings import make_finding_payload

    from vibesensor.shared.boundaries.analysis_payloads.reconstruction import (
        diagnostic_case_from_summary,
    )

    summary = {
        "case_id": "summary-case-guard-id",
        "run_id": "summary-case-guard",
        "metadata": {
            "run_id": "summary-case-guard",
            "active_car_snapshot": {"name": "Guard Car", "type": "sedan"},
        },
        "findings": [make_finding_payload(finding_id="F001", confidence=0.80)],
        "top_causes": [make_finding_payload(finding_id="F001", confidence=0.80)],
        "test_plan": [
            {
                "action_id": "check-wheel",
                "what": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHAT"},
                "why": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHY"},
            }
        ],
    }
    diagnostic_case = diagnostic_case_from_summary(summary)
    assert diagnostic_case.case_id == "summary-case-guard-id"
    assert diagnostic_case.test_runs
    assert diagnostic_case.primary_run is not None
