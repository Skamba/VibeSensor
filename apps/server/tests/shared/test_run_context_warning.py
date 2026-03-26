"""Tests for shared run-context warning contracts."""

from __future__ import annotations

from vibesensor.shared.run_context_warning import (
    WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
    RunContextWarning,
    build_summary_warnings,
    normalize_run_context_warnings,
)

_REFERENCE_CONTEXT_WARNING = RunContextWarning(
    code=WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
    severity="warn",
    applies_to="order_analysis",
    title={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
    detail={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
)


def test_build_summary_warnings_returns_app_level_models() -> None:
    warnings = build_summary_warnings(
        {"incomplete_for_order_analysis": True},
        reference_complete=False,
    )

    assert warnings == [_REFERENCE_CONTEXT_WARNING]


def test_normalize_run_context_warnings_keeps_wire_payload_shape() -> None:
    warnings = normalize_run_context_warnings(
        [
            {
                "code": WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
                "severity": "warn",
                "applies_to": "order_analysis",
                "title": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
                "detail": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
            },
            "skip-me",
        ]
    )

    assert warnings == [_REFERENCE_CONTEXT_WARNING]
