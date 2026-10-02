"""Canonical report-document assembly above the PDF renderer boundary."""

from __future__ import annotations

from vibesensor.use_cases.history.report_document._candidate_resolver import (
    PrimaryCandidateContext,
    resolve_primary_report_candidate,
)
from vibesensor.use_cases.history.report_document._card_builder import (
    build_system_cards,
    humanize_signatures,
)
from vibesensor.use_cases.history.report_document.builder import build_report_document

__all__ = [
    "PrimaryCandidateContext",
    "build_system_cards",
    "humanize_signatures",
    "build_report_document",
    "resolve_primary_report_candidate",
]
