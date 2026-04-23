"""Shared validation helpers for the canonical report-document boundary."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting.document.document import ReportDocument

__all__ = ["validate_report_document"]

_VALID_CERTAINTY_TIERS = frozenset({"A", "B", "C"})
_VALID_APPENDIX_A_MODES = frozenset({"workflow", "recapture"})


def validate_report_document(data: object) -> ReportDocument:
    """Validate one canonical report document before render planning."""

    if not isinstance(data, ReportDocument):
        raise TypeError(f"build_report_pdf expects ReportDocument, got {type(data).__name__}")
    _require_non_empty_text(data.title, field_name="title")
    _require_non_empty_text(data.run_id, field_name="run_id")
    _require_non_empty_text(data.lang, field_name="lang")
    if data.sample_count < 0:
        raise ValueError("report document sample_count must be non-negative")
    if data.sensor_count < 0:
        raise ValueError("report document sensor_count must be non-negative")
    if data.certainty_tier_key not in _VALID_CERTAINTY_TIERS:
        raise ValueError(
            "report document certainty_tier_key must be one of "
            f"{sorted(_VALID_CERTAINTY_TIERS)}, got {data.certainty_tier_key!r}"
        )
    if data.appendix_a.mode not in _VALID_APPENDIX_A_MODES:
        raise ValueError(
            "report document appendix_a.mode must be one of "
            f"{sorted(_VALID_APPENDIX_A_MODES)}, got {data.appendix_a.mode!r}"
        )
    return data


def _require_non_empty_text(value: str | None, *, field_name: str) -> None:
    if value is None or not value.strip():
        raise ValueError(f"report document {field_name} must be non-empty")
