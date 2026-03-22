"""Guardrails for summary and boundary modules around domain objects."""

from __future__ import annotations


def test_boundary_decoder_builds_diagnostic_case_from_summary() -> None:
    from test_support.findings import make_finding_payload

    from vibesensor.shared.boundaries.diagnostic_case import diagnostic_case_from_summary

    summary = {
        "case_id": "summary-case-guard-id",
        "run_id": "summary-case-guard",
        "metadata": {"car_name": "Guard Car", "car_type": "sedan"},
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


def test_finding_projector_in_finding_boundary_module() -> None:
    """Finding payload projector should live in boundaries/finding.py."""
    from vibesensor.shared.boundaries.finding import finding_payload_from_domain

    assert callable(finding_payload_from_domain)


def test_history_backend_types_do_not_export_history_run_payload() -> None:
    """History record typing must live in the dedicated shared history-record module."""
    from tests._paths import SERVER_ROOT

    backend_types_source = (
        SERVER_ROOT / "vibesensor" / "shared" / "types" / "backend_types.py"
    ).read_text()
    history_records_source = (
        SERVER_ROOT / "vibesensor" / "shared" / "types" / "history_records.py"
    ).read_text()
    assert "HistoryRunPayload" not in backend_types_source
    assert "class HistoryRecord" not in backend_types_source
    assert "class HistoryRunListEntry" in history_records_source
    assert "class StoredHistoryRun" in history_records_source
