"""Canonical prepared report input boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vibesensor.domain import TestRun
    from vibesensor.shared.boundaries.reporting.facts import PreparedReportFacts
    from vibesensor.shared.types.report_cache import ReportPdfCacheKey

__all__ = ["PreparedReportInput"]


@dataclass(frozen=True, slots=True)
class PreparedReportInput:
    """Mapping-ready report handoff with canonical domain and semantic facts."""

    language: str
    filename: str
    domain_test_run: TestRun
    report_facts: PreparedReportFacts
    cache_key: ReportPdfCacheKey | None = None
