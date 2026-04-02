"""Prepared report display dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PreparedRankedCandidateDisplay:
    source_name: str
    confidence_pct: str | None
    inspect_first: str | None
    path_role: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class PreparedVerdictDisplay:
    speed_window_label: str | None
    suspected_source: str | None
    inspect_first: str | None
    action_status: str
    action_status_note: str | None
    reason_sentence: str | None
    dominant_corner: str | None
    runner_up_corner: str | None
    location_confidence: str
    coverage_label: str
    also_consider: str | None
    proof_caveat: str | None
    proof_panel_title: str
    footer_routes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedAppendixADisplay:
    mode: str
    primary_source: str | None
    alternative_source: str | None
    why_primary_first: str | None
    why_alternative_next: str | None
    next_if_clean: str | None
    ranked_candidates: tuple[PreparedRankedCandidateDisplay, ...]
    capture_issues: tuple[str, ...]
    capture_changes: tuple[str, ...]
    capture_conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedAppendixBSummaryDisplay:
    dominant_corner: str | None
    runner_up_corner: str | None
    dominance_ratio_text: str
    location_confidence: str
    coverage_label: str
    coverage_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedReportDisplayFacts:
    verdict: PreparedVerdictDisplay
    appendix_a: PreparedAppendixADisplay
    appendix_b: PreparedAppendixBSummaryDisplay
