"""Shared verdict/appendix context for report-document composition."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.shared.boundaries.reporting.document import RankedCandidateRow

__all__ = ["RecaptureAssessment", "ReportSectionContext"]


@dataclass(frozen=True, slots=True)
class RecaptureAssessment:
    """Shared recapture guidance derived from one report-decision pass."""

    issues: tuple[str, ...]
    actions: tuple[str, ...]
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportSectionContext:
    """Common derived values reused by verdict and appendix builders."""

    action_status_key: str
    location_confidence_key: str
    alternative_source_visible: bool
    active_locations: tuple[str, ...]
    coverage_label: str
    coverage_notes: tuple[str, ...]
    proof_caveat: str | None
    runner_up_corner: str | None
    speed_window_label: str | None
    ranked_candidates: tuple[RankedCandidateRow, ...]
    recapture: RecaptureAssessment
