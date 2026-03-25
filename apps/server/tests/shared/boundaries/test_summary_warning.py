from __future__ import annotations

from vibesensor.shared.boundaries.summary_warning import (
    localize_warning_list,
    summary_warning_payloads,
)
from vibesensor.shared.run_context_warning import RunContextWarning


def test_summary_warning_payloads_keep_existing_wire_shape() -> None:
    warnings = [
        RunContextWarning(
            code="reference_context_incomplete",
            severity="warn",
            applies_to="order_analysis",
            title={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
            detail={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
        )
    ]

    assert summary_warning_payloads(warnings) == [
        {
            "code": "reference_context_incomplete",
            "severity": "warn",
            "applies_to": "order_analysis",
            "title": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
            "detail": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
        }
    ]


def test_localize_warning_list_resolves_run_context_warning_models() -> None:
    warnings = [
        RunContextWarning(
            code="reference_context_incomplete",
            severity="warn",
            applies_to="order_analysis",
            title={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
            detail={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
        )
    ]

    assert localize_warning_list(warnings, lang="nl") == [
        {
            "code": "reference_context_incomplete",
            "severity": "warn",
            "applies_to": "order_analysis",
            "title": "De referentiecontext voor ordeanalyse was onvolledig voor deze run",
            "detail": (
                "Voor deze run ontbreekt een deel van de wiel-/motorreferentie die "
                "nodig is voor betrouwbare ordeanalyse. Ordegebaseerde bevindingen "
                "kunnen nog steeds worden getoond, maar behandel ze als voorlopig "
                "totdat de run met volledige voertuigreferentiegegevens wordt "
                "herhaald."
            ),
        }
    ]


def test_localize_warning_list_resolves_persisted_warning_payloads() -> None:
    warnings = [
        {
            "code": "reference_context_incomplete",
            "severity": "warn",
            "applies_to": "order_analysis",
            "title": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
            "detail": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
        }
    ]

    assert localize_warning_list(warnings, lang="nl") == [
        {
            "code": "reference_context_incomplete",
            "severity": "warn",
            "applies_to": "order_analysis",
            "title": "De referentiecontext voor ordeanalyse was onvolledig voor deze run",
            "detail": (
                "Voor deze run ontbreekt een deel van de wiel-/motorreferentie die "
                "nodig is voor betrouwbare ordeanalyse. Ordegebaseerde bevindingen "
                "kunnen nog steeds worden getoond, maar behandel ze als voorlopig "
                "totdat de run met volledige voertuigreferentiegegevens wordt "
                "herhaald."
            ),
        }
    ]
