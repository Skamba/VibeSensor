from __future__ import annotations

from vibesensor.shared.boundaries.summary_fields.warnings import (
    localize_warning_list,
    summary_warning_payloads,
)
from vibesensor.shared.run_context_warning import RunContextWarning

_WARNING_MODEL = RunContextWarning(
    code="reference_context_incomplete",
    severity="warn",
    applies_to="order_analysis",
    title={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
    detail={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
)

_WARNING_PAYLOAD = {
    "code": "reference_context_incomplete",
    "severity": "warn",
    "applies_to": "order_analysis",
    "title": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
    "detail": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
}

_LOCALIZED_WARNING_NL = {
    "code": "reference_context_incomplete",
    "severity": "warn",
    "applies_to": "order_analysis",
    "title": "De referentiecontext voor ordeanalyse was onvolledig voor deze meting",
    "detail": (
        "Voor deze meting ontbreekt een deel van de wiel-/motorreferenties die "
        "nodig zijn voor betrouwbare ordeanalyse. Ordegebaseerde bevindingen "
        "kunnen nog steeds worden getoond, maar behandel ze als voorlopig "
        "totdat de meting met volledige voertuigreferentiegegevens wordt "
        "herhaald."
    ),
}


def test_summary_warning_payloads_keep_existing_wire_shape() -> None:
    warnings = [_WARNING_MODEL]

    assert summary_warning_payloads(warnings) == [_WARNING_PAYLOAD]


def test_localize_warning_list_resolves_run_context_warning_models() -> None:
    warnings = [_WARNING_MODEL]

    assert localize_warning_list(warnings, lang="nl") == [_LOCALIZED_WARNING_NL]


def test_localize_warning_list_resolves_persisted_warning_payloads() -> None:
    warnings = [_WARNING_PAYLOAD]

    assert localize_warning_list(warnings, lang="nl") == [_LOCALIZED_WARNING_NL]
