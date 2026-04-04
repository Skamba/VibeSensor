"""Shared verdict/appendix context for report-document composition."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.shared.boundaries.reporting.document import RankedCandidateRow

__all__ = [
    "AppendixAContext",
    "AppendixBContext",
    "AppendixCContext",
    "RecaptureAssessment",
    "VerdictPageContext",
]


@dataclass(frozen=True, slots=True)
class RecaptureAssessment:
    """Shared recapture guidance derived from one report-decision pass."""

    issues: tuple[str, ...]
    actions: tuple[str, ...]
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VerdictPageContext:
    """Derived values used by the verdict-page builder."""

    action_status_key: str
    location_confidence_key: str
    alternative_source_visible: bool
    active_locations: tuple[str, ...]
    coverage_label: str
    proof_caveat: str | None
    runner_up_corner: str | None
    speed_window_label: str | None
    recapture: RecaptureAssessment


@dataclass(frozen=True, slots=True)
class AppendixAContext:
    """Derived values used by the workflow appendix builder."""

    action_status_key: str
    alternative_source_visible: bool
    ranked_candidates: tuple[RankedCandidateRow, ...]
    recapture: RecaptureAssessment


@dataclass(frozen=True, slots=True)
class AppendixBContext:
    """Derived values used by the location appendix builder."""

    action_status_key: str
    location_confidence_key: str
    active_locations: tuple[str, ...]
    coverage_label: str
    coverage_notes: tuple[str, ...]
    runner_up_corner: str | None


@dataclass(frozen=True, slots=True)
class AppendixCContext:
    """Derived values used by the evidence appendix builder."""

    speed_window_label: str | None
    proof_caveat: str | None
