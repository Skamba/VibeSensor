from __future__ import annotations

from test_support.findings import make_finding_payload

from vibesensor.shared.boundaries.analysis_summary_projection import project_analysis_summary


def test_project_analysis_summary_projects_run_suitability_from_reconstructed_test_run() -> None:
    summary = {
        "case_id": "case-001",
        "run_id": "run-001",
        "metadata": {"car_name": "Guard Car", "car_type": "sedan"},
        "findings": [make_finding_payload(finding_id="F001", confidence=0.8)],
        "top_causes": [make_finding_payload(finding_id="F001", confidence=0.8)],
        "test_plan": [
            {
                "action_id": "check-wheel",
                "what": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHAT"},
                "why": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHY"},
            }
        ],
        "run_suitability": [
            {"check_key": "speed_profile", "state": "warn"},
        ],
    }

    projected, test_run = project_analysis_summary(summary)

    assert test_run.suitability is not None
    assert projected["run_suitability"] == [
        {
            "check": "speed_profile",
            "check_key": "speed_profile",
            "state": "warn",
            "explanation": test_run.suitability.checks[0].explanation_i18n_ref(),
        }
    ]
