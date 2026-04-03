"""Canonical prepared report input boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vibesensor.domain import TestRun
    from vibesensor.shared.boundaries.reporting.facts import PreparedReportFacts
    from vibesensor.shared.boundaries.reporting.payload import NormalizedReportSummary
    from vibesensor.shared.boundaries.reporting.presentation import PreparedReportPresentation
    from vibesensor.shared.types.report_cache import ReportPdfCacheKey

__all__ = ["PreparedReportInput"]


@dataclass(frozen=True, slots=True)
class PreparedReportInput:
    """Mapping-ready report handoff with separate semantic and presentation state."""

    summary: NormalizedReportSummary
    language: str
    filename: str
    domain_test_run: TestRun
    report_facts: PreparedReportFacts
    presentation: PreparedReportPresentation
    cache_key: ReportPdfCacheKey | None = None
