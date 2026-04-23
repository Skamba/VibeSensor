"""Canonical prepared report input boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vibesensor.domain import TestRun
    from vibesensor.shared.boundaries.reporting.facts import PreparedReportFacts
    from vibesensor.shared.types.report_cache import ReportPdfCacheKey

__all__ = ["PreparedReportInput", "validate_prepared_report_input"]


def validate_prepared_report_input(prepared: object) -> PreparedReportInput:
    """Validate one canonical prepared report handoff before document assembly."""

    if not isinstance(prepared, PreparedReportInput):
        raise TypeError(
            f"build_report_document expects PreparedReportInput, got {type(prepared).__name__}"
        )
    _require_non_empty_text(prepared.language, field_name="language")
    _require_non_empty_text(prepared.filename, field_name="filename")
    if not prepared.filename.lower().endswith(".pdf"):
        raise ValueError(
            f"prepared report input filename must end with .pdf, got {prepared.filename!r}"
        )
    report_run_id = _normalized_run_id(prepared.report_facts)
    test_run_id = prepared.domain_test_run.run_id.strip()
    if report_run_id != test_run_id:
        raise ValueError(
            "prepared report input run_id mismatch between domain_test_run and "
            f"report_facts.run: {test_run_id!r} != {report_run_id!r}"
        )
    return prepared


def _require_non_empty_text(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"prepared report input {field_name} must be non-empty")


def _normalized_run_id(report_facts: PreparedReportFacts) -> str:
    run_id = report_facts.run.run_id.strip()
    if not run_id:
        raise ValueError("prepared report input report_facts.run.run_id must be non-empty")
    return run_id


@dataclass(frozen=True, slots=True)
class PreparedReportInput:
    """Mapping-ready report handoff with canonical domain and semantic facts."""

    language: str
    filename: str
    domain_test_run: TestRun
    report_facts: PreparedReportFacts
    cache_key: ReportPdfCacheKey | None = None

    def __post_init__(self) -> None:
        validate_prepared_report_input(self)
