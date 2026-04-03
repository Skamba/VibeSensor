"""Validation helpers for the PDF adapter's report-document boundary."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting.document import ReportDocument

__all__ = ["validate_report_document"]

_VALID_CERTAINTY_TIERS = frozenset({"A", "B", "C"})


def validate_report_document(data: ReportDocument) -> ReportDocument:
    """Validate one report document before adapter-side layout planning."""
    if not isinstance(data, ReportDocument):
        raise TypeError(f"build_report_pdf expects ReportDocument, got {type(data).__name__}")
    if data.certainty_tier_key not in _VALID_CERTAINTY_TIERS:
        raise ValueError(
            "report document certainty_tier_key must be one of "
            f"{sorted(_VALID_CERTAINTY_TIERS)}, got {data.certainty_tier_key!r}"
        )
    return data
