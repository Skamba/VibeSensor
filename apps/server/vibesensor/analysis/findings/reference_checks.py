"""Reference-missing finding generation."""

from __future__ import annotations

from typing import Any

from ..order_analysis import _i18n_ref


def _reference_missing_finding(
    *,
    finding_id: str,
    suspected_source: str,
    evidence_summary: object,
    quick_checks: list[object],
    lang: str = "en",
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "finding_type": "reference",
        "suspected_source": suspected_source,
        "evidence_summary": evidence_summary,
        "frequency_hz_or_order": _i18n_ref("REFERENCE_MISSING"),
        "amplitude_metric": {
            "name": "not_available",
            "value": None,
            "units": "n/a",
            "definition": _i18n_ref("REFERENCE_MISSING_ORDER_SPECIFIC_AMPLITUDE_RANKING_SKIPPED"),
        },
        "confidence_0_to_1": None,
        "quick_checks": quick_checks[:3],
    }
