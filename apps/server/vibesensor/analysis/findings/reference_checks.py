"""Reference-missing finding generation."""

from __future__ import annotations

from .._types import Finding, JsonValue

# ---------------------------------------------------------------------------
# Module-level i18n reference constants (hoisted; avoids per-call dict
# construction and removes the cross-package import of order_analysis._i18n_ref).
# ---------------------------------------------------------------------------

_REF_MISSING: dict[str, str] = {"_i18n_key": "REFERENCE_MISSING"}
_REF_MISSING_AMPLITUDE: dict[str, str] = {
    "_i18n_key": "REFERENCE_MISSING_ORDER_SPECIFIC_AMPLITUDE_RANKING_SKIPPED",
}


def _reference_missing_finding(
    *,
    finding_id: str,
    suspected_source: str,
    evidence_summary: JsonValue,
    quick_checks: list[JsonValue],
) -> Finding:
    # All output fields are language-neutral i18n reference dicts; the
    # language is resolved at report-render time, not here.
    return {
        "finding_id": finding_id,
        "finding_type": "reference",
        "suspected_source": suspected_source,
        "evidence_summary": evidence_summary,
        "frequency_hz_or_order": {**_REF_MISSING},
        "amplitude_metric": {
            "name": "not_available",
            "value": None,
            "units": "n/a",
            "definition": {**_REF_MISSING_AMPLITUDE},
        },
        "confidence_0_to_1": None,
        "quick_checks": quick_checks[:3],
    }
