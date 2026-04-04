"""Canonical report-document assembly above the PDF renderer boundary."""

from __future__ import annotations

from ._candidate_resolver import (
    PrimaryCandidateContext,
    resolve_primary_report_candidate,
)
from ._card_builder import build_system_cards, humanize_signatures
from .builder import build_report_document, build_report_document_data
from .composition import compose_report_document_context

__all__ = [
    "PrimaryCandidateContext",
    "build_system_cards",
    "humanize_signatures",
    "build_report_document",
    "build_report_document_data",
    "compose_report_document_context",
    "resolve_primary_report_candidate",
]
