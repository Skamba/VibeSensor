"""Prepared presentation sections derived from semantic report facts."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixBData,
    VerdictPageData,
)

__all__ = ["PreparedReportPresentation"]


@dataclass(frozen=True, slots=True)
class PreparedReportPresentation:
    """Presentation-specific report sections prepared before document assembly."""

    verdict_page: VerdictPageData
    appendix_a: AppendixAData
    appendix_b: AppendixBData
