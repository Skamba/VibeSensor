from __future__ import annotations

from typing import cast

from test_support.report_helpers import minimal_summary

from vibesensor.shared.boundaries.analysis_summary import analysis_summary_with_warnings
from vibesensor.shared.run_context_warning import RunContextWarning
from vibesensor.shared.types.history_analysis_contracts import (
    AnalysisSummary,
    SummaryWarningResponse,
)


def _warning_model() -> RunContextWarning:
    return RunContextWarning(
        code="reference_context_incomplete",
        severity="warn",
        applies_to="order_analysis",
        title={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
        detail={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
    )


def _warning_payload() -> SummaryWarningResponse:
    return {
        "code": "reference_context_incomplete",
        "severity": "warn",
        "applies_to": "order_analysis",
        "title": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
        "detail": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
    }


def test_analysis_summary_with_warnings_replaces_warning_payloads() -> None:
    summary = cast(AnalysisSummary, minimal_summary())

    updated = analysis_summary_with_warnings(summary, [_warning_model()])

    assert updated["warnings"] == [_warning_payload()]
    assert summary["warnings"] == []


def test_analysis_summary_with_warnings_accepts_persisted_warning_payloads() -> None:
    summary = cast(AnalysisSummary, minimal_summary())

    updated = analysis_summary_with_warnings(summary, [_warning_payload()])

    assert updated["warnings"] == [_warning_payload()]
