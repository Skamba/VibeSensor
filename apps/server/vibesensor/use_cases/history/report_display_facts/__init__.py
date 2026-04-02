"""Prepared report display facts assembled on the history side."""

from __future__ import annotations

from .assembly import prepare_report_display_facts
from .models import (
    PreparedAppendixADisplay,
    PreparedAppendixBSummaryDisplay,
    PreparedRankedCandidateDisplay,
    PreparedReportDisplayFacts,
    PreparedVerdictDisplay,
)

__all__ = [
    "PreparedAppendixADisplay",
    "PreparedAppendixBSummaryDisplay",
    "PreparedRankedCandidateDisplay",
    "PreparedReportDisplayFacts",
    "PreparedVerdictDisplay",
    "prepare_report_display_facts",
]
